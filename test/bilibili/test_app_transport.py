from __future__ import annotations

import base64
import gzip
import json
import unittest
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from curl_cffi import requests

from reverse.bilibili_reverse.app_transport import (
    APP_BASE,
    _decode_response,
    _decode_unary,
    _encode_unary,
    _grpc_headers,
    app_rest_headers,
    fetch_app_grpc,
)
from reverse.bilibili_reverse.app_wire import _wire_fields
from reverse.bilibili_reverse.errors import BilibiliInputError, BilibiliResponseError
from reverse.bilibili_reverse.mobile_profile import MobileProfile


def _profile() -> MobileProfile:
    return MobileProfile(
        version=1,
        buvid="XX0123456789ABCDEFFEDCBA9876543210ABC",
        device_id="AbCdEfGhIjKlMnOpQrStUvWxYz0",
        created_at="2026-07-25T01:02:03Z",
    )


def _frame(payload: bytes, *, compressed: bool = False) -> bytes:
    body = gzip.compress(payload) if compressed else payload
    flag = b"\x01" if compressed else b"\x00"
    return flag + len(body).to_bytes(4, "big") + body


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        trailers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self.trailers = trailers or {}


class FakeSession:
    def __init__(self, results: list[FakeResponse | Exception]) -> None:
        self.results = deque(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError(f"出现未预期的 POST 请求：{url}")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class AppTransportTest(unittest.TestCase):
    def test_rest_headers_keep_mobile_identity_separate(self) -> None:
        profile = _profile()

        headers = app_rest_headers(profile, "fixture-agent")

        self.assertEqual(
            headers,
            {
                "accept": "application/json",
                "buvid": profile.buvid,
                "device-id": profile.device_id,
                "user-agent": "fixture-agent",
            },
        )
        self.assertNotIn("origin", headers)
        self.assertNotIn("referer", headers)

    def test_grpc_headers_encode_pinned_mobile_metadata(self) -> None:
        chunks = deque(
            [
                bytes(range(16)),
                bytes(range(32)),
            ]
        )

        def random_bytes(size: int) -> bytes:
            value = chunks.popleft()
            self.assertEqual(len(value), size)
            return value

        profile = _profile()
        headers = _grpc_headers(
            profile,
            "fixture-agent",
            random_bytes,
        )

        self.assertEqual(headers["content-type"], "application/grpc")
        self.assertEqual(headers["grpc-encoding"], "gzip")
        self.assertEqual(
            headers["grpc-accept-encoding"],
            "gzip,identity",
        )
        self.assertEqual(
            headers["user-agent"],
            "fixture-agent grpc-java-cronet/1.36.1",
        )
        self.assertEqual(headers["buvid"], profile.buvid)
        self.assertEqual(
            headers["x-bili-trace-id"],
            "000102030405060708090a0b0c0d0e0f:08090a0b0c0d0e0f:0:0",
        )

        metadata = _wire_fields(
            base64.b64decode(headers["x-bili-metadata-bin"]),
            20,
            "测试 metadata",
        )
        device = _wire_fields(
            base64.b64decode(headers["x-bili-device-bin"]),
            30,
            "测试 device",
        )
        fawkes = _wire_fields(
            base64.b64decode(headers["x-bili-fawkes-req-bin"]),
            10,
            "测试 fawkes",
        )

        self.assertIn((4, 0, 8180300, b""), metadata)
        self.assertIn(
            (6, 2, 0, profile.buvid.encode()),
            metadata,
        )
        created_at_ms = int(
            datetime.fromisoformat(
                profile.created_at.replace("Z", "+00:00")
            ).timestamp()
            * 1000
        )
        self.assertIn((15, 0, created_at_ms, b""), device)
        self.assertIn((3, 2, 0, b"ABCDEFGH"), fawkes)

    def test_fetch_posts_unary_frame_and_returns_payload(self) -> None:
        response_payload = b"\x08\x01"
        session = FakeSession(
            [
                FakeResponse(
                    content=_frame(response_payload),
                    headers={
                        "content-type": "application/grpc+proto",
                        "grpc-status": "0",
                    },
                )
            ]
        )

        result = fetch_app_grpc(
            session,  # type: ignore[arg-type]
            "/fixture.Service/Method",
            b"\x10\x02",
            profile=_profile(),
            user_agent="fixture-agent",
            timeout=3.5,
            retries=0,
        )

        self.assertEqual(result, response_payload)
        url, options = session.calls[0]
        self.assertEqual(url, f"{APP_BASE}/fixture.Service/Method")
        self.assertEqual(options["data"], b"\x00\x00\x00\x00\x02\x10\x02")
        self.assertEqual(options["timeout"], 3.5)
        self.assertIs(options["allow_redirects"], False)
        self.assertEqual(
            options["headers"]["user-agent"],
            "fixture-agent grpc-java-cronet/1.36.1",
        )

    def test_fetch_retries_transient_failures(self) -> None:
        session = FakeSession(
            [
                requests.RequestsError("fixture offline"),
                FakeResponse(status=503),
                FakeResponse(
                    content=_frame(b"ok"),
                    headers={
                        "content-type": "application/grpc",
                        "grpc-status": "0",
                    },
                ),
            ]
        )

        with patch("reverse.bilibili_reverse.app_transport.time.sleep") as sleep:
            result = fetch_app_grpc(
                session,  # type: ignore[arg-type]
                "/fixture.Service/Method",
                b"request",
                profile=_profile(),
                retries=2,
            )

        self.assertEqual(result, b"ok")
        self.assertEqual(len(session.calls), 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.35, 0.7])

    def test_fetch_retries_only_the_shared_transient_statuses(self) -> None:
        for status in (408, 425):
            with self.subTest(status=status):
                session = FakeSession(
                    [
                        FakeResponse(status=status),
                        FakeResponse(
                            content=_frame(b"ok"),
                            headers={
                                "content-type": "application/grpc",
                                "grpc-status": "0",
                            },
                        ),
                    ]
                )
                with patch(
                    "reverse.bilibili_reverse.app_transport.time.sleep"
                ) as sleep:
                    result = fetch_app_grpc(
                        session,  # type: ignore[arg-type]
                        "/fixture.Service/Method",
                        b"request",
                        profile=_profile(),
                        retries=1,
                    )
                self.assertEqual(result, b"ok")
                sleep.assert_called_once()

        session = FakeSession([FakeResponse(status=501), FakeResponse(status=200)])
        with patch("reverse.bilibili_reverse.app_transport.time.sleep") as sleep:
            with self.assertRaisesRegex(BilibiliResponseError, "HTTP 501"):
                fetch_app_grpc(
                    session,  # type: ignore[arg-type]
                    "/fixture.Service/Method",
                    b"request",
                    profile=_profile(),
                    retries=1,
                )
        self.assertEqual(len(session.calls), 1)
        sleep.assert_not_called()

    def test_gzip_trailer_and_status_validation(self) -> None:
        compressed = FakeResponse(
            content=_frame(b"compressed response", compressed=True),
            headers={
                "content-type": "application/grpc",
                "grpc-encoding": "gzip",
            },
            trailers={"grpc-status": "0"},
        )
        self.assertEqual(
            _decode_response(compressed),
            b"compressed response",
        )

        failure = FakeResponse(
            content=_frame(b"ignored"),
            headers={"content-type": "application/grpc"},
            trailers={
                "grpc-status": "13",
                "grpc-message": "bad%20request",
            },
        )
        with self.assertRaisesRegex(
            BilibiliResponseError,
            "bad request",
        ):
            _decode_response(failure)

    def test_response_and_frame_boundaries_are_enforced(self) -> None:
        invalid_responses = (
            FakeResponse(
                status=404,
                content=_frame(b"x"),
                headers={
                    "content-type": "application/grpc",
                    "grpc-status": "0",
                },
            ),
            FakeResponse(
                content=_frame(b"x"),
                headers={
                    "content-type": "application/json",
                    "grpc-status": "0",
                },
            ),
            FakeResponse(
                content=_frame(b"x"),
                headers={"content-type": "application/grpc"},
            ),
            FakeResponse(
                content=b"",
                headers={
                    "content-type": "application/grpc",
                    "grpc-status": "0",
                },
            ),
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaises(BilibiliResponseError):
                    _decode_response(response)

        invalid_frames = (
            b"\x00",
            b"\x02\x00\x00\x00\x00",
            b"\x00\x00\x00\x00\x02x",
            _frame(b"not gzip", compressed=False).replace(
                b"\x00",
                b"\x01",
                1,
            ),
        )
        for frame in invalid_frames:
            with self.subTest(frame=frame):
                with self.assertRaises(BilibiliResponseError):
                    _decode_unary(frame, "")

        with patch(
            "reverse.bilibili_reverse.app_transport.MAX_GRPC_MESSAGE_SIZE",
            4,
        ):
            with self.assertRaises(BilibiliInputError):
                _encode_unary(b"12345")
            compressed = gzip.compress(b"12345")
            oversized = b"\x01" + len(compressed).to_bytes(4, "big") + compressed
            with self.assertRaises(BilibiliResponseError):
                _decode_unary(oversized, "gzip")

    def test_live_evidence_fixture_is_structured_and_redacted(self) -> None:
        path = Path(__file__).with_name("testdata") / "app_grpc_live_evidence.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["schema_version"], 1)
        self.assertEqual(
            evidence["capture_kind"],
            "live_success_metadata",
        )
        self.assertEqual(evidence["request"]["method"], "POST")
        self.assertEqual(evidence["request"]["origin"], APP_BASE)
        self.assertEqual(
            evidence["request"]["path"],
            "/bilibili.main.community.reply.v1.Reply/DetailList",
        )
        self.assertEqual(evidence["response"]["http_status"], 200)
        self.assertEqual(evidence["response"]["http_protocol"], "HTTP/2.0")
        self.assertEqual(evidence["response"]["grpc_status"], "0")
        self.assertEqual(len(evidence["response"]["body_sha256"]), 64)
        self.assertEqual(
            evidence["parsed"]["top_level_fields"],
            [1, 2, 3, 6, 7, 8],
        )
        self.assertEqual(evidence["parsed"]["cursor_next"], "6")
        self.assertEqual(
            evidence["parsed"]["pagination_next"],
            "CAEaADICCAY=",
        )
        self.assertEqual(evidence["parsed"]["root_count"], 1469)
        self.assertEqual(evidence["parsed"]["reply_count"], 5)
        self.assertFalse(evidence["parsed"]["cursor_is_end"])
        self.assertEqual(
            evidence["cli_smoke"]["source"],
            "bilibili_android_grpc",
        )
        self.assertEqual(
            evidence["cli_smoke"]["transport"],
            "mobile_protocol",
        )
        self.assertEqual(evidence["cli_smoke"]["total"], 2)
        self.assertEqual(evidence["cli_smoke"]["pages"], 1)
        self.assertEqual(len(evidence["cli_smoke"]["output_sha256"]), 64)
        self.assertTrue(all(value is False for value in evidence["redaction"].values()))


if __name__ == "__main__":
    unittest.main()
