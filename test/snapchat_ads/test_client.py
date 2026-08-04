from __future__ import annotations

from email.message import Message
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit
import unittest

from reverse.snapchat_ads_reverse.client import (
    ADS_SEARCH_PATH,
    AD_DETAIL_PATH,
    BASE_URL,
    SPONSORED_CONTENT_PATH,
    SPONSORED_SEARCH_PATH,
    SnapchatAdsClient,
)
from reverse.snapchat_ads_reverse.errors import SnapchatAdsInputError, SnapchatAdsResponseError


def _ad(
    ad_id: str,
    impressions: int,
    *,
    dynamic: bool = False,
) -> dict:
    result = {
        "id": ad_id,
        "name": f"fixture-{ad_id[:4]}",
        "ad_account_name": "Fixture Ads",
        "status": "ACTIVE",
        "creative_type": "WEB_VIEW",
        "ad_type": "REMOTE_WEBPAGE",
        "ad_render_type": "DYNAMIC" if dynamic else "STATIC",
        "languages": ["de"],
        "headline": "Jetzt ansehen",
        "call_to_action": "SHOP NOW",
        "top_snap_media_type": "VIDEO",
        "top_snap_media_download_link": (
            f"https://cf-st.sc-cdn.net/d/{ad_id}.mp4"
        ),
        "start_date": "2026-07-01T00:00:00.000Z",
        "impressions_total": impressions,
        "impressions_map": {"de": impressions, "fr": 0},
        "targeting_v2": {
            "regulated_content": False,
            "demographics": [{"min_age": "18", "languages": ["de"]}],
        },
        "paying_advertiser_name": "Fixture GmbH",
        "profile_name": "Fixture",
        "profile_logo_url": "https://cf-st.sc-cdn.net/d/profile.png",
        "web_view_properties": {"url": "https://fixture.example/product"},
        "review_status": "APPROVED",
        "rejection_reasons": [],
    }
    if dynamic:
        result["dpa_preview"] = {
            "items": [
                {
                    "title": "商品一",
                    "brand": "Fixture",
                    "link": "https://fixture.example/one",
                    "main_image": {
                        "image_links": ["https://cf-st.sc-cdn.net/d/one.jpg"]
                    },
                },
                {
                    "title": "商品二",
                    "brand": "Fixture",
                    "link": "https://fixture.example/two",
                    "main_image": {
                        "image_links": ["https://cf-st.sc-cdn.net/d/two.jpg"]
                    },
                },
                {
                    "title": "商品三",
                    "brand": "Fixture",
                    "link": "https://fixture.example/three",
                    "main_image": {
                        "image_links": ["https://cf-st.sc-cdn.net/d/three.jpg"]
                    },
                },
            ]
        }
    return result


AD_1 = "11111111-1111-4111-8111-111111111111"
AD_2 = "22222222-2222-4222-8222-222222222222"
AD_3 = "33333333-3333-4333-8333-333333333333"

SEARCH_PAGE_1 = {
    "request_status": "SUCCESS",
    "request_id": "request-page-1",
    "paging": {
        "next_link": (
            f"{BASE_URL}{ADS_SEARCH_PATH}?cursor=CURSOR_PAGE_2%3D"
        )
    },
    "ad_previews": [
        {"sub_request_status": "SUCCESS", "ad_preview": _ad(AD_1, 100)},
        {
            "sub_request_status": "SUCCESS",
            "ad_preview": _ad(AD_2, 900, dynamic=True),
        },
    ],
}
SEARCH_PAGE_2 = {
    "request_status": "SUCCESS",
    "request_id": "request-page-2",
    "paging": {},
    "ad_previews": [
        {"sub_request_status": "SUCCESS", "ad_preview": _ad(AD_3, 500)}
    ],
}
DETAIL = {
    "request_status": "SUCCESS",
    "request_id": "request-detail",
    "ad_preview": _ad(AD_2, 900, dynamic=True),
}
SPONSORED = {
    "request_status": "SUCCESS",
    "request_id": "request-sponsored",
    "paging": {},
    "ad_previews": [
        {
            "sub_request_status": "SUCCESS",
            "sponsored_content_preview": {
                "sponsor_name": "Fixture Sponsor",
                "sponsor_url": "https://www.snapchat.com/add/fixture-sponsor",
                "creator_name": "fixture-creator",
                "creator_url": "https://www.snapchat.com/add/fixture-creator",
                "content_type": "SPOTLIGHT",
                "content_url": "https://www.snapchat.com/spotlight/FIXTURE",
                "thumbnail_url": "https://bolt-gcdn.sc-cdn.net/z/fixture.256",
            },
        }
    ],
}


class FakeResponse:
    def __init__(
        self,
        source: dict | bytes,
        *,
        url: str,
        content_type: str = "application/json; charset=utf-8",
    ) -> None:
        self.status = 200
        self._source = (
            json.dumps(source, ensure_ascii=False).encode("utf-8")
            if isinstance(source, dict)
            else source
        )
        self._offset = 0
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(self._source))

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


def response(payload: dict, path: str) -> FakeResponse:
    return FakeResponse(payload, url=f"{BASE_URL}{path}")


class SnapchatAdsSearchTest(unittest.TestCase):
    def test_search_paginates_sorts_real_impressions_and_bounds_products(self) -> None:
        opener = FakeOpener(
            [
                response(SEARCH_PAGE_1, ADS_SEARCH_PATH),
                response(SEARCH_PAGE_2, ADS_SEARCH_PATH),
            ]
        )
        client = SnapchatAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        result = client.search_ads(
            paying_advertiser_name="Fixture",
            countries=["DE", "GR"],
            start_date="2025-08-01",
            end_date="2026-08-01T00:00:00Z",
            limit=10,
            product_limit=1,
        )

        self.assertEqual(result["access"], "anonymous_official_api")
        self.assertEqual(result["count"], 3)
        self.assertEqual(
            [item["impressions_total"] for item in result["items"]],
            [900, 500, 100],
        )
        self.assertEqual(result["items"][0]["upstream_rank"], 2)
        self.assertEqual(result["items"][0]["impressions_by_country"]["de"], 900)
        self.assertEqual(result["items"][0]["creative"]["media"][0]["type"], "video")
        dpa = result["items"][0]["dpa"]
        self.assertEqual(dpa["product_count"], 3)
        self.assertEqual(dpa["returned_product_count"], 1)
        self.assertTrue(dpa["products_truncated"])
        self.assertEqual(result["pagination"]["pages_fetched"], 2)
        self.assertEqual(result["metric_scope"]["ctr"], "not_published")
        self.assertEqual(result["query"]["countries"], ["de", "el"])

        first_body = json.loads(opener.calls[0][0].data.decode("utf-8"))
        self.assertEqual(first_body["paying_advertiser_name"], "Fixture")
        self.assertEqual(first_body["countries"], ["de", "el"])
        self.assertEqual(first_body["start_date"], "2025-08-01T00:00:00.000Z")
        second_query = parse_qs(urlsplit(opener.calls[1][0].full_url).query)
        self.assertEqual(second_query["cursor"], ["CURSOR_PAGE_2="])

    def test_invalid_country_is_rejected_before_network(self) -> None:
        opener = FakeOpener([])
        client = SnapchatAdsClient(opener=opener, retries=0, request_interval=0)

        with self.assertRaises(SnapchatAdsInputError):
            client.search_ads(countries=["US"])

        self.assertEqual(opener.calls, [])

    def test_next_link_must_remain_on_official_endpoint(self) -> None:
        payload = {
            **SEARCH_PAGE_1,
            "paging": {"next_link": "https://example.com/steal?cursor=TOKEN"},
        }
        client = SnapchatAdsClient(
            opener=FakeOpener([response(payload, ADS_SEARCH_PATH)]),
            retries=0,
            request_interval=0,
        )

        with self.assertRaises(SnapchatAdsResponseError) as raised:
            client.search_ads(limit=10)

        self.assertEqual(raised.exception.code, "pagination_drift")


class SnapchatAdsDetailAndSponsoredTest(unittest.TestCase):
    def test_get_ad_returns_official_detail_source_and_metrics(self) -> None:
        path = AD_DETAIL_PATH.format(ad_id=AD_2)
        client = SnapchatAdsClient(
            opener=FakeOpener([response(DETAIL, path)]),
            retries=0,
            request_interval=0,
        )

        result = client.get_ad(AD_2, product_limit=2)

        self.assertEqual(result["item"]["id"], AD_2)
        self.assertEqual(result["item"]["impressions_total"], 900)
        self.assertEqual(
            result["item"]["source_url"],
            f"{BASE_URL}{path}",
        )
        self.assertEqual(result["item"]["dpa"]["returned_product_count"], 2)

    def test_sponsored_stream_and_creator_search_use_distinct_methods(self) -> None:
        opener = FakeOpener(
            [
                response(SPONSORED, SPONSORED_CONTENT_PATH),
                response(SPONSORED, SPONSORED_SEARCH_PATH),
            ]
        )
        client = SnapchatAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        stream = client.sponsored_content(limit=10)
        searched = client.search_sponsored_content(
            "fixture-creator",
            page_size=7,
            limit=10,
        )

        self.assertEqual(stream["count"], 1)
        self.assertEqual(
            stream["items"][0]["thumbnail_url"],
            "https://bolt-gcdn.sc-cdn.net/z/fixture.256",
        )
        self.assertEqual(opener.calls[0][0].method, "GET")
        self.assertEqual(opener.calls[1][0].method, "POST")
        self.assertEqual(
            json.loads(opener.calls[1][0].data.decode("utf-8")),
            {"creator_name": "fixture-creator"},
        )
        query = parse_qs(urlsplit(opener.calls[1][0].full_url).query)
        self.assertEqual(query["limit"], ["7"])
        self.assertEqual(searched["query"]["creator_name"], "fixture-creator")


class SnapchatAdsMediaTest(unittest.TestCase):
    def test_download_media_writes_atomic_file_and_hash(self) -> None:
        payload = b"fixture-snap-video\x00\x01"
        url = "https://cf-st.sc-cdn.net/d/fixture.mp4"
        opener = FakeOpener(
            [FakeResponse(payload, url=url, content_type="video/mp4")]
        )
        client = SnapchatAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "creative.mp4"
            result = client.download_media(url, destination)

            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(result["bytes"], len(payload))
            self.assertEqual(result["sha256"], sha256(payload).hexdigest())
            self.assertEqual(result["content_type"], "video/mp4")
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_download_media_rejects_untrusted_host(self) -> None:
        opener = FakeOpener([])
        client = SnapchatAdsClient(
            opener=opener,
            retries=0,
            request_interval=0,
        )

        with TemporaryDirectory() as directory:
            with self.assertRaises(SnapchatAdsInputError):
                client.download_media(
                    "https://example.com/creative.mp4",
                    Path(directory) / "creative.mp4",
                )

        self.assertEqual(opener.calls, [])


if __name__ == "__main__":
    unittest.main()
