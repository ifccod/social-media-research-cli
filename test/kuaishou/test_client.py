from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.kuaishou_reverse.client import DEFAULT_USER_AGENT, KuaishouClient
from reverse.kuaishou_reverse.cli import _parser, _run
from reverse.kuaishou_reverse.errors import KuaishouError, KuaishouInputError, KuaishouResponseError

FIXTURES = Path(__file__).with_name("fixtures")
SHARE_PAGE = (FIXTURES / "share_page.html").read_text(encoding="utf-8")
HOT_LIST = (FIXTURES / "hot_list.json").read_text(encoding="utf-8")


def response(
    source: str,
    *,
    status: int = 200,
    url: str = "https://m.gifshow.com/fw/photo/3x73wr9tdt7nxqy",
    content_type: str = "text/html; charset=utf-8",
    history: list[requests.Response] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["content-type"] = content_type
    result.content = source.encode("utf-8")
    result.default_encoding = "utf-8"
    result.history = history or []
    return result


class FakeSession(requests.Session):
    def __init__(self, results: list[requests.Response | Exception]) -> None:
        super().__init__()
        self.results = deque(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError("unexpected fake HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError("unexpected fake HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class KuaishouClientTest(unittest.TestCase):
    def test_public_error_hierarchy(self) -> None:
        self.assertTrue(issubclass(KuaishouInputError, KuaishouError))
        self.assertTrue(issubclass(KuaishouResponseError, KuaishouError))

    def test_reference_parser_accepts_public_share_forms(self) -> None:
        short = KuaishouClient.resolve_reference("复制打开 https://v.kuaishou.com/GKTpYm 看看！")
        self.assertEqual(short["short_code"], "GKTpYm")
        self.assertEqual(short["source_url"], "https://v.kuaishou.com/GKTpYm")

        direct = KuaishouClient.resolve_reference(
            "https://www.kuaishou.com/short-video/3x73wr9tdt7nxqy?shareToken=TOKEN123"
        )
        self.assertEqual(direct["photo_id"], "3x73wr9tdt7nxqy")
        self.assertEqual(direct["share_token"], "TOKEN123")

        token = KuaishouClient.resolve_reference("www.kuaishou.com/f/X-f2k5KJpiXN1SY")
        self.assertEqual(token["share_token"], "X-f2k5KJpiXN1SY")

        raw = KuaishouClient.resolve_reference("3x73wr9tdt7nxqy")
        self.assertEqual(
            raw["source_url"],
            "https://www.kuaishou.com/short-video/3x73wr9tdt7nxqy",
        )

    def test_reference_parser_rejects_foreign_and_malformed_urls(self) -> None:
        for value in (
            "https://example.com/short-video/3x73wr9tdt7nxqy",
            "https://kuaishou.com.example/short-video/3x73wr9tdt7nxqy",
            "https://www.kuaishou.com/profile/3xz63mn6fngqtiq",
            "not a share",
        ):
            with self.subTest(value=value), self.assertRaises(KuaishouInputError):
                KuaishouClient.resolve_reference(value)

    def test_fixture_hydration_normalizes_video_author_stats_and_sound(self) -> None:
        post = KuaishouClient.parse_share_html(
            SHARE_PAGE,
            expected_photo_id="3x73wr9tdt7nxqy",
        )

        self.assertEqual(post["photo_id"], "3x73wr9tdt7nxqy")
        self.assertEqual(post["internal_photo_id"], "5213479667346575810")
        self.assertEqual(post["media_type"], "video")
        self.assertEqual(post["title"], "外 星 鸭 脖")
        self.assertEqual(post["published_timestamp"], 1731058886)
        self.assertEqual(post["duration_seconds"], 58.75)
        self.assertEqual(post["statistics"]["views"], 1835143)
        self.assertEqual(post["statistics"]["shares"], 6293)
        self.assertEqual(post["cover_url"], "https://p.example.test/cover.jpg?fixture=1")
        self.assertEqual(len(post["videos"]), 4)
        self.assertEqual(post["videos"][2]["codec"], "avc")
        self.assertEqual(post["videos"][3]["quality_type"], "1080p")
        self.assertEqual(post["author"]["eid"], "3xz63mn6fngqtiq")
        self.assertEqual(post["author_profile"]["followers"], 4198320)
        self.assertEqual(post["author_profile"]["post_count"], 255)
        self.assertEqual(post["sound"]["id"], "21401564063")
        self.assertEqual(post["sound"]["audio_urls"][0]["url"], "https://audio.example.test/sound.m4a")

    def test_album_hydration_collects_static_images(self) -> None:
        state = {
            "loader": {
                "photo": {
                    "photoId": "9001",
                    "caption": "fixture album",
                    "timestamp": 1710000000000,
                    "userEid": "album-user",
                    "photoType": "ATLAS",
                    "atlas": {
                        "list": [
                            {"url": "https://img.example.test/one.jpg", "cdn": "img-1"},
                            {"url": "https://img.example.test/two.jpg", "cdn": "img-2"},
                        ]
                    },
                }
            }
        }
        source = f"<script>window.INIT_STATE = {json.dumps(state)};</script>"
        post = KuaishouClient.parse_share_html(source, expected_photo_id="album-public-id")
        self.assertEqual(post["media_type"], "album")
        self.assertEqual(len(post["images"]), 2)
        self.assertIsNone(post["video_url"])

    def test_get_post_follows_redirects_and_merges_url_identifiers(self) -> None:
        intermediate = response(
            "",
            status=302,
            url=(
                "https://www.kuaishou.com/short-video/3x73wr9tdt7nxqy"
                "?shareToken=X-f2k5KJpiXN1SY&authorId=3xz63mn6fngqtiq"
            ),
        )
        final_url = (
            "https://m.gifshow.com/fw/photo/3x73wr9tdt7nxqy"
            "?shareToken=X-f2k5KJpiXN1SY&userId=3xz63mn6fngqtiq"
        )
        session = FakeSession([response(SHARE_PAGE, url=final_url, history=[intermediate])])
        client = KuaishouClient(session=session, retries=0)

        post = client.get_post("https://www.kuaishou.com/f/X-f2k5KJpiXN1SY")

        self.assertEqual(post["photo_id"], "3x73wr9tdt7nxqy")
        self.assertEqual(post["share_token"], "X-f2k5KJpiXN1SY")
        self.assertEqual(post["share_user_id"], "3xz63mn6fngqtiq")
        self.assertEqual(post["resolved_url"], final_url)
        self.assertEqual(len(post["redirect_chain"]), 3)
        self.assertEqual(session.calls[0][1]["allow_redirects"], True)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)

    def test_resolve_reports_hydration_without_parsing_media(self) -> None:
        session = FakeSession(
            [
                response(
                    SHARE_PAGE,
                    url=(
                        "https://v.m.chenzhongtech.com/fw/photo/3xm2frwx5z6bnyk"
                        "?shareToken=XaOJrFveeeNhFTq&userId=3xuk66hz8hvt23e"
                    ),
                )
            ]
        )
        result = KuaishouClient(session=session, retries=0).resolve_share(
            "https://v.kuaishou.com/GKTpYm"
        )
        self.assertEqual(result["short_code"], "GKTpYm")
        self.assertEqual(result["photo_id"], "3xm2frwx5z6bnyk")
        self.assertEqual(result["share_token"], "XaOJrFveeeNhFTq")
        self.assertTrue(result["has_hydration"])

    def test_gate_and_missing_photo_data_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(KuaishouResponseError, "JSON gate.*result=2"):
            KuaishouClient.extract_init_state(
                '{"result":2,"error_msg":null,"request_id":"fixture-request"}'
            )
        with self.assertRaisesRegex(KuaishouResponseError, "public photo data"):
            KuaishouClient.parse_share_html(
                '<script>window.INIT_STATE = {"loader":{"result":1}};</script>'
            )
        with self.assertRaisesRegex(KuaishouResponseError, "window.INIT_STATE"):
            KuaishouClient.extract_init_state("<html>missing hydration</html>")

    def test_transport_and_transient_http_failures_retry(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection error"),
                response("busy", status=503),
                response(SHARE_PAGE),
            ]
        )
        client = KuaishouClient(session=session, retries=2)
        with patch("reverse.kuaishou_reverse.client.time.sleep") as sleep:
            post = client.get_post("3x73wr9tdt7nxqy")
        self.assertEqual(post["photo_id"], "3x73wr9tdt7nxqy")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

    def test_deterministic_http_failure_does_not_retry(self) -> None:
        session = FakeSession([response("missing", status=404), response(SHARE_PAGE)])
        client = KuaishouClient(session=session, retries=2)
        with self.assertRaisesRegex(KuaishouResponseError, "HTTP 404"):
            client.get_post("3x73wr9tdt7nxqy")
        self.assertEqual(len(session.calls), 1)

    def test_hot_list_fixture_normalizes_and_limits_items(self) -> None:
        result = KuaishouClient.parse_hot_list_payload(HOT_LIST, limit=2)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["available"], 3)
        self.assertEqual(result["cursor"], "no_more")
        self.assertFalse(result["has_more"])
        self.assertEqual(result["items"][0]["rank"], 0)
        self.assertIsNone(result["items"][0]["hot_value"])
        self.assertEqual(result["items"][0]["photo_ids"], ["3xfixturePinned"])
        self.assertEqual(
            result["items"][1]["primary_photo_id"],
            "3xfixtureNews1",
        )
        self.assertIn("%E7%83%AD", result["items"][1]["search_url"])

    def test_hot_list_posts_graphql_contract_and_retries(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection error"),
                response("busy", status=503),
                response(
                    HOT_LIST,
                    url="https://www.kuaishou.com/graphql",
                    content_type="application/json",
                ),
            ]
        )
        client = KuaishouClient(session=session, retries=2)
        with patch("reverse.kuaishou_reverse.client.time.sleep") as sleep:
            result = client.get_hot_list(limit=1)

        self.assertEqual(result["total"], 1)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])
        request_url, kwargs = session.calls[-1]
        self.assertEqual(request_url, "https://www.kuaishou.com/graphql")
        self.assertEqual(kwargs["json"]["operationName"], "hotRankQuery")
        self.assertEqual(kwargs["json"]["variables"], {"page": "home"})
        self.assertIn("visionHotRank", kwargs["json"]["query"])
        self.assertEqual(kwargs["headers"]["Origin"], "https://www.kuaishou.com")
        self.assertIn("Chrome/150.0.0.0", kwargs["headers"]["User-Agent"])

    def test_hot_list_validation_and_schema_errors(self) -> None:
        session = FakeSession([])
        client = KuaishouClient(session=session, retries=0)
        self.assertEqual(client.get_hot_list(limit=0)["total"], 0)
        self.assertEqual(session.calls, [])

        for limit in (-1, 51, True):
            with self.subTest(limit=limit), self.assertRaises(KuaishouInputError):
                client.get_hot_list(limit=limit)

        invalid_payloads = (
            "",
            "{}",
            '{"errors":[{"message":"blocked"}],"data":null}',
            '{"data":{"visionHotRank":{"result":21,"items":[]}}}',
            '{"data":{"visionHotRank":{"result":1,"items":{}}}}',
            (
                '{"data":{"visionHotRank":{"result":1,"items":['
                '{"rank":1,"id":"topic","name":"topic","photoIds":["!"]}]}}}'
            ),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(
                KuaishouResponseError
            ):
                KuaishouClient.parse_hot_list_payload(payload, limit=1)

    def test_hot_list_cli_dispatches_limit(self) -> None:
        args = _parser().parse_args(["hot-list", "--limit", "2"])
        with patch("reverse.kuaishou_reverse.cli.KuaishouClient") as client_type:
            client_type.return_value.get_hot_list.return_value = {"total": 2}
            result = _run(args)

        self.assertEqual(result, {"total": 2})
        client_type.return_value.get_hot_list.assert_called_once_with(limit=2)


if __name__ == "__main__":
    unittest.main()
