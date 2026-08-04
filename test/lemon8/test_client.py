from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.lemon8_reverse.client import DEFAULT_USER_AGENT, Lemon8Client
from reverse.lemon8_reverse.errors import Lemon8Error, Lemon8InputError, Lemon8ResponseError

FIXTURES = Path(__file__).with_name("fixtures")
GALLERY_HTML = (FIXTURES / "gallery_post.html").read_text(encoding="utf-8")
VIDEO_HTML = (FIXTURES / "video_post.html").read_text(encoding="utf-8")
PROFILE_HTML = (FIXTURES / "profile.html").read_text(encoding="utf-8")


def html_response(source: str, *, status: int = 200, url: str = "") -> requests.Response:
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


class Lemon8ClientTest(unittest.TestCase):
    def test_public_error_hierarchy_and_default_headers(self) -> None:
        self.assertTrue(issubclass(Lemon8InputError, Lemon8Error))
        self.assertTrue(issubclass(Lemon8ResponseError, Lemon8Error))
        session = FakeSession([])
        Lemon8Client(session=session)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("text/html", session.headers["Accept"])

    def test_post_reference_normalizes_id_author_locale_and_region_host(self) -> None:
        identifier = "7530097453324861953"
        bare = Lemon8Client.parse_post_reference(identifier, region="SG")
        self.assertEqual(bare["id"], identifier)
        self.assertIsNone(bare["author"])
        self.assertEqual(
            bare["url"],
            f"https://www.lemon8-app.com/@_/{identifier}?region=sg",
        )

        regional = Lemon8Client.parse_post_reference(
            f"https://sg.lemon8-app.com/en-SG/fixture.author/{identifier}?tracking=x"
        )
        self.assertEqual(regional["author"], "fixture.author")
        self.assertEqual(regional["region"], "sg")
        self.assertEqual(
            regional["url"],
            f"https://www.lemon8-app.com/@fixture.author/{identifier}?region=sg",
        )

        no_author = Lemon8Client.parse_post_reference(
            f"https://www.lemon8-app.com/article/{identifier}"
        )
        self.assertIsNone(no_author["author"])
        self.assertEqual(no_author["id"], identifier)

    def test_short_link_and_share_text_are_recognized_without_guessing_id(self) -> None:
        parsed = Lemon8Client.parse_post_reference(
            "Open this https://v.lemon8-app.com/al/OghwFTppx\u3002"
        )
        self.assertTrue(parsed["is_short_url"])
        self.assertIsNone(parsed["id"])
        self.assertEqual(parsed["url"], "https://v.lemon8-app.com/al/OghwFTppx")
        with self.assertRaisesRegex(Lemon8InputError, "require one HTTP request"):
            Lemon8Client.resolve_post_id(parsed["url"])

    def test_user_reference_accepts_handle_user_id_and_post_url(self) -> None:
        handle = Lemon8Client.parse_user_reference("@dateandtravell", region="US")
        self.assertEqual(handle["author"], "dateandtravell")
        self.assertEqual(
            handle["url"],
            "https://www.lemon8-app.com/@dateandtravell?region=us",
        )
        user_id = Lemon8Client.parse_user_reference("7191537130350330923")
        self.assertEqual(
            user_id["url"],
            "https://www.lemon8-app.com/user/7191537130350330923/share?region=us",
        )
        post = Lemon8Client.parse_user_reference(
            "https://www.lemon8-app.com/@dateandtravell/7548476697771950647?region=us"
        )
        self.assertEqual(post["author"], "dateandtravell")
        follow = Lemon8Client.parse_user_reference(
            "https://www.lemon8-app.com/@dateandtravell/follow?region=us"
        )
        self.assertEqual(follow["author"], "dateandtravell")
        self.assertEqual(Lemon8Client.resolve_author("@dateandtravell"), "dateandtravell")

    def test_reference_validation_rejects_lookalike_hosts_and_bad_values(self) -> None:
        with self.assertRaises(Lemon8InputError):
            Lemon8Client.parse_post_reference(
                "https://www.lemon8-app.com.example/@user/7530097453324861953"
            )
        with self.assertRaises(Lemon8InputError):
            Lemon8Client.parse_post_reference("123")
        with self.assertRaises(Lemon8InputError):
            Lemon8Client.parse_post_reference(
                "https://www.lemon8-app.com/extra/@user/7530097453324861953"
            )
        with self.assertRaises(Lemon8InputError):
            Lemon8Client.parse_post_reference(
                "https://www.lemon8-app.com:bad/@user/7530097453324861953"
            )
        with self.assertRaises(Lemon8InputError):
            Lemon8Client.parse_post_reference(
                "ftp://www.lemon8-app.com/@user/7530097453324861953"
            )
        with self.assertRaises(Lemon8InputError):
            Lemon8Client.parse_user_reference("https://www.lemon8-app.com/legal")
        with self.assertRaises(Lemon8InputError):
            Lemon8Client(region="usa")

    def test_gallery_remix_hydration_and_open_graph_are_normalized(self) -> None:
        post = Lemon8Client.parse_post_html(
            GALLERY_HTML,
            expected_id="7530097453324861953",
            page_url="https://www.lemon8-app.com/@fixture.author/7530097453324861953?region=sg",
        )
        self.assertEqual(post["source"], "hydration")
        self.assertEqual(post["media_type"], "gallery")
        self.assertEqual(post["title"], "Fixture gallery")
        self.assertEqual(post["body"], "First paragraph #Skin Care\nSecond paragraph.")
        self.assertEqual(post["author"]["id"], "6999059584212648961")
        self.assertEqual(post["author"]["username"], "fixture.author")
        self.assertTrue(post["author"]["verified"])
        self.assertEqual(post["stats"], {"views": 42, "likes": 7, "saves": 5, "comments": 3})
        self.assertEqual([tag["name"] for tag in post["tags"]], ["Skin Care"])
        self.assertEqual(post["tags"][0]["id"], "7209005694262411270")
        self.assertEqual(len(post["images"]), 2)
        self.assertEqual(post["images"][0]["share_url"], "https://cdn.example/share-1.jpeg")
        self.assertIsNone(post["video"]["url"])
        self.assertEqual(post["published_at"], "2025-07-23T02:28:50+00:00")
        self.assertEqual(post["location"]["name"], "Singapore")
        self.assertEqual(post["ocr_text"], ["fixture ocr"])
        self.assertEqual(post["open_graph"]["title"], "SEO fixture gallery title")

    def test_video_next_data_normalizes_cover_stream_stats_and_time(self) -> None:
        post = Lemon8Client.parse_post_html(
            VIDEO_HTML,
            expected_id="7548476697771950647",
            page_url="https://www.lemon8-app.com/@dateandtravell/7548476697771950647?region=us",
        )
        self.assertEqual(post["media_type"], "video")
        self.assertEqual(post["images"][0]["role"], "cover")
        self.assertEqual(post["video"]["url"], "https://cdn.example/video.mp4")
        self.assertEqual(post["video"]["duration_seconds"], 9)
        self.assertFalse(post["video"]["muted"])
        self.assertEqual(post["stats"]["views"], 8137)
        self.assertEqual(post["published_at"], "2025-09-10T15:06:49+00:00")

    def test_open_graph_only_page_is_a_structured_fallback(self) -> None:
        source = """<html><head>
        <meta property="og:title" content="Fallback title">
        <meta property="og:description" content="Fallback #tag">
        <meta property="og:url" content="/@fixture/7530097453324861953">
        <meta property="og:image" content="https://cdn.example/fallback.jpg">
        </head></html>"""
        post = Lemon8Client.parse_post_html(
            source,
            page_url="https://www.lemon8-app.com/@fixture/7530097453324861953?region=us",
        )
        self.assertEqual(post["source"], "open_graph")
        self.assertEqual(post["title"], "Fallback title")
        self.assertEqual(post["body"], "Fallback #tag")
        self.assertEqual(post["images"][0]["role"], "open_graph")
        self.assertEqual(post["tags"][0]["name"], "tag")

    def test_profile_prefers_full_user_detail_over_feed_author(self) -> None:
        profile = Lemon8Client.parse_profile_html(
            PROFILE_HTML,
            expected_author="dateandtravell",
            page_url="https://www.lemon8-app.com/@dateandtravell?region=us",
        )
        self.assertEqual(profile["id"], "7191537130350330923")
        self.assertEqual(profile["name"], "Date and Travel")
        self.assertEqual(profile["bio"], "Fixture profile")
        self.assertTrue(profile["verified"])
        self.assertEqual(profile["stats"]["followers"], 28257)
        self.assertEqual(profile["stats"]["posts"], 208)
        self.assertEqual(profile["stats"]["likes_received"], 56862)
        self.assertEqual(profile["links"][0]["url"], "https://example.com")

    def test_numeric_id_uses_placeholder_route_and_server_canonical_redirect(self) -> None:
        final_url = "https://www.lemon8-app.com/@dateandtravell/7548476697771950647?region=us"
        session = FakeSession([html_response(VIDEO_HTML, url=final_url)])
        client = Lemon8Client(session=session, retries=0)

        post = client.get_post("7548476697771950647")

        self.assertEqual(post["author"]["username"], "dateandtravell")
        self.assertEqual(
            session.calls[0][0],
            "https://www.lemon8-app.com/@_/7548476697771950647?region=us",
        )
        self.assertTrue(session.calls[0][1]["allow_redirects"])
        self.assertEqual(session.calls[0][1]["headers"], {"Referer": "https://www.lemon8-app.com/"})

    def test_short_link_fetches_and_parses_final_page_in_one_request(self) -> None:
        final_url = "https://www.lemon8-app.com/@fixture.author/7530097453324861953?region=sg"
        session = FakeSession([html_response(GALLERY_HTML, url=final_url)])
        client = Lemon8Client(session=session, retries=0)

        post = client.get_post("https://v.lemon8-app.com/al/FIXTURE")

        self.assertEqual(post["id"], "7530097453324861953")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][0], "https://v.lemon8-app.com/al/FIXTURE")

    def test_redirect_outside_lemon8_hosts_is_rejected(self) -> None:
        response = html_response(
            VIDEO_HTML,
            url="https://www.lemon8-app.com.example/@dateandtravell/7548476697771950647",
        )
        client = Lemon8Client(session=FakeSession([response]), retries=0)
        with self.assertRaisesRegex(Lemon8ResponseError, "left the owned hosts"):
            client.get_post("https://v.lemon8-app.com/al/FIXTURE")

    def test_user_id_route_and_final_author_profile(self) -> None:
        final_url = "https://www.lemon8-app.com/@dateandtravell?region=us"
        session = FakeSession([html_response(PROFILE_HTML, url=final_url)])
        profile = Lemon8Client(session=session, retries=0).get_user_profile(
            "7191537130350330923"
        )
        self.assertEqual(profile["username"], "dateandtravell")
        self.assertEqual(
            session.calls[0][0],
            "https://www.lemon8-app.com/user/7191537130350330923/share?region=us",
        )

    def test_transport_and_retryable_http_failures_back_off(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection error"),
                html_response("slow down", status=429),
                html_response("temporary", status=503),
                html_response(VIDEO_HTML),
            ]
        )
        client = Lemon8Client(session=session, retries=3)
        with patch("reverse.lemon8_reverse.client.time.sleep") as sleep:
            post = client.get_post("7548476697771950647")
        self.assertEqual(post["id"], "7548476697771950647")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,), (1.6,)])

    def test_deterministic_http_and_data_errors_do_not_retry(self) -> None:
        session = FakeSession([html_response("missing", status=404), html_response(VIDEO_HTML)])
        client = Lemon8Client(session=session, retries=2)
        with self.assertRaisesRegex(Lemon8ResponseError, "HTTP 404"):
            client.get_post("7548476697771950647")
        self.assertEqual(len(session.calls), 1)

        with self.assertRaisesRegex(Lemon8ResponseError, "public post data"):
            Lemon8Client.parse_post_html(
                '<meta property="og:url" content="/@fixture/7530097453324861953">',
                page_url="https://www.lemon8-app.com/@fixture/7530097453324861953",
            )
        with self.assertRaisesRegex(Lemon8ResponseError, "public user data"):
            Lemon8Client.parse_profile_html("<html><body>missing</body></html>")

    def test_expected_identity_mismatch_is_reported(self) -> None:
        with self.assertRaisesRegex(Lemon8ResponseError, "expected 7548476697771950647"):
            Lemon8Client.parse_post_html(
                GALLERY_HTML,
                expected_id="7548476697771950647",
                page_url="https://www.lemon8-app.com/@fixture.author/7530097453324861953",
            )
        with self.assertRaisesRegex(Lemon8ResponseError, "expected other.author"):
            Lemon8Client.parse_profile_html(
                PROFILE_HTML,
                expected_author="other.author",
            )


if __name__ == "__main__":
    unittest.main()
