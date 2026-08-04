from __future__ import annotations

import base64
import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from curl_cffi import requests

from reverse.bilibili_reverse.client import APP_USER_AGENT, BilibiliClient
from reverse.bilibili_reverse.errors import BilibiliInputError, BilibiliResponseError
from reverse.bilibili_reverse.mobile_profile import MobileProfile


def response(
    payload: object | None = None,
    *,
    text: str | None = None,
    status: int = 200,
    url: str = "",
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.content = (text if text is not None else json.dumps(payload)).encode()
    result.default_encoding = "utf-8"
    return result


def grpc_response(payload_base64: str) -> requests.Response:
    payload = base64.b64decode(payload_base64)
    result = requests.Response()
    result.status_code = 200
    result.content = b"\x00" + len(payload).to_bytes(4, "big") + payload
    result.headers = {
        "content-type": "application/grpc",
        "grpc-status": "0",
    }
    return result


class FakeSession(requests.Session):
    def __init__(self, results: list[requests.Response | Exception] | None = None) -> None:
        super().__init__()
        self.results = deque(results or [])
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError(f"unexpected HTTP request: {url}")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result

    def post(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((url, kwargs))
        if not self.results:
            raise AssertionError(f"unexpected HTTP request: {url}")
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        if not result.url:
            result.url = url
        return result


class FakeSigner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def sign(self, params: object) -> dict[str, str]:
        copied = dict(params)  # type: ignore[arg-type]
        self.calls.append(copied)
        return {key: str(value) for key, value in copied.items()} | {
            "appkey": "fixture-app-key",
            "ts": "1700000000",
            "sign": "fixture-signature",
        }


class FakeWbiSigner:
    img_key = "fixture-img-key"
    sub_key = "fixture-sub-key"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def sign(self, params: object) -> dict[str, str]:
        copied = dict(params)  # type: ignore[arg-type]
        self.calls.append(copied)
        return {key: str(value) for key, value in copied.items()} | {
            "wts": "1700000000",
            "w_rid": "fixture-wbi-signature",
        }


def identity_payload() -> dict[str, object]:
    return {"code": 0, "data": {"b_3": "fixture-buvid3", "b_4": "fixture-buvid4"}}


def video_payload() -> dict[str, object]:
    return {
        "code": 0,
        "data": {
            "aid": 2,
            "bvid": "BV1xx411c7mD",
            "cid": 62131,
            "title": "fixture video",
            "desc": "fixture description",
            "ctime": 1_700_000_000,
            "pubdate": 1_700_000_100,
            "duration": 123,
            "tname": "demo",
            "pic": "https://fixture.test/cover.jpg",
            "owner": {"mid": 9, "name": "creator", "face": "avatar"},
            "stat": {"view": 11, "reply": 2, "like": 7},
            "dimension": {"width": 1920, "height": 1080},
            "pages": [{"cid": 62131, "page": 1}],
        },
    }


def mobile_profile() -> MobileProfile:
    return MobileProfile(
        version=1,
        buvid="XX0123456789ABCDEFFEDCBA9876543210ABC",
        device_id="AbCdEfGhIjKlMnOpQrStUvWxYz0",
        created_at="2026-07-25T01:02:03Z",
    )


class BilibiliClientTest(unittest.TestCase):
    def test_six_migrated_app_methods_cross_the_client_boundary(self) -> None:
        testdata = Path(__file__).with_name("testdata")
        rest = json.loads(
            (testdata / "app_rest.json").read_text(encoding="utf-8")
        )
        search = json.loads(
            (testdata / "app_search_type.json").read_text(encoding="utf-8")
        )
        pgc = json.loads(
            (testdata / "app_pgc_tabs.json").read_text(encoding="utf-8")
        )
        reply = json.loads(
            (testdata / "app_comment_replies_proto.json").read_text(
                encoding="utf-8"
            )
        )
        session = FakeSession(
            [
                response(rest["video_detail"]["response"]),
                response(rest["comments_hot"]["response"]),
                grpc_response(
                    reply["response_payloads_base64"][0]
                ),
                grpc_response(search["responses"][0]["protobuf_base64"]),
                response(pgc["cinema"]["response"]),
                response(pgc["bangumi"]["response"]),
            ]
        )
        signer = FakeSigner()
        client = BilibiliClient(
            session=session,
            app_session=session,
            signer=signer,  # type: ignore[arg-type]
            mobile_profile=mobile_profile(),
            retries=0,
        )

        detail = client.get_app_video_detail("av2")
        comments = client.get_app_comments("av2", limit=1, page_size=1)
        replies = client.get_app_comment_replies(
            "av2",
            "495059",
            limit=1,
            page_size=1,
        )
        results = client.search_app_by_type(
            "python",
            order=4,
            limit=1,
            page_size=1,
        )
        cinema = client.get_app_cinema_tab()
        bangumi = client.get_app_bangumi_tab()

        self.assertEqual(detail["video"]["aid"], "2")
        self.assertEqual(comments["comments"][0]["id"], "495059")
        self.assertEqual(replies["replies"][0]["id"], "1")
        self.assertEqual(results["items"][0]["card_type"], "av")
        self.assertEqual(cinema["tab"], "cinema")
        self.assertEqual(bangumi["tab"], "bangumi")
        self.assertEqual(
            [urlsplit(url).path for url, _ in session.calls],
            [
                "/x/v2/view",
                "/x/v2/reply/main",
                "/bilibili.main.community.reply.v1.Reply/DetailList",
                "/bilibili.polymer.app.search.v1.Search/SearchByType",
                "/pgc/page/cinema/tab",
                "/pgc/page/bangumi",
            ],
        )
        self.assertEqual(len(signer.calls), 4)
        self.assertTrue(
            all(
                options["headers"]["buvid"] == mobile_profile().buvid
                for _, options in session.calls
            )
        )
        self.assertTrue(
            all(options["allow_redirects"] is False for _, options in session.calls)
        )

    def test_app_transport_uses_an_isolated_header_and_cookie_session(self) -> None:
        web_session = FakeSession()
        web_session.headers["X-Web-Only"] = "fixture"
        web_session.cookies.set(
            "SESSDATA",
            "fixture-secret",
            domain=".bilibili.com",
        )

        client = BilibiliClient(
            session=web_session,
            signer=FakeSigner(),  # type: ignore[arg-type]
            retries=0,
        )

        self.assertIsNot(client.app_session, web_session)
        self.assertNotIn("X-Web-Only", client.app_session.headers)
        self.assertIsNot(client.app_session.cookies, web_session.cookies)
        self.assertFalse(client.app_session.default_headers)
        self.assertEqual(client.app_session.impersonate, "chrome")

    def test_wbi_playurl_uses_gaia_parameters_and_returns_dash(self) -> None:
        wbi_signer = FakeWbiSigner()
        session = FakeSession(
            [
                response(identity_payload()),
                response(video_payload()),
                response(
                    {
                        "code": 0,
                        "data": {
                            "quality": 64,
                            "dash": {"video": [{"id": 64}], "audio": [{"id": 30280}]},
                        },
                    }
                ),
            ]
        )
        client = BilibiliClient(
            session=session,
            signer=FakeSigner(),
            wbi_signer=wbi_signer,  # type: ignore[arg-type]
            retries=0,
        )

        result = client.get_video_playurl(
            "BV1xx411c7mD", quality=64, prefer_wbi=True
        )

        self.assertEqual(result["source"], "wbi")
        self.assertEqual(result["playurl"]["quality"], 64)
        self.assertEqual(wbi_signer.calls[0]["gaia_source"], "pre-load")
        self.assertEqual(wbi_signer.calls[0]["avid"], "2")
        self.assertEqual(
            session.calls[-1][1]["params"]["w_rid"], "fixture-wbi-signature"
        )

    def test_wbi_voucher_falls_back_to_legacy_playurl(self) -> None:
        session = FakeSession(
            [
                response(identity_payload()),
                response(video_payload()),
                response({"code": 0, "data": {"v_voucher": "fixture"}}),
                response({"code": 0, "data": {"quality": 32, "durl": [{"url": "media"}]}}),
            ]
        )
        client = BilibiliClient(
            session=session,
            signer=FakeSigner(),
            wbi_signer=FakeWbiSigner(),  # type: ignore[arg-type]
            retries=0,
        )

        result = client.get_video_playurl(
            "BV1xx411c7mD", quality=32, prefer_wbi=True
        )

        self.assertEqual(result["source"], "legacy")
        self.assertEqual(result["playurl"]["durl"][0]["url"], "media")
        self.assertEqual(
            [urlsplit(url).path for url, _ in session.calls][-2:],
            ["/x/player/wbi/playurl", "/x/player/playurl"],
        )

    def test_web_app_and_live_requests_keep_transport_headers_separate(self) -> None:
        signer = FakeSigner()
        session = FakeSession(
            [
                response(identity_payload()),
                response(video_payload()),
                response(
                    {
                        "code": 0,
                        "data": {
                            "card": {
                                "mid": 2,
                                "name": "test user",
                                "fans": 3,
                                "attention": 4,
                                "level_info": {"current_level": 5},
                            },
                            "archive": {"count": 6},
                        },
                    }
                ),
                response({"code": 0, "data": {"room_id": 10, "title": "live"}}),
            ]
        )
        client = BilibiliClient(session=session, signer=signer, retries=0)

        with patch(
            "reverse.bilibili_reverse.client.load_mobile_profile",
            side_effect=AssertionError("既有 App 命令不应创建移动身份"),
        ):
            video = client.get_video("BV1xx411c7mD")
            profile = client.get_user_profile(2)
            room = client.get_live_room(10)

        self.assertEqual(video["id"], "BV1xx411c7mD")
        self.assertEqual(video["stats"]["views"], 11)
        self.assertEqual(profile["archive_count"], 6)
        self.assertEqual(room["title"], "live")
        self.assertNotIn("Origin", session.headers)
        self.assertNotIn("Referer", session.headers)
        self.assertEqual(session.cookies.get("buvid3"), "fixture-buvid3")
        self.assertEqual(session.cookies.get("buvid4"), "fixture-buvid4")
        self.assertTrue(session.cookies.get("b_nut").isdigit())
        self.assertEqual(len([url for url, _ in session.calls if url.endswith("/finger/spi")]), 1)

        spi_headers = session.calls[0][1]["headers"]
        web_headers = session.calls[1][1]["headers"]
        app_headers = session.calls[2][1]["headers"]
        live_headers = session.calls[3][1]["headers"]
        self.assertEqual(spi_headers["Origin"], "https://www.bilibili.com")
        self.assertEqual(web_headers["Referer"], "https://www.bilibili.com/")
        self.assertEqual(app_headers, {"User-Agent": APP_USER_AGENT})
        self.assertEqual(live_headers["Origin"], "https://live.bilibili.com")
        self.assertEqual(signer.calls[0]["vmid"], "2")
        self.assertEqual(signer.calls[0]["build"], "8180300")
        self.assertEqual(signer.calls[0]["mobi_app"], "android")
        self.assertEqual(signer.calls[0]["platform"], "android")
        self.assertEqual(session.calls[2][1]["params"]["sign"], "fixture-signature")

    def test_anonymous_nav_code_still_initializes_wbi_keys(self) -> None:
        img_key = "7cd084941338484aae1ad9425b84077c"
        sub_key = "4932caff0ff746eab6f01bf08b70ac45"
        session = FakeSession(
            [
                response(identity_payload()),
                response(
                    {
                        "code": -101,
                        "message": "account not logged in",
                        "data": {
                            "wbi_img": {
                                "img_url": f"https://i0.hdslb.com/bfs/wbi/{img_key}.png",
                                "sub_url": f"https://i0.hdslb.com/bfs/wbi/{sub_key}.png",
                            }
                        },
                    }
                ),
            ]
        )
        client = BilibiliClient(session=session, signer=FakeSigner(), retries=0)

        signer = client._ensure_wbi_signer()

        self.assertEqual(signer.img_key, img_key)
        self.assertEqual(signer.sub_key, sub_key)

    def test_user_video_pagination_deduplicates_and_advances_cursor(self) -> None:
        session = FakeSession(
            [
                response(
                    {
                        "code": 0,
                        "data": {
                            "count": 3,
                            "has_next": True,
                            "item": [
                                {"param": "11", "bvid": "BVfixture001", "title": "one"},
                                {"param": "22", "bvid": "BVfixture002", "title": "two"},
                            ],
                        },
                    }
                ),
                response(
                    {
                        "code": 0,
                        "data": {
                            "count": 3,
                            "has_next": False,
                            "item": [
                                {"param": "22", "bvid": "BVfixture002", "title": "duplicate"},
                                {"param": "33", "bvid": "BVfixture003", "title": "three"},
                            ],
                        },
                    }
                ),
            ]
        )
        signer = FakeSigner()
        client = BilibiliClient(session=session, signer=signer, retries=0)

        result = client.get_user_videos(2, page_size=100)

        self.assertEqual([item["aid"] for item in result["videos"]], ["11", "22", "33"])
        self.assertEqual(result["available"], 3)
        self.assertEqual(result["total"], 3)
        self.assertFalse(result["has_more"])
        self.assertEqual([call["aid"] for call in signer.calls], ["0", "22"])
        self.assertEqual([call["ps"] for call in signer.calls], [30, 30])

    def test_app_popular_uses_item_index_as_cursor_and_deduplicates(self) -> None:
        session = FakeSession(
            [
                response(
                    {
                        "code": 0,
                        "data": [
                            {"idx": 1, "bvid": "BVfixture001"},
                            {"idx": 2, "bvid": "BVfixture002"},
                        ],
                    }
                ),
                response(
                    {
                        "code": 0,
                        "data": [
                            {"idx": 3, "bvid": "BVfixture002"},
                            {"idx": 4, "bvid": "BVfixture003"},
                        ],
                    }
                ),
            ]
        )
        signer = FakeSigner()
        client = BilibiliClient(session=session, signer=signer, retries=0)

        result = client.get_app_popular(limit=3)

        self.assertEqual(
            [item["bvid"] for item in result["items"]],
            ["BVfixture001", "BVfixture002", "BVfixture003"],
        )
        self.assertEqual(result["cursor"], "4")
        self.assertTrue(result["has_more"])
        self.assertEqual([call["idx"] for call in signer.calls], ["0", "2"])

    def test_user_video_pagination_rejects_a_stalled_cursor(self) -> None:
        session = FakeSession(
            [
                response(
                    {
                        "code": 0,
                        "data": {
                            "has_next": True,
                            "item": [{"param": "0", "bvid": "BVfixture001"}],
                        },
                    }
                )
            ]
        )
        client = BilibiliClient(session=session, signer=FakeSigner(), retries=0)

        with self.assertRaisesRegex(BilibiliResponseError, "did not advance"):
            client.get_user_videos(2)

    def test_comments_and_nested_replies_are_normalized(self) -> None:
        session = FakeSession(
            [
                response(identity_payload()),
                response(video_payload()),
                response(
                    {
                        "code": 0,
                        "data": {
                            "cursor": {"all_count": 1, "is_end": True, "next": 1},
                            "replies": [
                                {
                                    "rpid": 100,
                                    "ctime": 1_700_000_200,
                                    "like": 9,
                                    "rcount": 1,
                                    "content": {"message": "root comment"},
                                    "member": {"mid": 8, "uname": "reader"},
                                }
                            ],
                        },
                    }
                ),
                response(
                    {
                        "code": 0,
                        "data": {
                            "page": {"count": 1},
                            "replies": [
                                {
                                    "rpid": 101,
                                    "root": 100,
                                    "parent": 100,
                                    "content": {"message": "child reply"},
                                    "member": {"mid": 7, "uname": "author"},
                                }
                            ],
                        },
                    }
                ),
            ]
        )
        client = BilibiliClient(session=session, signer=FakeSigner(), retries=0)

        result = client.get_comments("BV1xx411c7mD", include_replies=True)

        self.assertEqual(result["aid"], "2")
        self.assertEqual(result["comments"][0]["text"], "root comment")
        self.assertEqual(result["comments"][0]["user"]["name"], "reader")
        self.assertEqual(result["comments"][0]["replies"][0]["id"], "101")
        paths = [urlsplit(url).path for url, _ in session.calls]
        self.assertEqual(
            paths,
            [
                "/x/frontend/finger/spi",
                "/x/web-interface/view",
                "/x/v2/reply/main",
                "/x/v2/reply/reply",
            ],
        )

    def test_danmaku_parser_tolerates_malformed_numeric_fields(self) -> None:
        session = FakeSession(
            [
                response(
                    text=(
                        '<?xml version="1.0" encoding="UTF-8"?>'
                        '<i><d p="bad,1,25,16777215,1700000000,0,hash,42">hello</d></i>'
                    )
                )
            ]
        )
        client = BilibiliClient(session=session, signer=FakeSigner(), retries=0)

        result = client.get_video_danmaku(62131)

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["danmaku"][0]["time"], 0.0)
        self.assertEqual(result["danmaku"][0]["text"], "hello")

    def test_transient_requests_retry_but_deterministic_errors_do_not(self) -> None:
        session = FakeSession(
            [
                requests.exceptions.ConnectionError("fixture failure"),
                response({}, status=503),
                response({"code": 0, "data": {"ok": True}}),
            ]
        )
        client = BilibiliClient(session=session, signer=FakeSigner(), retries=2)

        with patch("reverse.bilibili_reverse.client.time.sleep") as sleep:
            payload = client._json_get("https://api.bilibili.com/fixture", {})

        self.assertTrue(payload["data"]["ok"])
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.35,), (0.7,)])

        error_session = FakeSession([response({}, status=404), response({"code": 0})])
        error_client = BilibiliClient(
            session=error_session, signer=FakeSigner(), retries=2
        )
        with patch("reverse.bilibili_reverse.client.time.sleep") as sleep:
            with self.assertRaisesRegex(BilibiliResponseError, "HTTP 404"):
                error_client._json_get("https://api.bilibili.com/fixture", {})
        self.assertEqual(len(error_session.calls), 1)
        sleep.assert_not_called()

        unsupported_session = FakeSession(
            [response({}, status=501), response({"code": 0})]
        )
        unsupported_client = BilibiliClient(
            session=unsupported_session,
            signer=FakeSigner(),
            retries=1,
        )
        with patch("reverse.bilibili_reverse.client.time.sleep") as sleep:
            with self.assertRaisesRegex(BilibiliResponseError, "HTTP 501"):
                unsupported_client._json_get(
                    "https://api.bilibili.com/fixture",
                    {},
                )
        self.assertEqual(len(unsupported_session.calls), 1)
        sleep.assert_not_called()

    def test_api_and_input_errors_are_layered(self) -> None:
        session = FakeSession(
            [
                response(
                    {
                        "code": -352,
                        "message": "risk control",
                        "data": {"v_voucher": "fixture-voucher"},
                    }
                ),
                response(text="not-json"),
            ]
        )
        client = BilibiliClient(session=session, signer=FakeSigner(), retries=0)

        with self.assertRaisesRegex(
            BilibiliResponseError, "code -352.*voucher=fixture-voucher"
        ):
            client._json_get("https://api.bilibili.com/fixture", {})
        with self.assertRaisesRegex(BilibiliResponseError, "non-JSON"):
            client._json_get("https://api.bilibili.com/fixture", {})
        with self.assertRaises(BilibiliInputError):
            client.get_video("https://bilibili.com.example/video/BV1xx411c7mD")
        with self.assertRaises(BilibiliInputError):
            client.get_user_videos(2, limit=-1)


if __name__ == "__main__":
    unittest.main()
