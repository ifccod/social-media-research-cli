from __future__ import annotations

import json
import unittest
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from curl_cffi import requests

from reverse.zhihu_reverse.cli import main as cli_main
from reverse.zhihu_reverse.client import DEFAULT_USER_AGENT, ZhihuClient
from reverse.zhihu_reverse.errors import (
    ZhihuError,
    ZhihuInputError,
    ZhihuResponseError,
    ZhihuSignatureError,
)
from reverse.zhihu_reverse.signing import ZhihuChallengeRunner, build_x_zse_96, encrypt_md5

FIXTURES = Path(__file__).with_name("fixtures")
QUESTION = json.loads((FIXTURES / "question.json").read_text(encoding="utf-8"))
ANSWER = json.loads((FIXTURES / "answer.json").read_text(encoding="utf-8"))
ARTICLE = json.loads((FIXTURES / "article.json").read_text(encoding="utf-8"))
PIN = json.loads((FIXTURES / "pin.json").read_text(encoding="utf-8"))
USER = json.loads((FIXTURES / "user.json").read_text(encoding="utf-8"))
LISTING = json.loads((FIXTURES / "listing.json").read_text(encoding="utf-8"))
HOT = json.loads((FIXTURES / "hot.json").read_text(encoding="utf-8"))
HOT_RECOMMEND = json.loads(
    (FIXTURES / "hot_recommend.json").read_text(encoding="utf-8")
)
ERROR_40362 = json.loads((FIXTURES / "error_40362.json").read_text(encoding="utf-8"))
CHALLENGE_HTML = (FIXTURES / "challenge.html").read_text(encoding="utf-8")
CHALLENGE_JS = (FIXTURES / "challenge.js").read_text(encoding="utf-8")


def response(
    body: object,
    *,
    status: int = 200,
    url: str = "",
    content_type: str = "application/json; charset=utf-8",
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers["content-type"] = content_type
    source = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
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


class FakeRunner:
    def __init__(self, token: str = "005_fixture-token-fixture-meta-token") -> None:
        self.token = token
        self.calls: list[tuple[str, dict[str, str]]] = []

    def run(self, source: str, **kwargs: str) -> str:
        self.calls.append((source, kwargs))
        return self.token


def ready_client(
    results: list[requests.Response | Exception],
) -> tuple[ZhihuClient, FakeSession]:
    session = FakeSession(results)
    session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
    client = ZhihuClient(session=session, challenge_runner=FakeRunner(), retries=0)
    client._visitor_ready = True
    client._challenge_ready = True
    return client, session


def bootstrap_results(final: object, *, final_status: int = 200) -> list[requests.Response]:
    return [
        response("<html>explore</html>", content_type="text/html"),
        response(CHALLENGE_HTML, status=403, content_type="text/html"),
        response(CHALLENGE_JS, content_type="application/javascript"),
        response(final, status=final_status),
    ]


class ZhihuSigningTest(unittest.TestCase):
    def test_fixed_encryption_vector_matches_reference_implementation(self) -> None:
        self.assertEqual(
            encrypt_md5("0123456789abcdef0123456789abcdef", random_byte=42),
            "AcsLmw4+iF0ZwoBwTNMf5nz3RxBNVxKTy2=dLgN=eqPX5FWFAas++M4fz/GZSCyR",
        )
        signature = build_x_zse_96(
            "/api/v4/questions/37811449?limit=5&offset=0",
            "fixture-d-c0",
            random_byte=42,
        )
        self.assertTrue(signature.startswith("2.0_"))
        self.assertEqual(len(signature), 68)

    def test_signing_inputs_and_runner_configuration_are_checked(self) -> None:
        for value in ("", "xyz", "g" * 32):
            with self.subTest(value=value), self.assertRaises(ZhihuSignatureError):
                encrypt_md5(value)
        with self.assertRaises(ZhihuSignatureError):
            encrypt_md5("0" * 32, random_byte=127)
        with self.assertRaises(ZhihuSignatureError):
            build_x_zse_96("https://www.zhihu.com/api/v4/test", "cookie")
        with self.assertRaises(ZhihuSignatureError):
            ZhihuChallengeRunner(node_binary="node\n--flag")
        with self.assertRaises(ZhihuSignatureError):
            ZhihuChallengeRunner(timeout=float("inf"))

    def test_minimal_node_v8_runner_exposes_current_script_tag(self) -> None:
        token = ZhihuChallengeRunner(timeout=8).run(
            CHALLENGE_JS,
            meta="fixture-meta-token",
            page_url="https://www.zhihu.com/question/37811449",
            user_agent=DEFAULT_USER_AGENT,
        )
        self.assertEqual(token, "005_fixture-token-fixture-meta-token")


class ZhihuClientValidationTest(unittest.TestCase):
    def test_public_errors_and_default_headers(self) -> None:
        self.assertTrue(issubclass(ZhihuInputError, ZhihuError))
        self.assertTrue(issubclass(ZhihuSignatureError, ZhihuError))
        self.assertTrue(issubclass(ZhihuResponseError, ZhihuError))
        session = FakeSession([])
        ZhihuClient(session=session, challenge_runner=FakeRunner())
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertIn("application/json", session.headers["Accept"])

    def test_numeric_references_accept_owned_public_routes(self) -> None:
        self.assertEqual(ZhihuClient.resolve_question_id(37811449), "37811449")
        self.assertEqual(
            ZhihuClient.resolve_question_id(
                "https://www.zhihu.com/question/37811449?utm_source=fixture"
            ),
            "37811449",
        )
        self.assertEqual(
            ZhihuClient.resolve_answer_id(
                "https://zhihu.com/question/37811449/answer/89226347214"
            ),
            "89226347214",
        )
        self.assertEqual(
            ZhihuClient.resolve_article_id("https://zhuanlan.zhihu.com/p/669214677"),
            "669214677",
        )
        self.assertEqual(
            ZhihuClient.resolve_pin_id("www.zhihu.com/pin/2050290260991534603"),
            "2050290260991534603",
        )

    def test_user_and_column_references_are_strict(self) -> None:
        self.assertEqual(ZhihuClient.resolve_user_token("ming-he-43-93"), "ming-he-43-93")
        self.assertEqual(
            ZhihuClient.resolve_user_token(
                "https://www.zhihu.com/people/ming-he-43-93/answers"
            ),
            "ming-he-43-93",
        )
        self.assertEqual(ZhihuClient.resolve_column_id("zhangjiawei"), "zhangjiawei")
        self.assertEqual(
            ZhihuClient.resolve_column_id("https://www.zhihu.com/column/zhangjiawei"),
            "zhangjiawei",
        )
        self.assertEqual(
            ZhihuClient.resolve_column_id("https://zhuanlan.zhihu.com/zhangjiawei"),
            "zhangjiawei",
        )

    def test_references_reject_lookalikes_credentials_ports_and_encoded_routes(self) -> None:
        bad_questions: list[object] = [
            True,
            "1234",
            "037811449",
            "https://example.com/question/37811449",
            "https://www.zhihu.com.example/question/37811449",
            "https://user@www.zhihu.com/question/37811449",
            "https://www.zhihu.com:444/question/37811449",
            "https://www.zhihu.com/question/%33%37%38%31%31%34%34%39",
            "https://www.zhihu.com/people/37811449",
            "https://www.zhihu.com/question/37811449/extra",
        ]
        for value in bad_questions:
            with self.subTest(value=value), self.assertRaises(ZhihuInputError):
                ZhihuClient.resolve_question_id(value)  # type: ignore[arg-type]
        for call in (
            lambda: ZhihuClient.resolve_user_token("https://evil.example/people/ming-he-43-93"),
            lambda: ZhihuClient.resolve_user_token("https://u:p@www.zhihu.com/people/ming-he-43-93"),
            lambda: ZhihuClient.resolve_column_id("https://zhuanlan.zhihu.com:444/zhangjiawei"),
            lambda: ZhihuClient.resolve_column_id("bad column"),
        ):
            with self.assertRaises(ZhihuInputError):
                call()

    def test_transport_pagination_filter_and_runner_options_are_checked(self) -> None:
        for kwargs in (
            {"timeout": 0},
            {"timeout": float("nan")},
            {"retries": -1},
            {"retries": True},
            {"user_agent": "bad\ragent"},
            {"challenge_runner": object()},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ZhihuInputError):
                ZhihuClient(session=FakeSession([]), **kwargs)  # type: ignore[arg-type]

        client, _ = ready_client([])
        for call in (
            lambda: client.get_hot_list(limit=0),
            lambda: client.get_hot_recommend(offset=-1),
            lambda: client.get_hot_recommend(page_number=0),
            lambda: client.get_hot_recommend(session_token="bad token"),
            lambda: client.get_question_answers("37811449", offset=-1),
            lambda: client.get_comments("89226347214", offset="bad cursor"),
            lambda: client.search(""),
            lambda: client.search("query", vertical="people"),
            lambda: client.search("query", sort="popular"),
            lambda: client.initialize_session("/api/v4/../account"),
            lambda: client.initialize_session("/api/v4/%2e%2e/account"),
        ):
            with self.assertRaises(ZhihuInputError):
                call()

    def test_challenge_html_parser_requires_unique_owned_v4_script(self) -> None:
        meta, script = ZhihuClient.parse_challenge_html(CHALLENGE_HTML)
        self.assertEqual(meta, "fixture-meta-token")
        self.assertEqual(
            script, "https://static.zhihu.com/zse-ck/v4/abcdef1234567890.js"
        )
        relative = CHALLENGE_HTML.replace(
            "https://static.zhihu.com", "//static.zhihu.com"
        )
        self.assertEqual(ZhihuClient.parse_challenge_html(relative)[1], script)

        bad_documents = (
            CHALLENGE_HTML.replace("static.zhihu.com", "static.zhihu.com.example"),
            CHALLENGE_HTML.replace("abcdef1234567890", "short"),
            CHALLENGE_HTML.replace(
                "https://static.zhihu.com", "https://user@static.zhihu.com"
            ),
            CHALLENGE_HTML.replace(
                "</head>",
                '<meta id="zh-zse-ck" content="other"></head>',
            ),
        )
        for source in bad_documents:
            with self.subTest(source=source), self.assertRaises(ZhihuResponseError):
                ZhihuClient.parse_challenge_html(source)


class ZhihuClientRequestTest(unittest.TestCase):
    def test_first_signed_request_bootstraps_guest_challenge(self) -> None:
        session = FakeSession(bootstrap_results(QUESTION))
        session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
        runner = FakeRunner()
        client = ZhihuClient(session=session, challenge_runner=runner, retries=0)

        result = client.get_question("37811449")

        self.assertEqual(result["title"], QUESTION["title"])
        self.assertEqual(len(session.calls), 4)
        self.assertEqual(session.calls[0][0], "https://www.zhihu.com/explore")
        self.assertEqual(session.calls[1][0], "https://www.zhihu.com/api/v4/questions/37811449")
        self.assertEqual(
            session.calls[2][0],
            "https://static.zhihu.com/zse-ck/v4/abcdef1234567890.js",
        )
        self.assertEqual(session.calls[3][0], session.calls[1][0])
        self.assertFalse(session.calls[1][1]["allow_redirects"])
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], CHALLENGE_JS)
        self.assertEqual(runner.calls[0][1]["meta"], "fixture-meta-token")
        self.assertEqual(
            runner.calls[0][1]["page_url"],
            "https://www.zhihu.com/question/37811449",
        )
        self.assertEqual(
            session.cookies.get("__zse_ck", domain=".zhihu.com"), runner.token
        )

    def test_query_is_encoded_once_and_the_exact_final_path_is_signed(self) -> None:
        session = FakeSession(bootstrap_results(LISTING))
        session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
        signed: list[tuple[str, str]] = []

        def signer(path: str, cookie: str) -> str:
            signed.append((path, cookie))
            return "2.0_fixture"

        with patch("reverse.zhihu_reverse.client.build_x_zse_96", side_effect=signer):
            ZhihuClient(session=session, challenge_runner=FakeRunner(), retries=0).search(
                "A&B 中文", limit=7, offset=2
            )

        expected = (
            "/api/v4/search_v3?t=general&q=A%26B+%E4%B8%AD%E6%96%87"
            "&correction=1&offset=2&limit=7&lc_idx=2&show_all_topics=0"
            "&search_source=Normal"
        )
        self.assertEqual(signed, [(expected, "fixture-d-c0"), (expected, "fixture-d-c0")])
        self.assertEqual(session.calls[1][0], "https://www.zhihu.com" + expected)
        self.assertEqual(session.calls[3][0], "https://www.zhihu.com" + expected)
        self.assertNotIn("params", session.calls[3][1])
        headers = session.calls[3][1]["headers"]
        self.assertEqual(headers["X-Zse-93"], "101_3_3.0")
        self.assertEqual(headers["X-Zse-96"], "2.0_fixture")
        self.assertEqual(headers["X-Api-Version"], "3.0.91")
        self.assertEqual(headers["X-App-Za"], "OS=Web")

    def test_challenge_initialization_is_reused_across_methods(self) -> None:
        session = FakeSession(bootstrap_results(QUESTION)[:-1] + [response(QUESTION), response(ARTICLE)])
        session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
        runner = FakeRunner()
        client = ZhihuClient(session=session, challenge_runner=runner, retries=0)

        client.get_question("37811449")
        client.get_article("669214677")

        self.assertEqual(len(session.calls), 5)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(session.calls[-1][0], "https://www.zhihu.com/api/v4/articles/669214677")

    def test_40362_refreshes_challenge_once_then_returns_data(self) -> None:
        results = bootstrap_results(ERROR_40362, final_status=403)
        results.extend(
            [
                response(CHALLENGE_HTML, status=403, content_type="text/html"),
                response(CHALLENGE_JS, content_type="application/javascript"),
                response(QUESTION),
            ]
        )
        session = FakeSession(results)
        session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
        runner = FakeRunner()

        result = ZhihuClient(session=session, challenge_runner=runner, retries=0).get_question(
            "37811449"
        )

        self.assertEqual(result["id"], 37811449)
        self.assertEqual(len(session.calls), 7)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(sum(url.endswith("/explore") for url, _ in session.calls), 1)

    def test_second_40362_is_structured_and_does_not_loop(self) -> None:
        results = bootstrap_results(ERROR_40362, final_status=403)
        results.extend(
            [
                response(CHALLENGE_HTML, status=403, content_type="text/html"),
                response(CHALLENGE_JS, content_type="application/javascript"),
                response(ERROR_40362, status=403),
            ]
        )
        session = FakeSession(results)
        session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
        client = ZhihuClient(session=session, challenge_runner=FakeRunner(), retries=0)

        with self.assertRaises(ZhihuResponseError) as raised:
            client.get_question("37811449")

        error = raised.exception
        self.assertEqual(error.status_code, 403)
        self.assertEqual(error.error_code, 40362)
        self.assertEqual(error.payload, ERROR_40362)
        self.assertFalse(error.retryable)
        self.assertIn("expired visitor challenge", str(error))
        self.assertEqual(len(session.calls), 7)

    def test_40353_and_401_are_structured_without_retry(self) -> None:
        for status, payload, expected_code in (
            (403, {"error": {"code": 40353, "message": "fixture rejected"}}, 40353),
            (401, {"message": "fixture authentication"}, None),
        ):
            client, session = ready_client([response(payload, status=status)])
            with self.subTest(status=status), self.assertRaises(ZhihuResponseError) as raised:
                client.get_question("37811449")
            self.assertEqual(raised.exception.status_code, status)
            self.assertEqual(raised.exception.error_code, expected_code)
            self.assertEqual(len(session.calls), 1)

    def test_transport_retries_only_connection_and_selected_statuses(self) -> None:
        client, session = ready_client(
            [
                requests.exceptions.ConnectionError("fixture connection"),
                response({"message": "slow"}, status=429),
                response(HOT),
            ]
        )
        client.retries = 2
        with patch("reverse.zhihu_reverse.client.time.sleep") as sleep:
            result = client.get_hot_list(limit=1)
        self.assertEqual(result["data"][0]["id"], "0_fixture")
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleep.call_count, 2)

        timeout_client, timeout_session = ready_client(
            [requests.exceptions.Timeout("fixture timeout"), response(HOT)]
        )
        timeout_client.retries = 3
        with self.assertRaisesRegex(ZhihuResponseError, "HTTP request failed"):
            timeout_client.get_hot_list(limit=1)
        self.assertEqual(len(timeout_session.calls), 1)

        missing_client, missing_session = ready_client(
            [response({"message": "missing"}, status=404)]
        )
        missing_client.retries = 3
        with self.assertRaisesRegex(ZhihuResponseError, "HTTP 404"):
            missing_client.get_hot_list(limit=1)
        self.assertEqual(len(missing_session.calls), 1)

    def test_invalid_json_identity_and_final_script_url_fail_cleanly(self) -> None:
        invalid, _ = ready_client([response("<html></html>", content_type="text/html")])
        with self.assertRaisesRegex(ZhihuResponseError, "not valid JSON"):
            invalid.get_question("37811449")

        mismatch, _ = ready_client([response({**QUESTION, "id": 99999999})])
        with self.assertRaisesRegex(ZhihuResponseError, "ID mismatch"):
            mismatch.get_question("37811449")

        user_mismatch, _ = ready_client([response({**USER, "url_token": "other-user"})])
        with self.assertRaisesRegex(ZhihuResponseError, "token mismatch"):
            user_mismatch.get_user("ming-he-43-93")

        results = bootstrap_results(QUESTION)
        results[2].url = "https://evil.example/zse-ck/v4/abcdef1234567890.js"
        session = FakeSession(results)
        session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
        with self.assertRaisesRegex(ZhihuResponseError, "owned endpoint"):
            ZhihuClient(session=session, challenge_runner=FakeRunner(), retries=0).get_question(
                "37811449"
            )

    def test_detail_and_listing_endpoint_contracts(self) -> None:
        cases = (
            (
                lambda client: client.get_question("37811449"),
                QUESTION,
                "/api/v4/questions/37811449",
            ),
            (
                lambda client: client.get_answer("89226347214"),
                ANSWER,
                "/api/v4/answers/89226347214",
            ),
            (
                lambda client: client.get_article("669214677"),
                ARTICLE,
                "/api/v4/articles/669214677",
            ),
            (
                lambda client: client.get_pin("2050290260991534603"),
                PIN,
                "/api/v4/pins/2050290260991534603",
            ),
            (
                lambda client: client.get_column_articles("zhangjiawei", limit=2, offset=3),
                LISTING,
                "/api/v4/columns/zhangjiawei/items?limit=2&offset=3",
            ),
            (
                lambda client: client.get_question_answers(
                    "37811449", limit=5, offset=10, order="updated"
                ),
                LISTING,
                "/api/v4/questions/37811449/answers?limit=5&offset=10&platform=desktop&sort_by=updated",
            ),
            (
                lambda client: client.get_user("ming-he-43-93"),
                USER,
                "/api/v4/members/ming-he-43-93",
            ),
            (
                lambda client: client.get_user_answers("ming-he-43-93", limit=7, offset=2),
                LISTING,
                "/api/v4/members/ming-he-43-93/answers?limit=7&offset=2",
            ),
            (
                lambda client: client.get_user_articles(
                    "ming-he-43-93", limit=7, offset=2, sort="updated"
                ),
                LISTING,
                "/api/v4/members/ming-he-43-93/articles?limit=7&offset=2&sort_by=updated",
            ),
            (
                lambda client: client.get_user_followers(
                    "ming-he-43-93", limit=7, offset=2
                ),
                LISTING,
                "/api/v4/members/ming-he-43-93/followers?limit=7&offset=2",
            ),
            (
                lambda client: client.get_user_followees(
                    "ming-he-43-93", limit=7, offset=2
                ),
                LISTING,
                "/api/v4/members/ming-he-43-93/followees?limit=7&offset=2",
            ),
            (
                lambda client: client.get_user_pins(
                    "ming-he-43-93", limit=7, offset=2
                ),
                LISTING,
                "/api/v4/members/ming-he-43-93/pins?limit=7&offset=2",
            ),
            (
                lambda client: client.get_comments(
                    "89226347214", order_by="ts", limit=9, offset="1739257701_11108372663_0"
                ),
                LISTING,
                "/api/v4/comment_v5/answers/89226347214/root_comment?order_by=ts&limit=9&offset=1739257701_11108372663_0",
            ),
            (
                lambda client: client.get_comment_replies("11100789728", limit=8, offset=0),
                LISTING,
                "/api/v4/comment_v5/comment/11100789728/child_comment?order_by=score&limit=8&offset=0",
            ),
            (
                lambda client: client.get_pin_comments("2050290260991534603", limit=6),
                LISTING,
                "/api/v4/comment_v5/pins/2050290260991534603/root_comment?order_by=score&limit=6&offset=",
            ),
        )
        for operation, payload, path in cases:
            with self.subTest(path=path):
                client, session = ready_client([response(payload)])
                result = operation(client)
                self.assertIsInstance(result, dict)
                self.assertEqual(session.calls[0][0], "https://www.zhihu.com" + path)
                self.assertNotIn("params", session.calls[0][1])

    def test_hot_list_is_unsigned_and_skips_guest_bootstrap(self) -> None:
        client, session = ready_client([response(HOT)])
        with patch("reverse.zhihu_reverse.client.build_x_zse_96") as signer:
            result = client.get_hot_list(limit=5)
        self.assertEqual(result, HOT)
        self.assertEqual(
            session.calls[0][0],
            "https://api.zhihu.com/topstory/hot-lists/total?limit=5&reverse_order=0",
        )
        signer.assert_not_called()

    def test_hot_recommend_is_unsigned_and_preserves_paging(self) -> None:
        client, session = ready_client([response(HOT_RECOMMEND)])
        with patch("reverse.zhihu_reverse.client.build_x_zse_96") as signer:
            result = client.get_hot_recommend(
                offset=6,
                page_number=2,
                session_token="fixture_token-1",
            )
        self.assertEqual(result, HOT_RECOMMEND)
        self.assertEqual(
            session.calls[0][0],
            "https://api.zhihu.com/topstory/recommend"
            "?action=down&ad_interval=-10&after_id=6"
            "&page_number=2&session_token=fixture_token-1",
        )
        self.assertEqual(result["data"][0]["target"]["id"], 2064289475916560021)
        signer.assert_not_called()

    def test_callable_runner_injection_is_supported(self) -> None:
        session = FakeSession(bootstrap_results(QUESTION))
        session.cookies.set("d_c0", "fixture-d-c0", domain=".zhihu.com", path="/")
        calls: list[str] = []

        def runner(source: str, **_: str) -> str:
            calls.append(source)
            return "005_callable-token-fixture-meta-token"

        result = ZhihuClient(session=session, challenge_runner=runner, retries=0).get_question(
            "37811449"
        )
        self.assertEqual(result["id"], 37811449)
        self.assertEqual(calls, [CHALLENGE_JS])


class ZhihuCliTest(unittest.TestCase):
    @patch("reverse.zhihu_reverse.cli.ZhihuClient")
    def test_cli_dispatches_and_prints_json(self, client_type) -> None:  # type: ignore[no-untyped-def]
        client_type.return_value.get_hot_list.return_value = HOT
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = cli_main(["hot", "--limit", "1"])
        self.assertEqual(exit_code, 0)
        client_type.return_value.get_hot_list.assert_called_once_with(limit=1)
        self.assertEqual(json.loads(stdout.getvalue()), HOT)

    @patch("reverse.zhihu_reverse.cli.ZhihuClient")
    def test_cli_dispatches_hot_recommend(self, client_type) -> None:  # type: ignore[no-untyped-def]
        client_type.return_value.get_hot_recommend.return_value = HOT_RECOMMEND
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = cli_main(
                [
                    "hot-recommend",
                    "--offset",
                    "6",
                    "--page",
                    "2",
                    "--session-token",
                    "fixture_token-1",
                ]
            )
        self.assertEqual(exit_code, 0)
        client_type.return_value.get_hot_recommend.assert_called_once_with(
            offset=6,
            page_number=2,
            session_token="fixture_token-1",
        )
        self.assertEqual(json.loads(stdout.getvalue()), HOT_RECOMMEND)

    @patch("reverse.zhihu_reverse.cli.ZhihuClient")
    def test_cli_reports_module_errors(self, client_type) -> None:  # type: ignore[no-untyped-def]
        client_type.return_value.get_question.side_effect = ZhihuResponseError("fixture")
        stderr = StringIO()
        with redirect_stderr(stderr):
            exit_code = cli_main(["question", "37811449"])
        self.assertEqual(exit_code, 1)
        self.assertIn("error: fixture", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
