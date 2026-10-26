from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reverse.twitter_reverse import cli
from reverse.twitter_reverse.client import (
    TWITTER_CREATE_SCHEDULED_TWEET_PATH,
    TWITTER_CREATE_TWEET_PATH,
    TWITTER_FOLLOW_PATH,
    TWITTER_HOME_REFERER,
    TWITTER_LIKE_PATH,
    TWITTER_TWEET_DETAIL_PATH,
    TWITTER_UPLOAD_MEDIA_PATH,
    TwitterClient,
    extract_rest_id,
)
from reverse.twitter_reverse.errors import TwitterInputError, TwitterResponseError


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00"
GIF_BYTES = b"GIF89a" + b"\x00" * 10
MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"\x00\x00\x02\x00isomiso2"
FUTURE_AT = 2000000000
VIDEO_MEDIA_ID = "1000000000000000001"


def _png(directory: Path, name: str = "pic.png") -> Path:
    path = directory / name
    path.write_bytes(PNG_BYTES)
    return path


def _gif(directory: Path, name: str = "clip.gif") -> Path:
    path = directory / name
    path.write_bytes(GIF_BYTES)
    return path


def _mp4(directory: Path, name: str = "clip.mp4") -> Path:
    path = directory / name
    path.write_bytes(MP4_BYTES)
    return path


class TwitterWriteClientTests(unittest.TestCase):
    def test_extract_rest_id_walks_data_without_binding_field_names(self) -> None:
        self.assertEqual(extract_rest_id({"tweet": {"rest_id": "11"}}), "11")
        self.assertEqual(
            extract_rest_id({"scheduledtweet": {"rest_id": "99"}}),
            "99",
        )
        self.assertIsNone(extract_rest_id({"foo": {"id": "1"}}))

    def test_follow_sends_follow_path_and_rejects_me(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "source": "twitter_web_rest",
                "transport": "browser_web",
                "endpoint": "/i/api/1.1/friendships/create.json",
                "following": True,
                "user_id": "12345",
                "screen_name": "alice",
            }

        client = TwitterClient(browser_fetch=fetch)
        result = client.follow(user_id="12345")
        tagged = client.follow(screen_name="@alice")
        with self.assertRaises(TwitterInputError):
            client.follow(screen_name="me")
        with self.assertRaises(TwitterInputError):
            client.follow()

        self.assertEqual(result["kind"], "twitter_follow")
        self.assertTrue(result["following"])
        self.assertFalse(result["already_following"])
        self.assertEqual(result["user_id"], "12345")
        self.assertEqual(
            calls[0],
            (TWITTER_FOLLOW_PATH, [("user_id", "12345")], TWITTER_HOME_REFERER),
        )
        self.assertEqual(
            calls[1],
            (
                TWITTER_FOLLOW_PATH,
                [("screen_name", "alice")],
                TWITTER_HOME_REFERER,
            ),
        )
        self.assertEqual(tagged["screen_name"], "alice")
        self.assertEqual(len(calls), 2)

    def test_schedule_tweet_uploads_then_creates_with_bridge_entries(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == TWITTER_UPLOAD_MEDIA_PATH:
                return {
                    "source": "twitter_web_upload",
                    "transport": "browser_web",
                    "endpoint": "/i/media/upload.json",
                    "media_id_string": "2211223344556677889",
                }
            return {
                "source": "twitter_web_graphql",
                "transport": "browser_web",
                "endpoint": "/i/api/graphql/SCHED/CreateScheduledTweet",
                "operation": "CreateScheduledTweet",
                "rate_limit": {"limit": 50},
                "data": {"scheduledtweet": {"rest_id": "99"}},
            }

        with tempfile.TemporaryDirectory() as raw:
            media = _png(Path(raw))
            result = TwitterClient(browser_fetch=fetch).schedule_tweet(
                "hello\nworld",
                FUTURE_AT,
                media=[media],
            )

        self.assertEqual(result["kind"], "twitter_scheduled_tweet")
        self.assertEqual(result["text"], "hello\nworld")
        self.assertEqual(result["execute_at"], FUTURE_AT)
        self.assertEqual(result["media_ids"], ["2211223344556677889"])
        self.assertEqual(result["id"], "99")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], TWITTER_UPLOAD_MEDIA_PATH)
        self.assertEqual(calls[0][2], TWITTER_HOME_REFERER)
        self.assertEqual(
            dict(calls[0][1]),
            {
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(PNG_BYTES).decode("ascii"),
            },
        )
        self.assertEqual(calls[1][0], TWITTER_CREATE_SCHEDULED_TWEET_PATH)
        self.assertEqual(
            dict(calls[1][1]),
            {
                "text": "hello\nworld",
                "execute_at": str(FUTURE_AT),
                "media_ids": "2211223344556677889",
            },
        )

    def test_schedule_tweet_reads_rest_id_from_tweet_data(self) -> None:
        def fetch(path, entries, referer):
            return {
                "data": {"tweet": {"rest_id": "42"}},
                "operation": "CreateScheduledTweet",
            }

        result = TwitterClient(browser_fetch=fetch).schedule_tweet(
            "hello",
            FUTURE_AT,
        )
        self.assertEqual(result["id"], "42")
        self.assertEqual(result["media_ids"], [])

    def test_schedule_tweet_rejects_past_time_too_many_and_non_image(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            raise AssertionError("must not call browser")

        client = TwitterClient(browser_fetch=fetch)
        with self.assertRaises(TwitterInputError):
            client.schedule_tweet("hello", 1000000000)
        with self.assertRaises(TwitterInputError):
            client.schedule_tweet("hello", "2020-01-01T00:00:00Z")
        with self.assertRaises(TwitterInputError):
            client.schedule_tweet("hello", FUTURE_AT, media=["a.png"] * 5)
        with tempfile.TemporaryDirectory() as raw:
            txt = Path(raw) / "note.txt"
            txt.write_bytes(b"not an image")
            with self.assertRaises(TwitterInputError):
                client.schedule_tweet("hello", FUTURE_AT, media=[txt])
            webm = Path(raw) / "clip.webm"
            webm.write_bytes(b"\x1aE\xdf\xa3")
            with self.assertRaises(TwitterInputError) as ctx:
                client.schedule_tweet("hello", FUTURE_AT, media=[webm])
            self.assertIn("scheduled tweet", str(ctx.exception))
        self.assertEqual(calls, [])

    def test_upload_media_error_code_passes_through(self) -> None:
        def fetch(path, entries, referer):
            raise TwitterResponseError("slow down", code="rate_limited")

        with self.assertRaises(TwitterResponseError) as ctx:
            TwitterClient(browser_fetch=fetch).follow(user_id="12345")
        self.assertEqual(ctx.exception.code, "rate_limited")

    def test_parser_exposes_post_as_browser_command(self) -> None:
        parser = cli._parser()
        args = parser.parse_args(
            ["post", "--text", "hello\nworld", "--reply-to", "1"]
        )
        self.assertIn("post", cli._BROWSER_COMMANDS)
        self.assertEqual(
            cli._BROWSER_ROUTES[TWITTER_CREATE_TWEET_PATH],
            ("twitter_home", "https://x.com/home"),
        )
        self.assertEqual(args.text, "hello\nworld")
        self.assertEqual(args.reply_to, "1")
        self.assertIsNone(args.media)
        self.assertIn("Chrome 登录态临时传输立即发推", parser.format_help())
        post_parser = next(
            action.choices["post"]
            for action in parser._actions
            if isinstance(getattr(action, "choices", None), dict)
            and "post" in action.choices
        )
        help_text = post_parser.format_help()
        self.assertIn("--text", help_text)
        self.assertIn("--media", help_text)
        self.assertIn("--reply-to", help_text)

    def test_post_uploads_then_creates_with_bridge_entries(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == TWITTER_UPLOAD_MEDIA_PATH:
                return {
                    "source": "twitter_web_upload",
                    "transport": "browser_web",
                    "endpoint": "/i/media/upload.json",
                    "media_id_string": "1000000000000000001",
                }
            return {
                "source": "twitter_web_graphql",
                "transport": "browser_web",
                "endpoint": "/i/api/graphql/CREATE/CreateTweet",
                "operation": "CreateTweet",
                "rate_limit": {"limit": 50},
                "data": {
                    "create_tweet": {
                        "tweet_results": {"result": {"rest_id": "1000000000000000003"}}
                    }
                },
            }

        with tempfile.TemporaryDirectory() as raw:
            media = _png(Path(raw))
            result = TwitterClient(browser_fetch=fetch).post(
                "hello\nworld",
                media=[media],
            )

        self.assertEqual(result["kind"], "twitter_tweet")
        self.assertEqual(result["text"], "hello\nworld")
        self.assertEqual(result["media_ids"], ["1000000000000000001"])
        self.assertIsNone(result["reply_to"])
        self.assertEqual(result["id"], "1000000000000000003")
        self.assertEqual(result["operation"], "CreateTweet")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], TWITTER_UPLOAD_MEDIA_PATH)
        self.assertEqual(calls[1][0], TWITTER_CREATE_TWEET_PATH)
        self.assertEqual(
            dict(calls[1][1]),
            {
                "text": "hello\nworld",
                "media_ids": "1000000000000000001",
            },
        )

    def test_post_sends_reply_to_and_reads_first_rest_id(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "data": {"tweet": {"rest_id": "42"}},
                "operation": "CreateTweet",
            }

        result = TwitterClient(browser_fetch=fetch).post(
            "hello",
            reply_to="1000000000000000002",
        )
        self.assertEqual(result["id"], "42")
        self.assertEqual(result["media_ids"], [])
        self.assertEqual(result["reply_to"], "1000000000000000002")
        self.assertEqual(calls[0][0], TWITTER_CREATE_TWEET_PATH)
        self.assertEqual(
            dict(calls[0][1]),
            {"text": "hello", "reply_to": "1000000000000000002"},
        )

    def test_post_rejects_invalid_reply_to_and_too_many_media(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            raise AssertionError("must not call browser")

        client = TwitterClient(browser_fetch=fetch)
        with self.assertRaises(TwitterInputError):
            client.post("hello", reply_to="abc")
        with self.assertRaises(TwitterInputError):
            client.post("hello", reply_to="https://x.com/i/status/1")
        with self.assertRaises(TwitterInputError):
            client.post("hello", media=["a.png"] * 5)
        self.assertEqual(calls, [])

    def test_post_uploads_mp4_via_init_append_finalize_status(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            values = dict(entries)
            if path == TWITTER_UPLOAD_MEDIA_PATH:
                command = values.get("command")
                if command == "init":
                    return {"media_id_string": VIDEO_MEDIA_ID}
                if command == "append":
                    return {}
                if command == "finalize":
                    return {
                        "media_id_string": VIDEO_MEDIA_ID,
                        "processing_info": {
                            "state": "pending",
                            "check_after_secs": 1,
                        },
                    }
                if command == "status":
                    return {
                        "media_id_string": VIDEO_MEDIA_ID,
                        "processing_info": {"state": "succeeded"},
                    }
                raise AssertionError(f"unexpected upload command: {command}")
            return {
                "operation": "CreateTweet",
                "data": {
                    "create_tweet": {
                        "tweet_results": {"result": {"rest_id": "9"}}
                    }
                },
            }

        with tempfile.TemporaryDirectory() as raw:
            media = _mp4(Path(raw))
            with patch("reverse.twitter_reverse.client.time.sleep") as slept:
                result = TwitterClient(browser_fetch=fetch).post(
                    "hello",
                    media=[media],
                )
        slept.assert_called_once()
        self.assertEqual(result["media_ids"], [VIDEO_MEDIA_ID])
        self.assertEqual(result["id"], "9")
        upload_calls = [
            dict(entries)
            for path, entries, _referer in calls
            if path == TWITTER_UPLOAD_MEDIA_PATH
        ]
        self.assertEqual(
            [item.get("command") for item in upload_calls],
            ["init", "append", "finalize", "status"],
        )
        self.assertEqual(upload_calls[0]["mimeType"], "video/mp4")
        self.assertEqual(upload_calls[0]["media_category"], "tweet_video")
        self.assertEqual(upload_calls[0]["total_bytes"], str(len(MP4_BYTES)))
        self.assertEqual(upload_calls[1]["segment_index"], "0")
        self.assertEqual(
            base64.b64decode(upload_calls[1]["dataBase64"]),
            MP4_BYTES,
        )
        self.assertEqual(calls[-1][0], TWITTER_CREATE_TWEET_PATH)
        self.assertEqual(dict(calls[-1][1])["media_ids"], VIDEO_MEDIA_ID)

    def test_schedule_tweet_uploads_gif_via_chunked_commands(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            values = dict(entries)
            if path == TWITTER_UPLOAD_MEDIA_PATH:
                command = values.get("command")
                if command == "init":
                    return {"media_id_string": VIDEO_MEDIA_ID}
                if command in {"append", "finalize"}:
                    return {"media_id_string": VIDEO_MEDIA_ID}
                raise AssertionError(f"unexpected upload command: {command}")
            return {
                "operation": "CreateScheduledTweet",
                "data": {"scheduledtweet": {"rest_id": "99"}},
            }

        with tempfile.TemporaryDirectory() as raw:
            result = TwitterClient(browser_fetch=fetch).schedule_tweet(
                "hello",
                FUTURE_AT,
                media=[_gif(Path(raw))],
            )
        self.assertEqual(result["media_ids"], [VIDEO_MEDIA_ID])
        upload_calls = [
            dict(entries)
            for path, entries, _referer in calls
            if path == TWITTER_UPLOAD_MEDIA_PATH
        ]
        self.assertEqual(
            [item.get("command") for item in upload_calls],
            ["init", "append", "finalize"],
        )
        self.assertEqual(upload_calls[0]["mimeType"], "image/gif")
        self.assertEqual(upload_calls[0]["media_category"], "tweet_gif")
        self.assertEqual(calls[-1][0], TWITTER_CREATE_SCHEDULED_TWEET_PATH)

    def test_post_image_path_does_not_use_chunked_commands(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == TWITTER_UPLOAD_MEDIA_PATH:
                return {"media_id_string": "2211223344556677889"}
            return {
                "operation": "CreateTweet",
                "data": {"tweet": {"rest_id": "42"}},
            }

        with tempfile.TemporaryDirectory() as raw:
            TwitterClient(browser_fetch=fetch).post(
                "hello",
                media=[_png(Path(raw))],
            )
        self.assertEqual(
            dict(calls[0][1]),
            {
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(PNG_BYTES).decode("ascii"),
            },
        )
        self.assertNotIn("command", dict(calls[0][1]))

    def test_post_and_schedule_reject_image_video_mix(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            raise AssertionError("must not call browser")

        client = TwitterClient(browser_fetch=fetch)
        with tempfile.TemporaryDirectory() as raw:
            png = _png(Path(raw))
            mp4 = _mp4(Path(raw))
            gif = _gif(Path(raw))
            second_mp4 = _mp4(Path(raw), "b.mp4")
            with self.assertRaises(TwitterInputError) as tweet_mix:
                client.post("hello", media=[png, mp4])
            with self.assertRaises(TwitterInputError) as scheduled_mix:
                client.schedule_tweet(
                    "hello",
                    FUTURE_AT,
                    media=[png, mp4],
                )
            with self.assertRaises(TwitterInputError) as two_videos:
                client.post("hello", media=[mp4, second_mp4])
            with self.assertRaises(TwitterInputError) as gif_image:
                client.post("hello", media=[png, gif])
        self.assertIn("tweet cannot mix video", str(tweet_mix.exception))
        self.assertNotIn("scheduled", str(tweet_mix.exception))
        self.assertIn(
            "scheduled tweet cannot mix video",
            str(scheduled_mix.exception),
        )
        self.assertIn("at most one video", str(two_videos.exception))
        self.assertIn("cannot mix gif", str(gif_image.exception))
        self.assertEqual(calls, [])

    def test_post_status_failed_is_request_failed(self) -> None:
        def fetch(path, entries, referer):
            values = dict(entries)
            if path != TWITTER_UPLOAD_MEDIA_PATH:
                raise AssertionError("must not create tweet")
            command = values.get("command")
            if command == "init":
                return {"media_id_string": VIDEO_MEDIA_ID}
            if command == "append":
                return {}
            if command == "finalize":
                return {
                    "media_id_string": VIDEO_MEDIA_ID,
                    "processing_info": {"state": "failed"},
                }
            raise AssertionError(f"unexpected upload command: {command}")

        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(TwitterResponseError) as ctx:
                TwitterClient(browser_fetch=fetch).post(
                    "hello",
                    media=[_mp4(Path(raw))],
                )
        self.assertEqual(ctx.exception.code, "request_failed")

    def test_parser_exposes_like_reply_view_as_browser_commands(self) -> None:
        parser = cli._parser()
        like = parser.parse_args(["like", "--tweet-id", "https://x.com/a/status/20"])
        reply = parser.parse_args(
            ["reply", "--tweet-id", "20", "--text", "hello"]
        )
        view = parser.parse_args(["view", "--tweet-id", "20"])
        self.assertIn("like", cli._BROWSER_COMMANDS)
        self.assertIn("reply", cli._BROWSER_COMMANDS)
        self.assertIn("view", cli._BROWSER_COMMANDS)
        self.assertEqual(
            cli._BROWSER_ROUTES[TWITTER_LIKE_PATH],
            ("twitter_home", "https://x.com/home"),
        )
        self.assertEqual(
            cli._BROWSER_ROUTES[TWITTER_TWEET_DETAIL_PATH],
            ("twitter_home", "https://x.com/home"),
        )
        self.assertEqual(like.tweet_id, "https://x.com/a/status/20")
        self.assertEqual(reply.tweet_id, "20")
        self.assertEqual(reply.text, "hello")
        self.assertIsNone(reply.media)
        self.assertEqual(view.tweet_id, "20")
        help_text = parser.format_help()
        self.assertIn("通过 Chrome 登录态临时传输点赞一条推", help_text)
        self.assertIn("通过 Chrome 登录态临时传输回复一条推", help_text)
        self.assertIn("通过 Chrome 登录态临时传输浏览一条推", help_text)

    def test_like_sends_favorite_bridge_entries(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "source": "twitter_web_graphql",
                "transport": "browser_web",
                "endpoint": "/i/api/graphql/FAV/FavoriteTweet",
                "operation": "FavoriteTweet",
                "rate_limit": {"limit": 50},
                "data": {"favorite_tweet": "Done"},
            }

        result = TwitterClient(browser_fetch=fetch).like(
            "https://x.com/jack/status/20"
        )
        self.assertEqual(result["kind"], "twitter_like")
        self.assertEqual(result["tweet_id"], "20")
        self.assertEqual(result["id"], "20")
        self.assertEqual(result["operation"], "FavoriteTweet")
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0],
            (TWITTER_LIKE_PATH, [("tweet_id", "20")], TWITTER_HOME_REFERER),
        )

    def test_reply_calls_post_with_reply_to(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "data": {"tweet": {"rest_id": "42"}},
                "operation": "CreateTweet",
            }

        client = TwitterClient(browser_fetch=fetch)
        with patch.object(client, "post", wraps=client.post) as posted:
            result = client.reply(
                "https://x.com/a/status/1000000000000000002",
                "hello",
            )
        posted.assert_called_once_with(
            "hello",
            media=None,
            reply_to="1000000000000000002",
        )
        self.assertEqual(result["id"], "42")
        self.assertEqual(result["reply_to"], "1000000000000000002")
        self.assertEqual(calls[0][0], TWITTER_CREATE_TWEET_PATH)
        self.assertEqual(
            dict(calls[0][1]),
            {"text": "hello", "reply_to": "1000000000000000002"},
        )

    def test_view_sends_tweet_detail_bridge_entries(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "source": "twitter_web_graphql",
                "transport": "browser_web",
                "endpoint": "/i/api/graphql/DETAIL/TweetDetail",
                "operation": "TweetDetail",
                "rate_limit": {"limit": 50},
                "data": {
                    "threaded_conversation_with_injections_v2": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-20",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "rest_id": "20",
                                                        "legacy": {
                                                            "full_text": "hello"
                                                        },
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "rest_id": "1",
                                                                    "legacy": {
                                                                        "screen_name": "alice"
                                                                    },
                                                                }
                                                            }
                                                        },
                                                    }
                                                }
                                            }
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                },
            }

        result = TwitterClient(browser_fetch=fetch).view(
            "https://x.com/alice/status/20"
        )
        self.assertEqual(result["kind"], "twitter_tweet_detail")
        self.assertEqual(result["id"], "20")
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["author"]["rest_id"], "1")
        self.assertEqual(result["author"]["screen_name"], "alice")
        self.assertEqual(result["operation"], "TweetDetail")
        self.assertEqual(
            calls[0],
            (
                TWITTER_TWEET_DETAIL_PATH,
                [("tweet_id", "20")],
                TWITTER_HOME_REFERER,
            ),
        )

    def test_view_fills_missing_author_and_text_with_null(self) -> None:
        def fetch(path, entries, referer):
            return {
                "operation": "TweetDetail",
                "data": {
                    "tweet_results": {"result": {"rest_id": "20"}}
                },
            }

        result = TwitterClient(browser_fetch=fetch).view("20")
        self.assertEqual(result["id"], "20")
        self.assertIsNone(result["text"])
        self.assertIsNone(result["author"]["rest_id"])
        self.assertIsNone(result["author"]["screen_name"])

    def test_like_reply_view_reject_invalid_tweet_id(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            raise AssertionError("must not call browser")

        client = TwitterClient(browser_fetch=fetch)
        with self.assertRaises(TwitterInputError):
            client.like("abc")
        with self.assertRaises(TwitterInputError):
            client.view("https://example.com/status/1")
        with self.assertRaises(TwitterInputError):
            client.reply("abc", "hello")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
