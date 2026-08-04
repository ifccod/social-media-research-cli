from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from reverse.reddit_reverse.cli import _parser, _run
from reverse.reddit_reverse.client import RedditClient
from reverse.reddit_reverse.errors import RedditInputError, RedditResponseError
from test.reddit.test_client import FakeSession, response


BATCH_INFO_FIXTURE = json.loads(
    (Path(__file__).with_name("fixtures") / "batch_info.json").read_text(
        encoding="utf-8"
    )
)


class RedditBatchInfoTest(unittest.TestCase):
    def test_shared_fixture_matches_full_contract_and_request(self) -> None:
        session = FakeSession(
            [response(text="identity"), response(BATCH_INFO_FIXTURE["response"])]
        )
        client = RedditClient(session=session, retries=0)

        result = client.get_batch_info(BATCH_INFO_FIXTURE["inputs"])

        self.assertEqual(result, BATCH_INFO_FIXTURE["expected"])
        self.assertEqual(session.calls[1][0], "https://www.reddit.com/api/info.json")
        self.assertEqual(
            session.calls[1][1]["params"],
            {
                "id": "t3_post1,t1_comm1,t3_missing",
                "raw_json": "1",
            },
        )

    def test_cli_dispatches_all_fullnames(self) -> None:
        with patch("reverse.reddit_reverse.cli.RedditClient") as client_class:
            client = client_class.return_value
            client.get_batch_info.return_value = {"items": []}
            args = _parser().parse_args(
                [
                    "--proxy",
                    "http://127.0.0.1:7890",
                    "batch-info",
                    "t3_post1,t1_comm1",
                    "t3_post2",
                ]
            )

            self.assertEqual(_run(args), {"items": []})
            client_class.assert_called_once_with(
                timeout=20,
                retries=2,
                proxy="http://127.0.0.1:7890",
            )
            client.get_batch_info.assert_called_once_with(
                ["t3_post1,t1_comm1", "t3_post2"]
            )

    def test_inputs_are_validated_before_http(self) -> None:
        invalid_values: list[object] = [
            [],
            ["t2_user"],
            ["t3_post1,"],
            ["post1"],
            ["t3_abcdefghijklm"],
            [1],
            [f"t3_{index:x}" for index in range(31)],
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                session = FakeSession([])
                client = RedditClient(session=session, retries=0)
                with self.assertRaises(RedditInputError):
                    client.get_batch_info(value)  # type: ignore[arg-type]
                self.assertEqual(session.calls, [])

        self.assertEqual(
            RedditClient._batch_fullnames(" T3_POST1,t1_COMM1,t3_post1 "),
            ["t3_post1", "t1_comm1"],
        )

    def test_malformed_listing_shapes_are_rejected(self) -> None:
        invalid_payloads = [
            [],
            {"data": []},
            {"data": {"children": {}}},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                client = RedditClient(
                    session=FakeSession(
                        [response(text="identity"), response(payload)]
                    ),
                    retries=0,
                )
                with self.assertRaisesRegex(RedditResponseError, "batch info JSON"):
                    client.get_batch_info("t3_post1")


if __name__ == "__main__":
    unittest.main()
