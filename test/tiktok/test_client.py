from __future__ import annotations

import io
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from curl_cffi import requests

from reverse.tiktok_reverse import cli
from reverse.tiktok_reverse.client import TikTokClient
from reverse.tiktok_reverse.errors import TikTokInputError, TikTokResponseError


FIXTURES = Path(__file__).with_name("fixtures")
NEW_CAPABILITIES = json.loads(
    (FIXTURES / "new_capabilities.json").read_text(encoding="utf-8")
)
CREATIVE_TRENDING_VIDEOS = json.loads(
    (FIXTURES / "creative_trending_videos.json").read_text(encoding="utf-8")
)


def response(
    payload: object | None = None,
    *,
    text: str | None = None,
    status: int = 200,
    url: str | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url or ""
    result.headers.update(headers or {})
    if text is not None:
        result.content = text.encode()
    else:
        result.content = json.dumps(payload).encode()
    result.default_encoding = "utf-8"
    return result


class FakeSession(requests.Session):
    def __init__(
        self,
        *,
        get: list[requests.Response | Exception] | None = None,
        post: list[requests.Response | Exception] | None = None,
    ) -> None:
        super().__init__()
        self.get_results = deque(get or [])
        self.post_results = deque(post or [])
        self.get_calls: list[tuple[str, dict[str, object]]] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []

    @staticmethod
    def _next(
        queue: deque[requests.Response | Exception], request_url: str
    ) -> requests.Response:
        if not queue:
            raise AssertionError("unexpected HTTP request")
        result = queue.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = request_url
        return result

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.get_calls.append((url, kwargs))
        return self._next(self.get_results, url)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        self.post_calls.append((url, kwargs))
        return self._next(self.post_results, url)


class FakeSigner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.telemetry_calls: list[object] = []

    def sign(self, raw_query: str, **kwargs: object) -> dict[str, str]:
        self.calls.append({"raw_query": raw_query, **kwargs})
        return {"query": raw_query or "report-signature=fixture"}

    def encode_telemetry(self, payload: object) -> str:
        self.telemetry_calls.append(payload)
        return "encoded-telemetry"


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TimedFakeSession(FakeSession):
    def __init__(self, clock: FakeClock, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.clock = clock
        self.request_starts: list[tuple[str, float]] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.request_starts.append(("GET", self.clock.monotonic()))
        return super().get(url, **kwargs)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        self.request_starts.append(("POST", self.clock.monotonic()))
        return super().post(url, **kwargs)


class TimedFakeSigner(FakeSigner):
    def __init__(self, clock: FakeClock) -> None:
        super().__init__()
        self.clock = clock
        self.sign_starts: list[float] = []

    def sign(self, raw_query: str, **kwargs: object) -> dict[str, str]:
        self.sign_starts.append(self.clock.monotonic())
        return super().sign(raw_query, **kwargs)


class DownloadResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> DownloadResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self._body.close()

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)


def mark_session_ready(client: TikTokClient) -> None:
    client.device_id = "device-123"
    client.odin_id = "odin-456"
    client.ms_token = "fixture-token"
    client._ms_token_ready = True


def profile_html() -> str:
    payload = {
        "__DEFAULT_SCOPE__": {
            "webapp.app-context": {
                "wid": "device-123",
                "webIdCreatedTime": "1700000000",
                "odinId": "odin-456",
                "language": "zh-Hans",
                "region": "SG",
                "abTestVersion": {"versionName": "v1,v2"},
            },
            "webapp.user-detail": {
                "statusCode": 0,
                "userInfo": {
                    "user": {"secUid": "sec-user", "uniqueId": "fixture"},
                    "stats": {"videoCount": 3},
                    "itemList": [{"id": "hydrated"}],
                },
            },
        }
    }
    return (
        '<html><script id="ignored">x</script>'
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
        f"{json.dumps(payload)}</script></html>"
    )


class TikTokClientTest(unittest.TestCase):
    def test_signer_is_loaded_only_when_a_signed_operation_uses_it(self) -> None:
        with patch(
            "reverse.tiktok_reverse.client.TikTokSigner",
            side_effect=RuntimeError("node fixture unavailable"),
        ) as signer:
            client = TikTokClient(session=FakeSession())
            signer.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "node fixture unavailable"):
                _ = client.signer

    def test_request_interval_accepts_bounds_and_rejects_invalid_values(self) -> None:
        default_client = TikTokClient(session=FakeSession(), signer=FakeSigner())
        self.assertEqual(default_client.request_interval, 3.0)

        for value in (0, 10):
            with self.subTest(value=value):
                client = TikTokClient(
                    session=FakeSession(),
                    signer=FakeSigner(),
                    request_interval=value,
                )
                self.assertEqual(client.request_interval, float(value))

        for value in (-0.01, 10.01, float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TikTokInputError, "range 0..10"):
                    TikTokClient(
                        session=FakeSession(),
                        signer=FakeSigner(),
                        request_interval=value,
                    )

    def test_profile_hydration_initializes_request_identity(self) -> None:
        session = FakeSession(
            get=[
                response(
                    text=profile_html(),
                    url="https://www.tiktok.com/@fixture",
                    headers={"x-ms-token": "page-token"},
                )
            ]
        )
        client = TikTokClient(
            session=session,
            request_interval=0,
        )

        result = client.get_profile("tiktok.com/@fixture")

        self.assertEqual(result["user"]["secUid"], "sec-user")
        self.assertEqual(result["stats"], {"videoCount": 3})
        self.assertEqual(result["item_list"], [{"id": "hydrated"}])
        self.assertEqual(client.device_id, "device-123")
        self.assertEqual(client.odin_id, "odin-456")
        self.assertEqual(client.web_id_last_time, 1700000000)
        self.assertEqual(client.language, "zh-Hans")
        self.assertEqual(client.region, "SG")
        self.assertEqual(client.client_ab_versions, "v1,v2")
        self.assertEqual(client.ms_token, "page-token")
        self.assertEqual(session.get_calls[0][0], "https://tiktok.com/@fixture")

    def test_creative_trending_hashtags_normalizes_public_preview(self) -> None:
        session = FakeSession(
            post=[
                response(
                    {
                        "items": [
                            {
                                "hashtagID": "7400795988650459167",
                                "hashtagName": "fixture",
                                "industryIDs": [23000000000],
                                "popularityCurve": [
                                    {"timestamp": "1784246400", "value": 63.03}
                                ],
                                "publishCnt": 34639,
                                "rankIndex": 1,
                                "topCreators": [{"handleName": "creator"}],
                                "vv": 29712825,
                            }
                        ],
                        "pagination": {
                            "hasMore": False,
                            "limit": 1,
                            "page": 1,
                            "totalCount": 1,
                        },
                    }
                )
            ]
        )
        client = TikTokClient(
            session=session,
            request_interval=0,
        )

        result = client.get_creative_trending_hashtags(
            country="us",
            time_range=7,
            industry_id="23000000000",
            page=1,
            limit=20,
        )

        self.assertEqual(result["source"], "tiktok_creative_center")
        self.assertEqual(result["available"], 1)
        self.assertTrue(result["anonymous_preview"])
        self.assertEqual(result["industry_id"], 23000000000)
        self.assertEqual(
            result["hashtags"][0],
            {
                "rank": 1,
                "id": "7400795988650459167",
                "name": "fixture",
                "post_count": 34639,
                "view_count": 29712825,
                "industry_ids": [23000000000],
                "popularity_curve": [
                    {"timestamp": "1784246400", "value": 63.03}
                ],
                "top_creators": [{"handleName": "creator"}],
            },
        )
        url, kwargs = session.post_calls[0]
        self.assertEqual(
            url,
            "https://ads.tiktok.com/CreativeOne/KnowledgeAPI/GetHashtagList",
        )
        self.assertEqual(
            kwargs["json"],
            {
                "timeRange": 7,
                "countryCode": "US",
                "industryID": 23000000000,
                "page": 1,
                "limit": 20,
            },
        )
        self.assertNotIn("Cookie", kwargs["headers"])
        self.assertNotIn("Authorization", kwargs["headers"])

    def test_creative_trending_hashtags_rejects_invalid_input_before_http(self) -> None:
        client = TikTokClient(
            session=FakeSession(),
            signer=FakeSigner(),
            request_interval=0,
        )
        cases = [
            {"country": "USA"},
            {"time_range": 14},
            {"industry_id": "topic"},
            {"industry_id": 0},
            {"page": 0},
            {"limit": 101},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TikTokInputError):
                    client.get_creative_trending_hashtags(**kwargs)
        self.assertEqual(client.session.post_calls, [])

    def test_creative_trending_hashtags_reports_origin_status(self) -> None:
        client = TikTokClient(
            session=FakeSession(
                post=[
                    response(
                        {
                            "BaseResp": {
                                "StatusCode": 38001001,
                                "StatusMessage": "InvalidLogin",
                            }
                        }
                    )
                ]
            ),
            signer=FakeSigner(),
            request_interval=0,
        )
        with self.assertRaisesRegex(TikTokResponseError, "InvalidLogin"):
            client.get_creative_trending_hashtags()

    def test_creative_trending_videos_normalizes_public_preview(self) -> None:
        session = FakeSession(
            get=[
                response(CREATIVE_TRENDING_VIDEOS["overview"]),
                response(CREATIVE_TRENDING_VIDEOS["response"]),
            ]
        )
        client = TikTokClient(
            session=session,
            request_interval=0,
        )

        result = client.get_creative_trending_videos(
            country="us",
            time_range=30,
            metric="views",
            content_label_ids="11002, 11003,11002",
            page=1,
            limit=1,
        )

        self.assertEqual(result["origin"], "https://ads.us.tiktok.com")
        self.assertEqual(result["period_dimension"], 5)
        self.assertEqual(result["period_end_timestamp"], "1784764800")
        self.assertEqual(result["content_label_ids"], ["11002", "11003"])
        self.assertEqual(result["available"], 1)
        self.assertEqual(result["total_count"], 100)
        self.assertFalse(result["has_more"])
        self.assertTrue(result["upstream_has_more"])
        self.assertTrue(result["anonymous_preview"])
        self.assertTrue(result["continuation_restricted"])
        self.assertEqual(
            result["videos"][0]["id"],
            "7656166869774109983",
        )
        self.assertEqual(
            result["videos"][0]["url"],
            "https://www.tiktok.com/@fixture.creator/video/"
            "7656166869774109983",
        )
        self.assertEqual(
            result["videos"][0]["metrics"]["video_views"],
            139898979,
        )

        self.assertEqual(
            session.get_calls[0][0],
            "https://ads.us.tiktok.com"
            "/CreativeOne/Report/GetTopContentsOverview",
        )
        list_url, list_kwargs = session.get_calls[1]
        self.assertEqual(
            list_url,
            "https://ads.us.tiktok.com"
            "/CreativeOne/Report/CreativeCenterGetTopContentsList",
        )
        self.assertEqual(
            list_kwargs["params"],
            {
                "periodDimension": 5,
                "periodEndTimestamp": "1784764800",
                "orderByMetric": 1,
                "countryCode": "US",
                "contentLabelIDs": "11002,11003",
                "organicOnly": "false",
                "limit": 20,
                "page": 1,
            },
        )
        self.assertNotIn("Cookie", list_kwargs["headers"])
        self.assertNotIn("Authorization", list_kwargs["headers"])

    def test_creative_trending_videos_routes_regions_and_metrics(self) -> None:
        self.assertEqual(
            TikTokClient._creative_center_origin("DE"),
            "https://ads-useast2a.tiktok.com",
        )
        self.assertEqual(
            TikTokClient._creative_center_origin("JP"),
            "https://ads.tiktok.com",
        )
        session = FakeSession(
            get=[
                response(CREATIVE_TRENDING_VIDEOS["overview"]),
                response(CREATIVE_TRENDING_VIDEOS["response"]),
            ]
        )
        result = TikTokClient(
            session=session,
            signer=FakeSigner(),
            request_interval=0,
        ).get_creative_trending_videos(
            country="DE",
            time_range=7,
            metric="engagement-rate",
            limit=20,
        )
        self.assertEqual(result["origin"], "https://ads-useast2a.tiktok.com")
        self.assertEqual(result["period_dimension"], 3)
        self.assertEqual(result["metric"], "engagement")
        self.assertEqual(result["order_by_metric"], 2)

    def test_creative_trending_videos_full_uses_browser_page_contract(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []
        payload = dict(CREATIVE_TRENDING_VIDEOS["response"])
        payload["entityInfos"] = payload["entityInfos"][:1]
        payload["pagination"] = {
            "page": 2,
            "limit": 20,
            "totalCount": 41,
            "hasMore": True,
        }

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == "/CreativeOne/Report/GetTopContentsOverview":
                return CREATIVE_TRENDING_VIDEOS["overview"]
            return payload

        session = FakeSession()
        result = TikTokClient(
            session=session,
            creative_fetch=fetch,
            request_interval=0,
        ).get_creative_trending_videos_full(
            country="us",
            time_range=30,
            metric="engagement",
            content_label_ids="11002,11003",
            page=2,
            limit=20,
        )

        self.assertEqual(result["transport"], "browser_web")
        self.assertTrue(result["browser_session"])
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["limit"], 20)
        self.assertEqual(result["total_count"], 41)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_page"], 3)
        self.assertFalse(result["anonymous_preview"])
        self.assertFalse(result["continuation_restricted"])
        self.assertEqual(result["videos"][0]["id"], "7656166869774109983")
        self.assertEqual(
            calls,
            [
                (
                    "/CreativeOne/Report/GetTopContentsOverview",
                    [],
                    (
                        "https://ads.tiktok.com/business/creativecenter/"
                        "inspiration/popular/video/pc/en"
                    ),
                ),
                (
                    "/CreativeOne/Report/CreativeCenterGetTopContentsList",
                    [
                        ("periodDimension", "5"),
                        ("periodEndTimestamp", "1784764800"),
                        ("orderByMetric", "2"),
                        ("countryCode", "US"),
                        ("contentLabelIDs", "11002,11003"),
                        ("page", "2"),
                        ("limit", "20"),
                    ],
                    (
                        "https://ads.tiktok.com/business/creativecenter/"
                        "inspiration/popular/video/pc/en"
                    ),
                )
            ],
        )
        self.assertEqual(session.get_calls, [])

    def test_creative_trending_videos_full_rejects_invalid_pagination(self) -> None:
        def invalid_fetch(path, *_args):
            if path == "/CreativeOne/Report/GetTopContentsOverview":
                return CREATIVE_TRENDING_VIDEOS["overview"]
            return {
                "entityInfos": [],
                "pagination": {
                    "page": 1,
                    "limit": 20,
                    "totalCount": 1,
                    "hasMore": False,
                },
            }

        client = TikTokClient(
            creative_fetch=invalid_fetch,
            request_interval=0,
        )
        with self.assertRaisesRegex(TikTokResponseError, "pagination"):
            client.get_creative_trending_videos_full()

        invalid_client = TikTokClient(
            session=FakeSession(),
            creative_fetch=lambda *_args: (_ for _ in ()).throw(
                AssertionError("unexpected browser request")
            ),
            request_interval=0,
        )
        for kwargs in (
            {"country": "USA"},
            {"time_range": 90},
            {"metric": "likes"},
            {"page": 0},
            {"limit": 21},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(TikTokInputError):
                invalid_client.get_creative_trending_videos_full(**kwargs)

    def test_creative_trending_videos_rejects_invalid_input_before_http(
        self,
    ) -> None:
        client = TikTokClient(
            session=FakeSession(),
            signer=FakeSigner(),
            request_interval=0,
        )
        cases = [
            {"country": "USA"},
            {"time_range": 90},
            {"metric": "likes"},
            {"content_label_ids": "video"},
            {"content_label_ids": "0"},
            {"page": 2},
            {"limit": 0},
            {"limit": 21},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TikTokInputError):
                    client.get_creative_trending_videos(**kwargs)
        self.assertEqual(client.session.get_calls, [])

    def test_creative_trending_videos_reports_origin_and_shape_errors(
        self,
    ) -> None:
        client = TikTokClient(
            session=FakeSession(
                get=[
                    response(
                        {
                            "BaseResp": {
                                "StatusCode": 38001001,
                                "StatusMessage": "InvalidLogin",
                            }
                        }
                    )
                ]
            ),
            signer=FakeSigner(),
            request_interval=0,
        )
        with self.assertRaisesRegex(TikTokResponseError, "InvalidLogin"):
            client.get_creative_trending_videos()

        missing_entities = TikTokClient(
            session=FakeSession(
                get=[
                    response(CREATIVE_TRENDING_VIDEOS["overview"]),
                    response({"pagination": {}}),
                ]
            ),
            signer=FakeSigner(),
            request_interval=0,
        )
        with self.assertRaisesRegex(TikTokResponseError, "entityInfos"):
            missing_entities.get_creative_trending_videos()

    def test_creative_trending_video_detail_normalizes_public_detail(self) -> None:
        item_id = "7656166869774109983"
        detail = {
            "BaseResp": {
                "StatusCode": 0,
                "StatusMessage": "",
                "Extra": {"traceparent": "TRACE-MUST-NOT-LEAK"},
            },
            "entityInfo": {
                "itemInfo": {
                    "itemID": int(item_id),
                    "authorID": 7506219246691926062,
                    "creatorID": 168541398546182144,
                    "title": "Fixture trending video",
                    "coverURL": (
                        "https://p16-common-sign.tiktokcdn-us.com/video/cover.webp"
                        "?x-signature=fixture"
                    ),
                    "coverURLList": [
                        {
                            "format": "avif",
                            "imageUrl": (
                                "https://p16-common-sign.tiktokcdn-us.com/"
                                "video/cover.avif?x-signature=fixture"
                            ),
                        },
                        {
                            "format": "jpeg",
                            "imageUrl": (
                                "https://p16-common-sign.tiktokcdn-us.com/"
                                "video/cover.jpeg?x-signature=fixture"
                            ),
                        },
                    ],
                    "videoURL": (
                        "https://v16m-default.tiktokcdn-us.com/video/fixture.mp4"
                        "?x-signature=fixture"
                    ),
                    "createTime": 1782590275,
                    "contentType": 1,
                },
                "itemAuthorInfo": {
                    "handlerName": "fixture.creator",
                    "nickName": "Fixture Creator",
                    "avatarURI": (
                        "https://p16-common-sign.tiktokcdn-us.com/avatar/creator.webp"
                        "?x-signature=fixture"
                    ),
                    "bio": "Fixture bio",
                    "creatorType": 2,
                    "riskInfo": {"marker": "RISK-MUST-NOT-LEAK"},
                },
                "itemAuthorMetrics": {"followers": 55128088},
                "itemMetrics": {
                    "videoViews": 139898979,
                    "videoViewsLifeTime": 139998979,
                    "organicVideoViews": 137104452,
                    "organicVideoViewsLifeTime": 137204452,
                    "engagementRate": 0.11059671135984488,
                    "engagementRateLifeTime": 0.12059671135984488,
                    "sixSecondsVTR": 0.5644874866791472,
                    "sixSecondsVTRLifeTime": 0.5744874866791472,
                },
                "commentInfos": [
                    {
                        "objectID": 7656175178786849544,
                        "userID": 7583679865322423297,
                        "text": "Fixture top comment",
                        "createTime": 1782592207,
                        "likeCnt": 757623,
                        "userName": "Fixture Commenter",
                        "userAvatarLink": (
                            "https://p19-common-sign.tiktokcdn-us.com/"
                            "avatar/comment.webp?x-signature=fixture"
                        ),
                    }
                ],
            },
        }
        session = FakeSession(
            get=[
                response(CREATIVE_TRENDING_VIDEOS["overview"]),
                response(detail),
            ]
        )
        client = TikTokClient(session=session, request_interval=0)

        result = client.get_creative_trending_video_detail(
            item_id,
            country="de",
            time_range=7,
        )

        self.assertEqual(result["origin"], "https://ads-useast2a.tiktok.com")
        self.assertEqual(result["period_dimension"], 3)
        self.assertEqual(result["period_end_timestamp"], "1784764800")
        self.assertEqual(result["id"], item_id)
        self.assertEqual(
            result["url"],
            "https://www.tiktok.com/@fixture.creator/video/" + item_id,
        )
        self.assertEqual(result["cover_variants"][0]["format"], "avif")
        self.assertEqual(result["author"]["id"], "7506219246691926062")
        self.assertEqual(result["author"]["followers"], 55128088)
        self.assertEqual(result["metrics"]["video_views"], 139898979)
        self.assertEqual(
            result["metrics"]["organic_video_views_lifetime"],
            137204452,
        )
        self.assertEqual(result["available_comments"], 1)
        self.assertEqual(result["comments"][0]["id"], "7656175178786849544")
        self.assertEqual(
            result["comments"][0]["user"]["id"],
            "7583679865322423297",
        )
        self.assertNotIn("TRACE-MUST-NOT-LEAK", json.dumps(result))
        self.assertNotIn("RISK-MUST-NOT-LEAK", json.dumps(result))

        self.assertEqual(
            session.get_calls[0][0],
            "https://ads-useast2a.tiktok.com"
            "/CreativeOne/Report/GetTopContentsOverview",
        )
        detail_url, detail_kwargs = session.get_calls[1]
        self.assertEqual(
            detail_url,
            "https://ads-useast2a.tiktok.com"
            "/CreativeOne/Report/CreativeCenterGetTopContentsItemDetail",
        )
        self.assertEqual(
            detail_kwargs["params"],
            {
                "itemID": item_id,
                "periodDimension": 3,
                "periodEndTimestamp": "1784764800",
            },
        )
        self.assertNotIn("Cookie", detail_kwargs["headers"])
        self.assertNotIn("Authorization", detail_kwargs["headers"])

    def test_creative_trending_video_detail_rejects_invalid_input_and_response(
        self,
    ) -> None:
        client = TikTokClient(session=FakeSession(), request_interval=0)
        for kwargs in (
            {"item_id": ""},
            {"item_id": "0"},
            {"item_id": "07656166869774109983"},
            {"item_id": "7656166869774109983x"},
            {"item_id": "9" * 33},
            {"item_id": "7656166869774109983", "country": "USA"},
            {"item_id": "7656166869774109983", "time_range": 90},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TikTokInputError):
                    client.get_creative_trending_video_detail(**kwargs)
        self.assertEqual(client.session.get_calls, [])

        bad_response = {
            "entityInfo": {
                "itemInfo": {"itemID": "7656166869774109984"},
                "itemAuthorInfo": {},
                "itemAuthorMetrics": {},
                "itemMetrics": {},
            }
        }
        mismatch = TikTokClient(
            session=FakeSession(
                get=[
                    response(CREATIVE_TRENDING_VIDEOS["overview"]),
                    response(bad_response),
                ]
            ),
            request_interval=0,
        )
        with self.assertRaisesRegex(TikTokResponseError, "does not match target"):
            mismatch.get_creative_trending_video_detail("7656166869774109983")

    def test_request_interval_covers_identity_token_and_signed_api_chain(self) -> None:
        clock = FakeClock()
        signer = TimedFakeSigner(clock)
        session = TimedFakeSession(
            clock,
            get=[
                response(text=profile_html(), url="https://www.tiktok.com/"),
                response(
                    {
                        "statusCode": 0,
                        "itemInfo": {"itemStruct": {"id": "7351", "desc": "video"}},
                    }
                ),
            ],
            post=[
                response({}, headers={"set-cookie": "msToken=initial-token; Path=/"}),
                response({}, headers={"set-cookie": "msToken=strong-token; Path=/"}),
            ],
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=3,
        )

        with patch(
            "reverse.tiktok_reverse.client.time.monotonic",
            side_effect=clock.monotonic,
        ), patch(
            "reverse.tiktok_reverse.client.time.sleep",
            side_effect=clock.sleep,
        ), patch(
            "reverse.tiktok_reverse.client.time.time",
            side_effect=clock.monotonic,
        ):
            result = client.get_video("7351")

        self.assertEqual(result["id"], "7351")
        self.assertEqual(
            session.request_starts,
            [
                ("GET", 1000.0),
                ("POST", 1003.0),
                ("POST", 1006.0),
                ("GET", 1009.0),
            ],
        )
        self.assertEqual(signer.sign_starts, [1006.0, 1009.0])
        self.assertEqual(clock.sleeps, [3.0, 3.0, 3.0])
        initial_body = json.loads(str(session.post_calls[0][1]["data"]))
        telemetry_body = json.loads(str(session.post_calls[1][1]["data"]))
        self.assertEqual(initial_body["tspFromClient"], 1003000)
        self.assertEqual(telemetry_body["tspFromClient"], 1006000)

    def test_hydration_retries_transient_and_missing_script_responses(self) -> None:
        session = FakeSession(
            get=[
                requests.exceptions.ConnectionError("fixture connection failure"),
                response({}, status=429),
                response({}, status=503),
                response(text="<html>challenge</html>"),
                response(
                    text=profile_html(),
                    url="https://www.tiktok.com/@fixture",
                ),
            ]
        )
        client = TikTokClient(
            session=session,
            signer=FakeSigner(),
            retries=4,
            request_interval=0,
        )

        with patch("reverse.tiktok_reverse.client.time.sleep") as sleep:
            result = client.get_profile("https://www.tiktok.com/@fixture")

        self.assertEqual(result["user"]["secUid"], "sec-user")
        self.assertEqual(len(session.get_calls), 5)
        self.assertEqual(
            [entry.args for entry in sleep.call_args_list],
            [(0.4,), (0.8,), (1.6,), (3.2,)],
        )

    def test_hydration_does_not_retry_deterministic_http_errors(self) -> None:
        session = FakeSession(
            get=[response({}, status=404), response(text=profile_html())]
        )
        client = TikTokClient(
            session=session,
            signer=FakeSigner(),
            retries=3,
            request_interval=0,
        )

        with patch("reverse.tiktok_reverse.client.time.sleep") as sleep:
            with self.assertRaisesRegex(TikTokResponseError, "HTTP 404"):
                client.get_profile("https://www.tiktok.com/@fixture")

        self.assertEqual(len(session.get_calls), 1)
        sleep.assert_not_called()

    def test_hydration_classifies_waf_without_retrying(self) -> None:
        session = FakeSession(
            get=[
                response(
                    text=(
                        '<script id="slardar-config">SlardarWAF</script>'
                        '<p id="wci" class="_wafchallengeid"></p>'
                    )
                ),
                response(text=profile_html()),
            ]
        )
        client = TikTokClient(
            session=session,
            signer=FakeSigner(),
            retries=3,
            request_interval=0,
        )

        with patch("reverse.tiktok_reverse.client.time.sleep") as sleep:
            with self.assertRaisesRegex(TikTokResponseError, "WAF challenge"):
                client.get_profile("https://www.tiktok.com/@fixture")

        self.assertEqual(len(session.get_calls), 1)
        sleep.assert_not_called()

    def test_video_input_accepts_ids_direct_urls_and_redirect_urls(self) -> None:
        session = FakeSession(
            get=[
                response(
                    text="",
                    url="https://www.tiktok.com/@fixture/video/7350000000000000003",
                    headers={"x-ms-token": "redirect-token"},
                )
            ]
        )
        client = TikTokClient(
            session=session,
            signer=FakeSigner(),
            request_interval=0,
        )

        self.assertEqual(
            client._resolve_video("7350000000000000001"),
            (
                "7350000000000000001",
                "https://www.tiktok.com/@_/video/7350000000000000001",
            ),
        )
        self.assertEqual(
            client._resolve_video("https://www.tiktok.com/@fixture/video/7350000000000000002"),
            (
                "7350000000000000002",
                "https://www.tiktok.com/@fixture/video/7350000000000000002",
            ),
        )
        self.assertEqual(
            client._resolve_video("https://vm.tiktok.com/short-code/"),
            (
                "7350000000000000003",
                "https://www.tiktok.com/@fixture/video/7350000000000000003",
            ),
        )
        self.assertEqual(client.ms_token, "redirect-token")
        with self.assertRaises(TikTokInputError):
            client._resolve_video("https://tiktok.com.example/video/7350000000000000001")

    def test_short_video_redirects_share_the_request_interval(self) -> None:
        clock = FakeClock()
        session = TimedFakeSession(
            clock,
            get=[
                response(
                    text="",
                    url="https://www.tiktok.com/@fixture/video/7350000000000000001",
                ),
                response(
                    text="",
                    url="https://www.tiktok.com/@fixture/video/7350000000000000002",
                ),
            ],
        )
        client = TikTokClient(
            session=session,
            signer=FakeSigner(),
            retries=0,
            request_interval=3,
        )

        with patch(
            "reverse.tiktok_reverse.client.time.monotonic",
            side_effect=clock.monotonic,
        ), patch(
            "reverse.tiktok_reverse.client.time.sleep",
            side_effect=clock.sleep,
        ):
            first, _ = client._resolve_video("https://vm.tiktok.com/first/")
            second, _ = client._resolve_video("https://vm.tiktok.com/second/")

        self.assertEqual((first, second), ("7350000000000000001", "7350000000000000002"))
        self.assertEqual(
            session.request_starts,
            [("GET", 1000.0), ("GET", 1003.0)],
        )
        self.assertEqual(clock.sleeps, [3.0])

    def test_explicit_zero_request_interval_disables_waiting(self) -> None:
        clock = FakeClock()
        session = TimedFakeSession(
            clock,
            get=[
                response(
                    text="",
                    url="https://www.tiktok.com/@fixture/video/7350000000000000001",
                ),
                response(
                    text="",
                    url="https://www.tiktok.com/@fixture/video/7350000000000000002",
                ),
            ],
        )
        client = TikTokClient(
            session=session,
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )

        with patch(
            "reverse.tiktok_reverse.client.time.monotonic",
            side_effect=clock.monotonic,
        ), patch(
            "reverse.tiktok_reverse.client.time.sleep",
            side_effect=clock.sleep,
        ):
            client._resolve_video("https://vm.tiktok.com/first/")
            client._resolve_video("https://vm.tiktok.com/second/")

        self.assertEqual(
            session.request_starts,
            [("GET", 1000.0), ("GET", 1000.0)],
        )
        self.assertEqual(clock.sleeps, [])

    def test_video_and_comment_fields_are_normalized(self) -> None:
        video = TikTokClient._normalize_video(
            {
                "aweme_id": 7350000000000000001,
                "description": "description fallback",
                "create_time": "1700000001",
                "seoInfos": {"seoTitle": "SEO title"},
                "author": {
                    "uid": 42,
                    "sec_uid": "sec-42",
                    "unique_id": "creator",
                    "nickname": "Creator",
                    "verified": True,
                },
                "statsV2": {
                    "digg_count": "11",
                    "play_count": "22",
                    "comment_count": "3",
                    "share_count": "4",
                    "collect_count": "5",
                },
                "video": {
                    "cover": {"urlList": ["cover"]},
                    "origin_cover": ["origin"],
                    "dynamicCover": "dynamic",
                    "play_addr": {"UrlList": ["play"]},
                    "downloadAddr": {"url_list": ["download"]},
                    "bit_rate": [
                        {"PlayAddr": {"UrlList": ["bitrate-1"]}},
                        {"playAddr": ["bitrate-1"]},
                        {"urlList": ["bitrate-2"]},
                    ],
                    "duration": "1234",
                    "width": 1080,
                    "height": 1920,
                },
            }
        )
        comment = TikTokClient._normalize_comment(
            {
                "cid": 99,
                "text": "hello",
                "createTime": "1700000002",
                "diggCount": "7",
                "replyCommentTotal": "2",
                "replyId": 88,
                "user": {
                    "id": 9,
                    "secUid": "sec-9",
                    "uniqueId": "commenter",
                    "nickname": "Commenter",
                    "avatarThumb": {"urlList": ["avatar"]},
                },
            }
        )

        self.assertEqual(video["id"], "7350000000000000001")
        self.assertEqual(video["title"], "SEO title")
        self.assertEqual(video["description"], "description fallback")
        self.assertEqual(
            video["stats"],
            {"likes": 11, "plays": 22, "comments": 3, "shares": 4, "collects": 5},
        )
        self.assertEqual(video["media"]["play_url"], "play")
        self.assertEqual(video["media"]["download_url"], "download")
        self.assertEqual(video["media"]["bitrate_urls"], ["bitrate-1", "bitrate-2"])
        self.assertEqual(comment["id"], "99")
        self.assertEqual(comment["likes"], 7)
        self.assertEqual(comment["reply_count"], 2)
        self.assertEqual(comment["parent_id"], "88")
        self.assertEqual(comment["user"]["avatar"], "avatar")

    def test_video_normalizes_expandable_tag_and_music_relationships(self) -> None:
        video = TikTokClient._normalize_video(
            {
                "id": "7350000000000000001",
                "challenges": [
                    {
                        "id": None,
                        "cid": "1622962893630470",
                        "title": None,
                        "cha_name": "#TeacherTok",
                    },
                    {"cid": "1622962893630470", "cha_name": "Duplicate"},
                    {"cid": "not-an-id", "cha_name": "Malformed"},
                    "malformed",
                ],
                "challengeInfo": [
                    {
                        "challenge": {
                            "id": "1622962893630471",
                            "title": "ClassroomDecor",
                        }
                    },
                    {"challenge": {"id": "1622962893630472"}},
                ],
                "music": {
                    "idStr": None,
                    "id_str": "7223827501163006766",
                    "title": "Fixture original sound",
                    "authorName": "Fixture Artist",
                    "isOriginal": "1",
                },
            }
        )

        self.assertEqual(
            video["tags"],
            [
                {
                    "id": "1622962893630470",
                    "name": "TeacherTok",
                    "url": "https://www.tiktok.com/tag/TeacherTok",
                },
                {
                    "id": "1622962893630471",
                    "name": "ClassroomDecor",
                    "url": "https://www.tiktok.com/tag/ClassroomDecor",
                },
            ],
        )
        self.assertEqual(
            video["music"],
            {
                "id": "7223827501163006766",
                "url": "https://www.tiktok.com/music/-7223827501163006766",
                "title": "Fixture original sound",
                "author_name": "Fixture Artist",
                "original": True,
            },
        )

        without_relationships = TikTokClient._normalize_video(
            {
                "id": "7350000000000000002",
                "challenges": "malformed",
                "challenge_info": [{"challenge": {"id": "not-an-id"}}],
                "music": [],
            }
        )
        self.assertNotIn("tags", without_relationships)
        self.assertNotIn("music", without_relationships)

    def test_direct_video_id_initializes_identity_before_building_query(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            get=[
                response(
                    text=profile_html(),
                    url="https://www.tiktok.com/",
                    headers={"x-ms-token": "page-token"},
                ),
                response(
                    {
                        "statusCode": 0,
                        "itemInfo": {"itemStruct": {"id": "7351", "desc": "video"}},
                    }
                ),
            ],
            post=[response({}, headers={"set-cookie": "msToken=strong-token; Path=/"})],
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )

        result = client.get_video("7351")

        self.assertEqual(result["id"], "7351")
        query = parse_qs(urlsplit(session.get_calls[-1][0]).query)
        self.assertEqual(query["device_id"], ["device-123"])
        self.assertEqual(query["odinId"], ["odin-456"])
        self.assertEqual(query["WebIdLastTime"], ["1700000000"])

    def test_user_video_pagination_deduplicates_and_advances_cursor(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            get=[
                response(
                    text=profile_html(),
                    url="https://www.tiktok.com/@fixture",
                    headers={"x-ms-token": "page-token"},
                ),
                response(
                    {
                        "statusCode": 0,
                        "itemList": [{"id": "1"}, {"id": "2"}],
                        "hasMore": True,
                        "cursor": 16,
                    }
                ),
                response(
                    {
                        "statusCode": 0,
                        "itemList": [{"id": "2"}, {"id": "3"}],
                        "hasMore": False,
                        "cursor": 32,
                    }
                ),
            ],
            post=[response({}, headers={"set-cookie": "msToken=strong-token; Path=/"})],
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )

        result = client.get_user_videos("https://www.tiktok.com/@fixture", page_size=100)

        self.assertEqual([item["id"] for item in result["videos"]], ["1", "2", "3"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["cursor"], "32")
        self.assertFalse(result["has_more"])
        api_calls = [call for call in signer.calls if "counters" in call]
        self.assertEqual([call["counters"]["txr"] for call in api_calls], [24, 25])
        for call in api_calls:
            query = str(call["raw_query"])
            keys = [part.split("=", 1)[0] for part in query.split("&")]
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(parse_qs(query)["count"], ["35"])

    def test_video_pagination_rejects_a_non_advancing_cursor(self) -> None:
        session = FakeSession(
            get=[
                response(
                    text=profile_html(),
                    url="https://www.tiktok.com/@fixture",
                    headers={"x-ms-token": "page-token"},
                ),
                response({"statusCode": 0, "itemList": [], "hasMore": True, "cursor": "0"})
            ],
            post=[response({}, headers={"set-cookie": "msToken=strong-token; Path=/"})],
        )
        client = TikTokClient(
            session=session,
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )

        with self.assertRaisesRegex(TikTokResponseError, "did not advance"):
            client.get_user_videos("https://www.tiktok.com/@fixture")

    def test_video_detail_and_nested_comment_pagination(self) -> None:
        clock = FakeClock()
        signer = TimedFakeSigner(clock)
        session = TimedFakeSession(
            clock,
            get=[
                response(
                    {
                        "statusCode": 0,
                        "itemInfo": {"itemStruct": {"id": "7351", "desc": "one video"}},
                    }
                ),
                response(
                    {
                        "statusCode": 0,
                        "comments": [
                            {"cid": "c1", "text": "first", "reply_comment_total": 2},
                            {"cid": "c2", "text": "second"},
                        ],
                        "has_more": True,
                        "cursor": 20,
                    }
                ),
                response(
                    {
                        "statusCode": 0,
                        "comments": [{"cid": "r1", "text": "reply one"}],
                        "has_more": True,
                        "cursor": 20,
                    }
                ),
                response(
                    {
                        "statusCode": 0,
                        "comments": [
                            {"cid": "r1", "text": "duplicate reply"},
                            {"cid": "r2", "text": "reply two"},
                        ],
                        "has_more": False,
                        "cursor": 40,
                    }
                ),
                response(
                    {
                        "statusCode": 0,
                        "comments": [
                            {"cid": "c2", "text": "duplicate"},
                            {"cid": "c3", "text": "third"},
                        ],
                        "has_more": False,
                        "cursor": 40,
                    }
                ),
            ]
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=3,
        )
        mark_session_ready(client)

        with patch(
            "reverse.tiktok_reverse.client.time.monotonic",
            side_effect=clock.monotonic,
        ), patch(
            "reverse.tiktok_reverse.client.time.sleep",
            side_effect=clock.sleep,
        ):
            video = client.get_video("https://www.tiktok.com/@fixture/video/7351")
            comments = client.get_comments(
                "7351",
                include_replies=True,
                reply_limit=2,
                reply_page_size=37,
                page_size=99,
            )

        self.assertEqual(video["id"], "7351")
        self.assertEqual(video["title"], "one video")
        self.assertEqual([item["id"] for item in comments["comments"]], ["c1", "c2", "c3"])
        self.assertEqual(
            [item["id"] for item in comments["comments"][0]["replies"]],
            ["r1", "r2"],
        )
        self.assertEqual(comments["cursor"], "40")
        reply_queries = [
            parse_qs(str(call["raw_query"]))
            for call in signer.calls
            if "comment_id=" in str(call["raw_query"])
        ]
        self.assertEqual([query["count"] for query in reply_queries], [["37"], ["37"]])
        paths = [urlsplit(url).path for url, _ in session.get_calls]
        self.assertEqual(
            paths,
            [
                "/api/item/detail/",
                "/api/comment/list/",
                "/api/comment/list/reply/",
                "/api/comment/list/reply/",
                "/api/comment/list/",
            ],
        )
        self.assertEqual(
            [started_at for _, started_at in session.request_starts],
            [1000.0, 1003.0, 1006.0, 1009.0, 1012.0],
        )
        self.assertEqual(clock.sleeps, [3.0, 3.0, 3.0, 3.0])

    def test_search_videos_uses_shared_fixture_and_preserves_tokens(self) -> None:
        fixture = NEW_CAPABILITIES["search"]
        signer = FakeSigner()
        session = FakeSession(get=[response(page) for page in fixture["pages"]])
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )
        mark_session_ready(client)

        result = client.search_videos(fixture["keyword"], limit=50, page_size=99)

        self.assertEqual(result, fixture["expected"])
        queries = [parse_qs(str(call["raw_query"]), keep_blank_values=True) for call in signer.calls]
        self.assertEqual([query["count"] for query in queries], [["20"], ["20"]])
        self.assertEqual([query["cursor"] for query in queries], [["0"], ["12"]])
        self.assertEqual([query["offset"] for query in queries], [["0"], ["12"]])
        self.assertEqual(queries[0]["search_id"], [""])
        self.assertEqual(queries[1]["search_id"], ["SEARCH-SESSION"])
        self.assertIn("search_engine", queries[0]["web_search_code"][0])
        self.assertEqual(
            [urlsplit(url).path for url, _ in session.get_calls],
            ["/api/search/item/full/", "/api/search/item/full/"],
        )

    def test_new_requests_initialize_identity_before_building_query(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            get=[
                response(
                    text=profile_html(),
                    url="https://www.tiktok.com/",
                    headers={"x-ms-token": "page-token"},
                ),
                response(
                    {
                        "statusCode": 0,
                        "itemList": [{"id": "7350000000000000001"}],
                        "hasMore": False,
                        "cursor": 1,
                    }
                ),
            ],
            post=[response({}, headers={"set-cookie": "msToken=strong-token; Path=/"})],
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )

        result = client.search_videos("fixture", limit=1, page_size=1)

        self.assertEqual(result["total"], 1)
        query = parse_qs(urlsplit(session.get_calls[-1][0]).query)
        self.assertEqual(query["device_id"], ["device-123"])
        self.assertEqual(query["odinId"], ["odin-456"])
        self.assertEqual(query["WebIdLastTime"], ["1700000000"])

    def test_search_videos_rejects_bad_pagination_tokens(self) -> None:
        cases = [
            (
                {"status_code": 0, "item_list": [], "has_more": 1, "cursor": 0},
                "advance",
            ),
            (
                {"status_code": 0, "item_list": [], "has_more": 1, "cursor": 1},
                "search_id or rid",
            ),
            (
                {
                    "status_code": 0,
                    "item_list": [],
                    "has_more": 1,
                    "cursor": 1,
                    "extra": {"logid": "one"},
                    "log_pb": {"impr_id": "two"},
                },
                "conflicting",
            ),
        ]
        for payload, message in cases:
            with self.subTest(message=message):
                client = TikTokClient(
                    session=FakeSession(get=[response(payload)]),
                    signer=FakeSigner(),
                    retries=0,
                    request_interval=0,
                )
                mark_session_ready(client)
                with self.assertRaisesRegex(TikTokResponseError, message):
                    client.search_videos("fixture")

        self.assertEqual(
            TikTokClient._search_tokens(
                {
                    "search_id": "EXPLICIT-SESSION",
                    "extra": {"logid": "REQUEST-TRACE"},
                    "log_pb": {"impr_id": "REQUEST-TRACE"},
                    "rid": "RID-VALUE",
                }
            ),
            ("EXPLICIT-SESSION", "RID-VALUE"),
        )

        retained_client = TikTokClient(
            session=FakeSession(
                get=[
                    response(
                        {
                            "statusCode": 0,
                            "itemList": [],
                            "hasMore": True,
                            "cursor": 1,
                            "extra": {"logid": "STABLE-SESSION"},
                        }
                    ),
                    response(
                        {
                            "statusCode": 0,
                            "itemList": [{"id": "7350000000000000001"}],
                            "hasMore": True,
                            "cursor": 2,
                        }
                    ),
                ]
            ),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(retained_client)
        retained = retained_client.search_videos("fixture", limit=1, page_size=1)
        self.assertEqual(retained["search_id"], "STABLE-SESSION")

    def test_general_search_normalizes_mixed_cards_and_continuation(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            get=[
                response(
                    {
                        "status_code": 0,
                        "data": [
                            {
                                "type": 1,
                                "common": {"doc_id_str": "VIDEO-CARD"},
                                "item": {
                                    "id": "7350000000000000001",
                                    "desc": "Fixture video",
                                    "author": {
                                        "id": "100",
                                        "secUid": "SEC-VIDEO",
                                        "uniqueId": "fixture.video",
                                        "nickname": "Fixture Video",
                                    },
                                    "stats": {"playCount": 22},
                                    "video": {
                                        "playAddr": {
                                            "urlList": [
                                                "https://cdn.example/video.mp4"
                                            ]
                                        }
                                    },
                                },
                            },
                            {
                                "type": "4",
                                "view_more": 1,
                                "user_list": [
                                    {
                                        "user_info": {
                                            "uid": "200",
                                            "sec_uid": "SEC-USER",
                                            "unique_id": "fixture.user",
                                            "nickname": "Fixture User",
                                            "custom_verify": "Fixture verified",
                                            "follower_count": 321,
                                        }
                                    }
                                ],
                            },
                            {
                                "type": 88,
                                "stream_url": "SECRET-MUST-NOT-LEAK",
                            },
                        ],
                        "has_more": 1,
                        "cursor": 19,
                        "extra": {"logid": "GENERAL-TRACE"},
                        "log_pb": {"impr_id": "GENERAL-TRACE"},
                        "rid": "GENERAL-RID",
                    }
                )
            ]
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )
        mark_session_ready(client)

        result = client.search_general(
            " fixture general ",
            limit=12,
            offset=7,
            search_id=" INITIAL ",
        )

        self.assertEqual(result["keyword"], "fixture general")
        self.assertEqual(result["offset"], "7")
        self.assertEqual(result["cursor"], "19")
        self.assertEqual(result["search_id"], "GENERAL-TRACE")
        self.assertEqual(
            [item["type"] for item in result["results"]],
            ["video", "user", "unknown"],
        )
        self.assertEqual(
            result["results"][1]["users"][0]["stats"]["followers"],
            321,
        )
        self.assertNotIn("SECRET-MUST-NOT-LEAK", json.dumps(result))
        query = parse_qs(str(signer.calls[0]["raw_query"]))
        self.assertEqual(query["count"], ["12"])
        self.assertEqual(query["cursor"], ["7"])
        self.assertEqual(query["offset"], ["7"])
        self.assertEqual(query["search_id"], ["INITIAL"])
        self.assertEqual(
            urlsplit(session.get_calls[0][0]).path,
            "/api/search/general/full/",
        )

    def test_user_and_music_search_preserve_tokens_and_deduplicate(self) -> None:
        user_signer = FakeSigner()
        user_session = FakeSession(
            get=[
                response(
                    {
                        "user_list": [
                            {
                                "user_info": {
                                    "user_id": 9007199254740993,
                                    "sec_uid": "SEC-A",
                                    "unique_id": "fixture.alpha",
                                    "nickname": "Fixture Alpha",
                                    "follower_count": "1200",
                                }
                            }
                        ],
                        "has_more": 1,
                        "cursor": 10,
                        "rid": "RID-ONE",
                    }
                ),
                response(
                    {
                        "userList": [
                            {
                                "userInfo": {
                                    "id": "9007199254740993",
                                    "secUid": "SEC-A",
                                }
                            },
                            {
                                "userInfo": {
                                    "id": "9007199254740994",
                                    "secUid": "SEC-B",
                                    "uniqueId": "fixture.beta",
                                    "nickname": "Fixture Beta",
                                }
                            },
                            {
                                "userInfo": {
                                    "id": "9007199254740995",
                                    "secUid": "SEC-C",
                                    "nickname": "Fixture Without Handle",
                                }
                            },
                        ],
                        "hasMore": False,
                        "cursor": "20",
                        "search_id": "SEARCH-FINAL",
                        "rid": "RID-TWO",
                    }
                ),
            ]
        )
        user_client = TikTokClient(
            session=user_session,
            signer=user_signer,
            retries=0,
            request_interval=0,
        )
        mark_session_ready(user_client)

        users = user_client.search_users(
            "fixture people",
            limit=3,
            offset=5,
            search_id="INITIAL",
        )

        self.assertEqual(users["total"], 3)
        self.assertEqual(users["cursor"], "20")
        self.assertEqual(users["search_id"], "SEARCH-FINAL")
        self.assertEqual(users["users"][0]["id"], "9007199254740993")
        self.assertEqual(
            users["users"][0]["profile_url"],
            "https://www.tiktok.com/@fixture.alpha",
        )
        self.assertTrue(users["users"][0]["profile_url_available"])
        self.assertEqual(users["users"][2]["profile_url"], "")
        self.assertFalse(users["users"][2]["profile_url_available"])
        user_queries = [
            parse_qs(str(call["raw_query"]))
            for call in user_signer.calls
        ]
        self.assertNotIn("count", user_queries[0])
        self.assertEqual(user_queries[1]["search_id"], ["RID-ONE"])

        music_signer = FakeSigner()
        music_session = FakeSession(
            get=[
                response(
                    {
                        "data": [
                            {
                                "music_info": {
                                    "id": 9007199254740995,
                                    "title": "Fixture Sound",
                                    "author": "Fixture Artist",
                                    "owner_handle": "fixture.artist",
                                    "owner_nickname": "Fixture Artist",
                                    "video_duration": 33,
                                    "is_original": 1,
                                    "user_count": "8",
                                    "play_url": {
                                        "url_list": [
                                            "https://cdn.example/sound.mp3"
                                        ]
                                    },
                                }
                            }
                        ],
                        "has_more": False,
                        "cursor": 15,
                        "search_id": "MUSIC-FINAL",
                    }
                )
            ]
        )
        music_client = TikTokClient(
            session=music_session,
            signer=music_signer,
            retries=0,
            request_interval=0,
        )
        mark_session_ready(music_client)

        music = music_client.search_music(
            "fixture sound",
            limit=3,
            offset=5,
            search_id="MUSIC-START",
        )

        self.assertEqual(music["music"][0]["id"], "9007199254740995")
        self.assertEqual(music["music"][0]["duration"], 33)
        self.assertTrue(music["music"][0]["original"])
        self.assertEqual(music["music"][0]["stats"]["videos"], 8)
        music_query = parse_qs(str(music_signer.calls[0]["raw_query"]))
        self.assertEqual(music_query["count"], ["3"])
        self.assertEqual(music_query["offset"], ["5"])

    def test_live_and_photo_search_return_bounded_public_shapes(self) -> None:
        live_session = FakeSession(
            get=[
                response(
                    {
                        "data": [
                            {
                                "live_info": {
                                    "raw_data": json.dumps(
                                        {
                                            "id_str": "9007199254740997",
                                            "title": "Fixture live",
                                            "status": 2,
                                            "user_count": 42,
                                            "owner": {
                                                "id_str": "7001",
                                                "display_id": "fixture.live",
                                            },
                                            "stream_url": {
                                                "rtmp_pull_url": "SECRET"
                                            },
                                        }
                                    ),
                                    "room_info": {
                                        "has_commerce_goods": True,
                                        "is_battle": False,
                                    },
                                }
                            }
                        ],
                        "cursor": 12,
                        "has_more": False,
                        "extra": {"logid": "LIVE-TRACE"},
                    }
                )
            ]
        )
        live_client = TikTokClient(
            session=live_session,
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(live_client)

        live = live_client.search_live("fixture live")

        self.assertEqual(live["rooms"][0]["id"], "9007199254740997")
        self.assertTrue(live["rooms"][0]["has_commerce_goods"])
        self.assertNotIn("SECRET", json.dumps(live))

        photo_session = FakeSession(
            get=[
                response(
                    {
                        "item_list": [
                            {
                                "id": "9007199254740998",
                                "desc": "Fixture gallery",
                                "author": {
                                    "id": "101",
                                    "secUid": "SEC-PHOTO",
                                    "uniqueId": "fixture.photo",
                                },
                                "video": {
                                    "playAddr": {
                                        "urlList": ["SECRET-VIDEO"]
                                    }
                                },
                                "imagePost": {
                                    "title": "Fixture title",
                                    "images": [
                                        {
                                            "imageURL": {
                                                "urlList": [
                                                    "https://cdn.example/a.webp",
                                                    "https://cdn.example/a.webp",
                                                ]
                                            },
                                            "imageWidth": 1080,
                                            "imageHeight": 1440,
                                        }
                                    ],
                                },
                            }
                        ],
                        "has_more": False,
                        "cursor": 12,
                        "rid": "PHOTO-RID",
                    }
                )
            ]
        )
        photo_client = TikTokClient(
            session=photo_session,
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(photo_client)

        photos = photo_client.search_photos("fixture photos")

        self.assertEqual(photos["photos"][0]["image_post"]["image_count"], 1)
        self.assertEqual(
            photos["photos"][0]["image_post"]["images"][0]["urls"],
            ["https://cdn.example/a.webp"],
        )
        self.assertNotIn("SECRET-VIDEO", json.dumps(photos))

    def test_search_suggestions_and_trending_words_skip_identity_and_signer(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            get=[
                response(
                    {
                        "sug_list": [
                            {
                                "content": "python coding",
                                "sug_type": "query",
                                "word_record": {
                                    "group_id": "8869171464509703876",
                                    "words_position": 0,
                                    "words_lang": "en",
                                },
                                "extra_info": {},
                            },
                            {
                                "content": "python creator",
                                "sug_type": "",
                                "word_record": {
                                    "group_id": "1904615180402165457",
                                    "words_position": 1,
                                },
                                "extra_info": {
                                    "lang": "en",
                                    "sug_user_id": "7171472358220858373",
                                    "sug_sec_user_id": "SEC-SUGGEST",
                                    "sug_uniq_id": "python.creator",
                                    "nickname": "Python Creator",
                                },
                            },
                        ],
                        "words_query_record": {"query_id": "QUERY-ID"},
                        "rid": "SUGGEST-RID",
                        "status_code": 0,
                    }
                ),
                response(
                    {
                        "status_code": 0,
                        "trending_search_words": [
                            {
                                "trendingSearchWord": "Fixture Alpha",
                                "trendingSearchWordType": "2",
                            },
                            {
                                "trendingSearchWord": "Fixture Alpha",
                                "trendingSearchWordType": "2",
                            },
                            {
                                "trendingSearchWord": "Fixture Beta",
                                "trendingSearchWordType": "",
                            },
                        ],
                    }
                ),
            ]
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )

        suggestions = client.search_suggestions(" python typing ")
        trending = client.get_trending_search_words(region="us", limit=3)

        self.assertEqual(suggestions["query_id"], "QUERY-ID")
        self.assertEqual(
            suggestions["suggestions"][1]["user"]["unique_id"],
            "python.creator",
        )
        self.assertEqual(
            [item["word"] for item in trending["words"]],
            ["Fixture Alpha", "Fixture Beta"],
        )
        self.assertEqual(signer.calls, [])
        self.assertEqual(session.post_calls, [])
        self.assertEqual(
            [urlsplit(url).path for url, _kwargs in session.get_calls],
            [
                "/api/search/general/preview/",
                "/api/trending/searchwords/",
            ],
        )
        self.assertEqual(
            parse_qs(urlsplit(session.get_calls[0][0]).query)["keyword"],
            ["python typing"],
        )

    def test_new_search_inputs_and_pagination_fail_before_unbounded_work(self) -> None:
        client = TikTokClient(
            session=FakeSession(),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        for method in (
            client.search_general,
            client.search_users,
            client.search_music,
            client.search_live,
            client.search_photos,
        ):
            with self.subTest(method=method.__name__):
                empty = method(
                    " fixture ",
                    limit=0,
                    offset=12,
                    search_id=" START ",
                )
                self.assertEqual(empty["cursor"], "12")
                self.assertEqual(empty["search_id"], "START")
        self.assertEqual(client.session.get_calls, [])

        stalled = TikTokClient(
            session=FakeSession(
                get=[
                    response(
                        {
                            "user_list": [],
                            "has_more": True,
                            "cursor": 0,
                            "rid": "RID",
                        }
                    )
                ]
            ),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(stalled)
        with self.assertRaisesRegex(TikTokResponseError, "advance"):
            stalled.search_users("fixture", limit=1)

        with self.assertRaises(TikTokInputError):
            client.search_suggestions(" ")
        with self.assertRaises(TikTokInputError):
            client.get_trending_search_words(region="USA")

    def test_tag_and_music_detail_shared_fixtures(self) -> None:
        tag_fixture = NEW_CAPABILITIES["tag"]
        music_fixture = NEW_CAPABILITIES["music"]
        signer = FakeSigner()
        session = FakeSession(
            get=[response(tag_fixture["payload"]), response(music_fixture["payload"])]
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )
        mark_session_ready(client)

        tag = client.get_tag("#" + tag_fixture["name"])
        music = client.get_music(music_fixture["music_id"])

        self.assertEqual(tag, tag_fixture["expected"])
        self.assertEqual(music, music_fixture["expected"])
        queries = [parse_qs(str(call["raw_query"])) for call in signer.calls]
        self.assertEqual(queries[0]["challengeName"], [tag_fixture["name"]])
        self.assertEqual(queries[1]["musicId"], [music_fixture["music_id"]])
        self.assertEqual(
            [urlsplit(url).path for url, _ in session.get_calls],
            ["/api/challenge/detail/", "/api/music/detail/"],
        )

    def test_detail_normalizers_fall_back_from_explicit_null_fields(self) -> None:
        tag = TikTokClient._normalize_tag(
            {
                "challengeInfo": {
                    "challenge": {
                        "id": "123",
                        "title": "STRASSE",
                        "stats": {"videoCount": 7},
                    },
                    "stats": None,
                }
            },
            expected_name="Straße",
        )
        self.assertEqual(tag["stats"]["videos"], 7)

        music = TikTokClient._normalize_music(
            {
                "musicInfo": {"music": None, "author": None, "stats": None},
                "music": {
                    "id": "456",
                    "title": "fallback",
                    "author": {"nickname": "Fixture Author"},
                },
                "stats": {"videoCount": 9},
            },
            expected_id="456",
        )
        self.assertEqual(music["author_name"], "Fixture Author")
        self.assertEqual(music["stats"]["videos"], 9)

    def test_detail_responses_are_bound_to_requested_identity(self) -> None:
        tag_payload = json.loads(json.dumps(NEW_CAPABILITIES["tag"]["payload"]))
        tag_payload["challengeInfo"]["challenge"]["title"] = "DifferentTag"
        tag_client = TikTokClient(
            session=FakeSession(get=[response(tag_payload)]),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(tag_client)
        with self.assertRaisesRegex(TikTokResponseError, "name mismatch"):
            tag_client.get_tag(NEW_CAPABILITIES["tag"]["name"])

        music_payload = json.loads(json.dumps(NEW_CAPABILITIES["music"]["payload"]))
        music_payload["musicInfo"]["music"]["id"] = "7223827501163006767"
        music_client = TikTokClient(
            session=FakeSession(get=[response(music_payload)]),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(music_client)
        with self.assertRaisesRegex(TikTokResponseError, "ID mismatch"):
            music_client.get_music(NEW_CAPABILITIES["music"]["music_id"])

    def test_tag_and_music_video_lists_deduplicate_and_clamp_page_size(self) -> None:
        cases = [
            ("tag_videos", "get_tag_videos", "tag_id", "challengeID", "/api/challenge/item_list/"),
            ("music_videos", "get_music_videos", "music_id", "musicID", "/api/music/item_list/"),
        ]
        for fixture_name, method_name, id_field, query_field, path in cases:
            with self.subTest(method=method_name):
                fixture = NEW_CAPABILITIES[fixture_name]
                signer = FakeSigner()
                session = FakeSession(get=[response(page) for page in fixture["pages"]])
                client = TikTokClient(
                    session=session,
                    signer=signer,
                    retries=0,
                    request_interval=0,
                )
                mark_session_ready(client)

                result = getattr(client, method_name)(
                    fixture[id_field], limit=50, page_size=99
                )

                self.assertEqual(
                    [video["id"] for video in result["videos"]], fixture["expected_ids"]
                )
                self.assertEqual(result[id_field], fixture[id_field])
                self.assertEqual(result["total"], 2)
                self.assertEqual(result["cursor"], "66" if id_field == "tag_id" else "20")
                self.assertFalse(result["has_more"])
                for call in signer.calls:
                    query = parse_qs(str(call["raw_query"]))
                    self.assertEqual(query[query_field], [fixture[id_field]])
                    self.assertEqual(query["count"], ["30"])
                self.assertEqual(
                    [urlsplit(url).path for url, _ in session.get_calls], [path, path]
                )

    def test_new_list_limits_and_repeated_cursors_are_guarded(self) -> None:
        client = TikTokClient(
            session=FakeSession(),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(client)
        self.assertEqual(client.search_videos("fixture", limit=0)["videos"], [])
        self.assertEqual(client.get_tag_videos("123", limit=0)["videos"], [])
        self.assertEqual(client.get_music_videos("456", limit=0)["videos"], [])
        self.assertEqual(client.session.get_calls, [])

        repeated = {
            "statusCode": 0,
            "itemList": [],
            "hasMore": True,
            "cursor": "0",
        }
        repeated_client = TikTokClient(
            session=FakeSession(get=[response(repeated)]),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )
        mark_session_ready(repeated_client)
        with self.assertRaisesRegex(TikTokResponseError, "did not advance"):
            repeated_client.get_tag_videos("123")

        for method, value in [
            (client.search_videos, "  "),
            (client.get_tag, "#"),
            (client.get_tag_videos, "not-an-id"),
            (client.get_tag_videos, "１２３"),
            (client.get_music, "-1"),
            (client.get_music_videos, "0"),
        ]:
            with self.subTest(method=method.__name__):
                with self.assertRaises(TikTokInputError):
                    method(value)

        self.assertFalse(TikTokClient._has_more({"has_more": "0"}))
        self.assertTrue(TikTokClient._has_more({"hasMore": "true"}))
        with self.assertRaises(TikTokInputError):
            client._resolve_video("１２３")

    def test_signed_request_retries_connection_errors_without_network(self) -> None:
        clock = FakeClock()
        signer = TimedFakeSigner(clock)
        session = TimedFakeSession(
            clock,
            get=[
                requests.exceptions.ConnectionError("fixture connection failure"),
                response({"statusCode": 0, "value": "ok"}),
            ]
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=1,
            request_interval=3,
        )
        mark_session_ready(client)

        with patch(
            "reverse.tiktok_reverse.client.time.monotonic",
            side_effect=clock.monotonic,
        ), patch(
            "reverse.tiktok_reverse.client.time.sleep",
            side_effect=clock.sleep,
        ):
            result = client._signed_get(
                "/api/fixture/", [("z", "last"), ("a", "first")], referer="https://www.tiktok.com/"
            )

        self.assertEqual(result["value"], "ok")
        self.assertEqual([call["raw_query"] for call in signer.calls], ["a=first&z=last"] * 2)
        self.assertEqual([call["counters"]["txr"] for call in signer.calls], [24, 24])
        self.assertEqual(
            session.request_starts,
            [("GET", 1000.0), ("GET", 1003.0)],
        )
        self.assertEqual(signer.sign_starts, [1000.0, 1003.0])
        self.assertEqual(clock.sleeps[0], 0.4)
        self.assertAlmostEqual(clock.sleeps[1], 2.6)

    def test_signed_request_retries_only_transient_http_responses(self) -> None:
        retry_session = FakeSession(
            get=[
                response({}, status=503),
                response({"statusCode": 0, "value": "ok"}),
            ]
        )
        retry_client = TikTokClient(
            session=retry_session,
            signer=FakeSigner(),
            retries=1,
            request_interval=0,
        )
        mark_session_ready(retry_client)

        with patch("reverse.tiktok_reverse.client.time.sleep") as sleep:
            result = retry_client._signed_get(
                "/api/fixture/", [], referer="https://www.tiktok.com/"
            )

        self.assertEqual(result["value"], "ok")
        sleep.assert_called_once_with(0.4)

        error_signer = FakeSigner()
        error_session = FakeSession(
            get=[
                response({}, status=400),
                response({"statusCode": 0, "value": "must not be requested"}),
            ]
        )
        error_client = TikTokClient(
            session=error_session,
            signer=error_signer,
            retries=2,
            request_interval=0,
        )
        mark_session_ready(error_client)

        with patch("reverse.tiktok_reverse.client.time.sleep") as sleep:
            with self.assertRaisesRegex(TikTokResponseError, "HTTP 400"):
                error_client._signed_get(
                    "/api/fixture/", [], referer="https://www.tiktok.com/"
                )

        self.assertEqual(len(error_session.get_calls), 1)
        self.assertEqual(len(error_signer.calls), 1)
        sleep.assert_not_called()

    def test_reply_page_size_has_api_minimum_and_deduplicates(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            get=[
                response(
                    {
                        "statusCode": 0,
                        "comments": [{"cid": "r1"}],
                        "has_more": True,
                        "cursor": 20,
                    }
                ),
                response(
                    {
                        "statusCode": 0,
                        "comments": [{"cid": "r1"}, {"cid": "r2"}],
                        "has_more": False,
                        "cursor": 40,
                    }
                ),
            ]
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            retries=0,
            request_interval=0,
        )
        mark_session_ready(client)

        result = client.get_comment_replies("7351", "c1", page_size=1)

        self.assertEqual([reply["id"] for reply in result["replies"]], ["r1", "r2"])
        for signer_call in signer.calls:
            self.assertEqual(parse_qs(str(signer_call["raw_query"]))["count"], ["20"])

    def test_ms_token_bootstrap_posts_initial_and_telemetry_reports(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            get=[response(text=profile_html(), url="https://www.tiktok.com/")],
            post=[
                response({}, headers={"set-cookie": "msToken=initial-token; Path=/"}),
                response({}, headers={"set-cookie": "msToken=strong-token; Path=/"}),
            ],
        )
        client = TikTokClient(
            session=session,
            signer=signer,
            request_interval=0,
        )

        with patch("reverse.tiktok_reverse.client.time.time", return_value=1700000000.123):
            client._ensure_ms_token()

        self.assertEqual(client.ms_token, "strong-token")
        self.assertTrue(client._ms_token_ready)
        self.assertEqual(len(session.post_calls), 2)

        initial_url, initial_options = session.post_calls[0]
        self.assertEqual(initial_url, "https://mssdk.tiktokw.us/web/report")
        self.assertEqual(initial_options["params"], {"msToken": ""})
        initial_body = json.loads(str(initial_options["data"]))
        self.assertEqual(initial_body["magic"], 538969122)
        self.assertEqual(initial_body["strData"], "")

        telemetry_url, telemetry_options = session.post_calls[1]
        self.assertEqual(
            telemetry_url,
            "https://mssdk.tiktokw.us/web/report?report-signature=fixture",
        )
        self.assertEqual(
            telemetry_options["headers"]["Cookie"], "msToken=initial-token"
        )
        telemetry_body = json.loads(str(telemetry_options["data"]))
        self.assertEqual(telemetry_body["strData"], "encoded-telemetry")
        self.assertEqual(signer.calls[0]["raw_query"], "")
        self.assertEqual(signer.calls[0]["ms_token"], "initial-token")
        self.assertEqual(signer.calls[0]["body"], telemetry_options["data"])
        self.assertEqual(signer.telemetry_calls[0]["customInit"]["ttwid"], "device-123")

    def test_profile_network_error_is_wrapped(self) -> None:
        error = requests.exceptions.ConnectionError("fixture connection failure")
        client = TikTokClient(
            session=FakeSession(get=[error]),
            signer=FakeSigner(),
            retries=0,
            request_interval=0,
        )

        with self.assertRaisesRegex(TikTokResponseError, "profile request failed") as caught:
            client.get_profile("https://www.tiktok.com/@fixture")

        self.assertIs(caught.exception.__cause__, error)

    def test_negative_top_level_limits_are_rejected_before_http(self) -> None:
        client = TikTokClient(
            session=FakeSession(),
            signer=FakeSigner(),
            request_interval=0,
        )

        with self.assertRaises(TikTokInputError):
            client.get_user_videos("https://www.tiktok.com/@fixture", limit=-1)
        with self.assertRaises(TikTokInputError):
            client.get_comments("7351", limit=-1)
        with self.assertRaises(TikTokInputError):
            client.get_comments("7351", reply_limit=-1)
        with self.assertRaises(TikTokInputError):
            client.get_comment_replies("7351", "c1", limit=-1)


class TikTokCreativeStudioTest(unittest.TestCase):
    TASK_ID = "7667519430651838480"

    @staticmethod
    def _task_payload(status: str = "processing") -> dict[str, object]:
        code = 2 if status == "processing" else 0
        return {
            "task_id": TikTokCreativeStudioTest.TASK_ID,
            "status": status,
            "poll_after_ms": 5000 if status == "processing" else 0,
            "drafts": [
                {
                    "task_id": TikTokCreativeStudioTest.TASK_ID,
                    "draft_id": "7667519189036662801",
                    "status": status,
                    "draft_status": code,
                    "render_status": code,
                    "vid": "",
                    "watermark_vid": "",
                }
            ],
        }

    def test_credits_and_generation_use_browser_contract(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []
        credit_responses = deque(
            [
                {
                    "credits": "2000",
                    "bonus": "0",
                    "weekly_spent": "0",
                    "tier": 2,
                    "is_unlimited": False,
                },
                {
                    "credits": "1995",
                    "bonus": "0",
                    "weekly_spent": "5",
                    "tier": 2,
                    "is_unlimited": False,
                },
            ]
        )

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            referer: str,
        ) -> dict[str, object]:
            calls.append((path, list(entries), referer))
            if path.endswith("QueryCreditAccount"):
                return credit_responses.popleft()
            if path.endswith("get_miniapp_permission_with_allowlist"):
                return {
                    "permissions": {
                        "CreativeStudio/MiniApp/TextToVideo": {
                            "entry_pass": True,
                        }
                    },
                    "allowlist": [],
                }
            if path.endswith("generating-task-count"):
                return {"total": 0}
            if path.endswith("get_generate_max_count"):
                return {
                    "limits": {
                        "CreativeStudio/MiniApp/TextToVideo": 5,
                    }
                }
            return self._task_payload()

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        result = client.create_creative_studio_video(
            "一杯冰咖啡",
            duration=5,
        )

        self.assertEqual(result["source"], "tiktok_symphony_creative_studio")
        self.assertEqual(result["model_id"], "5000005")
        self.assertEqual(result["task_id"], self.TASK_ID)
        self.assertEqual(result["status"], "processing")
        self.assertEqual(result["credits"]["consumed"], 5)
        self.assertEqual(
            calls[4][1],
            [
                ("prompt", "一杯冰咖啡"),
                ("duration", "5"),
                ("enhancePrompt", "0"),
            ],
        )
        self.assertTrue(calls[4][2].endswith("region=row"))
        self.assertTrue(result["preflight"]["ready"])
        self.assertEqual(result["preflight"]["concurrency"]["maximum"], 5)
        self.assertTrue(result["submitted"])
        self.assertFalse(result["waited"])
        self.assertFalse(result["finished"])
        self.assertFalse(result["output_available"])
        self.assertEqual(result["outputs"], [])

    def test_generation_waits_for_terminal_video_output(self) -> None:
        calls: list[str] = []
        credit_responses = deque(
            [
                {
                    "credits": "2000",
                    "bonus": "0",
                    "weekly_spent": "0",
                    "tier": 2,
                    "is_unlimited": False,
                },
                {
                    "credits": "1995",
                    "bonus": "0",
                    "weekly_spent": "5",
                    "tier": 2,
                    "is_unlimited": False,
                },
            ]
        )
        vid = "v14033g50000d9k838nog65j01cfgom0"
        video = {
            "vid": vid,
            "duration": 5.062,
            "poster_url": "https://cdn.example/poster.jpeg",
            "video_url": "https://cdn.example/video.mp4",
            "variants": [
                {
                    "url": "https://cdn.example/video.mp4",
                    "backup_url": "https://backup.example/video.mp4",
                    "width": 720,
                    "height": 1280,
                    "size": 846648,
                    "bitrate": 1338045,
                    "fps": 24,
                    "definition": "720p",
                    "format": "mp4",
                }
            ],
        }

        def fetch(
            path: str,
            _entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append(path)
            if path.endswith("QueryCreditAccount"):
                return credit_responses.popleft()
            if path.endswith("get_miniapp_permission_with_allowlist"):
                return {
                    "permissions": {
                        "CreativeStudio/MiniApp/TextToVideo": {
                            "entry_pass": True,
                        }
                    },
                    "allowlist": [],
                }
            if path.endswith("generating-task-count"):
                return {"total": 0}
            if path.endswith("get_generate_max_count"):
                return {
                    "limits": {
                        "CreativeStudio/MiniApp/TextToVideo": 5,
                    }
                }
            if path.endswith("create_generate_task"):
                return self._task_payload()
            return {
                "task_id": self.TASK_ID,
                "status": "succeeded",
                "poll_after_ms": 0,
                "drafts": [
                    {
                        "task_id": self.TASK_ID,
                        "draft_id": "7667519189036662801",
                        "status": "succeeded",
                        "draft_status": 0,
                        "render_status": 0,
                        "vid": vid,
                        "watermark_vid": "",
                        "video": video,
                    }
                ],
            }

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        with patch("reverse.tiktok_reverse.client.time.sleep"):
            result = client.create_creative_studio_video(
                "一杯冰咖啡",
                wait=True,
            )

        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["waited"])
        self.assertTrue(result["finished"])
        self.assertTrue(result["output_available"])
        self.assertEqual(
            result["outputs"][0]["video_url"],
            "https://cdn.example/video.mp4",
        )
        self.assertEqual(
            calls.count(
                "/creative_bff_i18n/api/cue/generate-task/check"
            ),
            1,
        )

    def test_upload_and_i2v_generation_keep_reference_frames(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]]]] = []
        first_url = (
            "https://p19-creative-tool-sg.ibyteimg.com/"
            "tos-alisg-i/first.image"
        )
        last_url = (
            "https://p19-creative-tool-sg.ibyteimg.com/"
            "tos-alisg-i/last.image"
        )

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append((path, list(entries)))
            if path.endswith("upload/local-image"):
                return {
                    "image_url": first_url,
                    "image_uri": "tos-alisg-i/first",
                    "width": 720,
                    "height": 1280,
                }
            if path.endswith("QueryCreditAccount"):
                return {
                    "credits": "2000",
                    "bonus": "0",
                    "weekly_spent": "0",
                    "tier": 2,
                    "is_unlimited": False,
                }
            if path.endswith("get_miniapp_permission_with_allowlist"):
                return {
                    "permissions": {
                        "CreativeStudio/MiniApp/TextToVideo": {
                            "entry_pass": True,
                        },
                        "CreativeStudio/MiniApp/ImageToVideo": {
                            "entry_pass": True,
                        },
                    },
                    "allowlist": [],
                }
            if path.endswith("generating-task-count"):
                return {"total": 0}
            if path.endswith("get_generate_max_count"):
                return {
                    "limits": {
                        "CreativeStudio/MiniApp/TextToVideo": 5,
                        "CreativeStudio/MiniApp/ImageToVideo": 5,
                    }
                }
            return self._task_payload()

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "first.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            upload = client.upload_creative_studio_image(image)
        result = client.create_creative_studio_i2v(
            "把门牌挂到教室门上",
            first_frame_url=upload["image_url"],
            last_frame_url=last_url,
            duration=5,
        )

        upload_entries = calls[0][1]
        self.assertEqual(upload_entries[0], ("name", "first.png"))
        self.assertEqual(upload_entries[1], ("mimeType", "image/png"))
        self.assertGreater(len(upload_entries[2][1]), 4)
        self.assertEqual(result["model_id"], "4000005")
        self.assertEqual(result["mode"], "first_last_frame")
        self.assertEqual(result["references"]["count"], 2)
        self.assertEqual(result["references"]["first_frame_url"], first_url)
        self.assertEqual(result["references"]["last_frame_url"], last_url)
        self.assertEqual(
            calls[-1],
            (
                "/creative_bff_i18n/api/cue/i2v/create_generate_task",
                [
                    ("prompt", "把门牌挂到教室门上"),
                    ("duration", "5"),
                    ("firstFrameUrl", first_url),
                    ("lastFrameUrl", last_url),
                ],
            ),
        )

    def test_task_and_inputs_are_strictly_validated(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]]]] = []

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append((path, list(entries)))
            return self._task_payload("succeeded")

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        result = client.get_creative_studio_task(self.TASK_ID)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(calls[0][1], [("taskId", self.TASK_ID)])

        for kwargs in (
            {"prompt": "", "duration": 5},
            {"prompt": "fixture", "duration": 3},
            {"prompt": "fixture\nsecond line", "duration": 5},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(TikTokInputError):
                client.create_creative_studio_video(**kwargs)
        with self.assertRaises(TikTokInputError):
            client.get_creative_studio_task("not-a-task")

    def test_failed_task_recovers_from_history_when_check_is_invalid(self) -> None:
        failed_draft = {
            "task_id": self.TASK_ID,
            "draft_id": "7667519189036662801",
            "status": "failed",
            "draft_status": 3,
            "render_status": 3,
            "vid": "",
            "watermark_vid": "",
            "errors": {
                "generate_code": "10043300",
                "generate_message": "output audio policy violation",
                "render_code": "",
                "render_message": "",
            },
        }
        calls: list[str] = []

        def fetch(
            path: str,
            _entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append(path)
            if path.endswith("generate-task/check"):
                raise TikTokResponseError("invalid_response")
            return {
                "offset": 0,
                "limit": 30,
                "total": 1,
                "has_more": False,
                "next_offset": 1,
                "drafts": [failed_draft],
            }

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        result = client.get_creative_studio_task(self.TASK_ID)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["finished"])
        self.assertFalse(result["output_available"])
        self.assertEqual(
            result["recovered_from"],
            "/creative_bff_i18n/api/cue/history/tasks",
        )
        self.assertEqual(
            calls,
            [
                "/creative_bff_i18n/api/cue/generate-task/check",
                "/creative_bff_i18n/api/cue/history/tasks",
            ],
        )

    def test_preflight_reports_credit_and_concurrency_blockers(self) -> None:
        calls: list[str] = []

        def fetch(
            path: str,
            _entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append(path)
            if path.endswith("QueryCreditAccount"):
                return {
                    "credits": "4",
                    "bonus": "0",
                    "weekly_spent": "1996",
                    "tier": 2,
                    "is_unlimited": False,
                }
            if path.endswith("get_miniapp_permission_with_allowlist"):
                return {
                    "permissions": {
                        "CreativeStudio/MiniApp/TextToVideo": {
                            "entry_pass": True,
                        }
                    },
                    "allowlist": [],
                }
            if path.endswith("generating-task-count"):
                return {"total": 5}
            return {
                "limits": {
                    "CreativeStudio/MiniApp/TextToVideo": 5,
                }
            }

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        result = client.prepare_creative_studio_video(
            "fixture prompt",
            duration=5,
        )

        self.assertFalse(result["ready"])
        self.assertEqual(
            result["blockers"],
            ["insufficient_credits", "concurrency_limit"],
        )
        self.assertEqual(result["estimated_credits"], 5)
        self.assertEqual(result["concurrency"]["available"], 0)
        self.assertEqual(len(calls), 4)

        with self.assertRaisesRegex(
            TikTokResponseError,
            "insufficient_credits",
        ):
            client.create_creative_studio_video("fixture prompt", duration=5)
        self.assertFalse(
            any(path.endswith("create_generate_task") for path in calls)
        )

    def test_r2v_preflight_checks_existing_studio_videos_without_submit(
        self,
    ) -> None:
        first_vid = "v14033g50000d9k838nog65j01cfgom0"
        second_vid = "v14033g50000d9k83dvog65vd9o9k8q0"
        calls: list[tuple[str, list[tuple[str, str]]]] = []

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append((path, list(entries)))
            if path.endswith("video_info"):
                vid = entries[0][1]
                return {
                    "vid": vid,
                    "duration": 5.062,
                    "poster_url": f"https://cdn.example/{vid}.jpeg",
                    "video_url": f"https://cdn.example/{vid}.mp4",
                    "variants": [
                        {
                            "url": f"https://cdn.example/{vid}.mp4",
                            "width": 720,
                            "height": 1280,
                        }
                    ],
                }
            if path.endswith("QueryCreditAccount"):
                return {
                    "credits": "2000",
                    "bonus": "0",
                    "weekly_spent": "0",
                    "tier": 2,
                    "is_unlimited": False,
                }
            if path.endswith("get_miniapp_permission_with_allowlist"):
                return {
                    "permissions": {
                        "CreativeStudio/MiniApp/TextToVideo": {
                            "entry_pass": True,
                        }
                    },
                    "allowlist": [],
                }
            if path.endswith("generating-task-count"):
                return {"total": 0}
            if path.endswith("get_generate_max_count"):
                return {
                    "limits": {
                        "CreativeStudio/MiniApp/TextToVideo": 5,
                        "CreativeStudio/ReferenceToVideo/ReferenceToVideo": 5,
                    }
                }
            raise AssertionError(f"unexpected Creative Studio path: {path}")

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        result = client.prepare_creative_studio_r2v(
            "把视频里的产品替换为木质教师门牌",
            reference_vids=[first_vid, second_vid],
            duration=5,
        )

        self.assertFalse(result["ready"])
        self.assertEqual(
            result["blockers"],
            ["r2v_entry_pass_missing", "r2v_submission_not_verified"],
        )
        self.assertEqual(result["reference_count"], 2)
        self.assertAlmostEqual(result["reference_duration_sum"], 10.124)
        self.assertFalse(result["submission_verified"])
        self.assertEqual(
            [entries for path, entries in calls if path.endswith("video_info")],
            [[("vid", first_vid)], [("vid", second_vid)]],
        )
        self.assertFalse(any("gen_r2v_video" in path for path, _ in calls))

    def test_r2v_preflight_validates_reference_video_constraints(self) -> None:
        calls: list[str] = []
        durations = {
            "short": 1.99,
            "first": 7.6,
            "second": 7.6,
        }

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append(path)
            if not path.endswith("video_info"):
                raise AssertionError(f"unexpected Creative Studio path: {path}")
            vid = entries[0][1]
            return {
                "vid": vid,
                "duration": durations[vid],
                "poster_url": f"https://cdn.example/{vid}.jpeg",
                "video_url": f"https://cdn.example/{vid}.mp4",
                "variants": [
                    {
                        "url": f"https://cdn.example/{vid}.mp4",
                        "width": 720,
                        "height": 1280,
                    }
                ],
            }

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        for reference_vids in (
            [],
            ["first", "second", "short", "extra"],
            ["first", "first"],
        ):
            with self.subTest(reference_vids=reference_vids):
                with self.assertRaises(TikTokInputError):
                    client.prepare_creative_studio_r2v(
                        "fixture prompt",
                        reference_vids=reference_vids,
                    )
        self.assertEqual(calls, [])

        with self.assertRaisesRegex(TikTokInputError, "at least 2 seconds"):
            client.prepare_creative_studio_r2v(
                "fixture prompt",
                reference_vids=["short"],
            )
        with self.assertRaisesRegex(TikTokInputError, "less than 15.2"):
            client.prepare_creative_studio_r2v(
                "fixture prompt",
                reference_vids=["first", "second"],
            )
        self.assertFalse(any("gen_r2v_video" in path for path in calls))

    def test_ledger_history_detail_and_video_form_recovery_chain(self) -> None:
        draft_id = "7667519189036662801"
        vid = "v14033g50000d9k838nog65j01cfgom0"
        draft = {
            "task_id": self.TASK_ID,
            "draft_id": draft_id,
            "status": "succeeded",
            "draft_status": 0,
            "render_status": 0,
            "vid": vid,
            "watermark_vid": "v10033g50000d9k83dvog65vd9o9k8q0",
        }
        video = {
            "vid": vid,
            "duration": 5.062,
            "poster_url": "https://cdn.example/poster.jpeg",
            "video_url": "https://cdn.example/video.mp4",
            "variants": [
                {
                    "url": "https://cdn.example/video.mp4",
                    "backup_url": "https://backup.example/video.mp4",
                    "width": 720,
                    "height": 1280,
                    "size": 846648,
                    "bitrate": 1338045,
                    "fps": 24,
                    "definition": "720p",
                    "format": "mp4",
                }
            ],
        }
        calls: list[tuple[str, list[tuple[str, str]]]] = []

        def fetch(
            path: str,
            entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            calls.append((path, list(entries)))
            if path.endswith("QueryCreditLedgerEntries"):
                return {
                    "entries": [
                        {
                            "action": "generate",
                            "amount": -5,
                            "duration": 5,
                        }
                    ],
                    "has_more": True,
                    "next_cursor": "next-page",
                }
            if path.endswith("/history/tasks"):
                return {
                    "offset": 0,
                    "limit": 30,
                    "total": 1,
                    "has_more": False,
                    "next_offset": 1,
                    "drafts": [draft],
                }
            if path.endswith("/history/task/detail"):
                return {**draft, "video": video}
            return video

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        ledger = client.get_creative_studio_credit_ledger(limit=20)
        history = client.get_creative_studio_history()
        detail = client.get_creative_studio_task_detail(draft_id)
        video_result = client.get_creative_studio_video_info(vid)

        self.assertEqual(ledger["next_cursor"], "next-page")
        self.assertEqual(history["drafts"][0]["draft_id"], draft_id)
        self.assertEqual(detail["video"]["video_url"], video["video_url"])
        self.assertEqual(video_result["vid"], vid)
        self.assertEqual(calls[0][1], [("pageSize", "20")])
        self.assertEqual(
            calls[1][1],
            [("offset", "0"), ("limit", "30")],
        )
        self.assertEqual(calls[2][1], [("draftId", draft_id)])
        self.assertEqual(calls[3][1], [("vid", vid)])

        with self.assertRaises(TikTokInputError):
            client.get_creative_studio_task_detail("bad-id")
        with self.assertRaises(TikTokInputError):
            client.get_creative_studio_video_info("bad vid")
        with self.assertRaises(TikTokInputError):
            client.get_creative_studio_history(offset=-1)

    def test_download_selects_exact_definition_and_validates_mp4(self) -> None:
        vid = "v14033g50000d9k838nog65j01cfgom0"
        video = {
            "vid": vid,
            "duration": 5.062,
            "poster_url": "https://cdn.example/poster.jpeg",
            "video_url": "https://cdn.example/video-720.mp4",
            "variants": [
                {
                    "url": "https://cdn.example/video-720.mp4",
                    "backup_url": "https://backup.example/video-720.mp4",
                    "width": 720,
                    "height": 1280,
                    "size": 846648,
                    "bitrate": 1338045,
                    "fps": 24,
                    "definition": "720p",
                    "format": "mp4",
                },
                {
                    "url": "https://cdn.example/video-540.mp4",
                    "backup_url": "https://backup.example/video-540.mp4",
                    "width": 540,
                    "height": 960,
                    "size": 546648,
                    "bitrate": 933045,
                    "fps": 24,
                    "definition": "540p",
                    "format": "mp4",
                },
            ],
        }
        body = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00fixture-video"
        requests: list[tuple[str, float, str | None]] = []

        def open_video(request, *, timeout: float) -> DownloadResponse:
            requests.append(
                (
                    request.full_url,
                    timeout,
                    request.get_header("Referer"),
                )
            )
            return DownloadResponse(
                body,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(body)),
                },
            )

        client = TikTokClient(
            creative_fetch=lambda *_args: video,
            request_interval=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.mp4"
            with patch(
                "reverse.tiktok_reverse.client.urlopen",
                side_effect=open_video,
            ):
                result = client.download_creative_studio_video(
                    vid,
                    definition=" 720P ",
                    output_path=output,
                )

            self.assertEqual(output.read_bytes(), body)

        self.assertEqual(result["definition"], "720p")
        self.assertEqual(result["bytes"], len(body))
        self.assertEqual(
            requests,
            [
                (
                    "https://cdn.example/video-720.mp4",
                    20,
                    "https://ads.tiktok.com/creative/creativestudio/create?from_creative=signup&region=row",
                )
            ],
        )

    def test_download_uses_default_video_url_and_never_overwrites(self) -> None:
        vid = "v14033g50000d9k838nog65j01cfgom0"
        video = {
            "vid": vid,
            "duration": 5.062,
            "poster_url": "https://cdn.example/poster.jpeg",
            "video_url": "https://cdn.example/video-720.mp4",
            "variants": [
                {
                    "url": "https://cdn.example/video-540.mp4",
                    "backup_url": "https://backup.example/video-540.mp4",
                    "width": 540,
                    "height": 960,
                    "size": 546648,
                    "bitrate": 933045,
                    "fps": 24,
                    "definition": "540p",
                    "format": "mp4",
                },
                {
                    "url": "https://cdn.example/video-720.mp4",
                    "backup_url": "https://backup.example/video-720.mp4",
                    "width": 720,
                    "height": 1280,
                    "size": 846648,
                    "bitrate": 1338045,
                    "fps": 24,
                    "definition": "720p",
                    "format": "mp4",
                },
            ],
        }
        body = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00fixture-video"
        urls: list[str] = []

        def open_video(request, *, timeout: float) -> DownloadResponse:
            del timeout
            urls.append(request.full_url)
            return DownloadResponse(body, headers={"Content-Type": "video/mp4"})

        client = TikTokClient(
            creative_fetch=lambda *_args: video,
            request_interval=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.mp4"
            with patch(
                "reverse.tiktok_reverse.client.urlopen",
                side_effect=open_video,
            ):
                result = client.download_creative_studio_video(
                    vid,
                    output_path=output,
                )
            self.assertEqual(output.read_bytes(), body)
            self.assertEqual(result["definition"], "720p")
            with self.assertRaisesRegex(TikTokInputError, "already exists"):
                client.download_creative_studio_video(
                    vid,
                    output_path=output,
                )

        self.assertEqual(urls, ["https://cdn.example/video-720.mp4"])

    def test_download_rejects_non_mp4_body_without_creating_output(self) -> None:
        vid = "v14033g50000d9k838nog65j01cfgom0"
        video = {
            "vid": vid,
            "duration": 5.062,
            "poster_url": "https://cdn.example/poster.jpeg",
            "video_url": "https://cdn.example/video.mp4",
            "variants": [
                {
                    "url": "https://cdn.example/video.mp4",
                    "backup_url": "https://backup.example/video.mp4",
                    "width": 720,
                    "height": 1280,
                    "size": 846648,
                    "bitrate": 1338045,
                    "fps": 24,
                    "definition": "720p",
                    "format": "mp4",
                }
            ],
        }
        client = TikTokClient(
            creative_fetch=lambda *_args: video,
            request_interval=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.mp4"
            with patch(
                "reverse.tiktok_reverse.client.urlopen",
                return_value=DownloadResponse(
                    b"<html>expired</html>",
                    headers={"Content-Type": "video/mp4"},
                ),
            ), self.assertRaisesRegex(TikTokResponseError, "not an MP4"):
                client.download_creative_studio_video(vid, output_path=output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_model_catalog_distinguishes_callable_and_research_models(self) -> None:
        models = TikTokClient.get_creative_studio_models()["models"]

        self.assertEqual(models[0]["model_id"], "5000005")
        self.assertTrue(models[0]["callable"])
        self.assertEqual(
            [item["model_id"] for item in models[1:]],
            ["4000005", "2000004"],
        )
        self.assertTrue(models[1]["callable"])
        self.assertFalse(models[2]["callable"])
        self.assertTrue(models[2]["preflight_callable"])
        self.assertEqual(
            models[2]["reference_inputs"]["videos"]["maximum"],
            3,
        )

    def test_wait_timeout_returns_last_task_without_another_request(self) -> None:
        calls = 0

        def fetch(
            _path: str,
            _entries: list[tuple[str, str]],
            _referer: str,
        ) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return self._task_payload()

        client = TikTokClient(creative_fetch=fetch, request_interval=0)
        with (
            patch(
                "reverse.tiktok_reverse.client.time.monotonic",
                side_effect=[0.0, 0.0, 0.25, 1.0],
            ),
            patch("reverse.tiktok_reverse.client.time.sleep"),
        ):
            result = client._wait_creative_studio_task(
                self.TASK_ID,
                wait_timeout=1,
                poll_interval=5,
            )
        self.assertEqual(calls, 1)
        self.assertEqual(result["status"], "processing")
        self.assertTrue(result["wait_timeout_reached"])

    def test_wait_interruption_preserves_the_last_recoverable_task(self) -> None:
        client = TikTokClient(
            creative_fetch=lambda *_args: (_ for _ in ()).throw(
                TikTokResponseError("tab_unavailable")
            ),
            request_interval=0,
        )
        initial = self._task_payload()

        result = client._wait_creative_studio_task(
            self.TASK_ID,
            wait_timeout=60,
            poll_interval=5,
            initial_task=initial,
        )

        self.assertEqual(result["task_id"], self.TASK_ID)
        self.assertEqual(result["status"], "processing")
        self.assertTrue(result["wait_interrupted"])
        self.assertEqual(result["wait_error"], "tab_unavailable")


class TikTokCliTest(unittest.TestCase):
    def test_request_interval_default_and_explicit_zero_reach_client(self) -> None:
        cases = [
            (["video", "7351"], 3.0),
            (["--request-interval", "0", "video", "7351"], 0.0),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                args = cli._parser().parse_args(argv)
                fake_client = Mock()
                fake_client.get_video.return_value = {"id": "7351"}
                with patch.object(
                    cli, "TikTokClient", return_value=fake_client
                ) as constructor:
                    cli._run(args)
                constructor.assert_called_once_with(
                    timeout=20,
                    request_interval=expected,
                )

    def test_new_commands_dispatch_all_options(self) -> None:
        cases = [
            (
                ["search-videos", "fixture", "--limit", "7", "--page-size", "8"],
                "search_videos",
                ("fixture",),
                {"limit": 7, "page_size": 8},
            ),
            (
                [
                    "search-general",
                    "fixture",
                    "--limit",
                    "7",
                    "--offset",
                    "12",
                    "--search-id",
                    "GENERAL-ID",
                ],
                "search_general",
                ("fixture",),
                {"limit": 7, "offset": 12, "search_id": "GENERAL-ID"},
            ),
            (
                [
                    "search-users",
                    "fixture",
                    "--limit",
                    "8",
                    "--offset",
                    "20",
                    "--search-id",
                    "USER-ID",
                ],
                "search_users",
                ("fixture",),
                {"limit": 8, "offset": 20, "search_id": "USER-ID"},
            ),
            (
                [
                    "search-music",
                    "fixture",
                    "--limit",
                    "9",
                    "--offset",
                    "10",
                    "--search-id",
                    "MUSIC-ID",
                ],
                "search_music",
                ("fixture",),
                {"limit": 9, "offset": 10, "search_id": "MUSIC-ID"},
            ),
            (
                [
                    "search-live",
                    "fixture",
                    "--limit",
                    "10",
                    "--offset",
                    "12",
                    "--search-id",
                    "LIVE-ID",
                ],
                "search_live",
                ("fixture",),
                {"limit": 10, "offset": 12, "search_id": "LIVE-ID"},
            ),
            (
                [
                    "search-photo",
                    "fixture",
                    "--limit",
                    "11",
                    "--offset",
                    "24",
                    "--search-id",
                    "PHOTO-ID",
                ],
                "search_photos",
                ("fixture",),
                {"limit": 11, "offset": 24, "search_id": "PHOTO-ID"},
            ),
            (
                ["search-suggest", "fixture", "--limit", "6"],
                "search_suggestions",
                ("fixture",),
                {"limit": 6},
            ),
            (
                ["trending-searchwords", "--country", "JP", "--limit", "5"],
                "get_trending_search_words",
                (),
                {"region": "JP", "limit": 5},
            ),
            (["tag", "fixturetag"], "get_tag", ("fixturetag",), {}),
            (
                ["tag-videos", "123", "--limit", "9", "--page-size", "10"],
                "get_tag_videos",
                ("123",),
                {"limit": 9, "page_size": 10},
            ),
            (["music", "456"], "get_music", ("456",), {}),
            (
                ["music-videos", "456", "--limit", "11", "--page-size", "12"],
                "get_music_videos",
                ("456",),
                {"limit": 11, "page_size": 12},
            ),
            (
                [
                    "creative-trending-hashtags",
                    "--country",
                    "JP",
                    "--time-range",
                    "30",
                    "--industry-id",
                    "23000000000",
                    "--page",
                    "2",
                    "--limit",
                    "10",
                ],
                "get_creative_trending_hashtags",
                (),
                {
                    "country": "JP",
                    "time_range": 30,
                    "industry_id": "23000000000",
                    "page": 2,
                    "limit": 10,
                },
            ),
            (
                [
                    "creative-trending-videos",
                    "--country",
                    "DE",
                    "--time-range",
                    "7",
                    "--metric",
                    "completion",
                    "--content-label-ids",
                    "11002,11003",
                    "--page",
                    "1",
                    "--limit",
                    "4",
                ],
                "get_creative_trending_videos",
                (),
                {
                    "country": "DE",
                    "time_range": 7,
                    "metric": "completion",
                    "content_label_ids": "11002,11003",
                    "page": 1,
                    "limit": 4,
                },
            ),
            (
                [
                    "creative-trending-video-detail",
                    "7656166869774109983",
                    "--country",
                    "DE",
                    "--time-range",
                    "7",
                ],
                "get_creative_trending_video_detail",
                ("7656166869774109983",),
                {"country": "DE", "time_range": 7},
            ),
            (
                ["creative-studio-credits"],
                "get_creative_studio_credits",
                (),
                {},
            ),
            (
                ["creative-studio-permissions"],
                "get_creative_studio_permissions",
                (),
                {},
            ),
            (
                ["creative-studio-limits"],
                "get_creative_studio_generation_limits",
                (),
                {},
            ),
            (
                ["creative-studio-status"],
                "get_creative_studio_status",
                (),
                {},
            ),
            (
                ["creative-studio-models"],
                "get_creative_studio_models",
                (),
                {},
            ),
            (
                [
                    "creative-studio-prepare",
                    "一杯冰咖啡",
                    "--duration",
                    "8",
                    "--enhance-prompt",
                ],
                "prepare_creative_studio_video",
                ("一杯冰咖啡",),
                {
                    "duration": 8,
                    "enhance_prompt": True,
                },
            ),
            (
                [
                    "creative-studio-prepare-r2v",
                    "把参考视频产品替换为木质教师门牌",
                    "--reference-vid",
                    "v14033g50000d9k838nog65j01cfgom0",
                    "--reference-vid",
                    "v14033g50000d9k83dvog65vd9o9k8q0",
                    "--duration",
                    "8",
                ],
                "prepare_creative_studio_r2v",
                ("把参考视频产品替换为木质教师门牌",),
                {
                    "reference_vids": [
                        "v14033g50000d9k838nog65j01cfgom0",
                        "v14033g50000d9k83dvog65vd9o9k8q0",
                    ],
                    "duration": 8,
                },
            ),
            (
                [
                    "creative-studio-ledger",
                    "--cursor",
                    "next-page",
                    "--limit",
                    "10",
                ],
                "get_creative_studio_credit_ledger",
                (),
                {"cursor": "next-page", "limit": 10},
            ),
            (
                [
                    "creative-studio-history",
                    "--offset",
                    "30",
                    "--limit",
                    "15",
                ],
                "get_creative_studio_history",
                (),
                {"offset": 30, "limit": 15},
            ),
            (
                [
                    "creative-studio-task-detail",
                    "7667519189036662801",
                ],
                "get_creative_studio_task_detail",
                ("7667519189036662801",),
                {},
            ),
            (
                [
                    "creative-studio-video-info",
                    "v14033g50000d9k838nog65j01cfgom0",
                ],
                "get_creative_studio_video_info",
                ("v14033g50000d9k838nog65j01cfgom0",),
                {},
            ),
            (
                [
                    "creative-studio-download",
                    "v14033g50000d9k838nog65j01cfgom0",
                    "--definition",
                    "540p",
                    "--output",
                    "artifacts/result.mp4",
                ],
                "download_creative_studio_video",
                ("v14033g50000d9k838nog65j01cfgom0",),
                {
                    "definition": "540p",
                    "output_path": Path("artifacts/result.mp4"),
                },
            ),
            (
                [
                    "creative-studio-generate",
                    "一杯冰咖啡",
                    "--duration",
                    "8",
                    "--enhance-prompt",
                    "--wait",
                    "--wait-timeout",
                    "600",
                    "--poll-interval",
                    "6",
                ],
                "create_creative_studio_video",
                ("一杯冰咖啡",),
                {
                    "duration": 8,
                    "enhance_prompt": True,
                    "wait": True,
                    "wait_timeout": 600.0,
                    "poll_interval": 6.0,
                },
            ),
            (
                [
                    "creative-studio-task",
                    "7667519430651838480",
                    "--wait",
                ],
                "get_creative_studio_task",
                ("7667519430651838480",),
                {
                    "wait": True,
                    "wait_timeout": 900,
                    "poll_interval": 5,
                },
            ),
        ]
        for argv, method_name, positional, keyword in cases:
            with self.subTest(command=argv[0]):
                args = cli._parser().parse_args(argv)
                fake_client = Mock()
                getattr(fake_client, method_name).return_value = {"command": argv[0]}
                with patch.object(cli, "TikTokClient", return_value=fake_client):
                    result = cli._run(args)
                getattr(fake_client, method_name).assert_called_once_with(
                    *positional, **keyword
                )
                self.assertEqual(result, {"command": argv[0]})

    def test_comment_command_dispatches_all_options(self) -> None:
        args = cli._parser().parse_args(
            [
                "--timeout",
                "3.5",
                "comments",
                "7351",
                "--include-replies",
                "--reply-limit",
                "4",
                "--reply-page-size",
                "25",
                "--limit",
                "7",
                "--page-size",
                "30",
            ]
        )
        fake_client = Mock()
        fake_client.get_comments.return_value = {"comments": []}

        with patch.object(cli, "TikTokClient", return_value=fake_client) as constructor:
            result = cli._run(args)

        constructor.assert_called_once_with(timeout=3.5, request_interval=3.0)
        fake_client.get_comments.assert_called_once_with(
            "7351",
            include_replies=True,
            reply_limit=4,
            reply_page_size=25,
            limit=7,
            page_size=30,
        )
        self.assertEqual(result, {"comments": []})

    def test_main_writes_utf8_json_or_reports_domain_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            args = SimpleNamespace(json_output=output)
            with patch.object(cli, "_parser") as parser, patch.object(
                cli, "_run", return_value={"title": "\u6807\u9898"}
            ):
                parser.return_value.parse_args.return_value = args
                self.assertEqual(cli.main(), 0)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")), {"title": "\u6807\u9898"}
            )

        stderr = io.StringIO()
        args = SimpleNamespace(json_output=None)
        with patch.object(cli, "_parser") as parser, patch.object(
            cli, "_run", side_effect=TikTokInputError("bad input")
        ), patch("sys.stderr", stderr):
            parser.return_value.parse_args.return_value = args
            self.assertEqual(cli.main(), 1)
        self.assertEqual(stderr.getvalue(), "error: bad input\n")


if __name__ == "__main__":
    unittest.main()
