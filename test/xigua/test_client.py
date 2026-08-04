from __future__ import annotations

import json
import unittest
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.xigua_reverse.cli import main as cli_main
from reverse.xigua_reverse.client import DEFAULT_USER_AGENT, XiguaClient
from reverse.xigua_reverse.crypto import PLAY_URL_PASSPHRASE, decrypt_play_url
from reverse.xigua_reverse.errors import XiguaError, XiguaInputError, XiguaResponseError

FIXTURES = Path(__file__).with_name("fixtures")
VIDEO = json.loads((FIXTURES / "video.json").read_text(encoding="utf-8"))
VIDEO_DATA = json.loads((FIXTURES / "video_data.json").read_text(encoding="utf-8"))
COMMENTS = json.loads((FIXTURES / "comments.json").read_text(encoding="utf-8"))
USER = json.loads((FIXTURES / "user.json").read_text(encoding="utf-8"))
POSTS = json.loads((FIXTURES / "posts.json").read_text(encoding="utf-8"))
SEARCH = json.loads((FIXTURES / "search.json").read_text(encoding="utf-8"))
HOT = json.loads((FIXTURES / "hot.json").read_text(encoding="utf-8"))
VIDEO_PAGE = (FIXTURES / "video_page.html").read_text(encoding="utf-8")
VIDEO_ID = "7354954305222377999"
USER_ID = "109186127659"
PLAY_URL = "https://v6-xgwap.ixigua.com/video/fixture.mp4?mime_type=video_mp4&token=fixture"
PLAY_CIPHERTEXT = (
    "ej1F7JHHuJzk5wvmhGlX5X3O9DfE05L6xaG5mg8fpFlBq7dqufgfapA3j/qm7IFU"
    "DsljbDm6j2yh5b3mKc0PY4UIkz/EcCJof8gwdgiBDvCO3YTN0MjMx81XkVGdsF2U"
)


def response(
    body: object,
    *,
    status: int = 200,
    url: str = "",
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

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError("unexpected fake HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result


class XiguaCryptoTest(unittest.TestCase):
    def test_cryptojs_fixed_vector_decrypts_with_python_stdlib(self) -> None:
        self.assertEqual(PLAY_URL_PASSPHRASE, "xigua.fe.web_mobile")
        self.assertEqual(decrypt_play_url(PLAY_CIPHERTEXT), PLAY_URL)

    def test_encrypted_play_url_rejects_bad_envelopes_and_plaintext(self) -> None:
        for value in ("", "not-base64", "==AAAA", "https://example.com/video.mp4"):
            with self.subTest(value=value), self.assertRaises(XiguaResponseError):
                decrypt_play_url(value)
        with self.assertRaises(XiguaResponseError):
            decrypt_play_url(PLAY_CIPHERTEXT, passphrase="incorrect")


class XiguaClientTest(unittest.TestCase):
    def test_public_errors_constructor_and_headers(self) -> None:
        self.assertTrue(issubclass(XiguaInputError, XiguaError))
        self.assertTrue(issubclass(XiguaResponseError, XiguaError))
        session = FakeSession([])
        XiguaClient(session=session)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("application/json", session.headers["Accept"])
        for kwargs in ({"timeout": 0}, {"timeout": float("inf")}, {"retries": -1}, {"user_agent": "bad\nua"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(XiguaInputError):
                XiguaClient(session=FakeSession([]), **kwargs)

    def test_video_and_user_references_are_strict(self) -> None:
        for value in (
            VIDEO_ID,
            f"https://m.ixigua.com/video/{VIDEO_ID}",
            f"https://www.ixigua.com/{'i' + VIDEO_ID}/",
            f"m.ixigua.com/i{VIDEO_ID}/info/video/",
        ):
            with self.subTest(value=value):
                self.assertEqual(XiguaClient.resolve_video_id(value), VIDEO_ID)
        for value in (
            USER_ID,
            f"https://m.ixigua.com/user/{USER_ID}?app=video_article",
            f"https://www.ixigua.com/home/{USER_ID}/",
        ):
            with self.subTest(value=value):
                self.assertEqual(XiguaClient.resolve_user_id(value), USER_ID)

    def test_references_reject_lookalikes_credentials_ports_and_bad_paths(self) -> None:
        for value in (
            "",
            "1234",
            f"https://ixigua.com.example/video/{VIDEO_ID}",
            f"https://example.com/video/{VIDEO_ID}",
            f"https://user@ixigua.com/video/{VIDEO_ID}",
            f"https://ixigua.com:444/video/{VIDEO_ID}",
            f"https://ixigua.com:bad/video/{VIDEO_ID}",
            f"https://ixigua.com/video/{VIDEO_ID}/extra",
            f"https://ixigua.com/search?video={VIDEO_ID}",
        ):
            with self.subTest(value=value), self.assertRaises(XiguaInputError):
                XiguaClient.resolve_video_id(value)

    def test_video_fixture_normalizes_identity_author_stats_and_timestamp(self) -> None:
        item = XiguaClient.parse_video_payload(VIDEO, expected_id=VIDEO_ID)
        self.assertEqual(item["id"], VIDEO_ID)
        self.assertEqual(item["video_id"], "v0201ag10000co90nejc77u3894773cg")
        self.assertEqual(item["author"]["id"], USER_ID)
        self.assertEqual(item["author"]["followers"], 1197253)
        self.assertEqual(item["stats"], {"views": 1467138, "likes": 42604, "comments": 1027})
        self.assertEqual(item["published_at"], "2024-04-07T02:59:05+00:00")
        self.assertTrue(item["cover_url"].startswith("https://"))

    def test_video_raw_and_v2_methods_use_plain_info_endpoint(self) -> None:
        session = FakeSession([response(VIDEO_DATA), response(VIDEO_DATA)])
        client = XiguaClient(session=session, retries=0)
        raw = client.get_video_data(VIDEO_ID)
        normalized = client.get_video_info_v2(f"https://m.ixigua.com/video/{VIDEO_ID}")
        self.assertEqual(raw["gid"], VIDEO_ID)
        self.assertEqual(normalized["title"], raw["title"])
        for url, kwargs in session.calls:
            self.assertEqual(url, "https://m.ixigua.com/xg/api/wap/video/getInfoByGid")
            self.assertEqual(kwargs["params"], {"gid": VIDEO_ID})

    def test_video_response_requires_success_and_matching_id(self) -> None:
        with self.assertRaises(XiguaResponseError):
            XiguaClient.parse_video_payload({"success": False, "data": {}})
        with self.assertRaisesRegex(XiguaResponseError, "does not match"):
            XiguaClient.parse_video_payload(VIDEO, expected_id="7354954305222377000")

    def test_play_page_extracts_ssr_and_decrypts_locally(self) -> None:
        result = XiguaClient.parse_play_page(VIDEO_PAGE, expected_id=VIDEO_ID)
        self.assertEqual(result["url"], PLAY_URL)
        self.assertEqual(result["definitions"], ["360p", "720p", "1080p"])
        self.assertEqual(result["duration_seconds"], 189.569)
        self.assertEqual(result["video_id"], "v0201ag10000co90nejc77u3894773cg")

    def test_play_json_decrypts_the_same_cryptojs_envelope(self) -> None:
        result = XiguaClient.parse_play_data_payload(VIDEO_DATA, expected_id=VIDEO_ID)
        self.assertEqual(result["url"], PLAY_URL)
        self.assertEqual(result["definitions"], ["360p", "720p", "1080p"])

    def test_play_request_is_one_mobile_html_get(self) -> None:
        session = FakeSession([response(VIDEO_DATA)])
        result = XiguaClient(session=session, retries=0).get_video_play_url(VIDEO_ID)
        self.assertEqual(result["url"], PLAY_URL)
        self.assertEqual(session.calls[0][0], "https://m.ixigua.com/xg/api/wap/video/getInfoByGid")
        self.assertEqual(session.calls[0][1]["params"], {"gid": VIDEO_ID})

    def test_play_page_rejects_missing_data_mismatch_and_tampering(self) -> None:
        with self.assertRaisesRegex(XiguaResponseError, "window._SSR_DATA"):
            XiguaClient.parse_play_page("<html><script>{}</script></html>")
        with self.assertRaisesRegex(XiguaResponseError, "does not match"):
            XiguaClient.parse_play_page(VIDEO_PAGE, expected_id="7354954305222377000")
        with self.assertRaises(XiguaResponseError):
            XiguaClient.parse_play_page(VIDEO_PAGE.replace(PLAY_CIPHERTEXT, PLAY_CIPHERTEXT[:-2] + "AA"))

    def test_comments_fixture_normalizes_replies_and_pagination(self) -> None:
        result = XiguaClient.parse_comments_payload(COMMENTS, video_id=VIDEO_ID)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total"], 1027)
        self.assertEqual(result["offset"], 2)
        self.assertEqual(result["comments"][0]["user"]["id"], "4494411680452766")
        self.assertEqual(result["comments"][0]["replies"][0]["text"], "fixture reply")
        self.assertTrue(result["comments"][0]["user"]["avatar_url"].startswith("https://"))

    def test_comments_request_uses_required_mobile_parameters(self) -> None:
        session = FakeSession([response(COMMENTS)])
        result = XiguaClient(session=session, retries=0).get_comments(VIDEO_ID, offset=10, count=5)
        self.assertEqual(result["count"], 1)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["aid"], 3586)
        self.assertEqual(params["group_id"], VIDEO_ID)
        self.assertEqual(params["tab_index"], 0)
        self.assertEqual((params["offset"], params["count"]), (10, 5))
        for offset, count in ((-1, 20), (0, 0), (0, 101)):
            with self.subTest(offset=offset, count=count), self.assertRaises(XiguaInputError):
                XiguaClient(session=FakeSession([])).get_comments(VIDEO_ID, offset=offset, count=count)

    def test_user_fixture_normalizes_profile_and_statistics(self) -> None:
        result = XiguaClient.parse_user_payload(USER, expected_id=USER_ID)
        self.assertEqual(result["name"], "十四毅")
        self.assertEqual(result["location"], "河南")
        self.assertEqual(result["stats"]["followers"], 1197254)
        self.assertEqual(result["stats"]["videos"], 612)
        self.assertEqual(result["stats"]["article_likes"], 4541307)
        self.assertTrue(result["background_url"].startswith("https://"))

    def test_user_request_uses_aid_app_id_and_numeric_user_id(self) -> None:
        session = FakeSession([response(USER)])
        profile = XiguaClient(session=session, retries=0).get_user(USER_ID)
        self.assertEqual(profile["id"], USER_ID)
        self.assertEqual(session.calls[0][0], "https://m.ixigua.com/video/app/user/userhome/v8/")
        self.assertEqual(
            session.calls[0][1]["params"],
            {"aid": 3586, "to_user_id": USER_ID, "app_id": 32},
        )

    def test_posts_fixture_normalizes_media_and_cursor(self) -> None:
        result = XiguaClient.parse_posts_payload(POSTS, user_id=USER_ID, offset=4)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["offset"], 4)
        self.assertEqual(result["next_offset"], 6)
        self.assertEqual(result["max_behot_time"], "1725616020")
        self.assertEqual(result["items"][0]["stats"]["views"], 29703)
        self.assertEqual(result["items"][0]["duration_seconds"], 204)
        self.assertEqual(result["items"][1]["author"]["name"], "十四毅")

    def test_posts_request_passes_cursor_without_interpolation(self) -> None:
        session = FakeSession([response(POSTS)])
        client = XiguaClient(session=session, retries=0)
        result = client.get_user_posts(
            USER_ID,
            offset=3,
            max_behot_time="1725616020",
            count=3,
        )
        self.assertEqual(result["count"], 2)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["max_behot_time"], "1725616020")
        self.assertEqual(params["offset"], 3)
        self.assertEqual(params["orderby"], "publishtime")
        self.assertEqual(params["tab"], 1)
        for cursor in (True, "bad-cursor", "-1"):
            with self.subTest(cursor=cursor), self.assertRaises(XiguaInputError):
                client.get_user_posts(USER_ID, max_behot_time=cursor)

    def test_search_filters_non_video_cells_and_normalizes_public_video(self) -> None:
        result = XiguaClient.parse_search_payload(SEARCH, query="航天", offset=4, limit=10)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["offset"], 4)
        self.assertEqual(result["next_offset"], 6)
        self.assertEqual(result["items"][0]["id"], "7020315917619986975")
        self.assertEqual(result["items"][0]["stats"]["views"], 568796)
        self.assertEqual(result["items"][0]["author"]["name"], "全球世界观")

    def test_search_request_supports_market_filters_as_query_parameters(self) -> None:
        session = FakeSession([response(SEARCH)])
        result = XiguaClient(session=session, retries=0).search(
            "航天 & 发射",
            offset=10,
            order_type="play_count",
            min_duration=1,
            max_duration=180,
            limit=5,
        )
        self.assertEqual(result["query"], "航天 & 发射")
        params = session.calls[0][1]["params"]
        self.assertEqual(params["keyword"], "航天 & 发射")
        self.assertEqual(params["order_type"], "play_count")
        self.assertEqual((params["min_duration"], params["max_duration"]), (1, 180))
        for kwargs in (
            {"keyword": ""},
            {"keyword": "x", "order_type": "invalid"},
            {"keyword": "x", "min_duration": 20, "max_duration": 10},
            {"keyword": "x", "limit": 101},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(XiguaInputError):
                XiguaClient(session=FakeSession([])).search(**kwargs)

    def test_hot_fixture_normalizes_words_long_videos_and_recommendations(self) -> None:
        result = XiguaClient.parse_hot_payload(HOT, limit=1)
        self.assertEqual(result["hot_search_words"][0]["text"], "动画《熊出没》")
        self.assertEqual(result["hot_long_videos"][0]["title"], "黑狐")
        self.assertEqual(result["hot_long_videos"][0]["rating"], 7.4)
        self.assertEqual(result["recommendations"][0]["id"], "7412111535362343458")

    def test_hot_request_uses_anonymous_initial_page_route(self) -> None:
        session = FakeSession([response(HOT)])
        result = XiguaClient(session=session, retries=0).get_hot_recommendations(limit=2)
        self.assertEqual(len(result["hot_search_words"]), 2)
        self.assertEqual(session.calls[0][0], "https://m.ixigua.com/video/app/article/hot_recommend/v1/")
        self.assertEqual(session.calls[0][1]["params"], {"aid": 3586, "device_id": ""})

    def test_transport_and_transient_statuses_retry_with_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection"),
                response("busy", status=503, content_type="text/plain"),
                response(VIDEO),
            ]
        )
        with patch("reverse.xigua_reverse.client.time.sleep") as sleep:
            result = XiguaClient(session=session, retries=2).get_video_info(VIDEO_ID)
        self.assertEqual(result["id"], VIDEO_ID)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

    def test_deterministic_http_and_invalid_json_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(XiguaResponseError, "HTTP 404"):
            XiguaClient(
                session=FakeSession([response("missing", status=404, content_type="text/plain")]),
                retries=2,
            ).get_video_info(VIDEO_ID)
        with self.assertRaisesRegex(XiguaResponseError, "invalid JSON"):
            XiguaClient(
                session=FakeSession([response("<html></html>", content_type="text/html")]),
                retries=0,
            ).get_video_info(VIDEO_ID)

    def test_cli_offline_play_fixture_prints_json(self) -> None:
        output = StringIO()
        errors = StringIO()
        argv = [
            "xigua_reverse",
            "parse",
            "play",
            str(FIXTURES / "video_page.html"),
            "--id",
            VIDEO_ID,
        ]
        with patch("sys.argv", argv), redirect_stdout(output), redirect_stderr(errors):
            status = cli_main()
        self.assertEqual(status, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(json.loads(output.getvalue())["url"], PLAY_URL)


if __name__ == "__main__":
    unittest.main()
