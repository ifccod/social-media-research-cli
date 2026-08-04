from __future__ import annotations

import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from curl_cffi import requests

from reverse.linkedin_reverse.ad_library import normalize_ad_search_params
from reverse.linkedin_reverse.cli import _parser, _run
from reverse.linkedin_reverse.client import LinkedInClient
from reverse.linkedin_reverse.errors import LinkedInInputError, LinkedInResponseError


FIXTURES = Path(__file__).with_name("fixtures")
SEARCH_HTML = (FIXTURES / "ad_search.html").read_text(encoding="utf-8")
SEARCH_PAGE_2_HTML = (FIXTURES / "ad_search_page2.html").read_text(encoding="utf-8")
DETAIL_HTML = (FIXTURES / "ad_detail.html").read_text(encoding="utf-8")
AD_ID = "1452369113"


def response(source: str, *, status: int = 200, url: str = "") -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers = requests.Headers()
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


class LinkedInAdLibraryTest(unittest.TestCase):
    def test_search_fixture_cards_and_pagination_are_normalized(self) -> None:
        result = LinkedInClient.parse_ads_html(SEARCH_HTML)

        self.assertEqual(result["source"], "ssr_html")
        self.assertEqual(result["total"], 2_345)
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            result["pagination"],
            {"token": "1452369222-1784563519937", "is_last_page": False},
        )
        first = result["items"][0]
        self.assertEqual((first["kind"], first["source"]), ("ad", "ssr_html"))
        self.assertEqual(first["ad_id"], AD_ID)
        self.assertEqual(first["creative_type"], "SPONSORED_STATUS_UPDATE")
        self.assertEqual(first["advertiser"]["name"], "Fixture Cloud")
        self.assertEqual(first["logo"], "https://media.licdn.com/fixture/cloud-logo.png")
        self.assertEqual(first["commentary"], "Build with fixture AI today.")
        self.assertEqual(first["headline"], "Ship the fixture faster")
        self.assertEqual(first["landing_url"], "")
        self.assertEqual(first["media"][0]["type"], "image")

    def test_content_image_external_link_is_landing_url_fallback(self) -> None:
        source = """<html><body><ul><li class="search-result-item">
        <div class="ad-preview" data-creative-type="SPONSORED_STATUS_UPDATE">
          <a data-tracking-control-name="ad_library_ad_preview_content_image"
             href="https://fixture.example/content?from=image#preview">
            <img class="ad-preview__dynamic-dimensions-image"
                 data-delayed-url="https://media.example/content.png">
          </a>
          <a data-tracking-control-name="ad_library_view_ad_detail"
             href="/ad-library/detail/1452369444">View details</a>
        </div></li></ul></body></html>"""

        result = LinkedInClient.parse_ads_html(source)

        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["items"][0]["landing_url"],
            "https://fixture.example/content?from=image",
        )

    def test_detail_fixture_covers_about_impressions_and_targeting(self) -> None:
        result = LinkedInClient.parse_ad_html(DETAIL_HTML, expected_id=AD_ID)

        self.assertEqual((result["kind"], result["source"]), ("ad", "ssr_html"))
        self.assertEqual(result["ad_id"], AD_ID)
        self.assertEqual(result["advertiser"]["id"], "13004429")
        self.assertEqual(
            result["landing_url"],
            "https://fixture.example/landing?utm_source=linkedin&item=one",
        )
        self.assertEqual(result["cta"], "Learn more")
        self.assertEqual(result["about"]["ad_format"], "Single Image Ad")
        self.assertEqual(result["about"]["payer"], "Fixture Cloud, LLC")
        self.assertEqual(result["about"]["run_from"], "Jul 17, 2026")
        self.assertEqual(result["about"]["run_to"], "Jul 22, 2026")
        self.assertEqual(result["impressions"]["total_range"], "10k-20k")
        self.assertEqual(
            result["impressions"]["countries"][0],
            {"country": "France", "share_text": "72%", "share_percent": 72},
        )
        self.assertIsNone(result["impressions"]["countries"][1]["share_percent"])
        self.assertEqual(result["targeting"]["included"][0]["values"], ["English"])
        self.assertEqual(
            result["targeting"]["excluded"][0]["values"],
            ["France", "Belgium", "Germany"],
        )
        self.assertEqual(
            result["targeting"]["facets"],
            [
                {"category": "Company", "included": True, "excluded": False},
                {"category": "Job", "included": True, "excluded": True},
            ],
        )

    def test_search_params_map_public_form_names_and_normalize_values(self) -> None:
        params, query = normalize_ad_search_params(
            keyword=" fixture ",
            advertiser_name="Fixture Cloud",
            countries=["fr,de", "US", "fr"],
            sort_order="oldest",
            payer="Fixture Payer",
            startdate="2026-06-01",
            enddate="2026-06-30",
            impressions_min="1.5k",
            impressions_max="2m",
            included_facets=["job,company"],
            excluded_facets="interests-and-traits",
            pagination_token="TOKEN-1",
        )

        values: dict[str, list[str]] = {}
        for key, value in params:
            values.setdefault(key, []).append(value)
        self.assertEqual(values["accountOwner"], ["Fixture Cloud"])
        self.assertEqual(values["countries"], ["FR", "DE", "US"])
        self.assertEqual(values["dateOption"], ["custom-date-range"])
        self.assertEqual(values["sortOrder"], ["ASCENDING"])
        self.assertEqual(values["impressionsMinValue"], ["1.5"])
        self.assertEqual(values["impressionsMinUnit"], ["thousand"])
        self.assertEqual(values["impressionsMaxUnit"], ["million"])
        self.assertEqual(values["includedTargetingFacetCategories"], ["JOB,COMPANY"])
        self.assertEqual(
            values["excludedTargetingFacetCategories"], ["INTERESTS_AND_TRAITS"]
        )
        self.assertEqual(query["pagination_token"], "TOKEN-1")
        self.assertEqual(query["sort_order"], "oldest")

    def test_keyword_that_mentions_linkedin_host_remains_plain_text(self) -> None:
        keyword = "news.linkedin.com/update"
        params, query = normalize_ad_search_params(keyword=keyword)

        self.assertIn(("keyword", keyword), params)
        self.assertEqual(query["keyword"], keyword)

    def test_search_uses_token_fragments_and_deduplicates_ads(self) -> None:
        session = FakeSession([response(SEARCH_HTML), response(SEARCH_PAGE_2_HTML)])
        client = LinkedInClient(session=session, retries=0)

        result = client.search_ads(
            keyword="fixture",
            countries=["fr,de", "US"],
            impressions_min="1k",
            impressions_max="2m",
            included_facets="job,company",
            limit=3,
        )

        self.assertEqual([item["ad_id"] for item in result["items"]], [
            "1452369113",
            "1452369222",
            "1452369333",
        ])
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["total"], 2_345)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertTrue(result["pagination"]["is_last_page"])
        first = urlsplit(session.calls[0][0])
        second = urlsplit(session.calls[1][0])
        self.assertEqual(first.path, "/ad-library/search")
        self.assertEqual(second.path, "/ad-library/searchPaginationFragment")
        self.assertEqual(parse_qs(first.query)["countries"], ["FR", "DE", "US"])
        self.assertEqual(
            parse_qs(second.query)["paginationToken"],
            ["1452369222-1784563519937"],
        )

    def test_explicit_pagination_token_starts_at_fragment(self) -> None:
        session = FakeSession([response(SEARCH_PAGE_2_HTML)])
        client = LinkedInClient(session=session, retries=0)

        result = client.search_ads(
            advertiser_name="Fixture",
            pagination_token="START-TOKEN",
            limit=1,
        )

        request = urlsplit(session.calls[0][0])
        self.assertEqual(request.path, "/ad-library/searchPaginationFragment")
        self.assertEqual(parse_qs(request.query)["paginationToken"], ["START-TOKEN"])
        self.assertEqual(result["count"], 1)

    def test_repeated_pagination_token_stops_without_an_extra_request(self) -> None:
        session = FakeSession([response(SEARCH_HTML), response(SEARCH_HTML)])
        client = LinkedInClient(session=session, retries=0)

        result = client.search_ads(keyword="fixture", limit=10)

        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(session.calls), 2)

    def test_missing_pagination_boolean_remains_unknown(self) -> None:
        source = SEARCH_HTML.replace(
            '{"isLastPage":false,"paginationToken":"1452369222-1784563519937"}',
            '{"paginationToken":"TOKEN-ONLY"}',
        )
        result = LinkedInClient.parse_ads_html(source)
        self.assertEqual(
            result["pagination"],
            {"token": "TOKEN-ONLY", "is_last_page": None},
        )

    def test_ad_reference_and_request_contract(self) -> None:
        detail_url = f"https://www.linkedin.com/ad-library/detail/{AD_ID}"
        self.assertEqual(LinkedInClient.parse_ad_reference(AD_ID)["url"], detail_url)
        self.assertEqual(
            LinkedInClient.parse_ad_reference(f"https://fr.linkedin.com/ad-library/detail/{AD_ID}")[
                "ad_id"
            ],
            AD_ID,
        )

        session = FakeSession([response(DETAIL_HTML)])
        result = LinkedInClient(session=session, retries=0).get_ad(AD_ID)
        self.assertEqual(result["requested_url"], detail_url)
        self.assertEqual(session.calls[0][0], detail_url)

    def test_invalid_search_and_detail_inputs_fail_cleanly(self) -> None:
        invalid_searches = [
            {},
            {"keyword": "x", "countries": "France"},
            {"keyword": "x", "date_option": "forever"},
            {"keyword": "x", "sort_order": "random"},
            {"keyword": "x", "startdate": "2026-01-01"},
            {
                "keyword": "x",
                "startdate": "2026-02-01",
                "enddate": "2026-01-01",
            },
            {"keyword": "x", "impressions_min": "many"},
            {"keyword": "x", "impressions_min": "2m", "impressions_max": "1m"},
            {"keyword": "x", "included_facets": "unknown"},
        ]
        for kwargs in invalid_searches:
            with self.subTest(kwargs=kwargs), self.assertRaises(LinkedInInputError):
                LinkedInClient(session=FakeSession([])).search_ads(**kwargs)

        for value in (
            "123",
            "0001452369113",
            "https://example.com/ad-library/detail/1452369113",
            "https://www.linkedin.com/jobs/view/1452369113",
        ):
            with self.subTest(value=value), self.assertRaises(LinkedInInputError):
                LinkedInClient.parse_ad_reference(value)

        with self.assertRaisesRegex(LinkedInResponseError, "did not match expected"):
            LinkedInClient.parse_ad_html(DETAIL_HTML, expected_id="1452369999")

        foreign_canonical = DETAIL_HTML.replace(
            'href="/ad-library/detail/1452369113"',
            'href="https://example.com/ad-library/detail/1452369113"',
            1,
        )
        with self.assertRaisesRegex(LinkedInResponseError, "left LinkedIn"):
            LinkedInClient.parse_ad_html(foreign_canonical, expected_id=AD_ID)

        for limit in (0, 101, True):
            with self.subTest(limit=limit), self.assertRaises(LinkedInInputError):
                LinkedInClient(session=FakeSession([])).search_ads(
                    keyword="fixture", limit=limit
                )

    def test_ads_cli_forwards_all_search_filters(self) -> None:
        args = _parser().parse_args(
            [
                "ads",
                "fixture",
                "--advertiser-name",
                "Fixture Cloud",
                "--country",
                "FR,DE",
                "--country",
                "US",
                "--date-option",
                "custom-date-range",
                "--sort-order",
                "oldest",
                "--payer",
                "Fixture Payer",
                "--start-date",
                "2026-06-01",
                "--enddate",
                "2026-06-30",
                "--impressions-min",
                "1k",
                "--impressions-max",
                "2m",
                "--include-facets",
                "job,company",
                "--exclude-facets",
                "language",
                "--pagination-token",
                "TOKEN-1",
                "--limit",
                "30",
            ]
        )
        with patch("reverse.linkedin_reverse.cli.LinkedInClient") as client_type:
            client_type.return_value.search_ads.return_value = {"items": []}
            result = _run(args)

        self.assertEqual(result, {"items": []})
        client_type.return_value.search_ads.assert_called_once_with(
            keyword="fixture",
            advertiser_name="Fixture Cloud",
            countries=["FR,DE", "US"],
            date_option="custom-date-range",
            sort_order="oldest",
            payer="Fixture Payer",
            startdate="2026-06-01",
            enddate="2026-06-30",
            impressions_min="1k",
            impressions_max="2m",
            included_facets="job,company",
            excluded_facets="language",
            pagination_token="TOKEN-1",
            limit=30,
        )


if __name__ == "__main__":
    unittest.main()
