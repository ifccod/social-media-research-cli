from __future__ import annotations

import base64
import hashlib
import json
import struct
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from reverse.bilibili_reverse.app_rest import (
    API_BASE,
    APP_BASE,
    APP_COMMENTS_PATH,
    APP_COMMENT_REPLIES_PATH,
    APP_VIDEO_DETAIL_PATH,
    get_app_comment_replies,
    get_app_comments,
    get_app_video_detail,
    _parse_detail_reply,
)
from reverse.bilibili_reverse.errors import BilibiliInputError, BilibiliResponseError


def _fixture() -> dict[str, Any]:
    path = Path(__file__).with_name("testdata") / "app_rest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _reply_fixture() -> dict[str, Any]:
    path = Path(__file__).with_name("testdata") / "app_comment_replies_proto.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _varint_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _bytes_field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _double_field(number: int, value: float) -> bytes:
    return _varint((number << 3) | 1) + struct.pack("<d", value)


def _reply_page(
    *,
    root_id: int = 10,
    oid: int = 2,
    reply_ids: tuple[int, ...] = (11,),
    is_end: bool = True,
    token: str = "",
) -> bytes:
    replies = b"".join(
        _bytes_field(1, _varint_field(2, reply_id)) for reply_id in reply_ids
    )
    root = (
        replies
        + _varint_field(2, root_id)
        + _varint_field(3, oid)
        + _varint_field(11, len(reply_ids))
    )
    cursor = _varint_field(1, 7) + _varint_field(4, int(is_end))
    pagination = _bytes_field(1, token.encode()) if token else b""
    return (
        _bytes_field(1, cursor)
        + _bytes_field(3, root)
        + _bytes_field(8, pagination)
    )


class AppRESTTest(unittest.TestCase):
    def test_migrated_live_evidence_keeps_original_bytes(self) -> None:
        expected = {
            "app_rest.json": (
                "5467dc4a7b7b52c30c3051fc8c6aca489d40daef0e7814230fb3adb7836aed55"
            ),
            "app_grpc_live_evidence.json": (
                "00276d732b10a756b37c0d196e16e31269584ea532373da65305629f5a156dd7"
            ),
            "app_search_type.json": (
                "fc45fdbf58d16e79006699d82198f1328a338d84b7a684ce77aca62df2d603dd"
            ),
            "app_search_live_evidence.json": (
                "8e56cd26871abe93b506c6612e773f07841845b8b2c6d2673f02f11769f5485a"
            ),
            "app_pgc_tabs.json": (
                "2abb7922ca37aded13d0b2f0630722cdd20470c4479c49c10a04101547a98db5"
            ),
        }
        root = Path(__file__).with_name("testdata")

        self.assertEqual(
            {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in expected
            },
            expected,
        )

    def test_video_detail_uses_fixed_fixture(self) -> None:
        fixture = _fixture()
        video_fixture = fixture["video_detail"]
        calls: list[tuple[str, str, Mapping[str, str]]] = []

        def fetch(
            base_url: str,
            path: str,
            params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            calls.append((base_url, path, params))
            return video_fixture["response"]

        result = get_app_video_detail("BV1xx411c7mD", fetch)

        self.assertEqual(
            calls,
            [
                (
                    APP_BASE,
                    APP_VIDEO_DETAIL_PATH,
                    {"bvid": "BV1xx411c7mD"},
                )
            ],
        )
        self.assertEqual(result["source"], "bilibili_android_rest")
        self.assertEqual(result["transport"], "mobile_protocol")
        self.assertEqual(result["video"]["aid"], "2")
        self.assertEqual(result["video"]["bvid"], "BV1xx411c7mD")
        self.assertEqual(result["video"]["cid"], "62131")
        self.assertEqual(result["video"]["title"], "字幕君交流场所")

    def test_video_detail_preserves_uint64_id(self) -> None:
        aid = "18446744073709551615"

        def fetch(
            base_url: str,
            path: str,
            params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            self.assertEqual((base_url, path), (APP_BASE, APP_VIDEO_DETAIL_PATH))
            self.assertEqual(params, {"aid": aid})
            return {
                "code": 0,
                "data": {"aid": aid, "bvid": "BV1LargeID01"},
            }

        result = get_app_video_detail(f"av{aid}", fetch)

        self.assertEqual(result["video"]["aid"], aid)

    def test_comments_resolve_bvid_and_use_app_cursor_contract(self) -> None:
        fixture = _fixture()
        detail = fixture["video_detail"]["response"]
        comments = fixture["comments_hot"]["response"]
        calls: list[tuple[str, str, Mapping[str, str]]] = []

        def fetch(
            base_url: str,
            path: str,
            params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            calls.append((base_url, path, params))
            if path == APP_VIDEO_DETAIL_PATH:
                return detail
            if path == APP_COMMENTS_PATH:
                return comments
            raise AssertionError(f"出现未预期的请求：{path}")

        result = get_app_comments(
            "BV1xx411c7mD",
            rest_fetch=fetch,
            limit=1,
            page_size=1,
            order="hot",
        )

        self.assertEqual(
            calls,
            [
                (
                    APP_BASE,
                    APP_VIDEO_DETAIL_PATH,
                    {"bvid": "BV1xx411c7mD"},
                ),
                (
                    API_BASE,
                    APP_COMMENTS_PATH,
                    {
                        "oid": "2",
                        "type": "1",
                        "mode": "3",
                        "next": "0",
                        "ps": "1",
                        "plat": "2",
                    },
                ),
            ],
        )
        self.assertEqual(result["aid"], "2")
        self.assertEqual(result["bvid"], "BV1xx411c7mD")
        self.assertEqual(result["next_offset"], "2")
        self.assertEqual(result["available"], 88640)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["pages"], 1)
        self.assertFalse(result["has_more"])
        self.assertEqual(result["comments"][0]["id"], "495059")
        self.assertEqual(result["comments"][0]["text"], "wwwww")
        self.assertEqual(result["comments"][0]["reply_count"], 1469)

    def test_comments_preserve_opaque_large_cursor(self) -> None:
        cursors: list[str] = []
        next_cursor = "9007199254740993"
        final_cursor = "9007199254740994"

        def page(
            cursor: str,
            *,
            is_end: bool,
            comment_id: str,
        ) -> Mapping[str, Any]:
            return {
                "code": 0,
                "data": {
                    "cursor": {
                        "next": cursor,
                        "is_end": is_end,
                        "all_count": "2",
                    },
                    "replies": [
                        {
                            "rpid_str": comment_id,
                            "content": {"message": comment_id},
                        }
                    ],
                },
            }

        def fetch(
            base_url: str,
            path: str,
            params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            self.assertEqual((base_url, path), (API_BASE, APP_COMMENTS_PATH))
            cursor = params["next"]
            cursors.append(cursor)
            if cursor == "0":
                return page(
                    next_cursor,
                    is_end=False,
                    comment_id="9007199254740995",
                )
            return page(
                final_cursor,
                is_end=True,
                comment_id="9007199254740996",
            )

        result = get_app_comments(
            "av9223372036854775806",
            rest_fetch=fetch,
            limit=2,
            page_size=1,
            order="time",
        )

        self.assertEqual(cursors, ["0", next_cursor])
        self.assertEqual(result["next_offset"], final_cursor)
        self.assertEqual(
            [item["id"] for item in result["comments"]],
            ["9007199254740995", "9007199254740996"],
        )

    def test_comments_parse_is_end_strictly(self) -> None:
        calls = 0

        def fetch(
            _base_url: str,
            _path: str,
            _params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            nonlocal calls
            calls += 1
            return {
                "code": 0,
                "data": {
                    "cursor": {"next": str(calls), "is_end": int(calls == 2)},
                    "replies": [{"rpid": calls}],
                },
            }

        result = get_app_comments(
            "av2",
            rest_fetch=fetch,
            limit=2,
            page_size=1,
        )
        self.assertEqual(calls, 2)
        self.assertFalse(result["has_more"])

        for value in ("false", 2, 0.0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(BilibiliResponseError, "is_end 非法"):
                    get_app_comments(
                        "av2",
                        rest_fetch=lambda _base, _path, _params, value=value: {
                            "code": 0,
                            "data": {
                                "cursor": {"next": "1", "is_end": value},
                                "replies": [{"rpid": 1}],
                            },
                        },
                        limit=1,
                    )

    def test_comment_replies_use_fixed_protobuf_fixture(self) -> None:
        fixture = _reply_fixture()
        expected_requests = fixture["request_payloads_base64"]
        responses = [
            base64.b64decode(value) for value in fixture["response_payloads_base64"]
        ]
        calls = 0

        def fetch(path: str, payload: bytes) -> bytes:
            nonlocal calls
            self.assertEqual(path, APP_COMMENT_REPLIES_PATH)
            self.assertEqual(
                base64.b64encode(payload).decode(),
                expected_requests[calls],
            )
            response = responses[calls]
            calls += 1
            return response

        result = get_app_comment_replies(
            "av2",
            "495059",
            rest_fetch=None,
            grpc_fetch=fetch,
            limit=2,
            page_size=1,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(result["source"], "bilibili_android_grpc")
        self.assertEqual(result["transport"], "mobile_protocol")
        self.assertEqual(result["aid"], "2")
        self.assertEqual(result["root_id"], "495059")
        self.assertEqual(result["next_offset"], "7")
        self.assertEqual(result["pagination_token"], "CAEaADICCAc=")
        self.assertEqual(result["available"], 1469)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["pages"], 2)
        self.assertFalse(result["has_more"])
        self.assertEqual(
            [item["id"] for item in result["replies"]],
            ["1", "2"],
        )
        self.assertEqual(result["replies"][0]["user"]["name"], "fixture-user")

    def test_grpc_singular_fields_are_last_wins(self) -> None:
        old_cursor = _varint_field(1, 1)
        new_cursor = _varint_field(1, 6) + _varint_field(1, 7)
        picture = (
            _bytes_field(1, b"old")
            + _bytes_field(1, b"new")
            + _double_field(2, 1.25)
            + _double_field(2, 2.5)
        )
        old_content = _bytes_field(1, b"discarded")
        new_content = (
            _bytes_field(1, b"old")
            + _bytes_field(1, b"new")
            + _bytes_field(9, picture)
        )
        old_member = _bytes_field(2, b"discarded")
        new_member = _bytes_field(2, b"old") + _bytes_field(2, b"new")
        old_root = _varint_field(2, 1)
        new_root = (
            _varint_field(2, 9)
            + _varint_field(2, 10)
            + _bytes_field(12, old_content)
            + _bytes_field(12, new_content)
            + _bytes_field(13, old_member)
            + _bytes_field(13, new_member)
        )
        payload = (
            _bytes_field(1, old_cursor)
            + _bytes_field(1, new_cursor)
            + _bytes_field(3, old_root)
            + _bytes_field(3, new_root)
            + _varint_field(6, 1)
            + _varint_field(6, 2)
        )

        parsed = _parse_detail_reply(payload)

        self.assertEqual(parsed["cursor"]["next"], 7)
        self.assertEqual(parsed["mode"], 2)
        self.assertEqual(parsed["root"]["id"], 10)
        self.assertEqual(parsed["root"]["content"]["message"], "new")
        self.assertEqual(parsed["root"]["content"]["pictures"][0]["url"], "new")
        self.assertEqual(parsed["root"]["content"]["pictures"][0]["width"], 2.5)
        self.assertEqual(parsed["root"]["member"]["name"], "new")

    def test_grpc_duplicate_singular_fields_validate_every_wire_type(self) -> None:
        cursor = _bytes_field(1, _varint_field(1, 1))
        root = _bytes_field(3, _varint_field(2, 10))
        invalid_payloads = {
            "bytes": cursor
            + _varint_field(3, 1)
            + root,
            "varint": cursor
            + _bytes_field(
                3,
                _bytes_field(2, b"bad") + _varint_field(2, 10),
            ),
            "fixed64": cursor
            + _bytes_field(
                3,
                _varint_field(2, 10)
                + _bytes_field(
                    12,
                    _bytes_field(
                        9,
                        _bytes_field(2, b"bad") + _double_field(2, 1.0),
                    ),
                ),
            ),
        }
        for kind, payload in invalid_payloads.items():
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(BilibiliResponseError, "wire type"):
                    _parse_detail_reply(payload)

    def test_grpc_reply_semantic_and_paging_boundaries(self) -> None:
        def request(response: bytes) -> dict[str, Any]:
            return get_app_comment_replies(
                "av2",
                "10",
                rest_fetch=None,
                grpc_fetch=lambda _path, _payload: response,
                limit=1,
            )

        cases = (
            (_reply_page(root_id=9), "root 不匹配"),
            (_reply_page(oid=3), "oid 不匹配"),
            (
                _reply_page(reply_ids=(), is_end=False, token="QQ=="),
                "回复页为空但未结束",
            ),
            (_reply_page(is_end=False), "缺下一页 pagination token"),
            (b"\x0b", "wire type"),
        )
        for response, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(BilibiliResponseError, message):
                    request(response)

    def test_grpc_next_token_has_size_and_base64_boundaries(self) -> None:
        valid = "A" * 4096
        parsed = _parse_detail_reply(_reply_page(token=valid))
        self.assertEqual(parsed["pagination"]["next_offset"], valid)

        for token, message in (("!", "合法 Base64"), ("A" * 4097, "超过 4096")):
            with self.subTest(message=message):
                with self.assertRaisesRegex(BilibiliResponseError, message):
                    _parse_detail_reply(_reply_page(token=token))

    def test_numeric_identifiers_are_ascii_and_domain_errors_are_wrapped(self) -> None:
        def no_rest(
            _base_url: str,
            _path: str,
            _params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            raise AssertionError("非法标识符不应发起 REST 请求")

        def no_grpc(_path: str, _payload: bytes) -> bytes:
            raise AssertionError("非法标识符不应发起 gRPC 请求")

        calls = (
            lambda: get_app_video_detail("av１２", no_rest),
            lambda: get_app_video_detail("av" + "9" * 5000, no_rest),
            lambda: get_app_video_detail("https://[v.bad]/video/av2", no_rest),
            lambda: get_app_comment_replies(
                "av2",
                "１２",
                rest_fetch=None,
                grpc_fetch=no_grpc,
            ),
        )
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(BilibiliInputError):
                    call()

        with self.assertRaisesRegex(BilibiliResponseError, "aid 非法"):
            get_app_comments(
                "BV1xx411c7mD",
                rest_fetch=lambda _base, _path, _params: {
                    "code": 0,
                    "data": {"aid": "１２", "bvid": "BV1xx411c7mD"},
                },
            )

    def test_limit_zero_skips_all_fetchers(self) -> None:
        calls = 0

        def rest_fetch(
            base_url: str,
            path: str,
            params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            nonlocal calls
            calls += 1
            return {}

        def grpc_fetch(path: str, payload: bytes) -> bytes:
            nonlocal calls
            calls += 1
            return b""

        comments = get_app_comments(
            "BV1xx411c7mD",
            rest_fetch=rest_fetch,
            limit=0,
            offset=900,
        )
        replies = get_app_comment_replies(
            "BV1xx411c7mD",
            "495059",
            rest_fetch=rest_fetch,
            grpc_fetch=grpc_fetch,
            limit=0,
        )

        self.assertEqual(calls, 0)
        self.assertEqual(comments["next_offset"], "900")
        self.assertEqual(comments["aid"], None)
        self.assertEqual(replies["total"], 0)
        self.assertEqual(replies["aid"], None)

    def test_invalid_options_and_payloads_fail_before_paging(self) -> None:
        def rest_fetch(
            base_url: str,
            path: str,
            params: Mapping[str, str],
        ) -> Mapping[str, Any]:
            raise AssertionError("非法输入不应发起 REST 请求")

        def grpc_fetch(path: str, payload: bytes) -> bytes:
            raise AssertionError("非法输入不应发起 gRPC 请求")

        invalid_calls = (
            lambda: get_app_comments(
                "av2",
                rest_fetch=rest_fetch,
                order="rank",
            ),
            lambda: get_app_comments(
                "av2",
                rest_fetch=rest_fetch,
                page_size=50,
            ),
            lambda: get_app_comment_replies(
                "av2",
                "1",
                rest_fetch=None,
                grpc_fetch=grpc_fetch,
                pagination_token="not base64!",
            ),
            lambda: get_app_comment_replies(
                "av2",
                "1",
                rest_fetch=None,
                grpc_fetch=grpc_fetch,
                offset=1,
                pagination_token="CAI=",
            ),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(BilibiliInputError):
                    call()

        with self.assertRaisesRegex(
            BilibiliResponseError,
            "响应缺 data",
        ):
            get_app_video_detail(
                "av2",
                lambda base_url, path, params: {"code": 0},
            )


if __name__ == "__main__":
    unittest.main()
