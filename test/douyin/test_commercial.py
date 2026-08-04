from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from reverse.douyin_reverse import cli
from reverse.douyin_reverse.client import DouyinClient
from reverse.douyin_reverse.errors import DouyinInputError, DouyinResponseError


class DouyinKeywordTrendTest(unittest.TestCase):
    def test_keyword_trend_builds_index_contract_and_normalizes_items(self) -> None:
        calls: list[
            tuple[str, list[tuple[str, str]], str]
        ] = []

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            referer: str,
        ) -> dict[str, object]:
            calls.append((path, entries, referer))
            return {
                "BaseResp": {"StatusCode": 0, "StatusMessage": ""},
                "hot_list": [
                    {
                        "keyword": "美 食",
                        "hot_list": [
                            {"datetime": "20260701", "index": "88"}
                        ],
                        "search_hot_list": [],
                        "top_point_list": [],
                        "search_top_point_list": [],
                    }
                ],
            }

        result = DouyinClient(index_fetch=fetch).get_keyword_trend(
            ["美食", "露营"],
            start_date="20260701",
            end_date="20260728",
            regions=["北京"],
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["missing_keywords"], ["露营"])
        self.assertEqual(result["items"][0]["keyword"], "美食")
        self.assertEqual(result["items"][0]["upstream_keyword"], "美 食")
        path, entries, referer = calls[0]
        self.assertEqual(path, "/api/v2/index/get_multi_keyword_hot_trend")
        self.assertEqual(
            dict(entries),
            {
                "keyword_list": json.dumps(
                    ["美食", "露营"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "start_date": "20260701",
                "end_date": "20260728",
                "app_name": "aweme",
                "region": json.dumps(
                    ["北京"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )
        self.assertEqual(
            referer,
            "https://creator.douyin.com/creator-micro/creator-count/"
            "arithmetic-index",
        )

    def test_keyword_trend_rejects_invalid_inputs_before_fetch(self) -> None:
        fetch = Mock()
        client = DouyinClient(index_fetch=fetch)
        cases = (
            {"keywords": [], "start_date": "20260701", "end_date": "20260728"},
            {
                "keywords": ["美食", "美食"],
                "start_date": "20260701",
                "end_date": "20260728",
            },
            {
                "keywords": ["美食", "美 食"],
                "start_date": "20260701",
                "end_date": "20260728",
            },
            {
                "keywords": ["美食"],
                "start_date": "20260230",
                "end_date": "20260728",
            },
            {
                "keywords": ["美食"],
                "start_date": "20260728",
                "end_date": "20260701",
            },
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(
                DouyinInputError
            ):
                client.get_keyword_trend(**arguments)
        fetch.assert_not_called()

    def test_keyword_trend_checks_real_base_response_status(self) -> None:
        client = DouyinClient(
            index_fetch=lambda *_args: {
                "BaseResp": {
                    "StatusCode": 1001,
                    "StatusMessage": "参数错误",
                },
                "hot_list": [],
            }
        )

        with self.assertRaisesRegex(
            DouyinResponseError,
            "StatusCode=1001: 参数错误",
        ):
            client.get_keyword_trend(
                ["美食"],
                start_date="20260701",
                end_date="20260728",
            )

    def test_keyword_trend_cli_exposes_all_observed_parameters(self) -> None:
        args = cli._parser().parse_args(
            [
                "keyword-trend",
                "美食",
                "露营",
                "--start-date",
                "20260701",
                "--end-date",
                "20260728",
                "--region",
                "北京",
                "--app-name",
                "toutiao",
            ]
        )
        client = Mock()
        client.get_keyword_trend.return_value = {"kind": "keyword_trend"}

        result = cli._dispatch(client, args)

        self.assertEqual(result, {"kind": "keyword_trend"})
        client.get_keyword_trend.assert_called_once_with(
            ["美食", "露营"],
            start_date="20260701",
            end_date="20260728",
            regions=["北京"],
            app_name="toutiao",
        )


if __name__ == "__main__":
    unittest.main()
