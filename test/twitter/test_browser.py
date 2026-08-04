from __future__ import annotations

import copy
import io
import unittest
from unittest.mock import AsyncMock, patch

from reverse.browser_progress import stderr_progress
from reverse.twitter_reverse import cli
from reverse.twitter_reverse.client import (
    TWITTER_HOME_FEED_PATH,
    TWITTER_SEARCH_POSTS_PATH,
    TwitterClient,
)
from reverse.twitter_reverse.errors import TwitterInputError


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


if __name__ == "__main__":
    unittest.main()
