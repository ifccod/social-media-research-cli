from __future__ import annotations

import copy
import io
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from reverse.browser_progress import stderr_progress
from reverse.browser_session import BrowserSessionError
from reverse.twitter_reverse import cli
from reverse.twitter_reverse.client import (
    TWITTER_CREATE_SCHEDULED_TWEET_PATH,
    TWITTER_FOLLOWERS_PATH,
    TWITTER_FOLLOWING_PATH,
    TWITTER_FOLLOW_PATH,
    TWITTER_HOME_FEED_PATH,
    TWITTER_SEARCH_POSTS_PATH,
    TWITTER_UPLOAD_MEDIA_PATH,
    TWITTER_USER_PATH,
    TWITTER_USER_TWEETS_PATH,
    TwitterClient,
)
from reverse.twitter_reverse.errors import TwitterInputError, TwitterResponseError

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def timeline_payload() -> dict:
    return {
        "source": "twitter_web_graphql",
        "transport": "browser_web",
        "endpoint": "/i/api/graphql/QUERY/SearchTimeline",
        "operation": "SearchTimeline",
        "rate_limit": {"limit": 50, "remaining": 49, "reset": 1785259000},
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-2082135737625895037",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "__typename": "Tweet",
                                                        "rest_id": "2082135737625895037",
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "__typename": "User",
                                                                    "rest_id": "1325102346792218629",
                                                                    "core": {
                                                                        "name": "研究者",
                                                                        "screen_name": "researcher",
                                                                    },
                                                                    "avatar": {
                                                                        "image_url": "https://pbs.twimg.com/avatar.jpg"
                                                                    },
                                                                    "verification": {
                                                                        "verified": False
                                                                    },
                                                                    "is_blue_verified": True,
                                                                    "profile_image_shape": "Circle",
                                                                    "relationship_counts": {
                                                                        "followers": 3053,
                                                                        "following": 1685,
                                                                    },
                                                                }
                                                            }
                                                        },
                                                        "legacy": {
                                                            "bookmark_count": 3,
                                                            "created_at": "Tue Jul 28 16:06:58 +0000 2026",
                                                            "favorite_count": 11,
                                                            "full_text": "social listening workflow",
                                                            "id_str": "2082135737625895037",
                                                            "lang": "en",
                                                            "quote_count": 2,
                                                            "reply_count": 4,
                                                            "retweet_count": 5,
                                                        },
                                                        "views": {
                                                            "count": "100",
                                                            "state": "EnabledWithCount",
                                                        },
                                                    }
                                                }
                                            }
                                        },
                                    },
                                    {
                                        "entryId": "cursor-bottom-0",
                                        "content": {
                                            "cursorType": "Bottom",
                                            "value": "NEXT_CURSOR",
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                }
            }
        },
    }


class TwitterBrowserClientTests(unittest.TestCase):
    def test_home_feed_builds_browser_request_and_normalizes_posts(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            value = timeline_payload()
            value["endpoint"] = "/i/api/graphql/QUERY/HomeTimeline"
            value["operation"] = "HomeTimeline"
            return value

        result = TwitterClient(browser_fetch=fetch).get_home_feed(limit=20)

        self.assertEqual(
            calls,
            [(TWITTER_HOME_FEED_PATH, [("count", "20")], "https://x.com/home")],
        )
        self.assertEqual(result["mode"], "home")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["next_cursor"], "NEXT_CURSOR")
        self.assertTrue(result["has_more"])
        post = result["posts"][0]
        self.assertEqual(post["id"], "2082135737625895037")
        self.assertEqual(post["text"], "social listening workflow")
        self.assertEqual(post["stats"]["views"], 100)
        self.assertEqual(post["stats"]["quotes"], 2)
        self.assertEqual(post["author"]["username"], "researcher")
        self.assertEqual(post["author"]["followers"], 3053)
        self.assertIsNotNone(post["created_timestamp"])

    def test_home_feed_enforces_output_limit_when_upstream_oversupplies(self) -> None:
        payload = timeline_payload()
        entries = payload["data"]["search_by_raw_query"]["search_timeline"][
            "timeline"
        ]["instructions"][0]["entries"]
        duplicate = copy.deepcopy(entries[0])
        duplicate["entryId"] = "tweet-2082135737625895038"
        result = duplicate["content"]["itemContent"]["tweet_results"]["result"]
        result["rest_id"] = "2082135737625895038"
        result["legacy"]["id_str"] = "2082135737625895038"
        entries.insert(1, duplicate)

        normalized = TwitterClient(
            browser_fetch=lambda *_args: payload
        ).get_home_feed(limit=1)

        self.assertEqual(normalized["count"], 1)
        self.assertEqual(len(normalized["posts"]), 1)

    def test_search_posts_preserves_query_product_and_cursor(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            return timeline_payload()

        result = TwitterClient(browser_fetch=fetch).search_posts(
            "social listening",
            product="latest",
            limit=10,
            cursor="NEXT_CURSOR",
        )

        self.assertEqual(calls[0][0], TWITTER_SEARCH_POSTS_PATH)
        self.assertEqual(
            calls[0][1],
            [
                ("query", "social listening"),
                ("count", "10"),
                ("product", "Latest"),
                ("cursor", "NEXT_CURSOR"),
            ],
        )
        self.assertIn("q=social+listening", calls[0][2])
        self.assertIn("f=live", calls[0][2])
        self.assertEqual(result["query"], "social listening")
        self.assertEqual(result["product"], "latest")

    def test_timeline_inputs_are_validated_before_browser_request(self) -> None:
        client = TwitterClient(
            browser_fetch=lambda *_args: self.fail("不应调用浏览器")
        )
        for invalid in (0, 101, True):
            with self.subTest(limit=invalid):
                with self.assertRaises(TwitterInputError):
                    client.get_home_feed(limit=invalid)
        with self.assertRaises(TwitterInputError):
            client.search_posts("\n")
        with self.assertRaises(TwitterInputError):
            client.search_posts("query", product="people")

    def test_get_user_by_screen_name_normalizes_profile_bio(self) -> None:
        calls: list[tuple] = []
        payload = load_fixture("user_by_screen_name.json")

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return payload

        result = TwitterClient(browser_fetch=fetch).get_user("OpenAI")
        expected = payload["data"]["user"]["result"]

        self.assertEqual(
            calls,
            [
                (
                    TWITTER_USER_PATH,
                    [("screen_name", "OpenAI")],
                    "https://x.com/home",
                )
            ],
        )
        self.assertEqual(result["kind"], "twitter_user")
        self.assertFalse(result["self"])
        user = result["user"]
        self.assertEqual(
            user["description"],
            expected["profile_bio"]["description"],
        )
        self.assertTrue(user["blue_verified"])
        self.assertEqual(user["followers"], 5259857)
        self.assertEqual(user["following"], 4)
        self.assertEqual(user["id"], "4398626122")
        self.assertEqual(user["username"], "OpenAI")
        self.assertEqual(user["homepage"], "https://x.com/OpenAI")
        self.assertFalse(user["protected"])
        self.assertFalse(user["unavailable"])
        self.assertIsNone(user["followed_by_me"])

    def test_user_tweets_with_user_id_does_not_fetch_user(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return load_fixture("user_tweets.json")

        result = TwitterClient(browser_fetch=fetch).get_user_tweets(
            user_id="4398626122",
            limit=10,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], TWITTER_USER_TWEETS_PATH)
        self.assertEqual(
            calls[0][1],
            [("user_id", "4398626122"), ("count", "10")],
        )
        self.assertEqual(calls[0][2], "https://x.com/home")
        self.assertEqual(result["kind"], "twitter_timeline")
        self.assertEqual(result["mode"], "user")
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["posts"][0]["id"], "2096133504417616165")
        self.assertEqual(
            result["next_cursor"],
            "DAAHCgABHRr-KDk___ELAAIAAAATMjA5MjY5MTg2MTc3MzE2MDY3MwgAAwAAAAIAAA",
        )
        self.assertTrue(result["has_more"])
        self.assertTrue(result["posts"][0]["author"]["blue_verified"])
        self.assertIn(
            "artificial general intelligence",
            result["posts"][0]["author"]["description"],
        )

    def test_followers_and_following_with_user_id_use_bottom_cursor(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == TWITTER_FOLLOWERS_PATH:
                return load_fixture("followers.json")
            return load_fixture("following.json")

        client = TwitterClient(browser_fetch=fetch)
        following = client.get_following(user_id="4398626122", limit=20)
        followers = client.get_followers(user_id="4398626122", limit=20)

        self.assertEqual(
            [path for path, _entries, _referer in calls],
            [TWITTER_FOLLOWING_PATH, TWITTER_FOLLOWERS_PATH],
        )
        self.assertEqual(
            calls[0][1],
            [("user_id", "4398626122"), ("count", "20")],
        )
        self.assertEqual(calls[0][2], "https://x.com/home")
        self.assertEqual(following["kind"], "twitter_following")
        self.assertEqual(followers["kind"], "twitter_followers")
        self.assertEqual(following["items"][0]["username"], "example_user")
        self.assertEqual(followers["items"][0]["username"], "example_user")
        self.assertTrue(following["items"][0]["followed_by_me"])
        self.assertFalse(followers["items"][0]["followed_by_me"])
        self.assertEqual(
            following["next_cursor"],
            "1875744586320135796|2097267989341536204",
        )
        self.assertEqual(
            followers["next_cursor"],
            "1875686408484125789|2097268007200882639",
        )
        self.assertTrue(following["has_more"])
        self.assertEqual(following["previous_cursor"], "-1|2097267989341536257")

    def test_following_screen_name_resolves_user_then_list(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == TWITTER_USER_PATH:
                return load_fixture("user_by_screen_name.json")
            return load_fixture("following.json")

        result = TwitterClient(browser_fetch=fetch).get_following(
            screen_name="alice",
            limit=20,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0],
            (
                TWITTER_USER_PATH,
                [("screen_name", "alice")],
                "https://x.com/home",
            ),
        )
        self.assertEqual(calls[1][0], TWITTER_FOLLOWING_PATH)
        self.assertEqual(
            calls[1][1],
            [("user_id", "4398626122"), ("count", "20")],
        )
        self.assertEqual(result["items"][0]["username"], "example_user")

    def test_me_identity_sends_screen_name_me_without_user_id(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == TWITTER_USER_PATH:
                return load_fixture("user_by_screen_name.json")
            if path == TWITTER_USER_TWEETS_PATH:
                return load_fixture("user_tweets.json")
            if path == TWITTER_FOLLOWERS_PATH:
                return load_fixture("followers.json")
            return load_fixture("following.json")

        client = TwitterClient(browser_fetch=fetch)
        client.get_user()
        client.get_user(screen_name="me")
        client.get_user_tweets(limit=10)
        client.get_followers()
        client.get_following(screen_name="me")

        self.assertEqual(len(calls), 5)
        for path, entries, referer in calls:
            names = dict(entries)
            self.assertEqual(names["screen_name"], "me")
            self.assertNotIn("user_id", names)
            self.assertEqual(referer, "https://x.com/home")
            self.assertIn(
                path,
                {
                    TWITTER_USER_PATH,
                    TWITTER_USER_TWEETS_PATH,
                    TWITTER_FOLLOWERS_PATH,
                    TWITTER_FOLLOWING_PATH,
                },
            )

    def test_user_graph_rejects_invalid_limit_before_browser_request(self) -> None:
        client = TwitterClient(
            browser_fetch=lambda *_args: self.fail("不应调用浏览器")
        )
        for method in (
            client.get_user_tweets,
            client.get_followers,
            client.get_following,
        ):
            for invalid in (0, 101, True):
                with self.subTest(method=method.__name__, limit=invalid):
                    with self.assertRaises(TwitterInputError):
                        method(user_id="4398626122", limit=invalid)

    def test_user_unavailable_is_not_forbidden(self) -> None:
        payload = {
            "source": "twitter_web_graphql",
            "transport": "browser_web",
            "data": {
                "user": {
                    "result": {
                        "__typename": "UserUnavailable",
                        "reason": "Suspended",
                    }
                }
            },
        }
        user = TwitterClient(browser_fetch=lambda *_args: payload).get_user(
            "ghost"
        )
        self.assertTrue(user["user"]["unavailable"])
        self.assertNotEqual(getattr(user, "code", None), "forbidden")

        empty = TwitterClient(browser_fetch=lambda *_args: payload).get_following(
            user_id="1"
        )
        self.assertEqual(empty["kind"], "twitter_following")
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["count"], 0)


class BrowserProgressTests(unittest.TestCase):
    def test_progress_uses_stderr_shape_and_deduplicates(self) -> None:
        output = io.StringIO()
        report = stderr_progress(output)
        event = {"label": "会话", "message": "正在探测 X 登录态"}
        report(event)
        report(event)
        report({"label": "完成", "message": "X 数据读取完成"})
        self.assertEqual(
            output.getvalue(),
            "[会话] 正在探测 X 登录态\n[完成] X 数据读取完成\n",
        )

    def test_cli_browser_fetch_forwards_progress_callback(self) -> None:
        call = AsyncMock(return_value={"data": {}})
        with (
            patch.object(cli, "start_daemon"),
            patch.object(cli, "call_daemon", call),
        ):
            result = cli._browser_fetch(3.0)(
                TWITTER_HOME_FEED_PATH,
                [("count", "20")],
                "https://x.com/home",
            )
        self.assertEqual(result, {"data": {}})
        request = call.await_args.args[0]
        self.assertEqual(request["platform"], "twitter_home")
        self.assertEqual(request["request_interval_ms"], 3000)
        self.assertTrue(call.await_args.kwargs["progress"])

    def test_cli_browser_fetch_maps_user_path_to_twitter_home(self) -> None:
        call = AsyncMock(return_value={"data": {}})
        with (
            patch.object(cli, "start_daemon"),
            patch.object(cli, "call_daemon", call),
        ):
            cli._browser_fetch(3.0)(
                TWITTER_USER_PATH,
                [("screen_name", "OpenAI")],
                "https://x.com/home",
            )
            search = cli._browser_fetch(3.0)(
                TWITTER_SEARCH_POSTS_PATH,
                [
                    ("query", "social"),
                    ("count", "10"),
                    ("product", "Top"),
                ],
                "https://x.com/search?q=social&src=typed_query&f=top",
            )
        self.assertEqual(call.await_args_list[0].args[0]["platform"], "twitter_home")
        self.assertEqual(call.await_args_list[0].args[0]["path"], TWITTER_USER_PATH)
        self.assertEqual(search, {"data": {}})
        self.assertEqual(
            call.await_args_list[1].args[0]["platform"],
            "twitter_search",
        )

    def test_cli_browser_fetch_maps_write_paths_to_twitter_home(self) -> None:
        call = AsyncMock(return_value={"ok": True})
        with (
            patch.object(cli, "start_daemon"),
            patch.object(cli, "call_daemon", call),
        ):
            fetch = cli._browser_fetch(3.0)
            fetch(
                TWITTER_FOLLOW_PATH,
                [("user_id", "12345")],
                "https://x.com/home",
            )
            fetch(
                TWITTER_UPLOAD_MEDIA_PATH,
                [("mimeType", "image/png"), ("dataBase64", "AAAA")],
                "https://x.com/home",
            )
            fetch(
                TWITTER_CREATE_SCHEDULED_TWEET_PATH,
                [("text", "hi"), ("execute_at", "2000000000")],
                "https://x.com/home",
            )
        self.assertEqual(len(call.await_args_list), 3)
        self.assertEqual(
            [item.args[0]["path"] for item in call.await_args_list],
            [
                TWITTER_FOLLOW_PATH,
                TWITTER_UPLOAD_MEDIA_PATH,
                TWITTER_CREATE_SCHEDULED_TWEET_PATH,
            ],
        )
        for item in call.await_args_list:
            self.assertEqual(item.args[0]["platform"], "twitter_home")
            self.assertEqual(item.args[0]["referer"], "https://x.com/home")

    def test_cli_browser_fetch_preserves_browser_session_error_code(self) -> None:
        with (
            patch.object(cli, "start_daemon"),
            patch.object(
                cli,
                "call_daemon",
                new=AsyncMock(
                    side_effect=BrowserSessionError("rate_limited", "slow down")
                ),
            ),
        ):
            with self.assertRaises(TwitterResponseError) as ctx:
                cli._browser_fetch(3.0)(
                    TWITTER_USER_PATH,
                    [("screen_name", "me")],
                    "https://x.com/home",
                )
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertIn("rate_limited", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
