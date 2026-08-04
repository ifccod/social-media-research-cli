from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.instagram_reverse.client import WEB_APP_ID, InstagramClient
from reverse.instagram_reverse.errors import InstagramError, InstagramInputError, InstagramResponseError

FIXTURES = Path(__file__).with_name("fixtures")
PROFILE = json.loads((FIXTURES / "profile.json").read_text(encoding="utf-8"))
POST_EMBED = (FIXTURES / "post_embed.html").read_text(encoding="utf-8")


def response(payload: object, *, status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = ""
    result.headers["content-type"] = "application/json"
    result.content = json.dumps(payload).encode("utf-8")
    return result


def html_response(source: str, *, status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = ""
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
        response_cookies = getattr(result, "cookies", None)
        if response_cookies is not None:
            self.cookies.update(response_cookies)
        return result


class InstagramClientTest(unittest.TestCase):
    def test_public_error_hierarchy(self) -> None:
        self.assertTrue(issubclass(InstagramInputError, InstagramError))
        self.assertTrue(issubclass(InstagramResponseError, InstagramError))

    def test_username_and_shortcode_urls_are_validated(self) -> None:
        self.assertEqual(InstagramClient.resolve_username("@NASA"), "nasa")
        self.assertEqual(
            InstagramClient.resolve_username("https://www.instagram.com/Fixture.User/?hl=en"),
            "fixture.user",
        )
        self.assertEqual(
            InstagramClient.resolve_shortcode("https://www.instagram.com/reel/DbB4is3D0GM/?igsh=x"),
            "DbB4is3D0GM",
        )
        with self.assertRaises(InstagramInputError):
            InstagramClient.resolve_username("fixture..user")
        with self.assertRaises(InstagramInputError):
            InstagramClient.resolve_username("https://www.instagram.com/p/code/")
        with self.assertRaises(InstagramInputError):
            InstagramClient.resolve_username("https://instagram.com.example/nasa/")
        with self.assertRaises(InstagramInputError):
            InstagramClient.resolve_shortcode("https://example.com/p/DbB4is3D0GM/")

    def test_shortcode_media_id_conversion_uses_instagram_alphabet(self) -> None:
        shortcode = "DbB4is3D0GM"
        media_id = "3945683423788482956"
        self.assertEqual(InstagramClient.shortcode_to_media_id(shortcode), media_id)
        self.assertEqual(InstagramClient.media_id_to_shortcode(media_id), shortcode)
        with self.assertRaises(InstagramInputError):
            InstagramClient.media_id_to_shortcode("0")

    def test_profile_normalizes_public_fields_and_request_contract(self) -> None:
        session = FakeSession([response(PROFILE)])
        client = InstagramClient(session=session, retries=0)

        profile = client.get_user_profile("https://instagram.com/Fixture.User/")

        self.assertEqual(profile["id"], "42")
        self.assertEqual(profile["username"], "fixture.user")
        self.assertEqual(profile["followers"], 1250)
        self.assertEqual(profile["following"], 25)
        self.assertEqual(profile["post_count"], 99)
        self.assertEqual(profile["category"], "Public Figure")
        self.assertEqual(profile["bio_links"][0]["url"], "https://example.com/fixture")
        self.assertEqual(session.headers["X-IG-App-ID"], WEB_APP_ID)
        self.assertEqual(
            session.calls[0][0],
            "https://www.instagram.com/api/v1/users/web_profile_info/",
        )
        self.assertEqual(session.calls[0][1]["params"], {"username": "fixture.user"})
        self.assertEqual(
            session.calls[0][1]["headers"],
            {"Referer": "https://www.instagram.com/fixture.user/"},
        )

    def test_profile_page_normalizes_image_video_and_carousel_edges(self) -> None:
        client = InstagramClient(session=FakeSession([response(PROFILE)]), retries=0)

        page = client.get_profile_page("fixture.user", limit=3)

        self.assertEqual(page["available"], 99)
        self.assertEqual(page["total"], 3)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_cursor"], "NEXT_CURSOR")
        image, video, carousel = page["posts"]
        self.assertEqual(image["media_type"], "image")
        self.assertEqual(image["caption"], "Image caption")
        self.assertEqual(image["resources"][0]["width"], 320)
        self.assertEqual(video["media_type"], "video")
        self.assertEqual(video["video_url"], "https://cdn.example/video.mp4")
        self.assertEqual(video["published_at"], "2024-01-02T00:00:00+00:00")
        self.assertEqual(carousel["media_type"], "carousel")
        self.assertEqual([item["media_type"] for item in carousel["children"]], ["image", "video"])
        self.assertEqual(carousel["children"][1]["shortcode"], "Carousel_3")

    def test_posts_limit_zero_avoids_network_and_positive_limit_truncates(self) -> None:
        empty_session = FakeSession([])
        empty = InstagramClient(session=empty_session).get_user_posts("fixture.user", limit=0)
        self.assertEqual(empty["posts"], [])
        self.assertEqual(empty_session.calls, [])

        session = FakeSession([response(PROFILE)])
        limited = InstagramClient(session=session).get_user_posts("fixture.user", limit=2)
        self.assertEqual([post["id"] for post in limited["posts"]], ["101", "102"])
        with self.assertRaises(InstagramInputError):
            InstagramClient(session=FakeSession([])).get_user_posts("fixture.user", limit=-1)
        with self.assertRaises(InstagramInputError):
            InstagramClient(session=FakeSession([])).get_user_posts("fixture.user", limit=13)

    def test_embed_serverjs_context_is_parsed_without_executing_javascript(self) -> None:
        session = FakeSession([html_response(POST_EMBED)])
        client = InstagramClient(session=session, retries=0)

        post = client.get_post("https://instagram.com/reel/Fixture_1/")

        self.assertEqual(post["id"], "123456")
        self.assertEqual(post["shortcode"], "Fixture_1")
        self.assertEqual(post["media_type"], "video")
        self.assertEqual(post["caption"], "Embed fixture caption")
        self.assertEqual(post["video_duration"], 12.5)
        self.assertEqual(post["view_count"], 345)
        self.assertEqual(post["like_count"], 234)
        self.assertEqual(post["comment_count"], 12)
        self.assertEqual(post["owner"]["username"], "fixture.user")
        self.assertEqual(post["resources"][0]["url"], "https://cdn.example/post-1080.jpg")
        self.assertEqual(
            session.calls[0][0],
            "https://www.instagram.com/p/Fixture_1/embed/captioned/",
        )

    def test_missing_embed_metadata_and_profile_data_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(InstagramResponseError, "public post metadata"):
            InstagramClient.parse_embed_html("<html><script>s.handle({});</script></html>")
        with self.assertRaisesRegex(InstagramResponseError, "public post metadata"):
            InstagramClient.parse_embed_html(
                '<html><script>s.handle({"broken":);</script></html>'
            )

        missing = InstagramClient(
            session=FakeSession([response({"data": {"user": None}, "status": "ok"})]),
            retries=0,
        )
        with self.assertRaisesRegex(InstagramResponseError, "public user data"):
            missing.get_user_profile("missing.user")

        failed = InstagramClient(
            session=FakeSession([response({"status": "fail", "message": "rate limited"})]),
            retries=0,
        )
        with self.assertRaisesRegex(InstagramResponseError, "rate limited"):
            failed.get_user_profile("fixture.user")

    def test_transport_and_transient_http_failures_retry_with_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection failure"),
                response({"message": "slow down"}, status=429),
                response({"message": "temporary"}, status=503),
                response(PROFILE),
            ]
        )
        client = InstagramClient(session=session, retries=3)

        with patch("reverse.instagram_reverse.client.time.sleep") as sleep:
            profile = client.get_user_profile("fixture.user")

        self.assertEqual(profile["id"], "42")
        self.assertEqual(
            [call.args for call in sleep.call_args_list],
            [(0.4,), (0.8,), (1.6,)],
        )

    def test_deterministic_http_and_json_errors_do_not_retry(self) -> None:
        session = FakeSession([html_response("missing", status=404), response(PROFILE)])
        client = InstagramClient(session=session, retries=2)
        with self.assertRaisesRegex(InstagramResponseError, "HTTP 404"):
            client.get_user_profile("fixture.user")
        self.assertEqual(len(session.calls), 1)

        non_object = InstagramClient(session=FakeSession([response([])]), retries=0)
        with self.assertRaisesRegex(InstagramResponseError, "non-object"):
            non_object.get_user_profile("fixture.user")

    def test_session_initialization_sets_csrf_header_and_is_idempotent(self) -> None:
        bootstrap = html_response("<html>fixture</html>")
        bootstrap.cookies.set("csrftoken", "fixture-token", domain=".instagram.com")
        session = FakeSession([bootstrap])
        client = InstagramClient(session=session, retries=0)

        client.initialize_session()
        client.initialize_session()

        self.assertEqual(session.headers["X-CSRFToken"], "fixture-token")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][0], "https://www.instagram.com/")


if __name__ == "__main__":
    unittest.main()
