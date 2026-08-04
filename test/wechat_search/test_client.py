from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.wechat_search_reverse.cli import main
from reverse.wechat_search_reverse.client import DEFAULT_USER_AGENT, WeChatSearchClient
from reverse.wechat_search_reverse.errors import (
    WeChatSearchError,
    WeChatSearchInputError,
    WeChatSearchResponseError,
)

FIXTURES = Path(__file__).with_name("fixtures")
ARTICLES_HTML = (FIXTURES / "articles.html").read_text(encoding="utf-8")
ACCOUNTS_HTML = (FIXTURES / "accounts.html").read_text(encoding="utf-8")
NO_RESULTS_HTML = (FIXTURES / "no_results.html").read_text(encoding="utf-8")
REDIRECT_HTML = (FIXTURES / "redirect.html").read_text(encoding="utf-8")
ANTISPIDER_HTML = (FIXTURES / "antispider.html").read_text(encoding="utf-8")
SOGOU_TOKEN = "12345678" + "A" * 32 + "90ABCDEF"
SOGOU_LINK = (
    "https://weixin.sogou.com/link?url=fixture-one&type=2"
    f"&query=Fixture&token={SOGOU_TOKEN}"
)
ARTICLE_URL = (
    "https://mp.weixin.qq.com/s?src=11&timestamp=1741148529"
    "&signature=fixture-signature&new=1"
)


def response(
    source: str,
    *,
    status: int = 200,
    url: str = "",
    content_type: str = "text/html; charset=utf-8",
    location: str = "",
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["content-type"] = content_type
    if location:
        result.headers["location"] = location
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


class WeChatSearchClientTest(unittest.TestCase):
    def test_error_hierarchy_headers_and_constructor_validation(self) -> None:
        self.assertTrue(issubclass(WeChatSearchInputError, WeChatSearchError))
        self.assertTrue(issubclass(WeChatSearchResponseError, WeChatSearchError))
        session = FakeSession([])
        WeChatSearchClient(session=session)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("text/html", session.headers["Accept"])
        for kwargs in (
            {"timeout": 0},
            {"timeout": float("inf")},
            {"retries": -1},
            {"retries": True},
            {"user_agent": "bad\nheader"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(WeChatSearchInputError):
                WeChatSearchClient(**kwargs)  # type: ignore[arg-type]

    def test_article_fixture_normalizes_results_pagination_and_cover(self) -> None:
        result = WeChatSearchClient.parse_search_html(
            ARTICLES_HTML,
            keyword="人工智能",
            kind="article",
            page=1,
            page_url="https://weixin.sogou.com/weixin?type=2&page=1",
        )
        self.assertEqual(result["provider"], "sogou_weixin")
        self.assertEqual(result["total"], 12345)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["next_page"], 2)
        self.assertTrue(result["has_more"])
        first = result["items"][0]
        self.assertEqual(first["title"], "人工智能 & 产业观察")
        self.assertEqual(first["summary"], "第一条摘要，包含 高亮词 与实体。")
        self.assertEqual(first["account"]["name"], "Fixture 公众号")
        self.assertEqual(first["published_timestamp"], 1741148529)
        self.assertEqual(first["published_at"], "2025-03-05T04:22:09+00:00")
        self.assertEqual(
            first["cover_url"],
            "https://mmbiz.qpic.cn/mmbiz_jpg/fixture-cover-one/0?wx_fmt=jpeg",
        )
        self.assertTrue(first["url"].startswith("https://weixin.sogou.com/link?"))
        self.assertEqual(first["url_kind"], "temporary_sogou_redirect")

    def test_account_fixture_and_legitimate_empty_result(self) -> None:
        result = WeChatSearchClient.parse_search_html(
            ACCOUNTS_HTML, keyword="Fixture", kind="account"
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["count"], 1)
        account = result["items"][0]
        self.assertEqual(account["name"], "Fixture 科技")
        self.assertEqual(account["username"], "gh_fixture123")
        self.assertEqual(account["description"], "技术资讯 & 工程实践")
        self.assertEqual(account["verification"], "Fixture Technology Co., Ltd.")
        self.assertEqual(
            account["avatar_url"],
            "https://mmbiz.qpic.cn/mmbiz_png/fixture-avatar/0",
        )

        empty = WeChatSearchClient.parse_search_html(
            NO_RESULTS_HTML, keyword="Fixture", kind="account"
        )
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["items"], [])
        self.assertFalse(empty["has_more"])

    def test_search_uses_query_params_page_and_local_limit(self) -> None:
        session = FakeSession(
            [response(ARTICLES_HTML, url="https://weixin.sogou.com/weixin?fixture=1")]
        )
        result = WeChatSearchClient(session=session, retries=0).search_articles(
            " 航天 & 发射 ", page=3, limit=1
        )
        self.assertEqual(result["keyword"], "航天 & 发射")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["available_on_page"], 2)
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://weixin.sogou.com/weixin")
        self.assertEqual(kwargs["params"]["type"], "2")  # type: ignore[index]
        self.assertEqual(kwargs["params"]["query"], "航天 & 发射")  # type: ignore[index]
        self.assertEqual(kwargs["params"]["page"], 3)  # type: ignore[index]
        self.assertFalse(kwargs["allow_redirects"])

    def test_account_request_and_generic_dispatch(self) -> None:
        session = FakeSession([response(NO_RESULTS_HTML)])
        result = WeChatSearchClient(session=session, retries=0).search(
            "Fixture", business_type="account", page=2
        )
        self.assertEqual(result["business_type"], "account")
        self.assertEqual(session.calls[0][1]["params"]["type"], "1")  # type: ignore[index]
        with self.assertRaisesRegex(WeChatSearchInputError, "article.*account"):
            WeChatSearchClient(session=FakeSession([])).search(
                "Fixture", business_type="video"
            )

    def test_parameter_validation(self) -> None:
        client = WeChatSearchClient(session=FakeSession([]))
        for keyword in ("", " ", "x" * 81, "bad\nquery", 123):
            with self.subTest(keyword=keyword), self.assertRaises(WeChatSearchInputError):
                client.search_articles(keyword)  # type: ignore[arg-type]
        for page in (0, 101, 1.5, True):
            with self.subTest(page=page), self.assertRaises(WeChatSearchInputError):
                client.search_articles("Fixture", page=page)  # type: ignore[arg-type]
        for limit in (0, 11, 1.5, True):
            with self.subTest(limit=limit), self.assertRaises(WeChatSearchInputError):
                client.search_articles("Fixture", limit=limit)  # type: ignore[arg-type]

    def test_access_page_and_missing_result_state_are_structured(self) -> None:
        with self.assertRaises(WeChatSearchResponseError) as raised:
            WeChatSearchClient.parse_search_html(
                ANTISPIDER_HTML,
                page_url="https://weixin.sogou.com/antispider/?from=fixture",
            )
        self.assertEqual(raised.exception.error_code, "verification_required")
        self.assertFalse(raised.exception.retryable)
        with self.assertRaisesRegex(WeChatSearchResponseError, "result state"):
            WeChatSearchClient.parse_search_html("<html><body>home</body></html>")

    def test_redirect_fixture_decodes_static_js_without_page_runtime(self) -> None:
        self.assertEqual(
            WeChatSearchClient.parse_article_redirect_html(REDIRECT_HTML), ARTICLE_URL
        )
        session = FakeSession([response(REDIRECT_HTML, url=SOGOU_LINK)])
        resolved = WeChatSearchClient(session=session, retries=0).resolve_article_url(
            SOGOU_LINK
        )
        self.assertEqual(resolved, ARTICLE_URL)
        self.assertEqual(session.calls[0][0], SOGOU_LINK)
        self.assertEqual(session.calls[0][1]["headers"]["Referer"], "https://weixin.sogou.com/")  # type: ignore[index]
        self.assertEqual(session.cookies.get("SNUID"), "A" * 32)

    def test_redirect_rejects_lookalike_input_and_external_targets(self) -> None:
        for value in (
            "",
            "http://weixin.sogou.com/link?url=x&type=2&token=t",
            "https://weixin.sogou.com:bad/link?url=x&type=2&token=t",
            "https://user@weixin.sogou.com/link?url=x&type=2&token=t",
            "https://weixin.sogou.com.example/link?url=x&type=2&token=t",
            "https://weixin.sogou.com/link?url=x&type=1&token=t",
        ):
            with self.subTest(value=value), self.assertRaises(WeChatSearchInputError):
                WeChatSearchClient(session=FakeSession([])).resolve_article_url(value)

        for target in (
            "https://example.com/s/FixtureToken123",
            "https://mp.weixin.qq.com:bad/s/FixtureToken123",
            "https://user@mp.weixin.qq.com/s/FixtureToken123",
            "https://mp.weixin.qq.com/s%2FFixtureToken123",
            "javascript:alert(1)",
        ):
            source = f"<script>var url = '{target}';</script>"
            with self.subTest(target=target), self.assertRaises(WeChatSearchResponseError):
                WeChatSearchClient.parse_article_redirect_html(source)

    def test_transient_failures_retry_and_antispider_redirect_does_not(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture disconnect"),
                response("busy", status=503),
                response(ARTICLES_HTML),
            ]
        )
        with patch("reverse.wechat_search_reverse.client.time.sleep") as sleep:
            result = WeChatSearchClient(session=session, retries=2).search_articles(
                "Fixture"
            )
        self.assertEqual(result["count"], 2)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.4,), (0.8,)])

        blocked = FakeSession(
            [
                response(
                    "",
                    status=302,
                    location="https://weixin.sogou.com/antispider/?from=fixture",
                )
            ]
        )
        with self.assertRaises(WeChatSearchResponseError) as raised:
            WeChatSearchClient(session=blocked, retries=2).search_articles("Fixture")
        self.assertEqual(raised.exception.error_code, "verification_required")
        self.assertEqual(len(blocked.calls), 1)


class WeChatSearchCliTest(unittest.TestCase):
    def test_cli_dispatches_json_and_reports_domain_errors(self) -> None:
        with patch.object(
            WeChatSearchClient,
            "search_articles",
            return_value={"keyword": "Fixture", "count": 1},
        ), patch("builtins.print") as output:
            self.assertEqual(main(["articles", "Fixture", "--limit", "1"]), 0)
        self.assertIn('"count": 1', output.call_args.args[0])

        with patch.object(
            WeChatSearchClient,
            "resolve_article_url",
            side_effect=WeChatSearchResponseError("fixture error"),
        ), patch("builtins.print") as output:
            self.assertEqual(main(["resolve", SOGOU_LINK]), 1)
        self.assertEqual(output.call_args.args[0], "error: fixture error")


if __name__ == "__main__":
    unittest.main()
