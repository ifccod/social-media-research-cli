from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.weibo_reverse.client import DEFAULT_CHANNEL_ID, DEFAULT_USER_AGENT, WeiboClient
from reverse.weibo_reverse.errors import WeiboError, WeiboInputError, WeiboResponseError

FIXTURES = Path(__file__).with_name("fixtures")
CONFIG = json.loads((FIXTURES / "config.json").read_text(encoding="utf-8"))
POST = json.loads((FIXTURES / "post.json").read_text(encoding="utf-8"))
PROFILE = json.loads((FIXTURES / "profile.json").read_text(encoding="utf-8"))
FEED = json.loads((FIXTURES / "feed.json").read_text(encoding="utf-8"))
COMMENTS = json.loads((FIXTURES / "comments.json").read_text(encoding="utf-8"))
REPLIES = json.loads((FIXTURES / "replies.json").read_text(encoding="utf-8"))
HOT = json.loads((FIXTURES / "hot.json").read_text(encoding="utf-8"))
VISITOR_HTML = (FIXTURES / "visitor.html").read_text(encoding="utf-8")


def response(
    payload: object | None = None,
    *,
    text: str | None = None,
    status: int = 200,
    url: str = "",
    content_type: str = "application/json; charset=utf-8",
    location: str | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.content = (text if text is not None else json.dumps(payload)).encode("utf-8")
    result.default_encoding = "utf-8"
    result.headers["content-type"] = content_type
    if location:
        result.headers["location"] = location
    return result


class FakeSession(requests.Session):
    def __init__(
        self,
        results: list[tuple[str, requests.Response | Exception]],
    ) -> None:
        super().__init__()
        self.results = deque(results)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def _take(self, method: str, url: str, kwargs: dict[str, object]) -> requests.Response:
        self.calls.append((method, url, kwargs))
        if not self.results:
            raise AssertionError(f"unexpected fake HTTP request: {method} {url}")
        expected_method, result = self.results.popleft()
        if expected_method != method:
            raise AssertionError(f"expected {expected_method}, got {method} for {url}")
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result

    def get(self, url: str, **kwargs: object) -> requests.Response:
        return self._take("GET", url, kwargs)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        return self._take("POST", url, kwargs)


def ready_client(
    results: list[tuple[str, requests.Response | Exception]],
) -> tuple[WeiboClient, FakeSession]:
    session = FakeSession(results)
    client = WeiboClient(session=session, retries=0)
    client._identity_ready = True
    client._config = dict(CONFIG["data"])
    return client, session


def visitor_jsonp(*, retcode: int = 20_000_000, data: dict[str, object] | None = None) -> str:
    body = data or {"sub": "SUB_VALUE", "subp": "SUBP_VALUE", "tid": "TID_VALUE"}
    payload = {"retcode": retcode, "msg": "succ", "data": body}
    return (
        "window.visitor_gray_callback && visitor_gray_callback("
        + json.dumps(payload)
        + ");"
    )


class WeiboClientTest(unittest.TestCase):
    def test_error_hierarchy_headers_and_reference_validation(self) -> None:
        self.assertTrue(issubclass(WeiboInputError, WeiboError))
        self.assertTrue(issubclass(WeiboResponseError, WeiboError))
        session = FakeSession([])
        client = WeiboClient(session=session, retries=0)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("application/json", session.headers["Accept"])

        self.assertEqual(client.resolve_post_id("5092682368025584"), "5092682368025584")
        self.assertEqual(
            client.resolve_post_id("https://m.weibo.cn/detail/5092682368025584"),
            "5092682368025584",
        )
        self.assertEqual(
            client.resolve_post_id("https://m.weibo.cn/statuses/show?id=5092682368025584"),
            "5092682368025584",
        )
        self.assertEqual(
            client.resolve_uid("https://m.weibo.cn/u/2992978081"), "2992978081"
        )
        with self.assertRaises(WeiboInputError):
            client.resolve_post_id("https://m.weibo.cn.example/detail/5092682368025584")
        with self.assertRaises(WeiboInputError):
            client.resolve_uid("https://example.com/u/2992978081")
        with self.assertRaises(WeiboInputError):
            client.get_trend_top("102803?redirect=https://example.com", limit=0)
        with self.assertRaises(WeiboInputError):
            client.get_trend_top("102803", page=0, limit=0)
        with self.assertRaises(WeiboInputError):
            client.get_user_posts("2992978081", since_id="bad", limit=0)
        with self.assertRaises(WeiboInputError):
            client.get_comments("5092682368025584", max_id_type=2, limit=0)
        with self.assertRaises(WeiboInputError):
            client.search("fixture", search_type="999", limit=0)
        with self.assertRaises(WeiboInputError):
            client.search("fixture", time_scope="year", limit=0)

    def test_visitor_jsonp_parser_is_structural_and_strict(self) -> None:
        parsed = WeiboClient.parse_visitor_jsonp(visitor_jsonp())
        self.assertEqual(parsed["retcode"], 20_000_000)
        self.assertEqual(parsed["data"]["tid"], "TID_VALUE")
        with self.assertRaisesRegex(WeiboResponseError, "callback"):
            WeiboClient.parse_visitor_jsonp(
                "window.other && other({\"retcode\":20000000});"
            )
        with self.assertRaisesRegex(WeiboResponseError, "trailing"):
            WeiboClient.parse_visitor_jsonp(visitor_jsonp() + "alert(1)")
        with self.assertRaisesRegex(WeiboResponseError, "invalid JSON"):
            WeiboClient.parse_visitor_jsonp(
                "window.visitor_gray_callback && visitor_gray_callback({bad});"
            )

    def test_config_visitor_generation_and_target_retry_contract(self) -> None:
        visitor_url = (
            "https://visitor.passport.weibo.cn/visitor/visitor?entry=sinawap"
            "&url=https%3A%2F%2Fm.weibo.cn%2Fapi%2Fcontainer%2FgetIndex"
        )
        session = FakeSession(
            [
                ("GET", response(CONFIG)),
                (
                    "GET",
                    response(
                        text="redirect",
                        status=302,
                        content_type="text/html",
                        location=visitor_url,
                    ),
                ),
                (
                    "GET",
                    response(
                        text=VISITOR_HTML,
                        url=visitor_url,
                        content_type="text/html; charset=utf-8",
                    ),
                ),
                ("POST", response(text=visitor_jsonp(), content_type="text/javascript")),
                ("GET", response(FEED)),
            ]
        )
        client = WeiboClient(session=session, retries=0)

        result = client.get_trend_top(DEFAULT_CHANNEL_ID, limit=1)

        self.assertEqual(result["posts"][0]["id"], "5092682368025584")
        self.assertEqual(
            [(method, url) for method, url, _ in session.calls],
            [
                ("GET", "https://m.weibo.cn/api/config/list"),
                ("GET", "https://m.weibo.cn/api/container/getIndex"),
                ("GET", visitor_url),
                ("POST", "https://visitor.passport.weibo.cn/visitor/genvisitor2"),
                ("GET", "https://m.weibo.cn/api/container/getIndex"),
            ],
        )
        post_call = session.calls[3][2]
        self.assertEqual(post_call["data"]["request_id"], "0123456789abcdef0123456789abcdef")
        self.assertEqual(post_call["data"]["webdriver"], "false")
        self.assertEqual(post_call["data"]["ver"], "20250916")
        self.assertEqual(
            post_call["data"]["return_url"],
            "https://m.weibo.cn/api/container/getIndex?containerid=102803&page=1",
        )
        self.assertEqual(post_call["headers"]["Origin"], "https://visitor.passport.weibo.cn")
        self.assertFalse(session.calls[1][2]["allow_redirects"])
        self.assertEqual(client._visitor_tid, "TID_VALUE")

    def test_visitor_refresh_happens_at_most_once(self) -> None:
        session = FakeSession(
            [
                ("GET", response(CONFIG)),
                ("GET", response(text=VISITOR_HTML, status=432, content_type="text/html")),
                ("POST", response(text=visitor_jsonp(), content_type="text/javascript")),
                ("GET", response(text=VISITOR_HTML, status=432, content_type="text/html")),
            ]
        )
        client = WeiboClient(session=session, retries=0)

        with self.assertRaisesRegex(WeiboResponseError, "did not unlock"):
            client.get_post("5092682368025584")

        self.assertEqual([method for method, _, _ in session.calls].count("POST"), 1)

    def test_visitor_response_requires_success_and_identity_fields(self) -> None:
        for body, expected in [
            (visitor_jsonp(retcode=50000000), "visitor API error"),
            (visitor_jsonp(data={"sub": "x", "subp": "", "tid": "t"}), "missing: subp"),
        ]:
            session = FakeSession(
                [
                    ("GET", response(CONFIG)),
                    ("GET", response(text=VISITOR_HTML, status=432, content_type="text/html")),
                    ("POST", response(text=body, content_type="text/javascript")),
                ]
            )
            client = WeiboClient(session=session, retries=0)
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(WeiboResponseError, expected):
                    client.get_post("5092682368025584")

    def test_transient_retry_and_deterministic_http_error(self) -> None:
        client, session = ready_client(
            [
                ("GET", requests.RequestsError("offline")),
                ("GET", response(POST)),
            ]
        )
        client.retries = 1
        with patch("reverse.weibo_reverse.client.time.sleep") as sleep:
            post = client.get_post("5092682368025584")
        self.assertEqual(post["id"], "5092682368025584")
        sleep.assert_called_once_with(0.4)
        self.assertEqual(len(session.calls), 2)

        client, session = ready_client([("GET", response(text="missing", status=404))])
        with self.assertRaisesRegex(WeiboResponseError, "HTTP 404"):
            client.get_post("5092682368025584")
        self.assertEqual(len(session.calls), 1)

    def test_redirect_response_cannot_leave_owned_hosts(self) -> None:
        client, _ = ready_client(
            [
                (
                    "GET",
                    response(
                        FEED,
                        url="https://m.weibo.cn.example/api/container/getIndex",
                    ),
                )
            ]
        )
        with self.assertRaisesRegex(WeiboResponseError, "invalid authority"):
            client.get_trend_top("102803", limit=1)

    def test_post_images_video_repost_text_counts_and_time_are_normalized(self) -> None:
        client, _ = ready_client([("GET", response(POST))])

        post = client.get_post("https://m.weibo.cn/detail/5092682368025584")

        self.assertEqual(post["text"], "Fixture @test\nsecond & line[smile]")
        self.assertEqual(post["source"], "iPhone 15 Pro")
        self.assertEqual(post["created_at"], "2024-11-14T09:25:23+00:00")
        self.assertEqual(post["author"]["stats"]["followers"], 10_374_000)
        self.assertEqual(post["images"][0]["url"], "https://img.example/large.jpg")
        self.assertEqual(post["images"][0]["width"], 1800)
        self.assertEqual(post["video"]["url"], "https://video.example/720.mp4")
        self.assertEqual(post["video"]["duration_seconds"], 9.5)
        self.assertEqual(post["video"]["play_count"], 12_000)
        self.assertEqual(
            post["stats"],
            {"reposts": 12, "comments": 34, "likes": 56, "favorites": 7},
        )
        self.assertEqual(post["reposted_post"]["id"], "5092200000000001")
        self.assertIsNone(post["reposted_post"]["reposted_post"])

    def test_user_profile_discovers_post_container_and_preserves_counts(self) -> None:
        client, session = ready_client([("GET", response(PROFILE))])

        user = client.get_user("https://m.weibo.cn/u/2992978081")

        self.assertEqual(user["id"], "2992978081")
        self.assertEqual(user["screen_name"], "fixture_user")
        self.assertEqual(user["avatar_url"], "https://img.example/avatar.jpg")
        self.assertEqual(user["stats"]["followers"], 10_374_000)
        self.assertEqual(user["stats"]["followers_text"], "1037.4\u4e07")
        self.assertEqual(user["post_container_id"], "1076032992978081")
        self.assertEqual(session.calls[0][2]["params"]["type"], "uid")
        self.assertEqual(session.calls[0][2]["params"]["containerid"], "1005052992978081")

    def test_feed_paginates_nested_cards_and_deduplicates_posts(self) -> None:
        page_two = {
            "ok": 1,
            "data": {
                "cardlistInfo": {"containerid": "1076032992978081", "total": 3},
                "cards": [
                    FEED["data"]["cards"][1],
                    {
                        "card_type": 9,
                        "mblog": {
                            "id": "5092682368025586",
                            "mid": "5092682368025586",
                            "text": "third fixture",
                            "user": {"id": 10003, "screen_name": "third_user"},
                        },
                    },
                ],
            },
        }
        client, session = ready_client(
            [("GET", response(FEED)), ("GET", response(page_two))]
        )

        result = client.get_user_posts("2992978081", limit=3)

        self.assertEqual(
            [post["id"] for post in result["posts"]],
            ["5092682368025584", "5092682368025585", "5092682368025586"],
        )
        self.assertEqual(session.calls[1][2]["params"]["page"], 2)
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_page"])

    def test_feed_rejects_a_non_advancing_since_id(self) -> None:
        stalled = json.loads(json.dumps(FEED))
        stalled["data"]["cardlistInfo"].pop("page")
        stalled["data"]["cardlistInfo"]["since_id"] = "12345"
        client, _ = ready_client([("GET", response(stalled))])

        with self.assertRaisesRegex(WeiboResponseError, "did not advance since_id"):
            client.get_user_posts("2992978081", since_id="12345", limit=3)

    def test_comments_paginate_and_normalize_nested_preview_replies(self) -> None:
        second = {
            "ok": 1,
            "data": {
                "data": [
                    COMMENTS["data"]["data"][0],
                    {
                        "id": "5100663573318496",
                        "rootid": "5100663573318496",
                        "text": "second root",
                        "user": {"id": 20003, "screen_name": "second_commenter"},
                        "like_count": 4,
                    },
                ],
                "total_number": 3,
                "max_id": 0,
                "max_id_type": 0,
            },
        }
        client, session = ready_client(
            [("GET", response(COMMENTS)), ("GET", response(second))]
        )

        result = client.get_comments("5092682368025584", limit=2)

        self.assertEqual(
            [comment["id"] for comment in result["comments"]],
            ["5100663573318494", "5100663573318496"],
        )
        self.assertEqual(result["comments"][0]["text"], "root [smile]")
        self.assertEqual(result["comments"][0]["replies"][0]["id"], "5100663573318495")
        self.assertEqual(session.calls[1][2]["params"]["max_id"], "123456")
        self.assertEqual(result["total_available"], 3)
        self.assertFalse(result["has_more"])

    def test_reply_pagination_uses_top_level_cursor_shape(self) -> None:
        second = {
            "ok": 1,
            "data": [
                REPLIES["data"][0],
                {
                    "id": "5100664479548338",
                    "rootid": "5100663573318494",
                    "text": "reply two",
                    "user": {"id": 20003, "screen_name": "another_replier"},
                },
            ],
            "total_number": 2,
            "max_id": 0,
            "max_id_type": 0,
        }
        client, session = ready_client(
            [("GET", response(REPLIES)), ("GET", response(second))]
        )

        result = client.get_comment_replies("5100663573318494", limit=2)

        self.assertEqual(
            [reply["id"] for reply in result["replies"]],
            ["5100664479548337", "5100664479548338"],
        )
        self.assertEqual(result["root_comment"]["id"], "5100663573318494")
        self.assertEqual(session.calls[1][2]["params"]["max_id"], "999")
        self.assertFalse(result["has_more"])

    def test_search_builds_nested_container_and_extracts_group_posts(self) -> None:
        client, session = ready_client([("GET", response(FEED))])

        result = client.search("fixture query", search_type="61", limit=1)

        self.assertEqual(result["keyword"], "fixture query")
        self.assertEqual(result["search_type"], "61")
        self.assertEqual(result["posts"][0]["id"], "5092682368025584")
        self.assertEqual(
            session.calls[0][2]["params"]["containerid"],
            "100103type=61&q=fixture%20query",
        )

    def test_user_search_collects_user_cards_and_counts_results(self) -> None:
        users = {
            "ok": 1,
            "data": {
                "cardlistInfo": {"page": 2, "total": 2},
                "cards": [
                    {
                        "card_type": 11,
                        "card_group": [
                            {
                                "card_type": 10,
                                "user": {
                                    "id": 2992978081,
                                    "screen_name": "fixture_user",
                                    "followers_count": "1.2\u4e07",
                                },
                            },
                            {
                                "card_type": 10,
                                "user": {
                                    "id": 7518663432,
                                    "screen_name": "fixture_studio",
                                    "followers_count": 9,
                                },
                            },
                        ],
                    }
                ],
            },
        }
        client, session = ready_client([("GET", response(users))])

        result = client.search("fixture & studio", search_type="3", limit=2)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["post_total"], 0)
        self.assertEqual(result["user_total"], 2)
        self.assertEqual(
            [user["id"] for user in result["users"]],
            ["2992978081", "7518663432"],
        )
        self.assertEqual(
            session.calls[0][2]["params"]["containerid"],
            "100103type=3&q=fixture%20%26%20studio",
        )

    def test_hot_search_parses_rank_heat_label_and_pinned_item(self) -> None:
        client, session = ready_client([("GET", response(HOT))])

        result = client.get_hot_search()

        self.assertEqual(result["total"], 2)
        self.assertTrue(result["trends"][0]["pinned"])
        self.assertIsNone(result["trends"][0]["rank"])
        self.assertEqual(result["trends"][1]["rank"], 1)
        self.assertEqual(result["trends"][1]["heat"], 746451)
        self.assertEqual(result["trends"][1]["label"], "\u5267\u96c6")
        self.assertEqual(
            session.calls[0][2]["params"]["containerid"],
            "106003type=25&t=3&disable_hot=1&filter_type=realtimehot",
        )

    def test_config_and_named_channel_selection(self) -> None:
        session = FakeSession([("GET", response(CONFIG)), ("GET", response(FEED))])
        client = WeiboClient(session=session, retries=0)

        result = client.get_channel_feed("\u699c\u5355", limit=1)

        self.assertEqual(result["channel"], "\u699c\u5355")
        self.assertEqual(result["container_id"], "102803_ctg1_8999_-_ctg1_8999_home")
        self.assertEqual(client.get_config()["hot"]["keyword"], "\u4eba\u5de5\u667a\u80fd")
        self.assertEqual(len(session.calls), 2)

    def test_invalid_json_api_error_and_post_id_mismatch_are_reported(self) -> None:
        client, _ = ready_client(
            [("GET", response(text="<html>error</html>", content_type="text/html"))]
        )
        with self.assertRaisesRegex(WeiboResponseError, "invalid JSON"):
            client.get_post("5092682368025584")

        client, _ = ready_client([("GET", response({"ok": 0, "msg": "gone"}))])
        with self.assertRaisesRegex(WeiboResponseError, "gone"):
            client.get_post("5092682368025584")

        mismatch = json.loads(json.dumps(POST))
        mismatch["data"]["id"] = "5092682368025589"
        mismatch["data"]["mid"] = "5092682368025589"
        client, _ = ready_client([("GET", response(mismatch))])
        with self.assertRaisesRegex(WeiboResponseError, "ID mismatch"):
            client.get_post("5092682368025584")


if __name__ == "__main__":
    unittest.main()
