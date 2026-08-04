from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from curl_cffi import requests

from reverse.douyin_reverse import cli
from reverse.douyin_reverse.client import DEFAULT_USER_AGENT, WEB_USER_AGENT, DouyinClient
from reverse.douyin_reverse.errors import DouyinError, DouyinInputError, DouyinResponseError

FIXTURES = Path(__file__).with_name("fixtures")
VIDEO_HTML = (FIXTURES / "video_page.html").read_text(encoding="utf-8")
IMAGE_HTML = (FIXTURES / "image_post_page.html").read_text(encoding="utf-8")
PROFILE_JSON = (FIXTURES / "profile.json").read_text(encoding="utf-8")
WEB_FIXTURES = json.loads(
    (FIXTURES / "web_endpoints.json").read_text(encoding="utf-8")
)

AWEME_ID = "7372484719365098803"
IMAGE_ID = "7372484719365098804"
OTHER_ID = "7372484719365098899"
SEC_UID = "MS4wLjABAAAAGhTVHcr1tmaen43gOCk7JxI2ZHioZL3UzgmydgHUFFQ"


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


class DouyinClientTest(unittest.TestCase):
    @staticmethod
    def _fixture_signer(payload: dict[str, object]) -> dict[str, str]:
        raw_query = str(payload["raw_query"])
        return {
            "a_bogus": "fixture-signature",
            "query": f"{raw_query}&a_bogus=fixture-signature",
        }

    def test_error_types_share_the_public_base(self) -> None:
        self.assertTrue(issubclass(DouyinInputError, DouyinError))
        self.assertTrue(issubclass(DouyinResponseError, DouyinError))

    def test_constructor_rejects_invalid_transport_settings(self) -> None:
        cases = [
            {"timeout": 0},
            {"timeout": float("nan")},
            {"timeout": True},
            {"retries": -1},
            {"retries": 1.5},
            {"retries": True},
            {"max_redirects": 0},
            {"max_redirects": 1.5},
            {"user_agent": ""},
            {"user_agent": "fixture\r\nX-Test: injected"},
            {"web_user_agent": ""},
            {"web_user_agent": "fixture\r\nX-Test: injected"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(DouyinInputError):
                DouyinClient(**kwargs)  # type: ignore[arg-type]

    def test_cli_constructs_plain_http_client(self) -> None:
        args = cli._parser().parse_args(["hot", "--limit", "1"])
        with patch("reverse.douyin_reverse.cli.DouyinClient") as client_type:
            client_type.return_value.get_hot_searches.return_value = {"kind": "hot"}
            self.assertEqual(cli._run(args), {"kind": "hot"})
        self.assertEqual(client_type.call_args.kwargs, {"timeout": 20, "retries": 2, "proxy": None})

    def test_aweme_reference_accepts_ids_routes_queries_and_share_text(self) -> None:
        direct = DouyinClient.parse_aweme_reference(int(AWEME_ID))
        self.assertEqual(direct["aweme_id"], AWEME_ID)
        self.assertEqual(
            direct["share_page_url"],
            f"https://www.iesdouyin.com/share/video/{AWEME_ID}/",
        )

        routes = {
            f"https://www.douyin.com/video/{AWEME_ID}": "video",
            f"https://www.douyin.com/note/{AWEME_ID}/?previous_page=web_code_link": "note",
            f"https://www.iesdouyin.com/share/slides/{AWEME_ID}/": "note",
            f"www.douyin.com/?modal_id={AWEME_ID}": "video",
            f"https://www.douyin.com/user/fixture?aweme_id={AWEME_ID}": "video",
            f"https://m.douyin.com/share?object_id={AWEME_ID}": "video",
        }
        for value, content_type in routes.items():
            with self.subTest(value=value):
                parsed = DouyinClient.parse_aweme_reference(value)
                self.assertEqual(parsed["aweme_id"], AWEME_ID)
                self.assertEqual(parsed["content_type"], content_type)

        short = DouyinClient.parse_aweme_reference(
            "5.12 Copy this https://v.douyin.com/Fixture_123/ open Douyin."
        )
        self.assertIsNone(short["aweme_id"])
        self.assertEqual(short["short_url"], "https://v.douyin.com/Fixture_123/")

    def test_user_reference_accepts_sec_uid_and_public_routes(self) -> None:
        direct = DouyinClient.parse_user_reference(SEC_UID)
        self.assertEqual(direct["sec_uid"], SEC_UID)
        self.assertEqual(direct["url"], f"https://www.douyin.com/user/{SEC_UID}")

        values = [
            f"https://www.douyin.com/user/{SEC_UID}?from_tab_name=main",
            f"https://www.iesdouyin.com/share/user/?sec_uid={SEC_UID}",
            f"iesdouyin.com/share/user/{SEC_UID}/",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    DouyinClient.parse_user_reference(value)["sec_uid"], SEC_UID
                )

        short = DouyinClient.parse_user_reference(
            "Profile: https://v.douyin.com/ProfileFixture/ ."
        )
        self.assertIsNone(short["sec_uid"])
        self.assertEqual(
            short["short_url"], "https://v.douyin.com/ProfileFixture/"
        )

    def test_malformed_or_unowned_references_are_rejected(self) -> None:
        bad_awemes: list[object] = [
            True,
            123,
            "",
            "not-an-aweme",
            "https://example.com/video/7372484719365098803",
            "https://www.douyin.com.example.com/video/7372484719365098803",
            "https://internal.douyin.com/video/7372484719365098803",
            "https://user@www.douyin.com/video/7372484719365098803",
            "https://www.douyin.com:444/video/7372484719365098803",
            "https://www.douyin.com/music/7372484719365098803",
            "https://v.douyin.com/a%2Fb/",
        ]
        for value in bad_awemes:
            with self.subTest(value=value), self.assertRaises(DouyinInputError):
                DouyinClient.parse_aweme_reference(value)  # type: ignore[arg-type]

        bad_users = [
            "MS4wLjABshort",
            "https://example.com/user/" + SEC_UID,
            "https://www.douyin.com.example.com/user/" + SEC_UID,
            "https://user@www.douyin.com/user/" + SEC_UID,
            "https://www.douyin.com:444/user/" + SEC_UID,
            f"https://www.douyin.com/video/{AWEME_ID}",
        ]
        for value in bad_users:
            with self.subTest(value=value), self.assertRaises(DouyinInputError):
                DouyinClient.parse_user_reference(value)

    def test_short_aweme_redirect_is_resolved_with_plain_http(self) -> None:
        short_url = "https://v.douyin.com/Fixture123/"
        target = f"https://www.douyin.com/video/{AWEME_ID}?previous_page=app_code_link"
        session = FakeSession(
            [response("redirect", status=302, headers={"Location": target})]
        )
        client = DouyinClient(session=session, retries=0)

        resolved = client.resolve_aweme_reference(short_url)

        self.assertEqual(resolved["aweme_id"], AWEME_ID)
        self.assertEqual(resolved["short_url"], short_url)
        self.assertEqual(resolved["redirect_url"], target)
        self.assertEqual(session.calls[0][0], short_url)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)

    def test_short_user_redirect_is_resolved_with_plain_http(self) -> None:
        short_url = "https://v.douyin.com/ProfileFixture/"
        target = f"https://www.iesdouyin.com/share/user/?sec_uid={SEC_UID}"
        session = FakeSession(
            [response("redirect", status=302, headers={"location": target})]
        )
        resolved = DouyinClient(session=session, retries=0).resolve_user_reference(
            short_url
        )

        self.assertEqual(resolved["sec_uid"], SEC_UID)
        self.assertEqual(resolved["short_url"], short_url)
        self.assertEqual(resolved["redirect_url"], target)

    def test_short_redirect_rejects_external_userinfo_and_nonstandard_port(self) -> None:
        targets = [
            f"https://example.com/video/{AWEME_ID}",
            f"https://internal.douyin.com/video/{AWEME_ID}",
            f"https://attacker@www.douyin.com/video/{AWEME_ID}",
            f"https://www.douyin.com:444/video/{AWEME_ID}",
            f"http://www.douyin.com/video/{AWEME_ID}",
        ]
        for target in targets:
            with self.subTest(target=target):
                session = FakeSession(
                    [response("redirect", status=302, headers={"Location": target})]
                )
                client = DouyinClient(session=session, retries=0)
                with self.assertRaisesRegex(DouyinResponseError, "owned hosts"):
                    client.resolve_aweme_reference(
                        "https://v.douyin.com/Fixture123/"
                    )

    def test_video_router_data_is_fully_normalized(self) -> None:
        aweme = DouyinClient.parse_aweme_html(
            VIDEO_HTML, expected_aweme_id=AWEME_ID
        )

        self.assertEqual(aweme["source"], "mobile_share_router_data")
        self.assertEqual(aweme["id"], AWEME_ID)
        self.assertEqual(aweme["media_type"], "video")
        self.assertEqual(aweme["published_at"], "2024-05-24T08:46:14+00:00")
        self.assertEqual(aweme["author"]["nickname"], "Fixture Author")
        self.assertEqual(aweme["author"]["followers"], 12_345)
        self.assertEqual(aweme["author"]["account_cert_info"]["label"], "fixture")
        self.assertTrue(aweme["author"]["verified"])
        self.assertEqual(
            aweme["statistics"],
            {
                "likes": 314_420,
                "comments": 4_083,
                "shares": 79_921,
                "collects": 20_157,
                "plays": 987_654,
            },
        )
        self.assertEqual(aweme["video"]["duration"], 8.01)
        self.assertEqual(aweme["video"]["play"]["uri"], "video-play")
        self.assertEqual(aweme["video"]["bit_rates"][0]["fps"], 30)
        self.assertEqual(aweme["music"]["title"], "Fixture sound")
        self.assertEqual([tag["name"] for tag in aweme["hashtags"]], ["douyin", "fixture"])
        self.assertEqual(aweme["mentions"][0]["nickname"], "Fixture Friend")
        self.assertEqual(aweme["location"]["city"], "Shanghai")

    def test_image_post_and_live_photo_media_are_normalized(self) -> None:
        aweme = DouyinClient.parse_aweme_html(
            IMAGE_HTML, expected_aweme_id=IMAGE_ID
        )

        self.assertEqual(aweme["media_type"], "images")
        self.assertEqual(aweme["url"], f"https://www.douyin.com/note/{IMAGE_ID}")
        self.assertIsNone(aweme["video"])
        self.assertEqual(aweme["statistics"]["likes"], 1_234)
        self.assertEqual(len(aweme["images"]), 2)
        self.assertEqual(aweme["images"][0]["width"], 1080)
        self.assertEqual(
            aweme["images"][0]["download_urls"],
            ["https://p3.douyinpic.com/fixture/image-1-download.jpeg"],
        )
        self.assertEqual(aweme["images"][1]["video"]["duration"], 3.2)

    def test_open_graph_metadata_is_an_explicit_limited_fallback(self) -> None:
        source = f"""
        <html><head>
          <link rel="canonical" href="https://www.douyin.com/video/{AWEME_ID}">
          <meta property="og:title" content="Fixture &amp; title">
          <meta property="og:description" content="Visible fixture description">
          <meta property="og:image" content="https://p3.douyinpic.com/fallback.jpg">
        </head></html>
        """
        aweme = DouyinClient.parse_aweme_html(source, expected_aweme_id=AWEME_ID)

        self.assertEqual(aweme["source"], "open_graph")
        self.assertEqual(aweme["title"], "Fixture & title")
        self.assertEqual(aweme["description"], "Visible fixture description")
        self.assertEqual(aweme["media_type"], "image")
        self.assertIsNone(aweme["statistics"]["likes"])
        self.assertEqual(
            aweme["images"][0]["url"],
            "https://p3.douyinpic.com/fallback.jpg",
        )

        og_url_only = source.replace(
            f'<link rel="canonical" href="https://www.douyin.com/video/{AWEME_ID}">',
            f'<meta property="og:url" content="https://www.douyin.com/video/{AWEME_ID}">',
        )
        self.assertEqual(
            DouyinClient.parse_aweme_html(
                og_url_only, expected_aweme_id=AWEME_ID
            )["id"],
            AWEME_ID,
        )

    def test_open_graph_fallback_requires_response_identity(self) -> None:
        source = """
        <html><head>
          <meta property="og:title" content="Unidentified response">
          <meta property="og:image" content="https://p3.douyinpic.com/fallback.jpg">
        </head></html>
        """
        with self.assertRaisesRegex(DouyinResponseError, "identity"):
            DouyinClient.parse_aweme_html(source, expected_aweme_id=AWEME_ID)

    def test_empty_challenge_and_malformed_router_pages_fail_cleanly(self) -> None:
        cases = [
            ("", "empty"),
            ("<html><script>var _$jsvmprt='challenge'</script></html>", "challenge"),
            ("<script>window._ROUTER_DATA={broken;</script>", "malformed"),
            ("<script>window._ROUTER_DATA=[];</script>", "not an object"),
            ("<script>window._ROUTER_DATA={\"loaderData\":{}};</script>", "no public video"),
            (
                '<script>window._ROUTER_DATA={"videoInfoRes":'
                '{"status_code":4,"status_msg":"not found"}};</script>',
                "not found",
            ),
        ]
        for source, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                DouyinResponseError, message
            ):
                DouyinClient.parse_aweme_html(source, expected_aweme_id=AWEME_ID)

    def test_aweme_response_identity_is_verified(self) -> None:
        canonical_mismatch = VIDEO_HTML.replace(
            f"/video/{AWEME_ID}", f"/video/{OTHER_ID}", 1
        )
        with self.assertRaisesRegex(DouyinResponseError, "expected"):
            DouyinClient.parse_aweme_html(
                canonical_mismatch, expected_aweme_id=AWEME_ID
            )

        item_mismatch = (
            '<script>window._ROUTER_DATA={"videoInfoRes":'
            f'{{"status_code":0,"item_list":[{{"aweme_id":"{OTHER_ID}"}}]}}'
            '};</script>'
        )
        with self.assertRaisesRegex(DouyinResponseError, "expected"):
            DouyinClient.parse_aweme_html(item_mismatch, expected_aweme_id=AWEME_ID)

    def test_profile_payload_is_normalized_and_identity_checked(self) -> None:
        profile = DouyinClient.parse_profile_payload(
            PROFILE_JSON, expected_sec_uid=SEC_UID
        )

        self.assertEqual(profile["source"], "public_user_info")
        self.assertEqual(profile["nickname"], "Fixture Author")
        self.assertEqual(profile["followers"], 2_690_000)
        self.assertEqual(profile["following"], 100)
        self.assertEqual(profile["aweme_count"], 641)
        self.assertEqual(profile["liked_total"], 60_914_997)
        self.assertEqual(profile["avatar"]["urls"][1], "https://p6.douyinpic.com/fixture/avatar.jpeg")
        self.assertEqual(profile["account_cert_info"], {"label": "public"})
        self.assertEqual(profile["mix_info"]["mix_id"], "fixture-mix")

        mismatch = PROFILE_JSON.replace(SEC_UID, "MS4wLjABAAAAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
        with self.assertRaisesRegex(DouyinResponseError, "expected"):
            DouyinClient.parse_profile_payload(mismatch, expected_sec_uid=SEC_UID)

    def test_profile_api_errors_and_access_pages_fail_cleanly(self) -> None:
        cases = [
            ("", "empty"),
            ("<html>Access Denied</html>", "access gate"),
            ('{"status_code":5,"status_msg":"private"}', "private"),
            ('{"status_code":0}', "user_info"),
        ]
        for source, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                DouyinResponseError, message
            ):
                DouyinClient.parse_profile_payload(source, expected_sec_uid=SEC_UID)

    def test_get_aweme_uses_mobile_share_page_request_contract(self) -> None:
        final_url = f"https://www.douyin.com/video/{AWEME_ID}"
        session = FakeSession([response(VIDEO_HTML, url=final_url)])
        client = DouyinClient(session=session, retries=0)

        aweme = client.get_aweme(AWEME_ID)

        expected = f"https://www.iesdouyin.com/share/video/{AWEME_ID}/"
        self.assertEqual(aweme["requested_url"], expected)
        self.assertEqual(session.calls[0][0], expected)
        self.assertEqual(session.calls[0][1]["params"], {})
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertEqual(
            session.calls[0][1]["headers"], {"Referer": "https://www.iesdouyin.com/"}
        )

    def test_owned_redirects_are_validated_and_followed_one_hop_at_a_time(self) -> None:
        initial = f"https://www.iesdouyin.com/share/video/{AWEME_ID}/"
        target = f"https://www.douyin.com/video/{AWEME_ID}"
        session = FakeSession(
            [
                response("redirect", status=302, url=initial, headers={"Location": target}),
                response(VIDEO_HTML, url=target),
            ]
        )

        aweme = DouyinClient(session=session, retries=0).get_aweme(AWEME_ID)

        self.assertEqual(aweme["id"], AWEME_ID)
        self.assertEqual([call[0] for call in session.calls], [initial, target])
        self.assertTrue(all(not call[1]["allow_redirects"] for call in session.calls))
        self.assertEqual(session.calls[1][1]["params"], {})

    def test_external_redirect_is_rejected_before_a_second_request(self) -> None:
        initial = f"https://www.iesdouyin.com/share/video/{AWEME_ID}/"
        session = FakeSession(
            [
                response(
                    "redirect",
                    status=302,
                    url=initial,
                    headers={"Location": f"https://example.com/video/{AWEME_ID}"},
                )
            ]
        )

        with self.assertRaisesRegex(DouyinResponseError, "owned hosts"):
            DouyinClient(session=session, retries=0).get_aweme(AWEME_ID)
        self.assertEqual(len(session.calls), 1)

    def test_get_profile_uses_public_user_info_request_contract(self) -> None:
        api_url = f"https://www.iesdouyin.com/web/api/v2/user/info/?sec_uid={SEC_UID}"
        session = FakeSession([response(PROFILE_JSON, url=api_url)])
        profile = DouyinClient(session=session, retries=0).get_profile(SEC_UID)

        self.assertEqual(profile["requested_url"], api_url)
        self.assertEqual(
            session.calls[0][0], "https://www.iesdouyin.com/web/api/v2/user/info/"
        )
        self.assertEqual(session.calls[0][1]["params"], {"sec_uid": SEC_UID})
        self.assertEqual(
            session.calls[0][1]["headers"]["Accept"],
            "application/json, text/plain, */*",
        )
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertIn(SEC_UID, session.calls[0][1]["headers"]["Referer"])

    def test_transport_and_transient_http_failures_retry_with_backoff(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture connection failure"),
                response("slow down", status=429),
                response(VIDEO_HTML),
            ]
        )
        client = DouyinClient(session=session, retries=2)

        with patch("reverse.douyin_reverse.client.time.sleep") as sleep:
            aweme = client.get_aweme(AWEME_ID)

        self.assertEqual(aweme["id"], AWEME_ID)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

    def test_deterministic_http_error_and_external_final_url_fail_cleanly(self) -> None:
        missing = FakeSession(
            [response("missing", status=404), response(VIDEO_HTML)]
        )
        with self.assertRaisesRegex(DouyinResponseError, "HTTP 404"):
            DouyinClient(session=missing, retries=2).get_aweme(AWEME_ID)
        self.assertEqual(len(missing.calls), 1)

        external = FakeSession(
            [response(VIDEO_HTML, url=f"https://example.com/video/{AWEME_ID}")]
        )
        with self.assertRaisesRegex(DouyinResponseError, "owned hosts"):
            DouyinClient(session=external, retries=0).get_aweme(AWEME_ID)

    def test_get_author_profile_composes_the_two_public_requests(self) -> None:
        session = FakeSession([response(VIDEO_HTML), response(PROFILE_JSON)])
        profile = DouyinClient(session=session, retries=0).get_author_profile(AWEME_ID)

        self.assertEqual(profile["source_aweme_id"], AWEME_ID)
        self.assertEqual(profile["sec_uid"], SEC_UID)
        self.assertEqual(len(session.calls), 2)
        self.assertIn("/share/video/", session.calls[0][0])
        self.assertIn("/web/api/v2/user/info/", session.calls[1][0])

    def test_user_posts_paginate_deduplicate_and_keep_cursor_strings(self) -> None:
        session = FakeSession(
            [response(json.dumps(page)) for page in WEB_FIXTURES["user_posts"]]
        )
        client = DouyinClient(
            session=session,
            retries=0,
            web_id="7362810250930783783",
            web_signer=self._fixture_signer,
        )

        result = client.get_user_posts(SEC_UID, limit=3, page_size=2)

        self.assertEqual([item["id"] for item in result["items"]], [AWEME_ID, IMAGE_ID])
        self.assertEqual(result["cursor"], "1720000000001")
        self.assertFalse(result["has_more"])
        self.assertEqual(result["items"][0]["source"], "web_user_posts")
        first = parse_qs(urlsplit(session.calls[0][0]).query, keep_blank_values=True)
        second = parse_qs(urlsplit(session.calls[1][0]).query, keep_blank_values=True)
        self.assertEqual(first["max_cursor"], ["0"])
        self.assertEqual(second["max_cursor"], ["1720000000000"])
        self.assertEqual(first["webid"], ["7362810250930783783"])
        self.assertEqual(first["a_bogus"], ["fixture-signature"])
        self.assertEqual(session.calls[0][1]["impersonate"], "chrome146")
        self.assertEqual(
            session.calls[0][1]["headers"]["User-Agent"], WEB_USER_AGENT
        )

    def test_comments_and_replies_share_normalized_contract(self) -> None:
        comments_session = FakeSession(
            [response(json.dumps(page)) for page in WEB_FIXTURES["comments"]]
        )
        comments = DouyinClient(
            session=comments_session,
            retries=0,
            web_id="7362810250930783783",
            web_signer=self._fixture_signer,
        ).get_comments(AWEME_ID, limit=3, page_size=2)

        self.assertEqual([item["id"] for item in comments["items"]], [
            "7372484719365098811",
            "7372484719365098812",
        ])
        self.assertEqual(comments["items"][0]["likes"], 7)
        self.assertEqual(comments["items"][0]["reply_count"], 2)
        self.assertEqual(comments["cursor"], "40")

        reply_session = FakeSession(
            [response(json.dumps(page)) for page in WEB_FIXTURES["comment_replies"]]
        )
        replies = DouyinClient(
            session=reply_session,
            retries=0,
            web_id="7362810250930783783",
            web_signer=self._fixture_signer,
        ).get_comment_replies(AWEME_ID, "7372484719365098811")
        self.assertEqual(replies["kind"], "comment_replies")
        self.assertEqual(replies["comment_id"], "7372484719365098811")
        self.assertEqual(replies["items"][0]["reply_to_comment_id"], "7372484719365098811")
        query = parse_qs(urlsplit(reply_session.calls[0][0]).query)
        self.assertEqual(query["item_id"], [AWEME_ID])
        self.assertEqual(query["comment_id"], ["7372484719365098811"])

    def test_web_fetch_drives_comment_pagination_without_http_defaults(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []
        top_ids = ("7372484719365098811", "7372484719365098812")
        reply_ids = ("7372484719365098821", "7372484719365098822")

        def fetch(
            path: str,
            params: list[tuple[str, str]],
            referer: str,
        ) -> dict[str, object]:
            calls.append((path, params, referer))
            values = dict(params)
            cursor = values["cursor"]
            if path == "/aweme/v1/web/comment/list/":
                index = 0 if cursor == "0" else 1
                return {
                    "status_code": 0,
                    "cursor": ("10", "20")[index],
                    "has_more": index == 0,
                    "comments": [{"cid": top_ids[index]}],
                }
            index = 0 if cursor == "7" else 1
            return {
                "status_code": 0,
                "cursor": ("8", "9")[index],
                "has_more": index == 0,
                "comments": [{"cid": reply_ids[index]}],
            }

        session = FakeSession([])
        client = DouyinClient(session=session, web_fetch=fetch)
        comments = client.get_comments(AWEME_ID, limit=2, page_size=1)
        replies = client.get_comment_replies(
            AWEME_ID,
            top_ids[0],
            limit=2,
            cursor="7",
            page_size=1,
        )

        self.assertEqual(session.calls, [])
        self.assertEqual([item["id"] for item in comments["items"]], list(top_ids))
        self.assertEqual(comments["cursor"], "20")
        self.assertEqual([item["id"] for item in replies["items"]], list(reply_ids))
        self.assertEqual(replies["cursor"], "9")
        self.assertEqual(
            calls[0][1],
            [
                ("aweme_id", AWEME_ID),
                ("pc_img_format", "webp"),
                ("cursor", "0"),
                ("count", "1"),
                ("item_type", "0"),
                ("insert_ids", ""),
                ("whale_cut_token", ""),
                ("cut_version", "1"),
                ("rcFT", ""),
            ],
        )
        self.assertEqual(dict(calls[1][1])["cursor"], "10")
        self.assertEqual(
            calls[2][1],
            [
                ("item_id", AWEME_ID),
                ("comment_id", top_ids[0]),
                ("whale_cut_token", ""),
                ("cut_version", "1"),
                ("cursor", "7"),
                ("count", "1"),
                ("item_type", "0"),
            ],
        )
        self.assertEqual(dict(calls[3][1])["cursor"], "8")
        self.assertTrue(
            all(
                name not in {"aid", "browser_name", "webid", "a_bogus"}
                for _path, params, _referer in calls
                for name, _value in params
            )
        )
        self.assertTrue(
            all(
                referer == f"https://www.douyin.com/video/{AWEME_ID}"
                for _path, _params, referer in calls
            )
        )

        default_page: list[tuple[str, str]] = []

        def default_fetch(
            _path: str,
            params: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            default_page.extend(params)
            return {
                "status_code": 0,
                "cursor": "0",
                "has_more": False,
                "comments": [],
            }

        DouyinClient(web_fetch=default_fetch).get_comments(
            AWEME_ID,
            page_size=0,
        )
        self.assertEqual(dict(default_page)["count"], "20")

    def test_include_replies_uses_independent_limits_and_zero_skips_fetch(self) -> None:
        parent_id = "7372484719365098811"
        empty_id = "7372484719365098812"
        reply_ids = ("7372484719365098821", "7372484719365098822")
        calls: list[tuple[str, list[tuple[str, str]]]] = []

        def fetch(
            path: str,
            params: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append((path, params))
            values = dict(params)
            if path == "/aweme/v1/web/comment/list/":
                return {
                    "status_code": 0,
                    "cursor": "2",
                    "has_more": False,
                    "comments": [
                        {"cid": parent_id, "reply_comment_total": 4},
                        {"cid": empty_id, "reply_comment_total": 0},
                    ],
                }
            index = int(values["cursor"])
            return {
                "status_code": 0,
                "cursor": str(index + 1),
                "has_more": index == 0,
                "comments": [{"cid": reply_ids[index]}],
            }

        result = DouyinClient(web_fetch=fetch).get_comments(
            AWEME_ID,
            limit=2,
            page_size=2,
            include_replies=True,
            reply_limit=2,
            reply_page_size=1,
        )

        first, second = result["items"]
        self.assertEqual([item["id"] for item in first["replies"]], list(reply_ids))
        self.assertNotIn("replies", second)
        self.assertEqual([dict(params)["count"] for _path, params in calls], ["2", "1", "1"])
        self.assertEqual(
            [dict(params).get("comment_id") for _path, params in calls],
            [None, parent_id, parent_id],
        )

        zero_calls: list[str] = []

        def zero_fetch(
            path: str,
            _params: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            zero_calls.append(path)
            return {
                "status_code": 0,
                "cursor": "1",
                "has_more": False,
                "comments": [{"cid": parent_id, "reply_comment_total": 2}],
            }

        zero = DouyinClient(web_fetch=zero_fetch).get_comments(
            AWEME_ID,
            limit=1,
            include_replies=True,
            reply_limit=0,
        )
        self.assertEqual(zero_calls, ["/aweme/v1/web/comment/list/"])
        self.assertEqual(zero["items"][0]["replies"], [])

    def test_comment_payload_fields_are_strict_for_comments_and_replies(self) -> None:
        valid_tail = {"cursor": "0", "has_more": False}
        malformed = (
            ({}, "status_code"),
            (
                {"status_code": "0", "comments": [], **valid_tail},
                "status_code",
            ),
            (
                {"status_code": 0.5, "comments": [], **valid_tail},
                "status_code",
            ),
            (
                {"status_code": 0, **valid_tail},
                "comments/data",
            ),
            (
                {
                    "status_code": 0,
                    "comments": {},
                    "data": [],
                    **valid_tail,
                },
                "comments 必须是数组",
            ),
            (
                {"status_code": 0, "data": {}, **valid_tail},
                "data 必须是数组",
            ),
            (
                {"status_code": 0, "comments": [], "has_more": False},
                "缺少 cursor",
            ),
            (
                {
                    "status_code": 0,
                    "comments": [],
                    "cursor": "",
                    "has_more": False,
                },
                "cursor 必须是非负十进制值",
            ),
            (
                {
                    "status_code": 0,
                    "comments": [],
                    "cursor": 1.5,
                    "has_more": False,
                },
                "cursor 必须是非负十进制值",
            ),
            (
                {"status_code": 0, "comments": [], "cursor": "0"},
                "缺少 has_more",
            ),
            (
                {
                    "status_code": 0,
                    "comments": [],
                    "cursor": "0",
                    "has_more": "false",
                },
                "has_more 必须是布尔值或数值 0/1",
            ),
            (
                {
                    "status_code": 0,
                    "comments": [],
                    "cursor": "0",
                    "has_more": 2,
                },
                "has_more 必须是布尔值或数值 0/1",
            ),
        )

        for replies in (False, True):
            for payload, message in malformed:
                with self.subTest(replies=replies, message=message):
                    client = DouyinClient(
                        web_fetch=lambda _path, _params, _referer, payload=payload: payload
                    )
                    with self.assertRaisesRegex(DouyinResponseError, message):
                        if replies:
                            client.get_comment_replies(
                                AWEME_ID,
                                "7372484719365098811",
                                limit=1,
                            )
                        else:
                            client.get_comments(AWEME_ID, limit=1)

        for field in ("comments", "data"):
            with self.subTest(field=field):
                result = DouyinClient(
                    web_fetch=lambda _path, _params, _referer, field=field: {
                        "status_code": 0,
                        field: [],
                        "cursor": "0",
                        "has_more": False,
                    }
                ).get_comments(AWEME_ID, limit=1)
                self.assertEqual(result["items"], [])

        precedence = DouyinClient(
            web_fetch=lambda _path, _params, _referer: {
                "status_code": 0,
                "comments": [],
                "data": [{"cid": "7372484719365098899"}],
                "cursor": "0",
                "has_more": False,
            }
        ).get_comments(AWEME_ID, limit=1)
        self.assertEqual(precedence["items"], [])

    def test_comment_and_reply_stale_pages_stop_after_three_requests(self) -> None:
        for replies in (False, True):
            calls = 0

            def fetch(
                _path: str,
                _params: list[tuple[str, str]],
                _referer: str,
            ) -> dict[str, object]:
                nonlocal calls
                calls += 1
                return {
                    "status_code": 0,
                    "cursor": str(calls),
                    "has_more": True,
                    "comments": [],
                }

            client = DouyinClient(web_fetch=fetch)
            label = "回复" if replies else "评论"
            with self.subTest(replies=replies), self.assertRaisesRegex(
                DouyinResponseError,
                f"{label}分页连续 3 页",
            ):
                if replies:
                    client.get_comment_replies(
                        AWEME_ID,
                        "7372484719365098811",
                        limit=1,
                    )
                else:
                    client.get_comments(AWEME_ID, limit=1)
            self.assertEqual(calls, 3)

    def test_comment_limit_zero_skips_network_and_still_validates_inputs(self) -> None:
        fetch_calls = 0
        session = FakeSession([])

        def fetch(
            _path: str,
            _params: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            nonlocal fetch_calls
            fetch_calls += 1
            raise AssertionError("limit=0 不应调用 web_fetch")

        client = DouyinClient(session=session, web_fetch=fetch)
        comments = client.get_comments(
            "https://v.douyin.com/FixtureCode/",
            limit=0,
            cursor="8",
        )
        replies = client.get_comment_replies(
            AWEME_ID,
            "7372484719365098811",
            limit=0,
            cursor="9",
        )
        self.assertEqual((comments["count"], comments["cursor"]), (0, "8"))
        self.assertEqual((replies["count"], replies["cursor"]), (0, "9"))
        self.assertEqual(fetch_calls, 0)
        self.assertEqual(session.calls, [])

        invalid = (
            lambda: client.get_comments("not-an-aweme", limit=0),
            lambda: client.get_comments(AWEME_ID, limit=0, page_size=51),
            lambda: client.get_comments(AWEME_ID, limit=0, cursor="bad"),
            lambda: client.get_comments(
                AWEME_ID,
                limit=0,
                include_replies=True,
                reply_limit=201,
            ),
            lambda: client.get_comments(
                AWEME_ID,
                limit=0,
                include_replies=False,
                reply_page_size=51,
            ),
            lambda: client.get_comment_replies(AWEME_ID, "bad", limit=0),
        )
        for call in invalid:
            with self.subTest(call=call), self.assertRaises(DouyinInputError):
                call()
        self.assertEqual(fetch_calls, 0)
        self.assertEqual(session.calls, [])

    def test_comment_ids_and_cursors_are_ascii_only(self) -> None:
        client = DouyinClient(
            web_fetch=lambda _path, _params, _referer: {
                "status_code": 0,
                "comments": [],
                "cursor": "０",
                "has_more": False,
            }
        )
        invalid = (
            lambda: client.get_comment_replies(
                AWEME_ID,
                "７372484719365098811",
            ),
            lambda: client.get_comments(AWEME_ID, cursor="１２"),
            lambda: client.get_comment_replies(
                AWEME_ID,
                "7372484719365098811",
                cursor="１２",
            ),
        )
        for call in invalid:
            with self.subTest(call=call), self.assertRaises(DouyinInputError):
                call()

        with self.assertRaisesRegex(DouyinResponseError, "cursor"):
            client.get_comments(AWEME_ID, limit=1)

    def test_reply_to_user_survives_reply_to_reply_id(self) -> None:
        result = DouyinClient(
            web_fetch=lambda _path, _params, _referer: {
                "status_code": 0,
                "cursor": "1",
                "has_more": False,
                "comments": [
                    {
                        "cid": "7372484719365098821",
                        "reply_to_reply_id": "7372484719365098811",
                        "reply_to_user": {
                            "uid": "20004",
                            "nickname": "Target User",
                        },
                    }
                ],
            }
        ).get_comment_replies(
            AWEME_ID,
            "7372484719365098811",
            limit=1,
        )

        reply = result["items"][0]
        self.assertEqual(reply["reply_to_comment_id"], "7372484719365098811")
        self.assertEqual(reply["reply_to_user"]["uid"], "20004")
        self.assertEqual(reply["reply_to_user"]["nickname"], "Target User")

    def test_video_search_carries_search_id_and_hot_list_is_normalized(self) -> None:
        search_session = FakeSession(
            [response(json.dumps(page)) for page in WEB_FIXTURES["search_videos"]]
        )
        search = DouyinClient(
            session=search_session,
            retries=0,
            web_id="7362810250930783783",
            web_signer=self._fixture_signer,
        ).search_videos("fixture query", limit=3, page_size=2)

        self.assertEqual([item["id"] for item in search["items"]], [AWEME_ID, IMAGE_ID])
        self.assertEqual(search["search_id"], "fixture-search-id")
        second = parse_qs(urlsplit(search_session.calls[1][0]).query)
        self.assertEqual(second["offset"], ["10"])
        self.assertEqual(second["search_id"], ["fixture-search-id"])
        self.assertEqual(
            search_session.calls[0][1]["headers"]["Referer"],
            "https://www.douyin.com/search/fixture%20query?type=video",
        )

        hot_session = FakeSession([response(json.dumps(WEB_FIXTURES["hot"]))])
        hot = DouyinClient(
            session=hot_session,
            retries=0,
            web_id="7362810250930783783",
            web_signer=self._fixture_signer,
        ).get_hot_searches(limit=1)
        self.assertEqual(hot["items"][0]["word"], "Fixture topic")
        self.assertEqual(hot["items"][0]["hot_value"], 987654)
        self.assertEqual(hot["count"], 1)

    def test_web_limits_response_errors_and_cursor_cycles_fail_cleanly(self) -> None:
        client = DouyinClient(web_id="7362810250930783783")
        for call in (
            lambda: client.get_comments(AWEME_ID, limit=-1),
            lambda: client.get_comments(AWEME_ID, page_size=51),
            lambda: client.get_comments(AWEME_ID, cursor="bad"),
            lambda: client.search_videos("", limit=1),
            lambda: client.get_comment_replies(AWEME_ID, "12"),
        ):
            with self.subTest(call=call), self.assertRaises(DouyinInputError):
                call()

        bad = FakeSession(
            [response('{"status_code": 5, "status_msg": "risk"}')]
        )
        with self.assertRaisesRegex(DouyinResponseError, "risk"):
            DouyinClient(
                session=bad,
                retries=0,
                web_id="7362810250930783783",
                web_signer=self._fixture_signer,
            ).get_comments(AWEME_ID)

        cycle_pages = [
            {"status_code": 0, "has_more": 1, "cursor": "20", "comments": []},
            {"status_code": 0, "has_more": 1, "cursor": "0", "comments": []},
        ]
        cycle = FakeSession([response(json.dumps(page)) for page in cycle_pages])
        with self.assertRaisesRegex(DouyinResponseError, "repeated"):
            DouyinClient(
                session=cycle,
                retries=0,
                web_id="7362810250930783783",
                web_signer=self._fixture_signer,
            ).get_comments(AWEME_ID, limit=2, page_size=1)

    def test_proxy_is_forwarded_to_share_and_web_requests(self) -> None:
        share_session = FakeSession([response(VIDEO_HTML)])
        DouyinClient(
            session=share_session, retries=0, proxy="http://127.0.0.1:7890"
        ).get_aweme(AWEME_ID)
        self.assertEqual(
            share_session.calls[0][1]["proxy"], "http://127.0.0.1:7890"
        )

        web_session = FakeSession([response(json.dumps(WEB_FIXTURES["hot"]))])
        DouyinClient(
            session=web_session,
            retries=0,
            proxy="http://127.0.0.1:7890",
            web_id="7362810250930783783",
            web_signer=self._fixture_signer,
        ).get_hot_searches()
        self.assertEqual(web_session.calls[0][1]["proxy"], "http://127.0.0.1:7890")

    def test_web_bootstrap_uses_chrome_without_changing_share_profile(self) -> None:
        session = FakeSession(
            [response("<html></html>"), response(json.dumps(WEB_FIXTURES["hot"]))]
        )
        client = DouyinClient(
            session=session,
            retries=0,
            web_signer=self._fixture_signer,
        )

        result = client.get_hot_searches(limit=1)

        self.assertEqual(result["count"], 1)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertEqual(session.calls[0][1]["impersonate"], "chrome146")
        self.assertEqual(
            session.calls[0][1]["headers"]["User-Agent"], WEB_USER_AGENT
        )
        self.assertEqual(session.calls[1][1]["impersonate"], "chrome146")

    def test_batch_operations_keep_order_and_isolate_item_errors(self) -> None:
        session = FakeSession([response(VIDEO_HTML)])
        result = DouyinClient(session=session, retries=0).get_awemes(
            [AWEME_ID, "not-an-aweme"]
        )
        self.assertEqual(result["kind"], "batch_awemes")
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertTrue(result["items"][0]["ok"])
        self.assertFalse(result["items"][1]["ok"])
        self.assertEqual(result["items"][0]["data"]["id"], AWEME_ID)

        stats_session = FakeSession([response(VIDEO_HTML)])
        stats = DouyinClient(
            session=stats_session, retries=0
        ).get_aweme_statistics_batch([AWEME_ID])
        self.assertEqual(stats["items"][0]["data"]["statistics"]["likes"], 314420)

        profile_session = FakeSession([response(PROFILE_JSON)])
        profiles = DouyinClient(
            session=profile_session, retries=0
        ).get_profiles([SEC_UID])
        self.assertEqual(profiles["items"][0]["data"]["sec_uid"], SEC_UID)

        with self.assertRaises(DouyinInputError):
            DouyinClient().get_awemes([])
        with self.assertRaises(DouyinInputError):
            DouyinClient().get_awemes([AWEME_ID] * 21)

    def test_extract_all_public_ids_from_copied_text(self) -> None:
        awemes = DouyinClient.extract_aweme_ids(
            f"https://www.douyin.com/video/{AWEME_ID} and {IMAGE_ID} then {AWEME_ID}"
        )
        self.assertEqual(awemes["items"], [AWEME_ID, IMAGE_ID])

        other_sec_uid = "MS4wLjABAAAAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        users = DouyinClient.extract_sec_uids(
            f"{SEC_UID}, https://www.douyin.com/user/{other_sec_uid}, {SEC_UID}"
        )
        self.assertEqual(users["items"], [SEC_UID, other_sec_uid])


if __name__ == "__main__":
    unittest.main()
