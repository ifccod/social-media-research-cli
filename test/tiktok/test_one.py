from __future__ import annotations

import unittest
from collections.abc import Mapping
from unittest.mock import patch

from reverse.tiktok_reverse import cli
from reverse.tiktok_reverse.client import TikTokClient
from reverse.tiktok_reverse.errors import TikTokInputError, TikTokResponseError


class TikTokOneTest(unittest.TestCase):
    @staticmethod
    def creator(creator_id: str) -> dict[str, object]:
        return {
            "creator_id": creator_id,
            "tiktok_uid": "6841953820793881606",
            "handle": f"creator_{creator_id[-4:]}",
            "nickname": "Coffee Creator",
            "bio": "coffee",
            "region": "BR",
            "avatar_url": "https://p16.example.test/avatar.jpeg",
            "banned": False,
            "metrics": {
                "followers": 1421277,
                "median_views": 30869,
                "engagement_rate": 0.236,
            },
            "scores": {
                "commercial": 60,
                "collaboration": 76,
                "broadcasting": 100,
                "comprehensive": 80.8,
            },
            "rates": {
                "regional_starting": {
                    "amount_100k": "55560000",
                    "currency": "BRL",
                }
            },
            "content_labels": [{"id": "11007004", "level": 2, "type": 2}],
            "recent_videos": [
                {
                    "id": "7647361736554614047",
                    "title": "Coffee fixture",
                    "created_at": "1756000000",
                    "views": "1200000",
                    "likes": 40000,
                    "comments": 1200,
                    "shares": 500,
                    "sponsored": False,
                    "cover_url": "https://p16.example.test/cover.jpeg",
                    "video_url": "https://v16.example.test/video.mp4",
                }
            ],
            "risk": {"discipline_count": 0, "event_count": 0},
        }

    def test_search_uses_fixed_upstream_page_size_and_deduplicates(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            referer: str,
        ) -> Mapping[str, object]:
            calls.append((path, list(entries), referer))
            page = int(dict(entries)["page"])
            creators = (
                [
                    self.creator("7074051131063664645"),
                    self.creator("7074051131063664646"),
                ]
                if page == 1
                else [
                    self.creator("7074051131063664646"),
                    self.creator("7074051131063664647"),
                ]
            )
            return {
                "creators": creators,
                "pagination": {
                    "page": page,
                    "limit": 24,
                    "totalCount": 3086,
                    "hasMore": page == 1,
                },
            }

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        result = client.search_one_creators(
            "coffee",
            countries=["us", "BR"],
            languages=["en", "pt"],
            min_followers=10000,
            max_followers=2000000,
            min_engagement_rate=0.01,
            sort="median_views",
            limit=3,
        )

        self.assertEqual(result["available"], 3)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(
            [item["creator_id"] for item in result["creators"]],
            [
                "7074051131063664645",
                "7074051131063664646",
                "7074051131063664647",
            ],
        )
        self.assertEqual(
            result["creators"][0]["rates"]["regional_starting"]["amount"],
            555.6,
        )
        self.assertEqual(
            result["creators"][0]["profile_url"],
            "https://www.tiktok.com/@creator_4645",
        )
        self.assertEqual(
            result["creators"][0]["recent_videos"][0]["url"],
            "https://www.tiktok.com/@creator_4645/video/7647361736554614047",
        )
        first = dict(calls[0][1])
        self.assertEqual(first["limit"], "24")
        self.assertEqual(first["countryCodeList"], "US,BR")
        self.assertEqual(first["languageList"], "en,pt")
        self.assertEqual(first["sortField"], "5")
        self.assertEqual(first["sortType"], "2")
        self.assertTrue(calls[0][2].endswith("region=row"))

    def test_filters_suggestions_and_zero_limit(self) -> None:
        calls: list[str] = []

        def fetch(
            path: str,
            _entries: list[tuple[str, str]],
            _referer: str,
        ) -> Mapping[str, object]:
            calls.append(path)
            if path.endswith("QueryPartnerSearchFilterOption"):
                return {
                    "allDataVDCRegions": [1, 2, 3],
                    "defaultDataVDCRegion": 1,
                    "languages": ["en", "pt"],
                    "personaList": [1, 2],
                }
            return {
                "suggestedWords": [
                    "coffeetiktok",
                    "coffeeaddict",
                    "coffeetiktok",
                ]
            }

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        filters = client.get_one_creator_filters()
        suggestions = client.get_one_creator_suggestions("coffee", limit=2)
        empty = client.get_one_creator_suggestions("coffee", limit=0)
        search_empty = client.search_one_creators("coffee", limit=0)

        self.assertEqual(filters["languages"], ["en", "pt"])
        self.assertEqual(
            suggestions["suggestions"], ["coffeetiktok", "coffeeaddict"]
        )
        self.assertEqual(empty["suggestions"], [])
        self.assertEqual(search_empty["creators"], [])
        self.assertEqual(len(calls), 2)

    def test_inputs_and_response_shape_are_strict(self) -> None:
        client = TikTokClient(
            creative_fetch=lambda *_args: {
                "creators": [],
                "pagination": {
                    "page": 2,
                    "limit": 24,
                    "totalCount": 0,
                    "hasMore": False,
                },
            },
            request_interval=0,
        )
        for kwargs in (
            {"keyword": "x\nx"},
            {"keyword": "x", "min_followers": -1},
            {
                "keyword": "x",
                "min_engagement_rate": 0.5,
                "max_engagement_rate": 0.1,
            },
            {"keyword": "x", "sort": "unknown"},
            {"keyword": "x", "limit": 201},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(TikTokInputError):
                client.search_one_creators(**kwargs)
        with self.assertRaises(TikTokResponseError):
            client.search_one_creators("coffee", page=1, limit=1)

    def test_cli_dispatches_one_commands(self) -> None:
        cases = [
            (
                ["one-creator-filters"],
                "get_one_creator_filters",
                (),
                {},
            ),
            (
                ["one-creator-suggest", "coffee", "--limit", "3"],
                "get_one_creator_suggestions",
                ("coffee",),
                {"limit": 3},
            ),
            (
                [
                    "one-creator-search",
                    "coffee",
                    "--country",
                    "US",
                    "--language",
                    "en",
                    "--min-followers",
                    "10000",
                    "--sort",
                    "median_views",
                    "--limit",
                    "30",
                ],
                "search_one_creators",
                ("coffee",),
                {
                    "countries": ["US"],
                    "languages": ["en"],
                    "min_followers": 10000,
                    "max_followers": None,
                    "min_median_views": None,
                    "max_median_views": None,
                    "min_engagement_rate": None,
                    "max_engagement_rate": None,
                    "sort": "median_views",
                    "sort_direction": "descending",
                    "page": 1,
                    "limit": 30,
                },
            ),
        ]
        for argv, method_name, positional, keyword in cases:
            with self.subTest(command=argv[0]):
                parser = cli._parser()
                args = parser.parse_args(argv)
                with (
                    patch.object(cli, "TikTokClient") as client_type,
                    patch.object(cli, "_creative_fetch", return_value=object()),
                ):
                    method = getattr(client_type.return_value, method_name)
                    method.return_value = {"ok": True}
                    self.assertEqual(cli._run(args), {"ok": True})
                    method.assert_called_once_with(*positional, **keyword)
                    self.assertEqual(
                        client_type.call_args.kwargs["creative_fetch"],
                        cli._creative_fetch.return_value,
                    )


if __name__ == "__main__":
    unittest.main()
