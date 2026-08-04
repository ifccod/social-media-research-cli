from __future__ import annotations

from email.message import Message
import json
from urllib.parse import parse_qs, urlsplit
import unittest

from reverse.microsoft_ads_reverse.client import ADS_PATH, ADVERTISERS_PATH, BASE_URL, MicrosoftAdsClient
from reverse.microsoft_ads_reverse.errors import MicrosoftAdsInputError, MicrosoftAdsResponseError


ADVERTISERS = {
    "@odata.count": 2,
    "value": [
        {
            "AdvertiserId": 4295001036,
            "AdvertiserName": "Fixture Europe B.V.",
            "AdvertiserCountry": "Netherlands",
            "IsVerified": True,
        },
        {
            "AdvertiserId": 4295001037,
            "AdvertiserName": "Fixture Gifts GmbH",
            "AdvertiserCountry": "Germany",
            "IsVerified": True,
        },
    ],
}

ADS_PAGE_1 = {
    "@odata.count": 3,
    "value": [
        {
            "AdId": 80195840328528,
            "AdvertiserName": "Fixture Europe B.V.",
            "AdvertiserId": 4295001036,
            "Title": "Personal Gifts for Teachers",
            "Description": "Create a personalised gift with photo and text.",
            "DisplayUrl": "fixture.example/teacher",
            "DestinationUrl": "https://fixture.example/teacher",
            "AssetJson": "",
        },
        {
            "AdId": 80195840328529,
            "AdvertiserName": "Fixture Europe B.V.",
            "AdvertiserId": 4295001036,
            "Title": "Teacher Door Sign",
            "Description": "A custom classroom sign.",
            "DisplayUrl": "fixture.example/sign",
            "DestinationUrl": "https://fixture.example/sign",
            "AssetJson": "https://assets.example/fixture.json",
        },
    ],
}

ADS_PAGE_2 = {
    "@odata.count": 3,
    "value": [
        {
            "AdId": 80195840328530,
            "AdvertiserName": "Fixture Gifts GmbH",
            "AdvertiserId": 4295001037,
            "Title": "Unique Teacher Gift",
            "Description": "Made for the classroom.",
            "DisplayUrl": "fixture.example/gift",
            "DestinationUrl": "https://fixture.example/gift",
            "AssetJson": "",
        }
    ],
}

AD_DETAIL = {
    **ADS_PAGE_1["value"][0],
    "AdDetails": {
        "PaidForByName": "Fixture Holding B.V.",
        "StartDate": "2026-02-27",
        "EndDate": "2026-07-14",
        "TotalImpressionsRange": "1K - 5K",
        "RejectionJson": None,
        "ImpressionsByCountry": [
            {"Country": "Ireland", "ImpressionShare": "99.9%"},
            {"Country": "Portugal", "ImpressionShare": "0.1%"},
        ],
        "Targets": [
            {"TargetType": "Location", "UsedForExclusion": True},
            {"TargetType": "MicrosoftAudiences", "UsedForExclusion": False},
        ],
    },
}


class FakeResponse:
    def __init__(self, payload: dict, *, url: str) -> None:
        self.status = 200
        self._source = json.dumps(payload).encode("utf-8")
        self._offset = 0
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.headers["Content-Length"] = str(len(self._source))

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._source) - self._offset
        chunk = self._source[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None

    def geturl(self) -> str:
        return self._url


class FakeOpener:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if not self.payloads:
            raise AssertionError("没有剩余的固定响应")
        return FakeResponse(self.payloads.pop(0), url=request.full_url)


class MicrosoftAdsClientTest(unittest.TestCase):
    def test_search_advertisers_uses_official_anonymous_api(self) -> None:
        opener = FakeOpener([ADVERTISERS])
        client = MicrosoftAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        result = client.search_advertisers("Fixture", limit=2, page_size=2)

        self.assertEqual(result["access"], "anonymous_official_api")
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["items"][0]["advertiser_id"], "4295001036")
        query = parse_qs(urlsplit(opener.calls[0][0].full_url).query)
        self.assertEqual(query["searchText"], ["Fixture"])
        self.assertEqual(query["$top"], ["2"])
        self.assertEqual(query["$skip"], ["0"])

    def test_search_ads_paginates_and_preserves_copy(self) -> None:
        opener = FakeOpener([ADS_PAGE_1, ADS_PAGE_2])
        client = MicrosoftAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        result = client.search_ads(
            "teacher gift",
            start_date="2026-06-01",
            end_date="2026-08-01",
            country_codes=["10", "26"],
            limit=3,
            page_size=2,
        )

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["source_count"], 3)
        self.assertEqual(result["items"][1]["copy"]["title"], "Teacher Door Sign")
        self.assertEqual(
            result["items"][1]["asset_resource_url"],
            "https://assets.example/fixture.json",
        )
        self.assertEqual(result["items"][2]["result_rank"], 3)
        self.assertEqual(result["pagination"]["pages_fetched"], 2)
        self.assertEqual(result["pagination"]["stop_reason"], "limit_reached")
        first_query = parse_qs(urlsplit(opener.calls[0][0].full_url).query)
        self.assertEqual(first_query["countryCodes"], ["10,26"])
        self.assertEqual(first_query["startDate"], ["2026-06-01"])
        second_query = parse_qs(urlsplit(opener.calls[1][0].full_url).query)
        self.assertEqual(second_query["$skip"], ["2"])

    def test_get_ad_returns_impression_bucket_country_share_and_targets(self) -> None:
        opener = FakeOpener([AD_DETAIL])
        client = MicrosoftAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        result = client.get_ad("80195840328528")

        details = result["item"]["details"]
        self.assertEqual(details["total_impressions_range"], "1K - 5K")
        self.assertEqual(
            details["impressions_by_country"][0],
            {"country": "Ireland", "impression_share": "99.9%"},
        )
        self.assertTrue(details["targets"][0]["used_for_exclusion"])
        self.assertEqual(
            result["metric_scope"]["impressions_by_country"],
            "published_percentage_share_not_count",
        )
        query = parse_qs(urlsplit(opener.calls[0][0].full_url).query)
        self.assertEqual(
            query["expand"],
            ["AdDetails(expand=ImpressionsByCountry,Targets)"],
        )

    def test_invalid_inputs_are_rejected_before_network(self) -> None:
        opener = FakeOpener([])
        client = MicrosoftAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        with self.assertRaises(MicrosoftAdsInputError):
            client.search_ads("", advertiser_id="")
        with self.assertRaises(MicrosoftAdsInputError):
            client.search_ads("teacher", start_date="2026-13-01")
        with self.assertRaises(MicrosoftAdsInputError):
            client.search_ads("teacher", country_codes=["US"])
        with self.assertRaises(MicrosoftAdsInputError):
            client.get_ad("not-an-id")
        self.assertEqual(opener.calls, [])

    def test_odata_error_payload_is_classified(self) -> None:
        opener = FakeOpener(
            [
                {
                    "error": {
                        "code": "",
                        "message": "The query specified in the URI is not valid.",
                    }
                }
            ]
        )
        client = MicrosoftAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        with self.assertRaises(MicrosoftAdsResponseError) as context:
            client.search_advertisers("Fixture")

        self.assertEqual(context.exception.code, "upstream_request_failed")
        self.assertIn("query specified", str(context.exception))


if __name__ == "__main__":
    unittest.main()
