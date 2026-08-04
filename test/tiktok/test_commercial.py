from __future__ import annotations

import unittest
from unittest.mock import ANY, AsyncMock, patch

from reverse.browser_session import BrowserSessionError
from reverse.tiktok_reverse import cli
from reverse.tiktok_reverse.client import TikTokClient
from reverse.tiktok_reverse.errors import TikTokInputError, TikTokResponseError


def material(material_id: str = "7656166869774109983") -> dict[str, object]:
    return {
        "id": material_id,
        "adTitle": "Coffee maker 开场直接展示产品结果",
        "brandName": "Example",
        "cost": 2,
        "ctr": 0.72,
        "like": 208,
        "industryKey": "label_14103000000",
        "objectiveKey": "campaign_objective_conversion",
        "sourceKey": 1,
        "favorite": False,
        "isSearch": True,
        "videoInfo": {
            "vid": "v100",
            "duration": 15.0,
            "width": 720,
            "height": 1280,
            "cover": "https://example.test/cover.webp",
            "videoUrl": {
                "720P": "https://example.test/720.mp4",
                "1080P": "https://example.test/1080.mp4",
            },
        },
    }


def performance_material(
    material_id: str = "7657000000000000001",
) -> dict[str, object]:
    return {
        "materialID": material_id,
        "videoInfo": {
            "video_url": {"720p": "https://example.test/720.mp4"},
            "coverAvif": "https://example.test/cover.avif",
            "cover": "https://example.test/cover.jpg",
        },
        "videoView": "9123456",
        "clickRate": "2.75",
        "ctrRank": 97.5,
        "engagementRate": "8.25",
        "videoView6sRank": "91.2",
        "sellingPointList": ["Clear product demo", "Before and after"],
    }


class TikTokAdsKeywordPlannerTest(unittest.TestCase):
    def test_ideas_map_observed_contract_and_filter_competition(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "keywordIdeaInfoList": [
                    {
                        "keyword": "wireless charger",
                        "searchVol": {"volumeMin": 1000, "volumeMax": 5000},
                        "threeMonthChange": -0.48,
                        "yoyChange": -0.63,
                        "trend": None,
                        "competition": 3,
                        "estimatedCpc": {
                            "estimatedCpcLow": 0.23,
                            "estimatedCpcHigh": 0.3,
                        },
                        "brandOption": 2,
                        "sourceType": 1,
                        "matchType": 3,
                        "language": "en",
                        "countryId": None,
                    },
                    {
                        "keyword": "charger stand",
                        "searchVol": {"volumeMin": 100, "volumeMax": 500},
                        "threeMonthChange": 0.1,
                        "yoyChange": 0.2,
                        "trend": [],
                        "competition": 1,
                        "estimatedCpc": {
                            "estimatedCpcLow": 0.1,
                            "estimatedCpcHigh": 0.2,
                        },
                        "brandOption": 2,
                        "sourceType": 1,
                        "matchType": 3,
                        "language": "en",
                        "countryId": None,
                    },
                ],
                "totalSearchVol": {"volumeMin": 250000, "volumeMax": 500000},
                "totalBudgetEstimate": {"volumeMin": 5, "volumeMax": 11},
                "validation": {
                    "keywordsInNoGoList": {"wireless charger": False}
                },
            }

        result = TikTokClient(
            creative_fetch=fetch,
            request_interval=0,
        ).get_ads_keyword_ideas(
            [" Wireless Charger "],
            country="US",
            competitions=["high"],
            sort="volume",
            order="descending",
            limit=10,
            start_time=1751299200,
            end_time=1782835199,
        )

        self.assertEqual(result["available"], 1)
        self.assertEqual(result["ideas"][0]["keyword"], "wireless charger")
        self.assertEqual(result["ideas"][0]["search_volume"]["max"], 5000)
        self.assertEqual(result["ideas"][0]["competition"]["level"], "high")
        self.assertEqual(result["ideas"][0]["estimated_cpc"]["min"], 0.23)
        self.assertEqual(
            dict(calls[0][1]),
            {
                "keywords": '["wireless charger"]',
                "startTime": "1751299200",
                "endTime": "1782835199",
                "brandOption": "0",
                "sortField": "1",
                "sortOrder": "1",
                "countryId": "6252001",
                "languageCode": "en",
                "languageName": "English",
            },
        )
        self.assertTrue(calls[0][2].endswith("/keyword-planner/creation"))

    def test_summary_builds_selected_word_contract(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "totalSearchVol": {"volumeMin": 1000, "volumeMax": 5000},
                "totalBudgetEstimate": None,
            }

        result = TikTokClient(
            creative_fetch=fetch,
            request_interval=0,
        ).get_ads_keyword_summary(
            ["Wireless Charger"],
            country="US",
            match_type="phrase",
        )

        self.assertEqual(result["total_search_volume"]["min"], 1000)
        self.assertIsNone(result["total_budget_estimate"])
        self.assertEqual(
            dict(calls[0][1]),
            {
                "words": (
                    '[{"keyword":"wireless charger",'
                    '"matchType":2,"sourceType":1}]'
                ),
                "countryName": "US",
            },
        )

    def test_invalid_inputs_stop_before_browser_fetch(self) -> None:
        calls: list[object] = []
        client = TikTokClient(
            creative_fetch=lambda *args: calls.append(args) or {},
            request_interval=0,
        )
        cases = (
            {"keywords": []},
            {"keywords": ["x", "x"]},
            {"keywords": ["x"], "country": "SG"},
            {"keywords": ["x"], "language": "zh"},
            {"keywords": ["x"], "competitions": []},
            {"keywords": ["x"], "limit": 201},
            {"keywords": ["x"], "start_time": 1},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(
                TikTokInputError
            ):
                client.get_ads_keyword_ideas(**arguments)
        self.assertEqual(calls, [])

    def test_cli_dispatches_keyword_commands(self) -> None:
        cases = [
            (
                [
                    "ads-keyword-ideas",
                    "wireless charger",
                    "--country",
                    "US",
                    "--competition",
                    "high",
                    "--sort",
                    "volume",
                    "--order",
                    "descending",
                    "--limit",
                    "8",
                ],
                "get_ads_keyword_ideas",
                (["wireless charger"],),
                {
                    "country": "US",
                    "language": "en",
                    "brand": "all",
                    "competitions": ["high"],
                    "sort": "volume",
                    "order": "descending",
                    "limit": 8,
                },
            ),
            (
                [
                    "ads-keyword-summary",
                    "wireless charger",
                    "--match-type",
                    "exact",
                ],
                "get_ads_keyword_summary",
                (["wireless charger"],),
                {
                    "country": "US",
                    "match_type": "exact",
                    "source_type": 1,
                },
            ),
        ]
        for argv, method_name, positional, keyword in cases:
            with self.subTest(command=argv[0]):
                args = cli._parser().parse_args(argv)
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


class TikTokCreativeHashtagPaginationTest(unittest.TestCase):
    def test_full_page_uses_chrome_contract_and_normalizes_metadata(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "items": [
                    {
                        "hashtagID": "7400795988650459167",
                        "hashtagName": "fixture",
                        "industryIDs": [23000000000],
                        "popularityCurve": [
                            {"timestamp": "1784246400", "value": 63.03}
                        ],
                        "publishCnt": "34639",
                        "rankIndex": "21",
                        "topCreators": [{"handleName": "creator"}],
                        "vv": "29712825",
                    }
                ],
                "pagination": {
                    "page": 2,
                    "limit": 20,
                    "totalCount": 41,
                    "hasMore": True,
                },
            }

        result = TikTokClient(
            creative_fetch=fetch,
            request_interval=0,
        ).get_creative_trending_hashtags_full(
            country="us",
            time_range=30,
            industry_id="23000000000",
            page=2,
            limit=20,
        )

        self.assertEqual(result["source"], "tiktok_creative_center")
        self.assertEqual(result["transport"], "browser_web")
        self.assertTrue(result["browser_session"])
        self.assertEqual(
            result["source_url"],
            "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag",
        )
        self.assertFalse(result["anonymous_preview"])
        self.assertFalse(result["continuation_restricted"])
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["limit"], 20)
        self.assertEqual(result["total_count"], 41)
        self.assertEqual(result["next_page"], 3)
        self.assertEqual(
            result["hashtags"],
            [
                {
                    "rank": 21,
                    "id": "7400795988650459167",
                    "name": "fixture",
                    "post_count": 34639,
                    "view_count": 29712825,
                    "industry_ids": [23000000000],
                    "popularity_curve": [
                        {"timestamp": "1784246400", "value": 63.03}
                    ],
                    "top_creators": [{"handleName": "creator"}],
                }
            ],
        )
        self.assertEqual(
            calls,
            [
                (
                    "/CreativeOne/KnowledgeAPI/GetHashtagList",
                    [
                        ("timeRange", "30"),
                        ("countryCode", "US"),
                        ("page", "2"),
                        ("limit", "20"),
                        ("industryID", "23000000000"),
                    ],
                    "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag",
                )
            ],
        )

    def test_full_page_rejects_invalid_input_and_pagination(self) -> None:
        calls: list[object] = []
        client = TikTokClient(
            creative_fetch=lambda *args: calls.append(args) or {},
            request_interval=0,
        )
        for kwargs in (
            {"country": "USA"},
            {"time_range": 14},
            {"industry_id": "topic"},
            {"industry_id": 0},
            {"page": 0},
            {"limit": 101},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(TikTokInputError):
                client.get_creative_trending_hashtags_full(**kwargs)
        self.assertEqual(calls, [])

        with self.assertRaisesRegex(TikTokResponseError, "pagination"):
            TikTokClient(
                creative_fetch=lambda *_args: {
                    "items": [],
                    "pagination": {
                        "page": 1,
                        "limit": 10,
                        "totalCount": 0,
                        "hasMore": False,
                    },
                },
                request_interval=0,
            ).get_creative_trending_hashtags_full(limit=20)

    def test_cli_dispatches_full_hashtag_page(self) -> None:
        args = cli._parser().parse_args(
            [
                "creative-trending-hashtags-full",
                "--country",
                "JP",
                "--time-range",
                "90",
                "--industry-id",
                "23000000000",
                "--page",
                "3",
                "--limit",
                "50",
            ]
        )
        with (
            patch.object(cli, "TikTokClient") as client_type,
            patch.object(
                cli,
                "_creative_fetch",
                return_value=object(),
            ) as creative_fetch,
        ):
            method = client_type.return_value.get_creative_trending_hashtags_full
            method.return_value = {"ok": True}

            self.assertEqual(cli._run(args), {"ok": True})
            method.assert_called_once_with(
                country="JP",
                time_range=90,
                industry_id="23000000000",
                page=3,
                limit=50,
            )
            self.assertEqual(
                client_type.call_args.kwargs["creative_fetch"],
                cli._creative_fetch.return_value,
            )
            creative_fetch.assert_called_once_with(
                "tiktok_creative",
                3.0,
                interactive_login=None,
                login_timeout=300,
            )

    def test_cli_dispatches_full_trending_video_page(self) -> None:
        args = cli._parser().parse_args(
            [
                "creative-trending-videos-full",
                "--country",
                "US",
                "--time-range",
                "7",
                "--metric",
                "completion",
                "--content-label-ids",
                "11002,11003",
                "--page",
                "3",
                "--limit",
                "20",
            ]
        )
        with (
            patch.object(cli, "TikTokClient") as client_type,
            patch.object(
                cli,
                "_creative_fetch",
                return_value=object(),
            ) as creative_fetch,
        ):
            method = client_type.return_value.get_creative_trending_videos_full
            method.return_value = {"ok": True}

            self.assertEqual(cli._run(args), {"ok": True})
            method.assert_called_once_with(
                country="US",
                time_range=7,
                metric="completion",
                content_label_ids="11002,11003",
                page=3,
                limit=20,
            )
            self.assertEqual(
                client_type.call_args.kwargs["creative_fetch"],
                cli._creative_fetch.return_value,
            )
            creative_fetch.assert_called_once_with(
                "tiktok_creative",
                3.0,
                interactive_login=None,
                login_timeout=300,
            )


class TikTokTopAdsTest(unittest.TestCase):
    def test_hashtag_detail_maps_audience_and_representative_videos(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "hashtagID": "1657263259226117",
                "hashtagName": "rushready",
                "industryIDs": ["22000000000"],
                "publishCnt": "859198",
                "vv": "399083713",
                "popularityCurve": [{"timestamp": "1785024000", "value": 100}],
                "ageProfile": [{"ageLevel": "3", "vvPercent": "37.26"}],
                "representativeCountryProfile": [
                    {"countryCode": "US", "countryTgiScore": "604.07"}
                ],
                "videoList": [
                    {
                        "itemID": "7664508454660345102",
                        "vid": "v12025gd0000d9ess17og65pqggvbgng",
                        "coverURL": "https://example.test/cover.webp",
                        "videoURL": {
                            "default": "https://example.test/video.mp4"
                        },
                    }
                ],
            }

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        result = client.get_creative_hashtag_detail(
            "1657263259226117",
            country="us",
            time_range=7,
        )

        self.assertEqual(result["hashtag"]["view_count"], 399083713)
        self.assertEqual(
            result["representative_country_profile"][0]["countryTgiScore"],
            "604.07",
        )
        self.assertEqual(
            result["representative_videos"][0]["item_id"],
            "7664508454660345102",
        )
        self.assertEqual(
            calls[0][0],
            "/CreativeOne/KnowledgeAPI/GetHashtagDetail",
        )
        self.assertEqual(
            calls[0][1],
            [
                ("hashtagID", "1657263259226117"),
                ("timeRange", "7"),
                ("countryCode", "US"),
            ],
        )

    def test_filters_and_suggestions_use_creative_radar(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path.endswith("/filters"):
                return {
                    "adLanguage": [{"id": "en", "label": "en", "value": "English"}],
                    "country": [{"id": "US", "label": "US", "value": "United States"}],
                    "industry": [
                        {"id": "14103000000", "label": "skin", "value": "Skincare"}
                    ],
                    "objective": [
                        {"id": "3", "label": "conversion", "value": "Conversions"}
                    ],
                    "patternLabel": [
                        {"id": "10100100000", "label": "hook", "value": "Hook"}
                    ],
                    "period": [{"id": "30", "label": "30d", "value": "30 days"}],
                }
            return {"query": ["coffee recipe", "coffee maker"]}

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        filters = client.get_creative_top_ads_filters()
        suggestions = client.get_creative_top_ads_suggestions(
            "coffee", country="us", limit=5
        )

        self.assertEqual(filters["country_codes"], ["US"])
        self.assertEqual(suggestions["scenario"], 2)
        self.assertEqual(suggestions["suggestions"], ["coffee recipe", "coffee maker"])
        self.assertEqual(calls[0][0], "/creative_radar_api/v1/top_ads/v2/filters")
        self.assertEqual(calls[0][1], [])
        self.assertEqual(
            dict(calls[1][1]),
            {"query": "coffee", "count": "5", "scenario": "2", "countryCode": "US"},
        )
        self.assertTrue(calls[0][2].endswith("/inspiration/topads/pc/en"))

    def test_search_builds_v2_filters_and_normalizes_materials(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "materials": [material()],
                "pagination": {
                    "page": 1,
                    "size": 20,
                    "hasMore": True,
                    "totalCount": 21,
                },
            }

        result = TikTokClient(
            creative_fetch=fetch,
            request_interval=0,
        ).get_creative_top_ads(
            "summer sale",
            countries=["us", "GB"],
            industry_label_ids="14103000000",
            objectives="3",
            ad_format="spark",
            duration="0-15",
            like_range="100-1000",
            pattern_label_ids="10100100000",
            languages=["en"],
            order="ctr",
        )

        self.assertEqual(result["available"], 1)
        self.assertEqual(result["next_page"], 2)
        self.assertEqual(result["ads"][0]["metrics"]["ctr"], 0.72)
        self.assertEqual(result["ads"][0]["video"]["media_quality"], "1080P")
        self.assertEqual(result["source_country"], "US")
        self.assertEqual(
            result["ads"][0]["creative_center_url"],
            "https://ads.tiktok.com/business/creativecenter/topads/"
            "7656166869774109983/pc/en?countryCode=US&period=30",
        )
        self.assertNotIn("GB", result["ads"][0]["creative_center_url"])
        self.assertEqual(
            dict(calls[0][1]),
            {
                "period": "30",
                "orderBy": "ctr",
                "countryCode": "US,GB",
                "page": "1",
                "limit": "20",
                "industry": "14103000000",
                "keyword": "summer sale",
                "objective": "3",
                "duration": "0-15",
                "like": "100-1000",
                "patternLabel": "10100100000",
                "adFormat": "spark",
                "adLanguage": "en",
            },
        )

    def test_performance_search_uses_library_contract_and_normalizes_metrics(
        self,
    ) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {
                "itemList": [performance_material()],
                "pagination": {
                    "page": "2",
                    "size": "20",
                    "total": "42",
                    "totalCount": 42,
                    "hasMore": True,
                },
            }

        result = TikTokClient(
            creative_fetch=fetch,
            request_interval=0,
        ).get_creative_top_ads_performance(
            "teacher sign",
            countries=["us", "GB"],
            time_range=180,
            industry_label_ids="14103000000",
            objectives="3,14",
            ad_format=99,
            like_count_filter=5,
            order="engagement",
            page=2,
        )

        self.assertEqual(result["endpoint"], "/CreativeOne/TopAds/SearchMaterial")
        self.assertEqual(result["source_module"], 2)
        self.assertEqual(result["country_codes"], ["US", "GB"])
        self.assertEqual(result["order"], "engagement_rate")
        self.assertEqual(result["order_field"], 3)
        self.assertEqual(result["total_count"], 42)
        self.assertEqual(result["next_page"], 3)
        self.assertEqual(
            result["source_url"],
            "https://ads.tiktok.com/creative/inspiration/top-ads/library",
        )
        self.assertEqual(
            result["ads"][0]["metrics"],
            {
                "video_views": 9_123_456,
                "click_rate": 2.75,
                "ctr_rank": 97.5,
                "engagement_rate": 8.25,
                "six_second_view_rank": 91.2,
            },
        )
        self.assertEqual(
            result["ads"][0]["selling_points"],
            ["Clear product demo", "Before and after"],
        )
        self.assertEqual(
            result["ads"][0]["video"]["preferred_cover"],
            "https://example.test/cover.avif",
        )
        self.assertEqual(
            result["ads"][0]["source_url"],
            result["source_url"],
        )
        self.assertEqual(calls[0][0], "/CreativeOne/TopAds/SearchMaterial")
        self.assertEqual(
            calls[0][1],
            [
                ("timeRange", "180"),
                ("orderField", "3"),
                ("page", "2"),
                ("limit", "20"),
                ("sourceModule", "2"),
                ("countryCodeList", "US,GB"),
                ("industryLabelList", "14103000000"),
                ("searchWord", "teacher sign"),
                ("objectiveList", "3,14"),
                ("adFormat", "99"),
                ("likeCntFilter", "5"),
            ],
        )
        self.assertEqual(
            calls[0][2],
            "https://ads.tiktok.com/creative/inspiration/top-ads/library",
        )

    def test_performance_search_rejects_invalid_input_and_payload(self) -> None:
        calls: list[object] = []
        client = TikTokClient(
            creative_fetch=lambda *args: calls.append(args) or {},
            request_interval=0,
        )
        for arguments in (
            {"countries": ["USA"]},
            {"industry_label_ids": "0"},
            {"objectives": "7"},
            {"ad_format": 5},
            {"like_count_filter": 6},
            {"order": "like"},
            {"page": 0},
            {"limit": 21},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(TikTokInputError):
                client.get_creative_top_ads_performance(**arguments)
        self.assertEqual(calls, [])

        malformed = performance_material()
        malformed["videoView"] = True
        with self.assertRaises(TikTokResponseError):
            TikTokClient(
                creative_fetch=lambda *_args: {
                    "itemList": [malformed],
                    "pagination": {
                        "page": 1,
                        "size": 20,
                        "total": 1,
                        "hasMore": False,
                    },
                },
                request_interval=0,
            ).get_creative_top_ads_performance()

    def test_cli_dispatches_top_ads_performance(self) -> None:
        args = cli._parser().parse_args(
            [
                "creative-top-ads-performance",
                "teacher sign",
                "--country",
                "US",
                "--country",
                "GB",
                "--time-range",
                "180",
                "--industry-label-ids",
                "14103000000",
                "--objectives",
                "3,14",
                "--ad-format",
                "99",
                "--like-count-filter",
                "5",
                "--order",
                "engagement",
                "--page",
                "2",
                "--limit",
                "12",
            ]
        )
        with (
            patch.object(cli, "TikTokClient") as client_type,
            patch.object(cli, "_creative_fetch", return_value=object()),
        ):
            method = client_type.return_value.get_creative_top_ads_performance
            method.return_value = {"ok": True}
            self.assertEqual(cli._run(args), {"ok": True})
            method.assert_called_once_with(
                "teacher sign",
                countries=["US", "GB"],
                time_range=180,
                industry_label_ids="14103000000",
                objectives="3,14",
                ad_format=99,
                like_count_filter=5,
                order="engagement",
                page=2,
                limit=12,
            )
            self.assertEqual(
                client_type.call_args.kwargs["creative_fetch"],
                cli._creative_fetch.return_value,
            )

    def test_detail_combines_curves_percentile_recommendations_and_analysis(
        self,
    ) -> None:
        calls: list[str] = []

        def fetch(path, entries, _referer):
            calls.append(path)
            if path.endswith("/v2/detail"):
                return {
                    **material(),
                    "countryCode": ["GB"],
                    "landingPage": "https://example.test/product",
                }
            if path.endswith("/keyframe"):
                return {
                    "duration": 16,
                    "analysis": [{"second": 0, "value": "0.5"}],
                    "highlight": [1, 6, 9],
                }
            if path.endswith("/percentile"):
                return {"ctrPercentile": 0.99}
            if path.endswith("/v2/recommend"):
                return {"materials": [material("7656166869774109984")]}
            if path.endswith("/v2/detail_analysis"):
                return {"summary": "首秒产品结果清晰"}
            raise AssertionError((path, entries))

        result = TikTokClient(
            creative_fetch=fetch,
            request_interval=0,
        ).get_creative_top_ads_detail(
            "7656166869774109983",
            country="gb",
            time_range=7,
            metrics=("retain_ctr", "play_retain_cnt"),
        )

        self.assertEqual(result["ctr_percentile"], 0.99)
        self.assertEqual(
            sorted(result["keyframes"]), ["play_retain_cnt", "retain_ctr"]
        )
        self.assertEqual(len(result["recommendations"]), 1)
        self.assertTrue(result["ai_analysis"]["available"])
        self.assertEqual(calls.count("/creative_radar_api/v1/top_ads/keyframe"), 2)
        self.assertEqual(
            result["ad"]["creative_center_url"],
            "https://ads.tiktok.com/business/creativecenter/topads/"
            "7656166869774109983/pc/en?countryCode=GB&period=7",
        )
        self.assertEqual(result["ad"]["source_key"], 1)
        self.assertEqual(
            result["recommendations"][0]["creative_center_url"],
            "https://ads.tiktok.com/business/creativecenter/topads/"
            "7656166869774109984/pc/en?countryCode=GB&period=7",
        )

    def test_top_ads_rejects_invalid_filter_values_before_fetch(self) -> None:
        calls: list[object] = []
        client = TikTokClient(
            creative_fetch=lambda *args: calls.append(args) or {},
            request_interval=0,
        )
        cases = (
            {"countries": ["USA"]},
            {"industry_label_ids": "0"},
            {"objectives": "7"},
            {"ad_format": "unknown"},
            {"duration": "1-2"},
            {"like_range": "100"},
            {"page": 0},
            {"limit": 21},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(
                TikTokInputError
            ):
                client.get_creative_top_ads(**arguments)
        self.assertEqual(calls, [])

    def test_commercial_fetch_routes_each_path_to_its_browser_scope(self) -> None:
        call_daemon = AsyncMock(return_value={"payload": {}})
        with (
            patch.object(cli, "start_daemon") as start_daemon,
            patch.object(cli, "call_daemon", call_daemon),
        ):
            fetch = cli._creative_fetch("tiktok_creative_topads", 0)
            fetch(
                "/api/v4/i18n/search_ads/search_keyword/mget_keyword_ideas/",
                [],
                "https://ads.tiktok.com/",
            )
            fetch(
                "/creative_radar_api/v1/top_ads/v2/list",
                [],
                "https://ads.tiktok.com/",
            )
            fetch(
                "/CreativeOne/MatchMaking/QueryPartnerCreatorSquare",
                [],
                "https://ads.tiktok.com/",
            )
            fetch(
                "/creative_bff_i18n/api/cue/t2v/create_generate_task",
                [],
                "https://ads.tiktok.com/",
            )

        start_daemon.assert_called_once_with()
        self.assertEqual(
            [
                call.args[0]["platform"]
                for call in call_daemon.await_args_list
            ],
            [
                "tiktok_ads_manager",
                "tiktok_creative_topads",
                "tiktok_one",
                "tiktok_creative_studio",
            ],
        )

    def test_commercial_progress_names_operations_and_reuses_session_message(
        self,
    ) -> None:
        progress_events: list[dict[str, object]] = []

        async def call_daemon(request, *, progress):
            platform = request["platform"]
            for event in (
                {
                    "stage": "session",
                    "platform": platform,
                    "message": "正在探测 TikTok Creative Studio 登录态",
                },
                {
                    "stage": "session",
                    "platform": platform,
                    "message": "TikTok Creative Studio 会话可用，复用现有页面",
                    "ready": True,
                },
                {
                    "stage": "request",
                    "platform": platform,
                    "message": "正在读取 TikTok Creative Studio 数据",
                },
                {
                    "stage": "complete",
                    "platform": platform,
                    "message": "TikTok Creative Studio 数据读取完成",
                },
            ):
                progress(event)
            return {"payload": {}}

        with (
            patch.object(cli, "start_daemon"),
            patch.object(cli, "call_daemon", side_effect=call_daemon),
            patch.object(
                cli,
                "stderr_progress",
                return_value=progress_events.append,
            ),
        ):
            fetch = cli._creative_fetch("tiktok_creative_studio", 0)
            fetch(
                "/CreativeOne/SymphonyPlatform/QueryCreditAccount",
                [],
                "https://ads.tiktok.com/",
            )
            fetch(
                "/creative_bff_i18n/api/cue/get_generate_max_count",
                [],
                "https://ads.tiktok.com/",
            )

        self.assertEqual(
            [
                event["stage"]
                for event in progress_events
                if event["stage"] == "session"
            ],
            ["session", "session"],
        )
        request_messages = [
            str(event["message"])
            for event in progress_events
            if event["stage"] == "request"
        ]
        self.assertIn("积分余额", request_messages[0])
        self.assertIn("并发上限", request_messages[1])

    def test_interactive_fetch_logs_in_once_then_replays_original_request(self) -> None:
        call_daemon = AsyncMock(
            side_effect=[
                BrowserSessionError("tab_unavailable"),
                {"payload": {"items": []}},
            ]
        )
        with (
            patch.object(cli, "start_daemon") as start_daemon,
            patch.object(cli, "call_daemon", call_daemon),
            patch.object(
                cli,
                "authorize_browser_session",
                return_value={"ready": True},
            ) as authorize,
        ):
            fetch = cli._creative_fetch(
                "tiktok_one",
                0,
                interactive_login=True,
            )
            result = fetch(
                "/CreativeOne/MatchMaking/QueryPartnerSearchSuggestWords",
                [("keyword", "coffee")],
                "https://ads.tiktok.com/creative/forpartners/creator/explore?region=row",
            )

        self.assertEqual(result, {"payload": {"items": []}})
        start_daemon.assert_called_once_with()
        self.assertEqual(call_daemon.await_count, 2)
        authorize.assert_called_once_with(
            "tiktok_one",
            url=(
                "https://ads.tiktok.com/creative/forpartners/creator/explore"
                "?region=row"
            ),
            timeout=300,
            open_browser=True,
            progress=ANY,
        )

    def test_interactive_fetch_waits_for_verification_then_replays(self) -> None:
        call_daemon = AsyncMock(
            side_effect=[
                BrowserSessionError("verification_required"),
                {"payload": {"items": []}},
            ]
        )
        with (
            patch.object(cli, "start_daemon"),
            patch.object(cli, "call_daemon", call_daemon),
            patch.object(
                cli,
                "authorize_browser_session",
                return_value={"ready": True},
            ) as authorize,
        ):
            fetch = cli._creative_fetch(
                "tiktok_creative",
                0,
                interactive_login=True,
            )
            result = fetch(
                "/api/v1/hashtag/trend/list",
                [],
                "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag",
            )

        self.assertEqual(result, {"payload": {"items": []}})
        self.assertEqual(call_daemon.await_count, 2)
        authorize.assert_called_once_with(
            "tiktok_creative",
            url=(
                "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag"
            ),
            timeout=300,
            open_browser=False,
            progress=ANY,
        )

    def test_ads_manager_runtime_context_is_not_reported_as_login_failure(
        self,
    ) -> None:
        with (
            patch.object(cli, "start_daemon"),
            patch.object(
                cli,
                "call_daemon",
                new=AsyncMock(
                    side_effect=BrowserSessionError("runtime_unavailable")
                ),
            ),
            patch.object(
                cli,
                "authorize_browser_session",
                side_effect=BrowserSessionError(
                    "runtime_unavailable",
                    "当前广告账户页面不是 Keyword Planner 请求上下文",
                ),
            ) as authorize,
        ):
            fetch = cli._creative_fetch(
                "tiktok_ads_manager",
                0,
                interactive_login=True,
            )
            with self.assertRaisesRegex(
                TikTokResponseError,
                "Keyword Planner 请求上下文不可用",
            ):
                fetch(
                    "/api/v4/i18n/search_ads/search_keyword/"
                    "mget_keyword_ideas/",
                    [],
                    "https://ads.tiktok.com/",
                )
        authorize.assert_called_once_with(
            "tiktok_ads_manager",
            url="https://ads.tiktok.com/",
            timeout=300,
            open_browser=True,
            progress=ANY,
        )

    def test_noninteractive_fetch_keeps_session_errors_immediate(self) -> None:
        with (
            patch.object(cli, "start_daemon"),
            patch.object(
                cli,
                "call_daemon",
                new_callable=AsyncMock,
                side_effect=BrowserSessionError("tab_unavailable"),
            ),
            patch.object(cli, "authorize_browser_session") as authorize,
        ):
            fetch = cli._creative_fetch(
                "tiktok_creative_topads",
                0,
                interactive_login=False,
            )
            with self.assertRaises(TikTokResponseError):
                fetch(
                    "/creative_radar_api/v1/top_ads/v2/list",
                    [],
                    "https://ads.tiktok.com/business/creativecenter/"
                    "inspiration/topads/pc/en",
                )
        authorize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
