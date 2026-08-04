from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.telegram_reverse.client import TelegramClient
from reverse.telegram_reverse.errors import TelegramError, TelegramInputError, TelegramResponseError

FIXTURES = Path(__file__).with_name("fixtures")
CHANNEL_HTML = (FIXTURES / "channel_page.html").read_text(encoding="utf-8")
OLDER_HTML = (FIXTURES / "older_page.html").read_text(encoding="utf-8")
SEARCH_HTML = (FIXTURES / "search_page.html").read_text(encoding="utf-8")


def response(source: str, *, status: int = 200, url: str = "") -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
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
            raise AssertionError("unexpected HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result


class TelegramClientTest(unittest.TestCase):
    def test_error_types_share_the_public_base(self) -> None:
        self.assertTrue(issubclass(TelegramInputError, TelegramError))
        self.assertTrue(issubclass(TelegramResponseError, TelegramError))

    def test_channel_metadata_is_parsed_and_counts_are_normalized(self) -> None:
        channel = TelegramClient.parse_channel_html(CHANNEL_HTML)

        self.assertEqual(channel["username"], "FixtureNews")
        self.assertEqual(channel["title"], "Fixture Channel")
        self.assertEqual(channel["description"], "Public fixture description")
        self.assertEqual(channel["avatar"], "https://cdn.example/avatar.jpg")
        self.assertTrue(channel["verified"])
        self.assertEqual(channel["subscribers"], 1250)
        self.assertEqual(channel["counters"], {"subscribers": 1250, "photos": 12})
        self.assertEqual(channel["counter_text"]["subscribers"], "1.25K")

    def test_post_body_media_metrics_reactions_and_time_are_normalized(self) -> None:
        post = TelegramClient.parse_post_html(CHANNEL_HTML, post_id=101)

        self.assertEqual(post["channel"], "FixtureNews")
        self.assertEqual(post["text"], "Hello 🌍\n\nRead more")
        self.assertEqual(post["links"], [{"url": "https://example.com/a?b=1", "text": "more"}])
        self.assertEqual(post["media"], [{"type": "photo", "url": "https://cdn.example/photo.jpg"}])
        self.assertEqual(post["views"], 1200)
        self.assertEqual(post["views_text"], "1.2K")
        self.assertEqual(post["forwards"], 34)
        self.assertEqual(
            post["forwarded_from"],
            {"name": "Source News", "url": "https://t.me/SourceNews/77"},
        )
        self.assertEqual(post["reaction_count"], 2510)
        self.assertEqual(post["reactions"][0]["emoji"], "⭐")
        self.assertEqual(post["reactions"][1]["emoji_id"], "123456")
        self.assertEqual(post["reactions"][2]["emoji"], "🔥")
        self.assertEqual(post["published_at"], "2024-01-01T00:00:00+00:00")
        self.assertEqual(post["published_timestamp"], 1704067200)
        self.assertTrue(post["edited"])

    def test_video_and_link_preview_are_distinct_media_items(self) -> None:
        post = TelegramClient.parse_post_html(CHANNEL_HTML, post_id="100")

        self.assertEqual(post["media"][0]["type"], "video")
        self.assertEqual(post["media"][0]["url"], "https://cdn.example/video.mp4")
        self.assertEqual(post["media"][0]["thumbnail_url"], "https://cdn.example/thumb.jpg")
        self.assertEqual(post["media"][0]["duration"], 62)
        self.assertEqual(post["media"][1]["type"], "link_preview")
        self.assertEqual(post["media"][1]["title"], "Preview title")

    def test_posts_follow_before_cursor_and_return_newest_first(self) -> None:
        session = FakeSession([response(CHANNEL_HTML), response(OLDER_HTML)])
        client = TelegramClient(session=session)

        result = client.get_posts("@FixtureNews", limit=3)

        self.assertEqual([post["id"] for post in result["posts"]], ["101", "100", "99"])
        self.assertEqual(result["total"], 3)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_before"], "99")
        self.assertEqual(session.calls[0][0], "https://t.me/s/FixtureNews")
        self.assertEqual(session.calls[0][1]["params"], {})
        self.assertEqual(session.calls[1][1]["params"], {"before": "100"})

    def test_page_truncation_exposes_cursor_even_without_older_page_link(self) -> None:
        source = CHANNEL_HTML.replace(
            '<a class="tme_messages_more js-messages_more" data-before="100" href="/s/FixtureNews?before=100"></a>',
            "",
        ).replace('<link rel="prev" href="/s/FixtureNews?before=100">', "")
        session = FakeSession([response(source)])
        client = TelegramClient(session=session)

        result = client.get_posts("FixtureNews", limit=1)

        self.assertEqual([post["id"] for post in result["posts"]], ["101"])
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_before"], "101")

    def test_search_passes_query_and_before_and_deduplicates_pages(self) -> None:
        session = FakeSession([response(SEARCH_HTML), response(CHANNEL_HTML)])
        client = TelegramClient(session=session)

        result = client.search(
            "@FixtureNews",
            "  release notes  ",
            before="200",
            limit=3,
        )

        self.assertEqual([post["id"] for post in result["posts"]], ["103", "101", "100"])
        self.assertEqual(result["query"], "release notes")
        self.assertEqual(result["scope"], "recent")
        self.assertTrue(result["bounded"])
        self.assertEqual(result["before"], "200")
        self.assertEqual(result["next_before"], "100")
        self.assertTrue(result["has_more"])
        self.assertEqual(
            [call[1]["params"] for call in session.calls],
            [
                {"q": "release notes", "before": "200"},
                {"q": "release notes", "before": "101"},
            ],
        )

    def test_search_rejects_repeated_cursor(self) -> None:
        client = TelegramClient(
            session=FakeSession([response(SEARCH_HTML), response(SEARCH_HTML)])
        )

        with self.assertRaisesRegex(TelegramResponseError, "repeated cursor 101"):
            client.search("FixtureNews", "release", limit=20)

    def test_search_inputs_are_bounded_before_network_access(self) -> None:
        client = TelegramClient(session=FakeSession([]))

        for query in ("", "x" * 101, "release\nnotes"):
            with self.subTest(query=query):
                with self.assertRaises(TelegramInputError):
                    client.search("FixtureNews", query)
        for limit in (0, 101):
            with self.subTest(limit=limit):
                with self.assertRaises(TelegramInputError):
                    client.search("FixtureNews", "release", limit=limit)
        with self.assertRaises(TelegramInputError):
            client.search("FixtureNews", "release", before="0")
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]

    def test_channels_returns_ordered_per_item_success_and_errors(self) -> None:
        session = FakeSession([response(CHANNEL_HTML), response("missing", status=404)])
        client = TelegramClient(session=session, retries=0)

        result = client.get_channels(["@FixtureNews", "bad/channel", "MissingNews"])

        self.assertEqual(result["requested"], 3)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["error_count"], 2)
        self.assertEqual(
            [item["input"] for item in result["results"]],
            ["@FixtureNews", "bad/channel", "MissingNews"],
        )
        self.assertTrue(result["results"][0]["ok"])
        self.assertIsNone(result["results"][0]["error"])
        self.assertEqual(result["results"][1]["error"]["code"], "input_error")
        self.assertEqual(result["results"][2]["error"]["code"], "response_error")
        self.assertEqual(len(session.calls), 2)

    def test_channels_batch_size_is_bounded_before_network_access(self) -> None:
        client = TelegramClient(session=FakeSession([]))

        for references in ([], ["FixtureNews"] * 21):
            with self.subTest(size=len(references)):
                with self.assertRaises(TelegramInputError):
                    client.get_channels(references)
        with self.assertRaises(TelegramInputError):
            client.get_channels("FixtureNews")  # type: ignore[arg-type]
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]

    def test_single_post_uses_before_id_plus_one_and_selects_exact_id(self) -> None:
        session = FakeSession([response(CHANNEL_HTML)])
        client = TelegramClient(session=session)

        post = client.get_post("https://t.me/FixtureNews/101")

        self.assertEqual(post["id"], "101")
        self.assertEqual(session.calls[0][1]["params"], {"before": "102"})

    def test_transient_failures_retry_with_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection failure"),
                response("temporary", status=503),
                response(CHANNEL_HTML),
            ]
        )
        client = TelegramClient(session=session, retries=2)

        with patch("reverse.telegram_reverse.client.time.sleep") as sleep:
            channel = client.get_channel("FixtureNews")

        self.assertEqual(channel["username"], "FixtureNews")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

    def test_deterministic_http_and_malformed_html_fail_cleanly(self) -> None:
        client = TelegramClient(
            session=FakeSession([response("missing", status=404), response(CHANNEL_HTML)]),
            retries=2,
        )
        with self.assertRaisesRegex(TelegramResponseError, "HTTP 404"):
            client.get_channel("FixtureNews")
        self.assertEqual(len(client.session.calls), 1)  # type: ignore[attr-defined]

        malformed = TelegramClient(session=FakeSession([response("<html>private</html>")]))
        with self.assertRaisesRegex(TelegramResponseError, "public channel history"):
            malformed.get_posts("FixtureNews")

    def test_inputs_are_validated_without_network_access(self) -> None:
        client = TelegramClient(session=FakeSession([]))

        with self.assertRaises(TelegramInputError):
            client.get_channel("https://example.com/FixtureNews")
        with self.assertRaises(TelegramInputError):
            client.get_channel("https://t.me/+private-invite")
        with self.assertRaises(TelegramInputError):
            client.get_post("FixtureNews/0")
        with self.assertRaises(TelegramInputError):
            client.get_posts("FixtureNews", limit=-1)

        empty = client.get_posts("FixtureNews", limit=0)
        self.assertEqual(empty["posts"], [])
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
