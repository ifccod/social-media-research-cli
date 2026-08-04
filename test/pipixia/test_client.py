from __future__ import annotations

import copy
import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.pipixia_reverse.client import APP_ID, APP_NAME, DEFAULT_USER_AGENT, PiPiXiaClient
from reverse.pipixia_reverse.errors import PiPiXiaError, PiPiXiaInputError, PiPiXiaResponseError

FIXTURES = Path(__file__).with_name("fixtures")
POST_COMMENTS = json.loads((FIXTURES / "post_comments.json").read_text(encoding="utf-8"))
USER = json.loads((FIXTURES / "user.json").read_text(encoding="utf-8"))
FOLLOWERS = json.loads((FIXTURES / "followers.json").read_text(encoding="utf-8"))
HOT = json.loads((FIXTURES / "hot.json").read_text(encoding="utf-8"))
HASHTAG = json.loads((FIXTURES / "hashtag.json").read_text(encoding="utf-8"))

CELL_ID = "7411193113223371043"
USER_ID = "1310254082831248"
HASHTAG_ID = "129559"


def response(
    payload: object,
    *,
    status: int = 200,
    url: str = "https://api.pipix.com/bds/test/",
    content_type: str = "application/json; charset=utf-8",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["content-type"] = content_type
    if headers:
        result.headers.update(headers)
    source = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
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
        return result

    def post(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError("unexpected fake HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class PiPiXiaClientTest(unittest.TestCase):
    def test_error_hierarchy_and_constructor_validation(self) -> None:
        self.assertTrue(issubclass(PiPiXiaInputError, PiPiXiaError))
        self.assertTrue(issubclass(PiPiXiaResponseError, PiPiXiaError))
        for kwargs in (
            {"timeout": 0},
            {"timeout": float("nan")},
            {"retries": -1},
            {"retries": True},
            {"user_agent": "bad\nheader"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PiPiXiaInputError):
                PiPiXiaClient(**kwargs)

    def test_local_reference_parsers_accept_public_forms(self) -> None:
        self.assertEqual(PiPiXiaClient.resolve_cell_id(CELL_ID), CELL_ID)
        self.assertEqual(
            PiPiXiaClient.resolve_cell_id(
                f"复制后打开 https://h5.pipix.com/item/{CELL_ID}?source=share 看看"
            ),
            CELL_ID,
        )
        self.assertEqual(
            PiPiXiaClient.resolve_user_id(f"https://h5.pipix.com/user/{USER_ID}"),
            USER_ID,
        )
        self.assertEqual(
            PiPiXiaClient.resolve_hashtag_id(
                f"https://www.pipix.com/hashtag/{HASHTAG_ID}"
            ),
            HASHTAG_ID,
        )

    def test_reference_parsers_reject_lookalikes_credentials_and_short_static_use(self) -> None:
        for value in (
            f"https://example.com/item/{CELL_ID}",
            f"https://pipix.com.example/item/{CELL_ID}",
            f"https://user:pass@h5.pipix.com/item/{CELL_ID}",
            f"https://h5.pipix.com/item/{CELL_ID}#fragment",
            "not a share",
        ):
            with self.subTest(value=value), self.assertRaises(PiPiXiaInputError):
                PiPiXiaClient.resolve_cell_id(value)
        with self.assertRaisesRegex(PiPiXiaInputError, "client instance"):
            PiPiXiaClient.resolve_cell_id("https://h5.pipix.com/s/wrp2m_sD-kU/")

    def test_short_share_is_resolved_manually_inside_allowed_hosts(self) -> None:
        redirect = response(
            "redirect",
            status=302,
            url="https://h5.pipix.com/s/wrp2m_sD-kU/",
            content_type="text/html",
            headers={"location": f"/item/{CELL_ID}"},
        )
        session = FakeSession([redirect])
        client = PiPiXiaClient(session=session, retries=0)

        result = client.resolve_share("分享 https://h5.pipix.com/s/wrp2m_sD-kU/ 打开")

        self.assertEqual(result["cell_id"], CELL_ID)
        self.assertEqual(result["short_code"], "wrp2m_sD-kU")
        self.assertEqual(result["resolved_url"], f"https://h5.pipix.com/item/{CELL_ID}")
        self.assertEqual(len(result["redirect_chain"]), 2)
        self.assertEqual(session.calls[0][1]["allow_redirects"], False)

        foreign = FakeSession(
            [
                response(
                    "redirect",
                    status=302,
                    headers={"location": f"https://example.com/item/{CELL_ID}"},
                )
            ]
        )
        with self.assertRaises(PiPiXiaInputError):
            PiPiXiaClient(session=foreign, retries=0).resolve_share(
                "https://h5.pipix.com/s/wrp2m_sD-kU/"
            )

    def test_post_fixture_normalizes_media_author_stats_and_preview_comments(self) -> None:
        post = PiPiXiaClient.parse_post_payload(POST_COMMENTS, expected_id=CELL_ID)

        self.assertEqual(post["id"], CELL_ID)
        self.assertEqual(post["media_type"], "video")
        self.assertEqual(post["content"], "fixture public post")
        self.assertEqual(post["duration_seconds"], 7.454)
        self.assertEqual(post["video_id"], "v0fixturevideo")
        self.assertEqual(post["video_url"], "https://video.example.test/download.mp4")
        self.assertEqual(len(post["videos"]), 2)
        self.assertEqual(post["videos"][1]["definition"], 3)
        self.assertEqual(post["cover_url"], "https://img.example.test/cover.webp")
        self.assertEqual(post["author"]["id"], "102759188023")
        self.assertEqual(post["author"]["followers"], 55093)
        self.assertEqual(
            post["author"]["avatar"]["download_urls"][0],
            "https://img.example.test/author-original.jpg",
        )
        self.assertEqual(post["statistics"]["comments"], 42)
        self.assertEqual(len(post["comments_preview"]), 2)

    def test_album_fixture_uses_note_images_without_a_video(self) -> None:
        payload = copy.deepcopy(POST_COMMENTS)
        item = payload["data"]["cell_comments"][0]["comment_info"]["item"]
        item["video"] = None
        item["note"] = {
            "multi_image": [
                {"width": 720, "height": 960, "url_list": [{"url": "http://img.example.test/one.jpg"}]},
                {"width": 1080, "height": 1080, "url_list": [{"url": "https://img.example.test/two.jpg"}]},
            ]
        }
        post = PiPiXiaClient.parse_post_payload(payload, expected_id=CELL_ID)
        self.assertEqual(post["media_type"], "album")
        self.assertEqual(len(post["images"]), 2)
        self.assertEqual(post["images"][0]["url"], "https://img.example.test/one.jpg")
        self.assertEqual(post["video_url"], "")

    def test_comments_fixture_normalizes_cursor_users_and_nested_replies(self) -> None:
        result = PiPiXiaClient.parse_comments_payload(POST_COMMENTS, cell_id=CELL_ID)

        self.assertEqual(result["total"], 42)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["next_offset"], "10")
        self.assertTrue(result["has_more"])
        top = result["comments"][0]
        self.assertEqual(top["id"], "7411241327297299263")
        self.assertEqual(top["user"]["name"], "Fixture Commenter")
        self.assertEqual(top["likes"], 7477)
        self.assertTrue(top["pinned"])
        self.assertEqual(top["city"], "杭州")
        self.assertEqual(top["replies"][0]["text"], "fixture nested reply")

    def test_get_post_resolves_short_share_then_calls_anonymous_comment_route(self) -> None:
        session = FakeSession(
            [
                response(
                    "redirect",
                    status=302,
                    headers={"location": f"https://h5.pipix.com/item/{CELL_ID}"},
                ),
                response(POST_COMMENTS),
            ]
        )
        client = PiPiXiaClient(session=session, retries=0)

        post = client.get_post("https://h5.pipix.com/s/wrp2m_sD-kU/")

        self.assertEqual(post["cell_id"], CELL_ID)
        self.assertEqual(session.calls[1][0], "https://api.pipix.com/bds/cell/cell_comment/")
        params = session.calls[1][1]["params"]
        self.assertEqual(params["cell_id"], CELL_ID)
        self.assertEqual(params["api_version"], 1)
        self.assertEqual(params["aid"], APP_ID)
        self.assertEqual(params["app_name"], APP_NAME)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)

    def test_get_comments_preserves_decimal_offset_and_count(self) -> None:
        session = FakeSession([response(POST_COMMENTS)])
        result = PiPiXiaClient(session=session, retries=0).get_comments(
            CELL_ID,
            offset="1784605819556",
            count=12,
        )
        self.assertEqual(result["count"], 2)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["offset"], "1784605819556")
        self.assertEqual(params["count"], 12)

    def test_user_fixture_and_live_request_contract(self) -> None:
        profile = PiPiXiaClient.parse_user_payload(USER, expected_id=USER_ID)
        self.assertEqual(profile["name"], "Fixture Profile")
        self.assertEqual(profile["followers"], 76273)
        self.assertEqual(profile["likes"], 12268578)
        self.assertEqual(profile["verification"], "fixture verified")
        self.assertEqual(profile["medal_count"], 3)
        self.assertTrue(profile["profile_ban"])

        session = FakeSession([response(USER)])
        fetched = PiPiXiaClient(session=session, retries=0).get_user(USER_ID)
        self.assertEqual(fetched["id"], USER_ID)
        self.assertEqual(session.calls[0][0], "https://api.pipix.com/bds/user/user_profile/")
        self.assertEqual(session.calls[0][1]["params"]["user_id"], USER_ID)

    def test_follower_and_following_routes_normalize_cursor(self) -> None:
        session = FakeSession([response(FOLLOWERS), response(FOLLOWERS)])
        client = PiPiXiaClient(session=session, retries=0)
        followers = client.get_followers(USER_ID, cursor=0, limit=1)
        following = client.get_following(USER_ID, cursor="1784536694404", limit=2)

        self.assertEqual(followers["kind"], "followers")
        self.assertEqual(followers["count"], 1)
        self.assertEqual(followers["cursor"]["loadmore"], "1784536694404")
        self.assertEqual(following["kind"], "following")
        self.assertEqual(following["count"], 2)
        self.assertTrue(following["cursor"]["has_more"])
        self.assertEqual(session.calls[0][0], "https://api.pipix.com/bds/user/follower/")
        self.assertEqual(session.calls[1][0], "https://api.pipix.com/bds/user/following/")
        self.assertEqual(session.calls[1][1]["params"]["cursor"], "1784536694404")

    def test_hot_words_and_hashtag_fixtures_and_routes(self) -> None:
        hot = PiPiXiaClient.parse_hot_payload(HOT, limit=1)
        self.assertEqual(hot["keywords"], ["funny videos"])
        self.assertEqual(hot["words"][0]["hot_type"], 1)

        hashtag = PiPiXiaClient.parse_hashtag_payload(HASHTAG, expected_id=HASHTAG_ID)
        self.assertEqual(hashtag["name"], "Fixture Topic")
        self.assertEqual(hashtag["statistics"]["works"], 810218)
        self.assertEqual(hashtag["statistics"]["views"], 13798861585)
        self.assertEqual(hashtag["categories"][0]["name"], "Entertainment")
        self.assertEqual(hashtag["hosts"][0]["id"], "1759652656449688")

        session = FakeSession([response(HOT), response(HASHTAG)])
        client = PiPiXiaClient(session=session, retries=0)
        self.assertEqual(client.get_hot_search_words(limit=2)["count"], 2)
        self.assertEqual(client.get_hashtag(HASHTAG_ID)["id"], HASHTAG_ID)
        self.assertEqual(session.calls[0][0], "https://api.pipix.com/bds/search/hot/")
        self.assertEqual(session.calls[1][0], "https://api.pipix.com/bds/hashtag/detail/")
        self.assertEqual(session.calls[1][1]["params"]["hashtag_id"], HASHTAG_ID)

    def test_short_url_uses_apk_post_contract_and_normalizes_response(self) -> None:
        original = f"https://h5.pipix.com/item/{CELL_ID}"
        payload = {
            "status_code": 0,
            "message": "success",
            "data": {"short_url": "https://h5.pipix.com/s/GOCDRBhQt6Q/"},
        }
        session = FakeSession([response(payload)])

        result = PiPiXiaClient(session=session, retries=0).get_short_url(original)

        self.assertEqual(result["original_url"], original)
        self.assertEqual(result["short_code"], "GOCDRBhQt6Q")
        self.assertEqual(
            session.calls[0][0],
            "https://api.pipix.com/bds/share/short_url/",
        )
        self.assertEqual(session.calls[0][1]["params"]["aid"], APP_ID)
        self.assertEqual(session.calls[0][1]["data"], {"url": original})

    def test_short_url_rejects_invalid_input_and_response(self) -> None:
        client = PiPiXiaClient(session=FakeSession([]), retries=0)
        for value in (
            "",
            "ftp://example.com/file",
            "https://user:pass@example.com/private",
            "https://example.com/\nInjected: value",
        ):
            with self.subTest(value=value), self.assertRaises(PiPiXiaInputError):
                client.get_short_url(value)

        for value in (
            "https://example.com/s/not-pipixia/",
            f"https://h5.pipix.com/item/{CELL_ID}",
            "",
        ):
            with self.subTest(value=value), self.assertRaises(PiPiXiaResponseError):
                PiPiXiaClient.parse_short_url_payload(
                    {"status_code": 0, "data": {"short_url": value}},
                    original_url="https://example.com/article",
                )

    def test_invalid_pagination_and_type_values_fail_before_http(self) -> None:
        client = PiPiXiaClient(session=FakeSession([]), retries=0)
        for call in (
            lambda: client.get_comments(CELL_ID, offset="-1"),
            lambda: client.get_comments(CELL_ID, count=0),
            lambda: client.get_comments(CELL_ID, count=51),
            lambda: client.get_comments(CELL_ID, cell_type=True),
            lambda: client.get_followers(USER_ID, cursor="1.5"),
            lambda: client.get_followers(USER_ID, limit=51),
            lambda: client.get_hot_search_words(limit=True),
        ):
            with self.subTest(call=call), self.assertRaises(PiPiXiaInputError):
                call()

    def test_business_errors_missing_data_and_id_mismatches_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(PiPiXiaResponseError, "API error 11001"):
            PiPiXiaClient.parse_hot_payload(
                {"status_code": 11001, "message": "invalid param", "prompt": "bad"}
            )
        with self.assertRaisesRegex(PiPiXiaResponseError, "did not include an item"):
            PiPiXiaClient.parse_post_payload(
                {"status_code": 0, "data": {"cell_comments": []}},
                expected_id=CELL_ID,
            )
        with self.assertRaisesRegex(PiPiXiaResponseError, "post response ID mismatch"):
            PiPiXiaClient.parse_post_payload(POST_COMMENTS, expected_id="7411193113223371044")
        with self.assertRaisesRegex(PiPiXiaResponseError, "user response ID mismatch"):
            PiPiXiaClient.parse_user_payload(USER, expected_id="1310254082831249")
        with self.assertRaisesRegex(PiPiXiaResponseError, "hashtag response ID mismatch"):
            PiPiXiaClient.parse_hashtag_payload(HASHTAG, expected_id="129558")

    def test_transport_and_transient_statuses_retry_with_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection"),
                response("busy", status=503, content_type="text/plain"),
                response(HOT),
            ]
        )
        with patch("reverse.pipixia_reverse.client.time.sleep") as sleep:
            result = PiPiXiaClient(session=session, retries=2).get_hot_search_words(limit=2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_invalid_json_and_terminal_http_error_are_wrapped(self) -> None:
        invalid = PiPiXiaClient(
            session=FakeSession([response("not json", content_type="text/plain")]),
            retries=0,
        )
        with self.assertRaisesRegex(PiPiXiaResponseError, "invalid JSON"):
            invalid.get_hot_search_words()

        missing = PiPiXiaClient(
            session=FakeSession([response("missing", status=404, content_type="text/plain")]),
            retries=0,
        )
        with self.assertRaisesRegex(PiPiXiaResponseError, "HTTP 404"):
            missing.get_hot_search_words()


if __name__ == "__main__":
    unittest.main()
