from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from reverse.twitter_reverse.client import (
    TWITTER_CREATE_SCHEDULED_TWEET_PATH,
    TWITTER_FOLLOW_PATH,
    TWITTER_HOME_REFERER,
    TWITTER_UPLOAD_MEDIA_PATH,
    TwitterClient,
    extract_rest_id,
)
from reverse.twitter_reverse.errors import TwitterInputError, TwitterResponseError


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00"
FUTURE_AT = 2000000000


def _png(directory: Path, name: str = "pic.png") -> Path:
    path = directory / name
    path.write_bytes(PNG_BYTES)
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
            gif = Path(raw) / "pic.gif"
            gif.write_bytes(b"GIF89a" + b"\x00" * 8)
            with self.assertRaises(TwitterInputError):
                client.schedule_tweet("hello", FUTURE_AT, media=[gif])
            txt = Path(raw) / "note.txt"
            txt.write_bytes(b"not an image")
            with self.assertRaises(TwitterInputError):
                client.schedule_tweet("hello", FUTURE_AT, media=[txt])
        self.assertEqual(calls, [])

    def test_upload_media_error_code_passes_through(self) -> None:
        def fetch(path, entries, referer):
            raise TwitterResponseError("slow down", code="rate_limited")

        with self.assertRaises(TwitterResponseError) as ctx:
            TwitterClient(browser_fetch=fetch).follow(user_id="12345")
        self.assertEqual(ctx.exception.code, "rate_limited")


if __name__ == "__main__":
    unittest.main()
