from __future__ import annotations

import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.wechat_mp_reverse.cli import main
from reverse.wechat_mp_reverse.client import DEFAULT_USER_AGENT, WeChatMPClient
from reverse.wechat_mp_reverse.errors import WeChatMPError, WeChatMPInputError, WeChatMPResponseError

FIXTURES = Path(__file__).with_name("fixtures")
ARTICLE_HTML = (FIXTURES / "article.html").read_text(encoding="utf-8")
EXTENSIONS = (FIXTURES / "extensions.json").read_text(encoding="utf-8")
ARTICLE_URL = "https://mp.weixin.qq.com/s/FixtureArticleToken_123"


def response(
    source: str,
    *,
    status: int = 200,
    url: str = "",
    content_type: str = "text/html; charset=utf-8",
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["content-type"] = content_type
    result.content = source.encode("utf-8")
    result.default_encoding = "utf-8"
    return result


class FakeSession(requests.Session):
    def __init__(self, results: list[requests.Response | Exception]) -> None:
        super().__init__()
        self.results = deque(results)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        return self._next("GET", url, kwargs)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        return self._next("POST", url, kwargs)

    def _next(
        self, method: str, url: str, kwargs: dict[str, object]
    ) -> requests.Response:
        self.calls.append((method, url, kwargs))
        if not self.results:
            raise AssertionError("unexpected HTTP request")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result


class WeChatMPClientTest(unittest.TestCase):
    def test_public_error_hierarchy_headers_and_constructor_validation(self) -> None:
        self.assertTrue(issubclass(WeChatMPInputError, WeChatMPError))
        self.assertTrue(issubclass(WeChatMPResponseError, WeChatMPError))
        session = FakeSession([])
        WeChatMPClient(session=session)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("text/html", session.headers["Accept"])
        for kwargs in (
            {"timeout": 0},
            {"timeout": float("inf")},
            {"retries": -1},
            {"retries": True},
            {"user_agent": "bad\nheader"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(WeChatMPInputError):
                WeChatMPClient(**kwargs)  # type: ignore[arg-type]

    def test_article_url_accepts_short_long_http_and_share_text(self) -> None:
        self.assertEqual(WeChatMPClient.resolve_article_url(ARTICLE_URL), ARTICLE_URL)
        self.assertEqual(
            WeChatMPClient.resolve_article_url(
                "Read this: http://mp.weixin.qq.com/s/FixtureArticleToken_123)."
            ),
            ARTICLE_URL,
        )
        long_url = (
            "https://mp.weixin.qq.com/s?__biz=MTIzNDU2Nzg5MA=="
            "&mid=2247483999&idx=1&sn=0123456789abcdef0123456789abcdef#rd"
        )
        self.assertEqual(WeChatMPClient.resolve_article_url(long_url), long_url)

    def test_article_url_rejects_lookalikes_credentials_ports_and_bad_routes(self) -> None:
        for value in (
            "",
            "https://mp.weixin.qq.com.example/s/FixtureArticleToken_123",
            "https://user@mp.weixin.qq.com/s/FixtureArticleToken_123",
            "https://mp.weixin.qq.com:444/s/FixtureArticleToken_123",
            "https://mp.weixin.qq.com/s%2FFixtureArticleToken_123",
            "https://mp.weixin.qq.com/s",
            "https://mp.weixin.qq.com/mp/profile_ext?action=home",
            "https://mp.weixin.qq.com/s/tiny",
        ):
            with self.subTest(value=value), self.assertRaises(WeChatMPInputError):
                WeChatMPClient.resolve_article_url(value)

    def test_fixture_parses_article_account_ids_content_media_and_albums(self) -> None:
        article = WeChatMPClient.parse_article_html(
            ARTICLE_HTML,
            page_url=ARTICLE_URL,
            expected_url=ARTICLE_URL,
        )
        self.assertEqual(article["title"], "Fixture & Title")
        self.assertEqual(article["author"], "Fixture Author")
        self.assertEqual(article["published_timestamp"], 1741148529)
        self.assertEqual(article["published_at"], "2025-03-05T04:22:09+00:00")
        self.assertEqual(article["account"]["username"], "gh_fixture123")
        self.assertEqual(article["account"]["alias"], "FixtureAlias")
        self.assertEqual(article["account"]["biz_uin"], "1234567890")
        self.assertEqual(article["ids"]["comment_id"], "12109128638545265979")
        self.assertEqual(
            article["content_text"],
            "Fixture intro & more\nSecond line\n\ndiagram\n\nSource link",
        )
        self.assertNotIn("not article text", article["content_text"])
        self.assertNotIn("id=\"js_content\"", article["content_html"])
        self.assertEqual(article["media"]["videos"], ["https://cdn.example/video.mp4"])
        self.assertEqual(article["media"]["images"][1], "https://cdn.example/content-one.jpg")
        self.assertEqual(article["links"], ["https://example.com/source?a=1&b=2"])
        self.assertEqual(article["albums"][0]["id"], "90071992547409930")
        self.assertEqual(article["albums"][0]["title"], "AI & ML")
        self.assertEqual(article["related_articles"][0]["relation"], "previous")
        self.assertTrue(article["comment"]["enabled"])

    def test_empty_access_page_and_canonical_mismatch_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(WeChatMPResponseError, "public article metadata"):
            WeChatMPClient.parse_article_html("<html><body>empty</body></html>")
        with self.assertRaisesRegex(WeChatMPResponseError, "verification or access"):
            WeChatMPClient.parse_article_html(
                "<html><head><title>Verify</title></head><body>wappoc_appmsgcaptcha</body></html>"
            )
        mismatch = ARTICLE_HTML.replace(
            "FixtureArticleToken_123", "DifferentArticleToken_456"
        )
        with self.assertRaisesRegex(WeChatMPResponseError, "canonical token"):
            WeChatMPClient.parse_article_html(
                mismatch,
                page_url="https://mp.weixin.qq.com/s/DifferentArticleToken_456",
                expected_url=ARTICLE_URL,
            )

    def test_get_article_validates_final_route_and_returns_parsed_data(self) -> None:
        session = FakeSession([response(ARTICLE_HTML, url=ARTICLE_URL)])
        article = WeChatMPClient(session=session).get_article(ARTICLE_URL)
        self.assertEqual(article["title"], "Fixture & Title")
        self.assertEqual(session.calls[0][0:2], ("GET", ARTICLE_URL))
        self.assertTrue(session.calls[0][2]["allow_redirects"])

        external = FakeSession(
            [response(ARTICLE_HTML, url="https://example.com/s/FixtureArticleToken_123")]
        )
        with self.assertRaisesRegex(WeChatMPResponseError, "outside"):
            WeChatMPClient(session=external).get_article(ARTICLE_URL)

    def test_extension_request_contract_and_normalization(self) -> None:
        session = FakeSession(
            [
                response(ARTICLE_HTML, url=ARTICLE_URL),
                response(
                    EXTENSIONS,
                    url="https://mp.weixin.qq.com/mp/getappmsgext?f=json",
                    content_type="application/json; charset=utf-8",
                ),
            ]
        )
        result = WeChatMPClient(session=session).get_article_extensions(ARTICLE_URL)
        self.assertEqual(result["base_response"]["ret"], 0)
        self.assertEqual(result["statistics"]["reads"], 100001)
        self.assertEqual(result["tags"][0]["id"], "90071992547409930")
        self.assertEqual(result["tags"][0]["name"], "AI & ML")
        self.assertEqual(result["related_articles"][2]["relation"], "recommended")

        method, url, kwargs = session.calls[1]
        self.assertEqual((method, url), ("POST", "https://mp.weixin.qq.com/mp/getappmsgext"))
        self.assertEqual(kwargs["params"], {"f": "json", "__biz": "MTIzNDU2Nzg5MA=="})
        form = kwargs["data"]
        self.assertEqual(form["mid"], "2247483999")  # type: ignore[index]
        self.assertEqual(form["comment_id"], "12109128638545265979")  # type: ignore[index]
        self.assertIn("%26", form["title"])  # type: ignore[index]
        self.assertEqual(kwargs["headers"]["X-Requested-With"], "XMLHttpRequest")  # type: ignore[index]

    def test_related_articles_deduplicate_page_and_extension_items(self) -> None:
        session = FakeSession(
            [
                response(ARTICLE_HTML, url=ARTICLE_URL),
                response(
                    EXTENSIONS,
                    url="https://mp.weixin.qq.com/mp/getappmsgext?f=json",
                    content_type="application/json",
                ),
            ]
        )
        result = WeChatMPClient(session=session).get_related_articles(ARTICLE_URL)
        self.assertEqual(result["count"], 3)
        self.assertEqual(
            [item["relation"] for item in result["items"]],
            ["previous", "next", "recommended"],
        )

    def test_extension_json_and_api_errors_are_structured(self) -> None:
        invalid_json = FakeSession(
            [
                response(ARTICLE_HTML, url=ARTICLE_URL),
                response("not json", url="https://mp.weixin.qq.com/mp/getappmsgext"),
            ]
        )
        with self.assertRaisesRegex(WeChatMPResponseError, "not JSON"):
            WeChatMPClient(session=invalid_json).get_article_extensions(ARTICLE_URL)

        error_payload = json.dumps({"base_resp": {"ret": -13, "err_msg": "expired"}})
        api_error = FakeSession(
            [
                response(ARTICLE_HTML, url=ARTICLE_URL),
                response(error_payload, url="https://mp.weixin.qq.com/mp/getappmsgext"),
            ]
        )
        with self.assertRaises(WeChatMPResponseError) as raised:
            WeChatMPClient(session=api_error).get_article_extensions(ARTICLE_URL)
        self.assertEqual(raised.exception.error_code, -13)
        self.assertEqual(str(raised.exception), "expired")

    def test_transient_failures_retry_but_deterministic_http_errors_do_not(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture disconnect"),
                response("busy", status=503, url=ARTICLE_URL),
                response(ARTICLE_HTML, url=ARTICLE_URL),
            ]
        )
        with patch("reverse.wechat_mp_reverse.client.time.sleep") as sleep:
            article = WeChatMPClient(session=session, retries=2).get_article(ARTICLE_URL)
        self.assertEqual(article["title"], "Fixture & Title")
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

        deterministic = FakeSession([response("missing", status=404, url=ARTICLE_URL)])
        with self.assertRaisesRegex(WeChatMPResponseError, "HTTP 404"):
            WeChatMPClient(session=deterministic, retries=2).get_article(ARTICLE_URL)
        self.assertEqual(len(deterministic.calls), 1)


class WeChatMPCliTest(unittest.TestCase):
    def test_cli_dispatches_json_and_reports_domain_errors(self) -> None:
        with patch.object(
            WeChatMPClient,
            "get_account_from_article",
            return_value={"name": "Fixture Account"},
        ), patch("builtins.print") as output:
            self.assertEqual(main(["account", ARTICLE_URL]), 0)
        self.assertIn("Fixture Account", output.call_args.args[0])

        with patch.object(
            WeChatMPClient,
            "get_article",
            side_effect=WeChatMPResponseError("fixture error"),
        ), patch("builtins.print") as output:
            self.assertEqual(main(["article", ARTICLE_URL]), 1)
        self.assertEqual(output.call_args.args[0], "error: fixture error")


if __name__ == "__main__":
    unittest.main()
