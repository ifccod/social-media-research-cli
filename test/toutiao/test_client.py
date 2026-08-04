from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.toutiao_reverse.client import CRAWLER_USER_AGENT, DEFAULT_USER_AGENT, ToutiaoClient
from reverse.toutiao_reverse.errors import ToutiaoError, ToutiaoInputError, ToutiaoResponseError

FIXTURES = Path(__file__).with_name("fixtures")
ARTICLE_PAYLOAD = json.loads((FIXTURES / "article_info.json").read_text(encoding="utf-8"))
VIDEO_PAYLOAD = json.loads((FIXTURES / "video_info.json").read_text(encoding="utf-8"))
VOD_PAYLOAD = json.loads((FIXTURES / "vod.json").read_text(encoding="utf-8"))
COMMENTS_PAYLOAD = json.loads((FIXTURES / "comments.json").read_text(encoding="utf-8"))
HOT_PAYLOAD = json.loads((FIXTURES / "hot.json").read_text(encoding="utf-8"))
USER_INFO_PAYLOAD = json.loads((FIXTURES / "user_info.json").read_text(encoding="utf-8"))
SEARCH_HTML = (FIXTURES / "search.html").read_text(encoding="utf-8")
PROFILE_HTML = (FIXTURES / "profile.html").read_text(encoding="utf-8")


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
    if isinstance(body, str):
        source = body
    else:
        source = json.dumps(body, ensure_ascii=False)
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


class ToutiaoClientTest(unittest.TestCase):
    def test_public_errors_and_default_headers(self) -> None:
        self.assertTrue(issubclass(ToutiaoInputError, ToutiaoError))
        self.assertTrue(issubclass(ToutiaoResponseError, ToutiaoError))
        session = FakeSession([])
        ToutiaoClient(session=session)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("application/json", session.headers["Accept"])

    def test_content_reference_accepts_ids_routes_and_share_text(self) -> None:
        content_id = "7450114952884503059"
        self.assertEqual(ToutiaoClient.resolve_content_id(content_id), content_id)
        for value in (
            f"https://www.toutiao.com/article/{content_id}/?source=fixture",
            f"https://www.toutiao.com/video/{content_id}/",
            f"https://m.toutiao.com/group/{content_id}/",
            f"https://m.toutiao.com/i{content_id}/info/",
            f"打开 https://toutiao.com/a{content_id}。",
        ):
            with self.subTest(value=value):
                self.assertEqual(ToutiaoClient.resolve_content_id(value), content_id)

    def test_content_reference_rejects_lookalikes_ports_and_bad_routes(self) -> None:
        content_id = "7450114952884503059"
        for value in (
            "",
            "123",
            f"https://toutiao.com.example/article/{content_id}/",
            f"https://example.com/article/{content_id}/",
            f"https://toutiao.com:444/article/{content_id}/",
            f"https://user@toutiao.com/article/{content_id}/",
            f"https://example.com/redirect?url=https://toutiao.com/article/{content_id}/",
            f"https://toutiao.com/trending/{content_id}/",
            f"https://toutiao.com/article/{content_id}/extra",
        ):
            with self.subTest(value=value), self.assertRaises(ToutiaoInputError):
                ToutiaoClient.resolve_content_id(value)

    def test_user_reference_accepts_token_and_strict_profile_url(self) -> None:
        token = "MS4wLjABAAAA_fixture-token-123456789"
        expected = f"https://www.toutiao.com/c/user/token/{token}/"
        self.assertEqual(ToutiaoClient.parse_user_reference(token)["url"], expected)
        self.assertEqual(ToutiaoClient.parse_user_reference(expected)["token"], token)
        padded = "Ciz_fixture-token-123456789="
        self.assertEqual(ToutiaoClient.parse_user_reference(padded)["token"], padded)
        with self.assertRaises(ToutiaoInputError):
            ToutiaoClient.parse_user_reference(f"https://toutiao.com.example/c/user/token/{token}/")
        with self.assertRaises(ToutiaoInputError):
            ToutiaoClient.parse_user_reference("https://www.toutiao.com/c/user/123/")

    def test_article_fixture_normalizes_body_media_author_stats_and_time(self) -> None:
        item = ToutiaoClient.parse_info_payload(
            ARTICLE_PAYLOAD,
            expected_id="7450114952884503059",
        )
        self.assertEqual(item["media_type"], "article")
        self.assertEqual(item["text"], "第一段任务说明。\n第二段任务完成。")
        self.assertEqual(item["images"][0]["width"], 640)
        self.assertEqual(item["author"]["id"], "51050126444")
        self.assertEqual(item["author"]["creator_uid"], "51050126444")
        self.assertEqual(item["author"]["media_id"], "51201073347")
        self.assertTrue(item["author"]["verified"])
        self.assertEqual(item["stats"], {"views": 95, "video_plays": 0, "likes": 2, "comments": 1, "reposts": 3, "saves": 4})
        self.assertEqual(item["published_at"], "2024-12-19T13:31:15+00:00")
        self.assertTrue(item["flags"]["top_pick"])

    def test_video_info_fixture_extracts_embedded_id_and_token(self) -> None:
        item = ToutiaoClient.parse_info_payload(
            VIDEO_PAYLOAD,
            expected_id="7664159782743441970",
        )
        self.assertEqual(item["media_type"], "video")
        self.assertEqual(item["video"]["id"], "vfixture123")
        self.assertEqual(item["video"]["duration_seconds"], 358)
        self.assertEqual(item["text"], "发射圆满成功。")
        self.assertTrue(item["_play_auth_token_v2"])

    def test_info_payload_rejects_empty_and_mismatched_content(self) -> None:
        with self.assertRaises(ToutiaoResponseError):
            ToutiaoClient.parse_info_payload({"success": False, "data": None})
        with self.assertRaisesRegex(ToutiaoResponseError, "expected"):
            ToutiaoClient.parse_info_payload(ARTICLE_PAYLOAD, expected_id="7664159782743441970")

    def test_play_token_is_local_decoding_with_action_and_id_checks(self) -> None:
        token = VIDEO_PAYLOAD["data"]["play_auth_token_v2"]
        query = ToutiaoClient.decode_play_auth_token(token, expected_video_id="vfixture123")
        self.assertIn("Action=GetPlayInfo", query)
        self.assertIn("video_id=vfixture123", query)
        with self.assertRaisesRegex(ToutiaoResponseError, "does not match"):
            ToutiaoClient.decode_play_auth_token(token, expected_video_id="different")
        with self.assertRaises(ToutiaoResponseError):
            ToutiaoClient.decode_play_auth_token("not-base64")

    def test_vod_fixture_normalizes_and_sorts_public_streams(self) -> None:
        video = ToutiaoClient.parse_vod_payload(VOD_PAYLOAD, expected_video_id="vfixture123")
        self.assertEqual(video["id"], "vfixture123")
        self.assertTrue(video["adaptive"])
        self.assertEqual([item["definition"] for item in video["streams"]], ["480p", "720p"])
        self.assertEqual(video["streams"][1]["height"], 720)
        self.assertEqual(video["streams"][1]["format"], "mp4")
        self.assertTrue(video["streams"][1]["url"].startswith("https://"))

    def test_get_video_performs_info_then_vod_without_page_runtime(self) -> None:
        session = FakeSession([response(VIDEO_PAYLOAD), response(VOD_PAYLOAD)])
        video = ToutiaoClient(session=session, retries=0).get_video_info("7664159782743441970")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0][0], "https://m.toutiao.com/i7664159782743441970/info/")
        self.assertTrue(session.calls[1][0].startswith("https://vod.bytedanceapi.com/?Action=GetPlayInfo"))
        self.assertEqual(video["video"]["streams"][-1]["definition"], "720p")
        self.assertNotIn("_play_auth_token_v2", video)

    def test_article_and_content_methods_enforce_or_autodetect_type(self) -> None:
        article = ToutiaoClient(
            session=FakeSession([response(ARTICLE_PAYLOAD)]), retries=0
        ).get_article_info("7450114952884503059")
        self.assertEqual(article["media_type"], "article")
        content = ToutiaoClient(
            session=FakeSession([response(VIDEO_PAYLOAD)]), retries=0
        ).get_content_info("7664159782743441970")
        self.assertEqual(content["media_type"], "video")
        with self.assertRaisesRegex(ToutiaoResponseError, "use get_video_info"):
            ToutiaoClient(
                session=FakeSession([response(VIDEO_PAYLOAD)]), retries=0
            ).get_article_info("7664159782743441970")

    def test_comments_fixture_normalizes_replies_and_pagination(self) -> None:
        result = ToutiaoClient.parse_comments_payload(
            COMMENTS_PAYLOAD,
            content_id="7450114952884503059",
        )
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["has_more"])
        self.assertEqual(result["comments"][0]["user"]["id"], "89664200362")
        self.assertEqual(result["comments"][0]["replies"][0]["text"], "祝贺！")
        self.assertEqual(result["comments"][0]["location"], "江苏")

    def test_get_comments_uses_required_aid_and_validates_window(self) -> None:
        session = FakeSession([response(COMMENTS_PAYLOAD)])
        result = ToutiaoClient(session=session, retries=0).get_comments(
            "7450114952884503059", offset=10, count=5
        )
        params = session.calls[0][1]["params"]
        self.assertEqual(params["aid"], 24)
        self.assertEqual(params["app_name"], "toutiao_web")
        self.assertEqual(params["offset"], 10)
        self.assertEqual(result["comments"][0]["likes"], 3)
        for offset, count in ((-1, 20), (0, 0), (0, 101)):
            with self.subTest(offset=offset, count=count), self.assertRaises(ToutiaoInputError):
                ToutiaoClient(session=FakeSession([])).get_comments(
                    "7450114952884503059", offset=offset, count=count
                )

    def test_search_fixture_extracts_ala_json_without_running_script(self) -> None:
        cards = ToutiaoClient.extract_search_cards(SEARCH_HTML)
        self.assertEqual(len(cards), 2)
        result = ToutiaoClient.parse_search_html(SEARCH_HTML, query="科技")
        self.assertEqual(result["count"], 2)
        by_id = {item["id"]: item for item in result["items"]}
        short = by_id["7663347831810111995"]
        self.assertEqual(short["media_type"], "short_video")
        self.assertEqual(short["title"], "别再被利空骗了！科技连跌的真相")
        self.assertEqual(short["duration_seconds"], 149)
        video = by_id["7664159782743441970"]
        self.assertEqual(video["author"]["name"], "灿烂微笑")

    def test_search_request_is_plain_get_and_keyword_is_not_interpolated(self) -> None:
        session = FakeSession([response(SEARCH_HTML, content_type="text/html")])
        result = ToutiaoClient(session=session, retries=0).search("航天 & 发射", limit=1)
        self.assertEqual(session.calls[0][0], "https://so.toutiao.com/search")
        self.assertEqual(session.calls[0][1]["params"]["keyword"], "航天 & 发射")
        self.assertEqual(result["count"], 1)

    def test_hot_fixture_normalizes_rank_label_categories_and_image(self) -> None:
        result = ToutiaoClient.parse_hot_board_payload(HOT_PAYLOAD, limit=1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["rank"], 1)
        self.assertEqual(result["items"][0]["hot_value"], 143274038)
        self.assertEqual(result["items"][0]["label"], "解读")
        self.assertEqual(result["items"][0]["categories"], ["international"])

    def test_profile_fixture_extracts_identity_stats_and_content_ids(self) -> None:
        profile = ToutiaoClient.parse_profile_html(
            PROFILE_HTML,
            token="fixture-token-1234",
            page_url="https://www.toutiao.com/c/user/token/fixture-token-1234/",
        )
        self.assertEqual(profile["name"], "天下")
        self.assertEqual(profile["stats"], {"likes": 12, "followers": 34, "following": 5})
        self.assertEqual(profile["content_ids"], ["7664159782743441970"])
        self.assertEqual(profile["avatar_url"], "https://cdn.example/profile-avatar.jpg")

    def test_profile_request_uses_crawler_ssr_and_resolves_numeric_id(self) -> None:
        token = "MS4wLjABAAAA_fixture-token-123456789"
        profile_response = response(
            PROFILE_HTML,
            url=f"https://www.toutiao.com/c/user/token/{token}/",
            content_type="text/html",
        )
        session = FakeSession([profile_response, response(VIDEO_PAYLOAD)])
        profile = ToutiaoClient(session=session, retries=0).get_user_profile(token)
        self.assertEqual(session.calls[0][1]["headers"]["User-Agent"], CRAWLER_USER_AGENT)
        self.assertEqual(session.calls[1][0], "https://m.toutiao.com/i7664159782743441970/info/")
        self.assertEqual(profile["id"], "2491926578470986")
        self.assertEqual(profile["stats"]["followers"], 34)

    def test_numeric_user_info_uses_public_app_endpoint_and_normalizes_profile(self) -> None:
        session = FakeSession([response(USER_INFO_PAYLOAD)])
        profile = ToutiaoClient(session=session, retries=0).get_user_info("1352838578180211")
        self.assertEqual(profile["id"], "1352838578180211")
        self.assertEqual(profile["name"], "Evil0ctal")
        self.assertTrue(profile["verified"])
        self.assertEqual(profile["verification"], "科技创作者")
        self.assertEqual(profile["stats"]["followers"], 115)
        self.assertEqual(session.calls[0][0], "https://ib.snssdk.com/user/profile/homepage/v6/")
        self.assertEqual(session.calls[0][1]["params"]["aid"], 13)
        self.assertIn("com.ss.android.article.news", session.calls[0][1]["headers"]["User-Agent"])
        with self.assertRaises(ToutiaoInputError):
            ToutiaoClient(session=FakeSession([])).get_user_info("not-an-id")

    def test_transport_and_retryable_statuses_back_off(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection"),
                response("slow", status=429, content_type="text/plain"),
                response(HOT_PAYLOAD),
            ]
        )
        with patch("reverse.toutiao_reverse.client.time.sleep") as sleep:
            result = ToutiaoClient(session=session, retries=2).get_hot_board(limit=1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(sleep.call_count, 2)

    def test_deterministic_http_and_invalid_json_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(ToutiaoResponseError, "HTTP 404"):
            ToutiaoClient(
                session=FakeSession([response("missing", status=404, content_type="text/plain")]),
                retries=2,
            ).get_hot_board()
        with self.assertRaisesRegex(ToutiaoResponseError, "invalid JSON"):
            ToutiaoClient(
                session=FakeSession([response("<html></html>", content_type="text/html")]),
                retries=0,
            ).get_hot_board()


if __name__ == "__main__":
    unittest.main()
