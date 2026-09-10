from __future__ import annotations

import json
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from reverse.twitter_reverse.errors import TwitterInputError, TwitterResponseError
from reverse.twitter_reverse.judge import (
    judge_account,
    response_output_text,
    responses_url,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_CRITERIA = "only local test topic"
_API_KEY = "test-key"
_ACCOUNT = {
    "username": "example_dev",
    "name": "Example Dev",
    "description": "I ship local LLM tools",
    "followers": 3200,
    "following": 2900,
    "blue_verified": True,
    "tweets": [{"text": "shipping a local model router"}],
    "endpoint": "/i/api/graphql/AbCdQueryId/UserByScreenName",
    "queryId": "AbCdQueryIdNotForLLM",
    "cookie": "auth_token=should-not-leave",
}


def load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def fixture_bytes(name: str) -> bytes:
    return json.dumps(load_fixture(name), ensure_ascii=False).encode("utf-8")


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def http_error(status: int) -> HTTPError:
    headers = Message()
    headers["Content-Type"] = "application/json"
    return HTTPError(
        url="https://example.com/v1/responses",
        code=status,
        msg="error",
        hdrs=headers,
        fp=BytesIO(b"{}"),
    )


def call_judge(**kwargs: object) -> dict:
    params: dict[str, object] = {
        "account": _ACCOUNT,
        "criteria": _CRITERIA,
        "base_url": "https://example.com",
        "api_key": _API_KEY,
        "timeout": 60.0,
    }
    params.update(kwargs)
    return judge_account(**params)  # type: ignore[arg-type]


def posted_request(mock_urlopen) -> Request:
    request = mock_urlopen.call_args.args[0]
    assert isinstance(request, Request)
    return request


def posted_payload(mock_urlopen) -> dict:
    return json.loads(posted_request(mock_urlopen).data.decode("utf-8"))


class ResponsesUrlTest(unittest.TestCase):
    def test_joins_without_doubling_responses(self) -> None:
        expected = "https://example.com/v1/responses"
        self.assertEqual(responses_url("https://example.com"), expected)
        self.assertEqual(responses_url("https://example.com/"), expected)
        self.assertEqual(responses_url("https://example.com/v1"), expected)
        self.assertEqual(responses_url("https://example.com/v1/responses"), expected)
        self.assertEqual(responses_url("https://example.com/v1/responses/"), expected)


class ResponseOutputTextTest(unittest.TestCase):
    def test_prefers_output_text_then_message_parts(self) -> None:
        top = load_fixture("judge_responses_output_text.json")
        parts = load_fixture("judge_responses_output_parts.json")
        self.assertIn("AI tooling in bio", response_output_text(top))
        parsed = json.loads(response_output_text(parts))
        self.assertFalse(parsed["matches_criteria"])
        self.assertTrue(parsed["need_tweets"])
        self.assertNotIn("should ignore reasoning", response_output_text(parts))
        self.assertNotIn("should ignore non output_text", response_output_text(parts))


class JudgeAccountTest(unittest.TestCase):
    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_request_json_locks_schema_and_sampling(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(fixture_bytes("judge_responses_output_text.json"))
        call_judge()

        request = posted_request(mock_urlopen)
        payload = posted_payload(mock_urlopen)
        body_text = request.data.decode("utf-8")
        schema = payload["text"]["format"]["schema"]

        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://example.com/v1/responses")
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 60.0)
        self.assertEqual(payload["model"], "gemini-3.8-flash")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(payload["text"]["format"]["name"], "twitter_follow_judgment")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertIn("matches_criteria", schema["required"])
        self.assertEqual(
            schema["properties"]["matches_criteria"]["description"],
            "true iff the account matches --criteria",
        )
        self.assertIn(_CRITERIA, payload["input"][0]["content"])
        self.assertIn("只输出一个 JSON 对象", payload["input"][0]["content"])
        self.assertNotIn("temperature", payload)
        self.assertNotIn("top_p", payload)
        self.assertNotIn("top_k", payload)
        self.assertNotIn("Authorization", payload)
        self.assertNotIn(_API_KEY, body_text)
        self.assertNotIn("x-goog-api-key", json.dumps(dict(request.header_items())).lower())

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_authorization_is_bearer_header_only(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(fixture_bytes("judge_responses_output_text.json"))
        call_judge()

        request = posted_request(mock_urlopen)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["authorization"], "Bearer test-key")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertNotIn(_API_KEY, request.data.decode("utf-8"))

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_parses_output_text_fixture(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(fixture_bytes("judge_responses_output_text.json"))
        result = call_judge()
        self.assertEqual(
            result,
            {
                "matches_criteria": True,
                "need_tweets": False,
                "confidence": 1.0,
                "summary": "AI tooling in bio",
                "reasons": ["bio mentions local LLM"],
            },
        )
        self.assertIsInstance(result["confidence"], float)

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_parses_output_parts_fixture_without_output_text(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(fixture_bytes("judge_responses_output_parts.json"))
        result = call_judge()
        self.assertEqual(
            result,
            {
                "matches_criteria": False,
                "need_tweets": True,
                "confidence": 0.4,
                "summary": "bio is too thin",
                "reasons": ["need recent tweets"],
            },
        )

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_http_401_and_403_are_gemini_unauthorized(self, mock_urlopen) -> None:
        for status in (401, 403):
            with self.subTest(status=status):
                mock_urlopen.reset_mock()
                mock_urlopen.side_effect = http_error(status)
                with self.assertRaises(TwitterResponseError) as raised:
                    call_judge()
                self.assertEqual(raised.exception.code, "gemini_unauthorized")
                self.assertIsInstance(raised.exception.__cause__, HTTPError)
                self.assertNotIn(_API_KEY, str(raised.exception))
                self.assertNotIn("Bearer", str(raised.exception))
                self.assertEqual(mock_urlopen.call_count, 1)

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_http_429_retries_once_then_succeeds(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = [
            http_error(429),
            FakeResponse(fixture_bytes("judge_responses_output_text.json")),
        ]
        result = call_judge()
        self.assertTrue(result["matches_criteria"])
        self.assertEqual(mock_urlopen.call_count, 2)
        first = mock_urlopen.call_args_list[0].args[0]
        second = mock_urlopen.call_args_list[1].args[0]
        self.assertEqual(first.data, second.data)
        self.assertEqual(mock_urlopen.call_args_list[1].kwargs["timeout"], 60.0)

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_http_429_twice_is_gemini_rate_limited(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = [http_error(429), http_error(429)]
        with self.assertRaises(TwitterResponseError) as raised:
            call_judge()
        self.assertEqual(raised.exception.code, "gemini_rate_limited")
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertNotIn(_API_KEY, str(raised.exception))

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_maps_relevant_reason_aliases(self, mock_urlopen) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "relevant": True,
                                    "reason": "bio mentions local LLM tools",
                                }
                            ),
                        }
                    ],
                }
            ]
        }
        mock_urlopen.return_value = FakeResponse(
            json.dumps(payload).encode("utf-8")
        )
        result = call_judge()
        self.assertTrue(result["matches_criteria"])
        self.assertFalse(result["need_tweets"])
        self.assertEqual(result["summary"], "bio mentions local LLM tools")
        self.assertEqual(result["reasons"], ["bio mentions local LLM tools"])
        self.assertEqual(result["confidence"], 0.5)

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_parses_markdown_wrapped_json(self, mock_urlopen) -> None:
        judgment = {
            "matches_criteria": True,
            "need_tweets": False,
            "confidence": 0.8,
            "summary": "from markdown",
            "reasons": ["wrapped"],
        }
        payload = {
            "output": [
                {
                    "type": "reasoning",
                    "summary": "should ignore reasoning",
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "```json\n"
                            + json.dumps(judgment)
                            + "\n```",
                        }
                    ],
                },
            ]
        }
        mock_urlopen.return_value = FakeResponse(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        result = call_judge()
        self.assertEqual(result["summary"], "from markdown")
        self.assertTrue(result["matches_criteria"])

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_damaged_json_is_llm_failed(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(b"{not-json")
        with self.assertRaises(TwitterResponseError) as raised:
            call_judge()
        self.assertEqual(raised.exception.code, "llm_failed")
        self.assertIsInstance(raised.exception.__cause__, json.JSONDecodeError)

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_missing_config_is_twitter_input_error(self, mock_urlopen) -> None:
        cases = [
            {"api_key": ""},
            {"api_key": "  "},
            {"base_url": ""},
            {"base_url": "   "},
            {"criteria": ""},
            {"criteria": "\n\t"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                mock_urlopen.reset_mock()
                with self.assertRaises(TwitterInputError):
                    call_judge(**kwargs)
                mock_urlopen.assert_not_called()

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_account_prompt_drops_graphql_and_auth_keys(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(fixture_bytes("judge_responses_output_text.json"))
        call_judge()
        payload = posted_payload(mock_urlopen)
        body_text = json.dumps(payload, ensure_ascii=False)
        user_content = payload["input"][1]["content"]
        self.assertIsInstance(user_content, str)
        self.assertIn("username: example_dev", user_content)
        self.assertIn("bio: I ship local LLM tools", user_content)
        self.assertIn("- shipping a local model router", user_content)
        self.assertNotIn("endpoint", body_text)
        self.assertNotIn("queryId", body_text)
        self.assertNotIn("AbCdQueryIdNotForLLM", body_text)
        self.assertNotIn("auth_token=should-not-leave", body_text)
        self.assertNotIn("cookie", body_text)

    @patch("reverse.twitter_reverse.judge.urlopen")
    def test_other_http_and_url_errors_are_llm_failed(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = http_error(500)
        with self.assertRaises(TwitterResponseError) as raised:
            call_judge()
        self.assertEqual(raised.exception.code, "llm_failed")
        self.assertEqual(mock_urlopen.call_count, 1)

        mock_urlopen.reset_mock()
        mock_urlopen.side_effect = URLError("timed out")
        with self.assertRaises(TwitterResponseError) as raised:
            call_judge()
        self.assertEqual(raised.exception.code, "llm_failed")
        self.assertIsInstance(raised.exception.__cause__, URLError)


if __name__ == "__main__":
    unittest.main()
