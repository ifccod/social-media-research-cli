from __future__ import annotations

from email.message import Message
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs
import unittest

from reverse.facebook_ads_reverse.client import (
    DETAILS_DOC_ID,
    FacebookAdsClient,
    SEARCH_DOC_ID,
    TYPEAHEAD_DOC_ID,
)
from reverse.facebook_ads_reverse.errors import FacebookAdsInputError, FacebookAdsResponseError, FacebookAdsTransportError


TESTDATA = Path(__file__).with_name("testdata")
HOME = (TESTDATA / "homepage.html").read_text(encoding="utf-8")
SUGGEST = (TESTDATA / "suggest.json").read_text(encoding="utf-8")
SEARCH_PAGE_1 = (TESTDATA / "search_page_1.ndjson").read_text(encoding="utf-8")
SEARCH_PAGE_2 = (TESTDATA / "search_page_2.json").read_text(encoding="utf-8")

DETAILS = json.dumps(
    {
        "data": {
            "ad_library_main": {
                "ad_details": {
                    "advertiser": {
                        "page": {
                            "about": {"text": "Fixture advertiser"},
                            "id": "300000000000001",
                        },
                        "ad_library_page_info": {
                            "page_spend": {
                                "current_week": None,
                                "lifetime_by_disclaimer": [],
                                "weekly_by_disclaimer": [],
                                "is_political_page": False,
                            },
                            "page_info": {
                                "entity_type": "PERSON_PROFILE",
                                "likes": 42,
                                "page_id": "300000000000001",
                                "page_name": "Fixture Teacher Gifts",
                                "page_profile_uri": "https://www.facebook.com/fixture",
                                "page_verification": "NOT_VERIFIED",
                                "profile_photo": "https://lookaside.example/profile.jpg",
                                "page_is_deleted": False,
                                "page_is_restricted": False,
                            },
                        },
                    },
                    "aaa_info": {
                        "payer_beneficiary_data": [
                            {"payer": "Fixture", "beneficiary": "Fixture"}
                        ],
                        "targets_eu": True,
                        "has_violating_payer_beneficiary": False,
                        "is_ad_taken_down": False,
                    },
                    "violation_types": [],
                    "verified_voice_context": None,
                    "transparency_by_location": {
                        "br_transparency": None,
                        "eu_transparency": {
                            "targets_eu": True,
                            "location_audience": [
                                {
                                    "name": "Europe",
                                    "num_obfuscated": 0,
                                    "type": "country_groups",
                                    "excluded": False,
                                }
                            ],
                            "gender_audience": "All",
                            "age_audience": {"min": 18, "max": 65},
                            "eu_total_reach": 982,
                            "age_country_gender_reach_breakdown": [
                                {
                                    "country": "DE",
                                    "age_gender_breakdowns": [
                                        {
                                            "age_range": "25-34",
                                            "male": 10,
                                            "female": 5,
                                            "unknown": 1,
                                        }
                                    ],
                                }
                            ],
                        },
                        "uk_transparency": {
                            "location_audience": [],
                            "gender_audience": "All",
                            "age_audience": {"min": 18, "max": 65},
                            "total_reach": 76,
                            "age_country_gender_reach_breakdown": [
                                {
                                    "country": "GB",
                                    "age_gender_breakdowns": [
                                        {
                                            "age_range": "25-34",
                                            "male": 7,
                                            "female": 3,
                                            "unknown": None,
                                        }
                                    ],
                                }
                            ],
                        },
                    },
                    "is_siep_advertiser_eligible_for_ai_disclosure": True,
                    "is_violating_eu_siep": False,
                }
            }
        }
    }
)


def ssr(source: str, **variable_overrides) -> str:
    first_line = source.splitlines()[0]
    payload = json.loads(first_line.removeprefix("for (;;);"))
    variables = {
        "activeStatus": "active",
        "adType": "ALL",
        "bylines": [],
        "collationToken": None,
        "contentLanguages": [],
        "countries": ["US"],
        "country": "US",
        "isTargetedCountry": False,
        "location": None,
        "mediaType": "all",
        "multiCountryFilterMode": None,
        "pageIDs": [],
        "potentialReachInput": None,
        "publisherPlatforms": [],
        "queryString": "personalized teacher sign",
        "regions": None,
        "searchType": "keyword_exact_phrase",
        "sessionID": "fixture-search-session",
        "sortData": {"mode": "total_impressions", "direction": "desc"},
        "source": None,
        "startDate": None,
        "v": "fixturev",
        "viewAllPageID": "0",
    }
    variables.update(variable_overrides)
    preloader = {
        "queryName": "AdLibraryFoundationRootQuery",
        "queryID": "26438337149177216",
        "variables": variables,
    }
    script = json.dumps(
        {"preloaders": [preloader], "fixture_result": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return HOME.replace(
        "</body>",
        f'<script type="application/json" data-sjs>{script}</script></body>',
    )


class FakeResponse:
    def __init__(
        self,
        source: str | bytes,
        *,
        status: int = 200,
        url: str = "",
        content_type: str = "application/json; charset=utf-8",
        content_length: int | None = None,
    ) -> None:
        self.status = status
        self._source = source.encode("utf-8") if isinstance(source, str) else source
        self._offset = 0
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._source) - self._offset
        chunk = self._source[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        return None


class FakeOpener:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if not self.responses:
            raise AssertionError("没有剩余的固定响应")
        return self.responses.pop(0)


def response(source: str, *, status: int = 200, graphql: bool = False) -> FakeResponse:
    url = (
        "https://www.facebook.com/api/graphql/"
        if graphql
        else "https://www.facebook.com/"
    )
    return FakeResponse(source, status=status, url=url)


class FacebookAdsSessionTest(unittest.TestCase):
    def test_homepage_bootstrap_extracts_real_anonymous_fields(self) -> None:
        client = FacebookAdsClient(
            opener=FakeOpener([response(HOME)]),
            retries=0,
            request_interval=0,
        )

        status = client.initialize()

        self.assertTrue(status["ready"])
        self.assertEqual(status["access"], "anonymous")
        self.assertEqual(client._tokens["lsd"], "LSD_TEST_123")
        self.assertEqual(client._tokens["__rev"], "1033837939")
        self.assertEqual(client._tokens["__hsi"], "7123456789012345678")
        self.assertEqual(
            client._tokens["jazoest"],
            str(2 + sum(ord(char) for char in "LSD_TEST_123")),
        )

    def test_homepage_block_and_missing_token_have_distinct_codes(self) -> None:
        blocked = FacebookAdsClient(
            opener=FakeOpener([response("blocked", status=403)]),
            retries=0,
            request_interval=0,
        )
        with self.assertRaises(FacebookAdsTransportError) as blocked_error:
            blocked.initialize()
        self.assertEqual(blocked_error.exception.code, "network_reputation_blocked")

        missing = FacebookAdsClient(
            opener=FakeOpener([response("<html>no token</html>")]),
            retries=0,
            request_interval=0,
        )
        with self.assertRaises(FacebookAdsResponseError) as missing_error:
            missing.initialize()
        self.assertEqual(missing_error.exception.code, "session_bootstrap_failed")


class FacebookAdsMediaTest(unittest.TestCase):
    def test_download_media_writes_content_hash_and_metadata(self) -> None:
        payload = b"fixture-meta-video\x00\x01"
        media_url = "https://video-lax3-2.xx.fbcdn.net/o1/fixture.mp4?token=test"
        opener = FakeOpener(
            [
                FakeResponse(
                    payload,
                    url=media_url,
                    content_type="video/mp4",
                    content_length=len(payload),
                )
            ]
        )
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "reference.mp4"
            result = client.download_media(media_url, destination)

            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(result["kind"], "facebook_media_download")
            self.assertEqual(result["bytes"], len(payload))
            self.assertEqual(result["sha256"], sha256(payload).hexdigest())
            self.assertEqual(result["content_type"], "video/mp4")
            self.assertEqual(result["destination"], str(destination.resolve()))

    def test_download_media_rejects_untrusted_hosts_before_network(self) -> None:
        opener = FakeOpener([])
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        with TemporaryDirectory() as directory:
            with self.assertRaises(FacebookAdsInputError):
                client.download_media(
                    "https://example.com/video.mp4",
                    Path(directory) / "video.mp4",
                )

        self.assertEqual(opener.calls, [])

    def test_download_media_enforces_size_limit_without_partial_file(self) -> None:
        media_url = "https://scontent-lax3-1.xx.fbcdn.net/v/fixture.jpg"
        opener = FakeOpener(
            [
                FakeResponse(
                    b"oversized",
                    url=media_url,
                    content_type="image/jpeg",
                    content_length=9,
                )
            ]
        )
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "reference.jpg"
            with self.assertRaises(FacebookAdsResponseError) as raised:
                client.download_media(media_url, destination, max_bytes=8)
            self.assertEqual(raised.exception.code, "media_too_large")
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])


class FacebookAdsSuggestTest(unittest.TestCase):
    def test_page_suggest_uses_current_typeahead_document(self) -> None:
        opener = FakeOpener([response(HOME), response(SUGGEST, graphql=True)])
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        result = client.search_pages("teacher gifts", country="US", limit=1)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["page_id"], "100654373063470")
        self.assertEqual(result["items"][0]["like_count"], 125000)
        self.assertEqual(
            result["items"][0]["profile_picture_url"],
            "https://lookaside.example/page.jpg",
        )
        self.assertEqual(result["items"][0]["verification_status"], "VERIFIED")
        self.assertTrue(result["items"][0]["verified"])
        self.assertEqual(
            result["items"][0]["url"],
            "https://www.facebook.com/fixtureteachergifts",
        )
        self.assertEqual(result["items"][0]["instagram"]["follower_count"], 42000)
        self.assertFalse(result["items"][0]["page_is_deleted"])
        form = parse_qs(opener.calls[1][0].data.decode("utf-8"))
        self.assertEqual(form["doc_id"], [TYPEAHEAD_DOC_ID])
        variables = json.loads(form["variables"][0])
        self.assertEqual(variables["queryString"], "teacher gifts")
        self.assertEqual(variables["country"], "US")


class FacebookAdsDetailsTest(unittest.TestCase):
    def test_ad_details_returns_reach_targeting_and_payer_evidence(self) -> None:
        ad_id = "1175193775686253"
        page_id = "300000000000001"
        opener = FakeOpener(
            [
                response(
                    ssr(
                        SEARCH_PAGE_1,
                        deeplinkAdID=int(ad_id),
                        hasDeeplinkAdID=True,
                        sessionID="fixture-detail-session",
                        viewAllPageID=page_id,
                    )
                ),
                response(DETAILS, graphql=True),
            ]
        )
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        result = client.ad_details(ad_id, country="DE")

        self.assertEqual(result["kind"], "facebook_ad_details")
        self.assertEqual(result["page_id"], page_id)
        self.assertEqual(
            result["transparency"]["reach"]["eu"]["reported_total_reach"],
            982,
        )
        self.assertEqual(
            result["transparency"]["reach"]["uk"]["reported_total_reach"],
            76,
        )
        self.assertEqual(
            result["transparency"]["reach"]["eu"]["reach_by_country"]["DE"],
            16,
        )
        self.assertEqual(
            result["payer_beneficiary"],
            [{"payer": "Fixture", "beneficiary": "Fixture"}],
        )
        self.assertEqual(
            result["metric_scope"]["reported_total_reach"],
            "published_estimated_unique_accounts",
        )
        self.assertFalse(result["advertiser"]["page"]["verified"])
        self.assertNotIn("raw", result)

        form = parse_qs(opener.calls[1][0].data.decode("utf-8"))
        self.assertEqual(form["doc_id"], [DETAILS_DOC_ID])
        variables = json.loads(form["variables"][0])
        self.assertEqual(variables["adArchiveID"], ad_id)
        self.assertEqual(variables["pageID"], page_id)
        self.assertEqual(variables["country"], "DE")
        self.assertEqual(variables["sessionID"], "fixture-detail-session")
        self.assertTrue(variables["isAdNonPolitical"])
        self.assertFalse(variables["isAdNotAAAEligible"])

    def test_ad_details_rejects_invalid_id_before_network(self) -> None:
        opener = FakeOpener([])
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        with self.assertRaises(FacebookAdsInputError):
            client.ad_details("not-an-ad")

        self.assertEqual(opener.calls, [])


class FacebookAdsSearchTest(unittest.TestCase):
    def test_search_paginates_and_preserves_material_evidence(self) -> None:
        opener = FakeOpener(
            [
                response(ssr(SEARCH_PAGE_1)),
                response(SEARCH_PAGE_2, graphql=True),
            ]
        )
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        result = client.search_ads(
            "personalized teacher sign",
            countries=["US"],
            media_type="ALL",
            start_date="2026-07-01",
            limit=10,
        )

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["pagination"]["pages_fetched"], 2)
        self.assertEqual(result["pagination"]["stop_reason"], "source_exhausted")
        self.assertEqual(result["metric_scope"]["ad_likes"], "not_published")
        first = result["items"][0]
        self.assertEqual(
            first["source_url"],
            "https://www.facebook.com/ads/library/?id=1888158438694361",
        )
        self.assertEqual(
            first["creatives"][0]["landing_url"],
            "https://fixture.example/teacher-sign?utm_source=meta",
        )
        self.assertEqual(first["creatives"][0]["media"][0]["type"], "video")
        self.assertEqual(
            first["creatives"][0]["media"][0]["variants"]["hd"],
            "https://video.example/teacher-hd.mp4",
        )
        self.assertEqual(first["proxy_signals"]["same_page_ads_in_sample"], 2)
        self.assertGreater(first["proxy_signals"]["active_days"], 0)
        carousel = result["items"][1]
        self.assertEqual(len(carousel["creatives"]), 2)
        self.assertEqual(carousel["creatives"][1]["media"][0]["type"], "image")
        self.assertNotIn("raw", first)

        form = parse_qs(opener.calls[1][0].data.decode("utf-8"))
        self.assertEqual(form["doc_id"], [SEARCH_DOC_ID])
        variables = json.loads(form["variables"][0])
        self.assertEqual(
            variables["startDate"],
            {"min": "2026-07-01", "max": None},
        )
        self.assertEqual(variables["cursor"], "CURSOR_PAGE_2")
        self.assertEqual(variables["sessionID"], "fixture-search-session")

    def test_page_ads_uses_page_search_contract(self) -> None:
        opener = FakeOpener(
            [response(ssr(SEARCH_PAGE_1)), response(SEARCH_PAGE_2, graphql=True)]
        )
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        result = client.page_ads("300000000000001", limit=10)

        self.assertEqual(result["query"]["search_type"], "PAGE")
        self.assertEqual(result["query"]["page_ids"], ["300000000000001"])
        form = parse_qs(opener.calls[1][0].data.decode("utf-8"))
        variables = json.loads(form["variables"][0])
        self.assertEqual(variables["searchType"], "page")
        self.assertEqual(variables["pageIDs"], ["300000000000001"])

    def test_repeated_cursor_is_reported_without_losing_collected_ads(self) -> None:
        opener = FakeOpener(
            [response(ssr(SEARCH_PAGE_1)), response(SEARCH_PAGE_1, graphql=True)]
        )
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        result = client.search_ads("teacher sign", limit=10)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["pagination"]["stop_reason"], "pagination_abnormal")
        self.assertEqual(result["warnings"][0]["code"], "pagination_abnormal")

    def test_graphql_document_drift_has_a_stable_error_code(self) -> None:
        drift = json.dumps(
            {"errors": [{"message": "Unknown persisted document", "code": 1675012}]}
        )
        client = FacebookAdsClient(
            opener=FakeOpener([response(ssr(SEARCH_PAGE_1)), response(drift, graphql=True)]),
            retries=0,
            request_interval=0,
        )

        with self.assertRaises(FacebookAdsResponseError) as caught:
            client.search_ads("teacher sign", limit=10)
        self.assertEqual(caught.exception.code, "graphql_document_drift")

    def test_document_drift_discovers_bundle_id_and_retries_once(self) -> None:
        drift = json.dumps(
            {"errors": [{"message": "Unknown persisted document", "code": 1675012}]}
        )
        bundle_url = "https://static.xx.fbcdn.net/rsrc.php/v4/test/ad-library.js"
        html = ssr(SEARCH_PAGE_1).replace(
            "</body>", f'<script src="{bundle_url}"></script></body>'
        )
        new_doc_id = "29999999999999999"
        bundle = (
            '__d("AdLibrarySearchPaginationQuery_facebookRelayOperation",[],'
            f'(function(t,n,r,o,a,i){{a.exports="{new_doc_id}"}}),null);'
        )
        opener = FakeOpener(
            [
                response(html),
                response(drift, graphql=True),
                FakeResponse(bundle, url=bundle_url),
                response(SEARCH_PAGE_2, graphql=True),
            ]
        )
        client = FacebookAdsClient(opener=opener, retries=0, request_interval=0)

        result = client.search_ads("teacher sign", limit=10)

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["protocol"]["document_id"], new_doc_id)
        retry_form = parse_qs(opener.calls[3][0].data.decode("utf-8"))
        self.assertEqual(retry_form["doc_id"], [new_doc_id])

    def test_invalid_filters_fail_before_network(self) -> None:
        client = FacebookAdsClient(opener=FakeOpener([]), retries=0, request_interval=0)
        with self.assertRaises(FacebookAdsInputError):
            client.search_ads("teacher sign", countries=["United States"])
        with self.assertRaises(FacebookAdsInputError):
            client.search_ads("teacher sign", sort="time_active")
        with self.assertRaises(FacebookAdsInputError):
            client.page_ads("not-a-page")
        with self.assertRaises(FacebookAdsInputError):
            client.search_ads("", page_ids=[])


if __name__ == "__main__":
    unittest.main()
