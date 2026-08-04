from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.xiaohongshu_reverse.client import DEFAULT_USER_AGENT, XiaohongshuClient
from reverse.xiaohongshu_reverse.errors import (
    XiaohongshuError,
    XiaohongshuInputError,
    XiaohongshuResponseError,
)

FIXTURES = Path(__file__).with_name("fixtures")
NOTE_HTML = (FIXTURES / "note_page.html").read_text(encoding="utf-8")
PROFILE_HTML = (FIXTURES / "profile_page.html").read_text(encoding="utf-8")
NOTE_ID = "64c13017000000000103cde1"
USER_ID = "5cbc3d1c0000000011035f05"
TOKEN = "ABfixture_token_123="


def response(
    source: str,
    *,
    status: int = 200,
    url: str = "",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers = requests.Headers(headers or {})
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


class XiaohongshuClientTest(unittest.TestCase):
    def test_error_types_share_the_public_base(self) -> None:
        self.assertTrue(issubclass(XiaohongshuInputError, XiaohongshuError))
        self.assertTrue(issubclass(XiaohongshuResponseError, XiaohongshuError))

    def test_initial_state_parser_replaces_only_javascript_literals(self) -> None:
        state = XiaohongshuClient.extract_initial_state(NOTE_HTML)

        self.assertIsNone(state["nioStore"]["error"])
        self.assertIsNone(state["negative"])
        self.assertIsNone(state["notANumber"])
        description = state["note"]["noteDetailMap"][NOTE_ID]["note"]["desc"]
        self.assertIn("undefined stays text", description)

    def test_note_fields_media_interactions_tags_and_time_are_normalized(self) -> None:
        note = XiaohongshuClient.parse_note_html(
            NOTE_HTML,
            expected_note_id=NOTE_ID,
            xsec_source="pc_feed",
        )

        self.assertEqual(note["id"], NOTE_ID)
        self.assertEqual(note["title"], "Fixture title")
        self.assertEqual(note["author"]["id"], USER_ID)
        self.assertEqual(note["author"]["avatar"], "https://sns-avatar-qc.xhscdn.com/avatar/fixture.jpg")
        self.assertEqual(note["like_count"], 21_000)
        self.assertEqual(note["collect_count"], 1_234)
        self.assertEqual(note["comment_count"], 56)
        self.assertEqual(note["share_count"], 7)
        self.assertEqual(note["tags"], [{"id": "topic-fixture", "name": "Fixture", "type": "topic"}])
        self.assertEqual(note["mentions"][0]["nickname"], "Mentioned")
        self.assertTrue(note["is_live_photo"])
        image = note["images"][0]
        self.assertEqual(image["url"], "https://sns-webpic-qc.xhscdn.com/fixture-default.webp")
        self.assertEqual(image["live_photo_streams"][0]["duration"], 3.1)
        self.assertEqual(note["video"]["id"], "136446300595413207")
        self.assertEqual(note["video"]["duration"], 17)
        self.assertEqual(note["video"]["url"], "https://sns-video-v2.xhscdn.com/fixture.mp4?sign=fixture")
        self.assertEqual(note["published_timestamp"], 1_690_382_359)
        self.assertEqual(note["published_at"], "2023-07-26T14:39:19+00:00")
        self.assertTrue(note["shareable"])

    def test_direct_url_extracts_id_token_and_source_without_network(self) -> None:
        client = XiaohongshuClient(session=FakeSession([]))
        result = client.resolve_note_reference(
            f"See https://www.xiaohongshu.com/discovery/item/{NOTE_ID}"
            f"?xsec_token={TOKEN}%3D&xsec_source=app_share，打开 App"
        )

        self.assertEqual(result["note_id"], NOTE_ID)
        self.assertEqual(result["xsec_token"], f"{TOKEN}=")
        self.assertEqual(result["xsec_source"], "app_share")
        self.assertEqual(result["page_url"], f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}")
        self.assertEqual(client.session.calls, [])  # type: ignore[attr-defined]

    def test_short_link_is_resolved_with_plain_http_then_note_is_fetched(self) -> None:
        location = (
            f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}"
            f"?xsec_token={TOKEN}%3D&xsec_source=app_share"
        )
        session = FakeSession(
            [
                response("redirect", status=302, headers={"Location": location}),
                response(NOTE_HTML),
            ]
        )
        client = XiaohongshuClient(session=session, retries=0)

        note = client.get_note("Share text http://xhslink.com/m/Fixture123 。")

        self.assertEqual(note["id"], NOTE_ID)
        self.assertEqual(note["short_url"], "http://xhslink.com/m/Fixture123")
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertEqual(session.calls[1][0], f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}")
        self.assertEqual(
            session.calls[1][1]["params"],
            {"xsec_token": f"{TOKEN}=", "xsec_source": "app_share"},
        )

    def test_note_id_and_explicit_token_build_expected_request(self) -> None:
        session = FakeSession([response(NOTE_HTML)])
        client = XiaohongshuClient(session=session, retries=0)

        note = client.get_note(NOTE_ID, xsec_token=TOKEN)

        self.assertEqual(note["xsec_token"], TOKEN)
        self.assertEqual(session.calls[0][0], f"https://www.xiaohongshu.com/explore/{NOTE_ID}")
        self.assertEqual(
            session.calls[0][1]["params"],
            {"xsec_token": TOKEN, "xsec_source": "pc_feed"},
        )
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)

    def test_profile_page_is_anonymous_and_normalizes_public_counters(self) -> None:
        session = FakeSession([response(PROFILE_HTML)])
        client = XiaohongshuClient(session=session, retries=0)

        profile = client.get_profile(f"https://www.xiaohongshu.com/user/profile/{USER_ID}")

        self.assertEqual(profile["id"], USER_ID)
        self.assertEqual(profile["nickname"], "Fixture author")
        self.assertEqual(profile["description"], "Public fixture profile")
        self.assertEqual(profile["followers"], 12_000)
        self.assertEqual(profile["following"], 10)
        self.assertEqual(profile["likes_and_collections"], 34_000)
        self.assertEqual(profile["counter_text"]["fans"], "1.2万+")
        self.assertEqual(profile["tags"][1]["name"], "Food creator")
        self.assertEqual(
            profile["tags"][0]["icon"],
            "https://ci.xiaohongshu.com/icons/user/gender-female-v1.png",
        )
        self.assertEqual(session.calls[0][1]["params"], {})

    def test_transport_and_transient_http_failures_retry_with_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection failure"),
                response("slow down", status=429),
                response(NOTE_HTML),
            ]
        )
        client = XiaohongshuClient(session=session, retries=2)

        with patch("reverse.xiaohongshu_reverse.client.time.sleep") as sleep:
            note = client.get_note(NOTE_ID, xsec_token=TOKEN)

        self.assertEqual(note["id"], NOTE_ID)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

    def test_bad_inputs_and_deterministic_http_errors_fail_cleanly(self) -> None:
        client = XiaohongshuClient(session=FakeSession([]))
        with self.assertRaises(XiaohongshuInputError):
            client.resolve_note_reference("https://example.com/explore/64c13017000000000103cde1")
        with self.assertRaises(XiaohongshuInputError):
            client.resolve_note_reference("not-a-note")
        with self.assertRaises(XiaohongshuInputError):
            client.resolve_profile_reference("https://example.com/user/profile/5cbc3d1c0000000011035f05")
        with self.assertRaises(XiaohongshuInputError):
            client.resolve_note_reference(NOTE_ID, xsec_token="bad token")

        session = FakeSession([response("missing", status=404), response(NOTE_HTML)])
        failed = XiaohongshuClient(session=session, retries=2)
        with self.assertRaisesRegex(XiaohongshuResponseError, "HTTP 404"):
            failed.get_note(NOTE_ID, xsec_token=TOKEN)
        self.assertEqual(len(session.calls), 1)

    def test_missing_or_mismatched_ssr_data_fails_cleanly(self) -> None:
        with self.assertRaisesRegex(XiaohongshuResponseError, "__INITIAL_STATE__"):
            XiaohongshuClient.parse_note_html("<html>challenge</html>")
        empty = (
            '<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{},'
            '"serverRequestInfo":{"errMsg":"token expired"}}};</script>'
        )
        with self.assertRaisesRegex(XiaohongshuResponseError, "token expired"):
            XiaohongshuClient.parse_note_html(empty, expected_note_id=NOTE_ID)
        with self.assertRaisesRegex(XiaohongshuResponseError, "expected"):
            XiaohongshuClient.parse_note_html(
                NOTE_HTML,
                expected_note_id="aaaaaaaaaaaaaaaaaaaaaaaa",
            )

    def test_short_link_rejects_redirects_outside_owned_hosts(self) -> None:
        session = FakeSession(
            [response("redirect", status=302, headers={"Location": "https://example.com/note"})]
        )
        client = XiaohongshuClient(session=session, retries=0)
        with self.assertRaisesRegex(XiaohongshuResponseError, "unexpected host"):
            client.resolve_note_reference("https://xhslink.com/m/Fixture123")


if __name__ == "__main__":
    unittest.main()
