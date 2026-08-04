from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.wechat_channels_reverse.cli import main
from reverse.wechat_channels_reverse.client import DEFAULT_USER_AGENT, WeChatChannelsClient
from reverse.wechat_channels_reverse.errors import (
    WeChatChannelsError,
    WeChatChannelsInputError,
    WeChatChannelsResponseError,
)

FIXTURES = Path(__file__).with_name("fixtures")
FEED_PAYLOAD = json.loads((FIXTURES / "feed_info.json").read_text(encoding="utf-8"))
IMAGE_PAYLOAD = json.loads((FIXTURES / "image_feed.json").read_text(encoding="utf-8"))
SHORT_URI = "AH3sCoIPhH"
SHARE_URL = f"https://weixin.qq.com/sph/{SHORT_URI}"
EXPORT_ID = "export/UzFfBgAA_fixture-dynamic-id-123456789"
API_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"


def response(
    body: object,
    *,
    status: int = 201,
    url: str = API_URL,
    content_type: str = "application/json; charset=utf-8",
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["content-type"] = content_type
    source = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    result.content = source.encode("utf-8")
    result.default_encoding = "utf-8"
    return result


class FakeSession(requests.Session):
    def __init__(self, results: list[requests.Response | Exception]) -> None:
        super().__init__()
        self.results = deque(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError("unexpected HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result


class WeChatChannelsClientTest(unittest.TestCase):
    def test_public_errors_headers_and_constructor_validation(self) -> None:
        self.assertTrue(issubclass(WeChatChannelsInputError, WeChatChannelsError))
        self.assertTrue(issubclass(WeChatChannelsResponseError, WeChatChannelsError))
        session = FakeSession([])
        WeChatChannelsClient(session=session)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("application/json", session.headers["Accept"])
        self.assertEqual(session.headers["Origin"], "https://channels.weixin.qq.com")
        for kwargs in (
            {"timeout": 0},
            {"timeout": float("inf")},
            {"retries": -1},
            {"retries": True},
            {"user_agent": "bad\nheader"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(WeChatChannelsInputError):
                WeChatChannelsClient(**kwargs)  # type: ignore[arg-type]

    def test_share_reference_accepts_token_urls_preview_and_share_text(self) -> None:
        values = (
            SHORT_URI,
            SHARE_URL,
            f"http://weixin.qq.com/sph/{SHORT_URI}/?from=fixture",
            f"https://channels.weixin.qq.com/sph/{SHORT_URI}",
            (
                "https://channels.weixin.qq.com/finder-preview/pages/sph"
                f"?id={SHORT_URI}&theme=dark"
            ),
            f"打开视频号 {SHARE_URL}。",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(WeChatChannelsClient.resolve_short_uri(value), SHORT_URI)

    def test_share_reference_rejects_lookalikes_credentials_ports_and_bad_routes(self) -> None:
        values = (
            "",
            "short",
            f"https://weixin.qq.com.example/sph/{SHORT_URI}",
            f"https://user@weixin.qq.com/sph/{SHORT_URI}",
            f"https://weixin.qq.com:444/sph/{SHORT_URI}",
            f"https://weixin.qq.com/sph%2F{SHORT_URI}",
            f"https://weixin.qq.com/profile/{SHORT_URI}",
            f"https://example.com/redirect?url={SHARE_URL}",
            "https://channels.weixin.qq.com/finder-preview/pages/sph?id=bad",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(WeChatChannelsInputError):
                WeChatChannelsClient.resolve_short_uri(value)

    def test_export_id_validation(self) -> None:
        self.assertEqual(WeChatChannelsClient.resolve_export_id(EXPORT_ID), EXPORT_ID)
        for value in ("", "export/short", "other/UzFfBgAA_fixture-dynamic-id", "export/a b c"):
            with self.subTest(value=value), self.assertRaises(WeChatChannelsInputError):
                WeChatChannelsClient.resolve_export_id(value)

        with self.assertRaises(WeChatChannelsInputError):
            WeChatChannelsClient.parse_feed_payload(
                FEED_PAYLOAD,
                short_uri=SHORT_URI,
                export_id=EXPORT_ID,
            )

    def test_video_fixture_normalizes_author_counts_media_scene_and_time(self) -> None:
        item = WeChatChannelsClient.parse_feed_payload(FEED_PAYLOAD, short_uri=SHORT_URI)
        self.assertTrue(item["available"])
        self.assertEqual(item["reference"]["share_url"], SHARE_URL)
        self.assertEqual(item["author"]["nickname"], "Fixture Channel")
        self.assertEqual(item["author"]["username"], "v2_fixture@finder")
        self.assertTrue(item["author"]["verified"])
        self.assertTrue(item["author"]["avatar_url"].startswith("https://"))
        self.assertEqual(item["description"], "Fixture public feed #testing")
        self.assertEqual(item["ids"]["object_id"], "14941130915890399732")
        self.assertEqual(item["stats"]["favorites"], 13_000)
        self.assertEqual(item["stats"]["forwards"], 100_000)
        self.assertTrue(item["stats_metadata"]["favorites"]["approximate"])
        self.assertTrue(item["stats_metadata"]["forwards"]["lower_bound"])
        self.assertFalse(item["stats_metadata"]["likes"]["approximate"])
        self.assertEqual(item["media"]["type"], "video")
        self.assertEqual([entry["codec"] for entry in item["media"]["videos"]], ["h264", "h265"])
        self.assertEqual(item["media"]["videos"][0]["duration_seconds"], 23)
        self.assertEqual(item["published_at"], "2025-03-05T04:22:09+00:00")
        self.assertEqual(item["scene"]["comment_scene"], 39)
        self.assertEqual(item["scene"]["dynamic_export_id"], EXPORT_ID)
        self.assertEqual(item["raw"]["errCode"], 0)

    def test_image_fixture_normalizes_exact_counts_and_deduplicates_images(self) -> None:
        item = WeChatChannelsClient.parse_feed_payload(IMAGE_PAYLOAD, short_uri=SHORT_URI)
        self.assertEqual(item["media"]["type"], "images")
        self.assertEqual(len(item["media"]["images"]), 2)
        self.assertEqual(item["media"]["images"][0]["width"], 1080)
        self.assertTrue(item["media"]["images"][0]["url"].startswith("https://"))
        self.assertEqual(item["stats"]["likes"], 34)
        self.assertFalse(item["stats_metadata"]["likes"]["approximate"])

    def test_short_uri_request_contract_and_normalized_result(self) -> None:
        session = FakeSession([response(FEED_PAYLOAD)])
        item = WeChatChannelsClient(session=session).get_feed(SHARE_URL)
        self.assertEqual(item["author"]["nickname"], "Fixture Channel")
        url, kwargs = session.calls[0]
        self.assertEqual(url, API_URL)
        self.assertEqual(
            kwargs["json"],
            {"baseReq": {"generalToken": ""}, "shortUri": SHORT_URI},
        )
        self.assertFalse(kwargs["allow_redirects"])
        self.assertIn(f"id={SHORT_URI}", kwargs["headers"]["Referer"])  # type: ignore[index]

    def test_export_id_request_contract_and_warning_response(self) -> None:
        warning = {
            "data": {
                "errMsg": {"type": 2, "title": "此内容暂时无法播放"},
                "sceneInfo": {
                    "dynamicExportId": EXPORT_ID,
                    "commentScene": 39,
                    "expiredTime": 1741152129,
                },
            },
            "errCode": 0,
            "errMsg": "",
        }
        session = FakeSession([response(warning)])
        item = WeChatChannelsClient(session=session).get_feed_by_export_id(EXPORT_ID)
        self.assertFalse(item["available"])
        self.assertEqual(item["warning"]["type"], 2)
        self.assertEqual(item["warning"]["title"], "此内容暂时无法播放")
        self.assertEqual(item["reference"]["export_id"], EXPORT_ID)
        self.assertEqual(
            session.calls[0][1]["json"],
            {"baseReq": {"generalToken": ""}, "exportId": EXPORT_ID},
        )

    def test_json_api_and_server_errors_are_structured(self) -> None:
        invalid_json = FakeSession([response("not json")])
        with self.assertRaisesRegex(WeChatChannelsResponseError, "not JSON"):
            WeChatChannelsClient(session=invalid_json).get_feed(SHORT_URI)

        api_error = FakeSession(
            [response({"errCode": -1, "errMsg": "permission verification failed"}, status=401)]
        )
        with self.assertRaises(WeChatChannelsResponseError) as raised:
            WeChatChannelsClient(session=api_error).get_feed(SHORT_URI)
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.error_code, -1)
        self.assertFalse(raised.exception.retryable)

        server_error = FakeSession(
            [response({"error": {"name": "ServerError", "message": "请求异常"}}, status=200)]
        )
        with self.assertRaises(WeChatChannelsResponseError) as raised:
            WeChatChannelsClient(session=server_error).get_feed(SHORT_URI)
        self.assertEqual(raised.exception.error_code, "ServerError")
        self.assertEqual(str(raised.exception), "请求异常")

    def test_transient_failures_retry_but_deterministic_failures_do_not(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture disconnect"),
                response({"errCode": 503, "errMsg": "busy"}, status=503),
                response(FEED_PAYLOAD),
            ]
        )
        with patch("reverse.wechat_channels_reverse.client.time.sleep") as sleep:
            item = WeChatChannelsClient(session=session, retries=2).get_feed(SHORT_URI)
        self.assertEqual(item["author"]["nickname"], "Fixture Channel")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

        deterministic = FakeSession(
            [response({"errCode": -1, "errMsg": "bad reference"}, status=401)]
        )
        with self.assertRaises(WeChatChannelsResponseError):
            WeChatChannelsClient(session=deterministic, retries=2).get_feed(SHORT_URI)
        self.assertEqual(len(deterministic.calls), 1)


class WeChatChannelsCliTest(unittest.TestCase):
    def test_cli_dispatches_json_and_reports_domain_errors(self) -> None:
        with patch.object(
            WeChatChannelsClient,
            "get_feed",
            return_value={"author": {"nickname": "Fixture Channel"}},
        ), patch("builtins.print") as output:
            self.assertEqual(main(["feed", SHARE_URL]), 0)
        self.assertIn("Fixture Channel", output.call_args.args[0])

        with patch.object(
            WeChatChannelsClient,
            "get_feed_by_export_id",
            side_effect=WeChatChannelsResponseError("fixture error"),
        ), patch("builtins.print") as output:
            self.assertEqual(main(["export", EXPORT_ID]), 1)
        self.assertEqual(output.call_args.args[0], "error: fixture error")


if __name__ == "__main__":
    unittest.main()
