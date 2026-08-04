from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.threads_reverse.client import DEFAULT_USER_AGENT, ThreadsClient
from reverse.threads_reverse.errors import ThreadsError, ThreadsInputError, ThreadsResponseError

FIXTURES = Path(__file__).with_name("fixtures")
PROFILE_PAGE = (FIXTURES / "profile_page.html").read_text(encoding="utf-8")
POST_PAGE = (FIXTURES / "post_page.html").read_text(encoding="utf-8")
POST_EMBED = (FIXTURES / "post_embed.html").read_text(encoding="utf-8")


def html_response(
    source: str,
    *,
    status: int = 200,
    url: str = "",
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["content-type"] = "text/html; charset=utf-8"
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


class ThreadsClientTest(unittest.TestCase):
    def test_public_error_hierarchy_and_crawler_headers(self) -> None:
        self.assertTrue(issubclass(ThreadsInputError, ThreadsError))
        self.assertTrue(issubclass(ThreadsResponseError, ThreadsError))
        session = FakeSession([])
        ThreadsClient(session=session)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("text/html", session.headers["Accept"])

    def test_profile_reference_accepts_handle_and_both_domains(self) -> None:
        self.assertEqual(ThreadsClient.resolve_username("@Zuck"), "zuck")
        self.assertEqual(ThreadsClient.resolve_username("zuck"), "zuck")
        self.assertEqual(
            ThreadsClient.resolve_username("https://www.threads.net/@Zuck?hl=en"),
            "zuck",
        )
        self.assertEqual(
            ThreadsClient.resolve_username("Open https://threads.com/@zuck now"),
            "zuck",
        )

    def test_profile_reference_rejects_lookalikes_and_bad_routes(self) -> None:
        for value in (
            "https://threads.com.example/@zuck",
            "https://user@threads.com/@zuck",
            "https://threads.com:444/@zuck",
            "https://threads.com/@zuck/post/DPVUglOjOUu",
            "@bad..name",
            "",
        ):
            with self.subTest(value=value), self.assertRaises(ThreadsInputError):
                ThreadsClient.resolve_username(value)

    def test_post_reference_accepts_url_share_shortcode_legacy_and_numeric_id(self) -> None:
        direct = ThreadsClient.resolve_post_reference(
            "https://www.threads.net/@taylorswift/post/DPVUglOjOUu?xmt=fixture"
        )
        self.assertEqual(direct["username"], "taylorswift")
        self.assertEqual(direct["shortcode"], "DPVUglOjOUu")
        self.assertEqual(direct["id"], "3734981665899734318")
        self.assertEqual(
            direct["url"],
            "https://www.threads.com/@taylorswift/post/DPVUglOjOUu",
        )

        share = ThreadsClient.resolve_post_reference(
            "Look https://threads.com/@taylorswift/post/DPVUglOjOUu)."
        )
        self.assertEqual(share["shortcode"], "DPVUglOjOUu")
        legacy = ThreadsClient.resolve_post_reference("https://threads.net/t/DPVUglOjOUu")
        self.assertIsNone(legacy["username"])
        raw = ThreadsClient.resolve_post_reference("DPVUglOjOUu")
        numeric = ThreadsClient.resolve_post_reference("3734981665899734318")
        self.assertEqual(raw["id"], numeric["id"])
        self.assertEqual(raw["shortcode"], numeric["shortcode"])

    def test_post_reference_rejects_foreign_hosts_and_malformed_paths(self) -> None:
        for value in (
            "https://example.com/@taylorswift/post/DPVUglOjOUu",
            "https://threads.com.example/@taylorswift/post/DPVUglOjOUu",
            "https://threads.com/@taylorswift/reply/DPVUglOjOUu",
            "https://threads.com/@taylorswift/post/DPVUglOjOUu/extra",
            "https://threads.com/@bad..name/post/DPVUglOjOUu",
        ):
            with self.subTest(value=value), self.assertRaises(ThreadsInputError):
                ThreadsClient.resolve_post_reference(value)

    def test_shortcode_numeric_id_round_trip_matches_real_samples(self) -> None:
        samples = {
            "3734981665899734318": "DPVUglOjOUu",
            "3349029093483693129": "C56JDdzi0RJ",
            "3390920896561588969": "C8O-JbtAKrp",
        }
        for media_id, shortcode in samples.items():
            with self.subTest(shortcode=shortcode):
                self.assertEqual(ThreadsClient.media_id_to_shortcode(media_id), shortcode)
                self.assertEqual(ThreadsClient.shortcode_to_media_id(shortcode), media_id)
        with self.assertRaises(ThreadsInputError):
            ThreadsClient.media_id_to_shortcode("0")

    def test_profile_fixture_parses_open_graph_stats_bio_and_route_id(self) -> None:
        profile = ThreadsClient.parse_profile_html(
            PROFILE_PAGE,
            expected_username="zuck",
        )
        self.assertEqual(profile["id"], "63055343223")
        self.assertEqual(profile["username"], "zuck")
        self.assertEqual(profile["name"], "Mark Zuckerberg")
        self.assertEqual(profile["stats"], {"followers": 5_700_000, "threads": 151})
        self.assertEqual(profile["stats_display"]["followers"], "5.7M")
        self.assertEqual(
            profile["biography"],
            "Mostly superintelligence and MMA takes.",
        )
        self.assertEqual(
            profile["avatar"],
            "https://cdn.example/profile-zuck.jpg?size=640&fixture=1",
        )

    def test_profile_mismatch_and_empty_public_metadata_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(ThreadsResponseError, "expected @different"):
            ThreadsClient.parse_profile_html(PROFILE_PAGE, expected_username="different")
        with self.assertRaisesRegex(ThreadsResponseError, "public username"):
            ThreadsClient.parse_profile_html("<html><head></head></html>")

    def test_post_page_fixture_parses_canonical_route_and_open_graph(self) -> None:
        post = ThreadsClient.parse_post_page_html(
            POST_PAGE,
            expected_shortcode="DPVUglOjOUu",
        )
        self.assertEqual(post["id"], "3734981665899734318")
        self.assertEqual(post["owner_id"], "66109110437")
        self.assertFalse(post["is_reply"])
        self.assertEqual(post["username"], "taylorswift")
        self.assertEqual(post["author_name"], "Taylor Swift")
        self.assertEqual(post["open_graph"]["image_width"], 2159)

    def test_gallery_embed_parses_full_text_author_links_media_time_and_stats(self) -> None:
        post = ThreadsClient.parse_embed_html(
            POST_EMBED,
            expected_shortcode="DPVUglOjOUu",
        )
        self.assertEqual(post["id"], "3734981665899734318")
        self.assertEqual(post["media_type"], "carousel")
        self.assertEqual(
            post["text"],
            "I can't tell you how proud I am.\nAlbum out now. example.com/album",
        )
        self.assertEqual(post["author"]["username"], "taylorswift")
        self.assertTrue(post["author"]["verified"])
        self.assertEqual(len(post["images"]), 4)
        self.assertEqual(post["images"][0]["height"], 300)
        self.assertEqual(post["links"][0]["url"], "https://example.com/album")
        self.assertEqual(post["topics"][0]["name"], "music")
        self.assertEqual(post["published_at_text"], "9:08 PM \u00b7 Oct 2, 2025")
        self.assertEqual(
            post["stats"],
            {"likes": 139_000, "replies": 6_400, "reposts": 11_600, "shares": 1_300},
        )

    def test_video_embed_preserves_zero_count_position(self) -> None:
        source = """
        <div class="LinkContainer"><a href="https://threads.com/@aiatmeta/post/C56JDdzi0RJ"></a></div>
        <div class="OuterContainer">
          <div class="AvatarContainer"><img src="https://cdn.example/avatar.jpg"></div>
          <a class="HeaderLink" href="https://threads.com/@aiatmeta"><span>aiatmeta</span></a>
          <span class="BodyTextContainer">Fixture video</span>
          <div class="SingleInnerMediaContainerVideo"><video><source src="https://cdn.example/video.mp4"></video></div>
          <span class="Timestamp">9:30 AM &middot; Apr 18, 2024</span>
          <div class="ActionBarContainer">
            <span class="ActionBarIcon"><span class="ActionBarCount">520</span></span>
            <span class="ActionBarIcon"></span>
            <span class="ActionBarIcon"><span class="ActionBarCount">52</span></span>
            <span class="ActionBarIcon"><span class="ActionBarCount">91</span></span>
          </div>
        </div>
        """
        post = ThreadsClient.parse_embed_html(source, expected_shortcode="C56JDdzi0RJ")
        self.assertEqual(post["media_type"], "video")
        self.assertEqual(post["video_url"], "https://cdn.example/video.mp4")
        self.assertEqual(
            post["stats"],
            {"likes": 520, "replies": 0, "reposts": 52, "shares": 91},
        )

    def test_nested_visible_post_blocks_keep_main_post_first(self) -> None:
        source = """
        <div class="LinkContainer"><a href="https://threads.com/@outer/post/DPVUglOjOUu"></a></div>
        <div class="OuterContainer">
          <a class="HeaderLink" href="https://threads.com/@outer">outer</a>
          <span class="BodyTextContainer">outer text</span>
          <div class="OuterContainer">
            <a class="HeaderLink" href="https://threads.com/@quoted">quoted</a>
            <span class="BodyTextContainer">quoted text</span>
          </div>
        </div>
        """
        post = ThreadsClient.parse_embed_html(source)
        self.assertEqual(post["author"]["username"], "outer")
        self.assertEqual(post["quoted_posts"][0]["author"]["username"], "quoted")

    def test_get_profile_and_post_use_only_injected_http_session(self) -> None:
        profile_session = FakeSession(
            [html_response(PROFILE_PAGE, url="https://www.threads.com/@zuck")]
        )
        profile = ThreadsClient(session=profile_session, retries=0).get_profile("zuck")
        self.assertEqual(profile["id"], "63055343223")
        self.assertEqual(profile_session.calls[0][0], "https://www.threads.com/@zuck")
        self.assertTrue(profile_session.calls[0][1]["allow_redirects"])

        post_session = FakeSession(
            [
                html_response(
                    POST_EMBED,
                    url="https://www.threads.com/@taylorswift/post/DPVUglOjOUu/embed",
                ),
                html_response(
                    POST_PAGE,
                    url="https://www.threads.com/@taylorswift/post/DPVUglOjOUu",
                ),
            ]
        )
        post = ThreadsClient(session=post_session, retries=0).get_post("DPVUglOjOUu")
        self.assertEqual(post["owner_id"], "66109110437")
        self.assertEqual(post["author"]["name"], "Taylor Swift")
        self.assertEqual(
            post_session.calls[0][0],
            "https://www.threads.com/@threads/post/DPVUglOjOUu/embed",
        )
        self.assertEqual(
            post_session.calls[1][0],
            "https://www.threads.com/@taylorswift/post/DPVUglOjOUu",
        )

    def test_transport_and_transient_http_failures_retry(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection error"),
                html_response("busy", status=503),
                html_response(PROFILE_PAGE, url="https://www.threads.com/@zuck"),
            ]
        )
        client = ThreadsClient(session=session, retries=2)
        with patch("reverse.threads_reverse.client.time.sleep") as sleep:
            profile = client.get_profile("zuck")
        self.assertEqual(profile["username"], "zuck")
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleep.call_count, 2)

        failing = FakeSession([html_response("missing", status=404)])
        with self.assertRaisesRegex(ThreadsResponseError, "HTTP 404"):
            ThreadsClient(session=failing, retries=0).get_profile("zuck")

    def test_missing_embed_post_and_shortcode_mismatch_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(ThreadsResponseError, "public post"):
            ThreadsClient.parse_embed_html("<html><body>gate</body></html>")
        with self.assertRaisesRegex(ThreadsResponseError, "expected C56JDdzi0RJ"):
            ThreadsClient.parse_embed_html(
                POST_EMBED,
                expected_shortcode="C56JDdzi0RJ",
            )


if __name__ == "__main__":
    unittest.main()
