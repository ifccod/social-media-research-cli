from __future__ import annotations

import base64
import json
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

from reverse.bilibili_reverse import app_catalog
from reverse.bilibili_reverse.app_catalog import (
    APP_API_BASE,
    APP_SEARCH_BY_TYPE_PATH,
    APP_SEARCH_PROTO_COMMIT,
    APP_SEARCH_PROTO_SHA256,
    get_app_bangumi_tab,
    get_app_cinema_tab,
    search_app_by_type,
)
from reverse.bilibili_reverse.errors import BilibiliInputError, BilibiliResponseError

_FIXTURE_DIR = Path(__file__).with_name("testdata")


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _integer_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _item(card_field: int, item_id: str, title: str) -> bytes:
    card = _field(1, title.encode())
    return _field(2, item_id.encode()) + _field(card_field, card)


def _page(next_token: str, *items: bytes) -> bytes:
    payload = b"".join(_field(6, item) for item in items)
    pagination = _field(1, next_token.encode()) if next_token else b""
    return payload + _field(7, pagination)


class AppSearchCatalogTest(unittest.TestCase):
    def test_pinned_fixture_covers_request_mapping_and_pagination(self) -> None:
        fixture = _fixture("app_search_type.json")
        request_fixture = fixture["request"]
        responses = [
            base64.b64decode(item["protobuf_base64"]) for item in fixture["responses"]
        ]
        requests: list[bytes] = []

        def fetch(path: str, payload: bytes) -> bytes:
            self.assertEqual(path, APP_SEARCH_BY_TYPE_PATH)
            requests.append(payload)
            return responses[len(requests) - 1]

        result = search_app_by_type(
            fetch,
            request_fixture["keyword"],
            category=request_fixture["category"],
            order=request_fixture["order"],
            limit=2,
            page_size=1,
        )

        self.assertEqual(len(requests), 2)
        self.assertEqual(
            base64.b64encode(requests[1]).decode(),
            request_fixture["protobuf_base64"],
        )
        self.assertEqual(fixture["rpc_path"], APP_SEARCH_BY_TYPE_PATH)
        self.assertEqual(fixture["source"]["commit"], APP_SEARCH_PROTO_COMMIT)
        self.assertEqual(fixture["source"]["sha256"], APP_SEARCH_PROTO_SHA256)
        self.assertEqual(result["schema_commit"], APP_SEARCH_PROTO_COMMIT)
        self.assertEqual(result["schema_sha256"], APP_SEARCH_PROTO_SHA256)
        self.assertEqual(result["category_type"], request_fixture["category_type"])
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["total"], 2)
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["pagination_token"])

        video, author = result["items"]
        self.assertEqual(
            {
                "id": video["id"],
                "title": video["title"],
                "author": video["author"],
                "description": video["description"],
                "card_type": video["card_type"],
                "spread_id": video["spread_id"],
                "user_act": video["user_act"],
            },
            {
                "id": "BV1Fixture01",
                "title": "Python 类型系统",
                "author": "fixture-up",
                "description": "typing fixture",
                "card_type": "av",
                "spread_id": "42",
                "user_act": "fixture-user-act",
            },
        )
        self.assertEqual(author["id"], "42")
        self.assertEqual(author["title"], "Fixture Author")
        self.assertEqual(author["url"], "bilibili://space/42")
        self.assertEqual(author["card_url"], "bilibili://space/42/live")
        self.assertEqual(author["card_url_kind"], "live_uri")
        self.assertEqual(
            result["raw_pages"][0]["annotations"]["fixture"], "pinned proto"
        )

    def test_live_evidence_keeps_only_success_metadata(self) -> None:
        evidence = _fixture("app_search_live_evidence.json")

        self.assertEqual(evidence["schema_version"], 1)
        self.assertEqual(evidence["capture_kind"], "live_success_metadata")
        self.assertEqual(evidence["request"]["path"], APP_SEARCH_BY_TYPE_PATH)
        self.assertEqual(evidence["request"]["category_type"], 10)
        self.assertEqual(evidence["response"]["http_status"], 200)
        self.assertEqual(evidence["response"]["grpc_status"], "0")
        self.assertEqual(evidence["parsed"]["transport"], "mobile_protocol")
        self.assertEqual(evidence["parsed"]["card_types"], ["av"])
        self.assertTrue(evidence["parsed"]["pagination_token_present"])
        self.assertFalse(any(evidence["redaction"].values()))

    def test_category_types_and_zero_limit_do_not_fetch(self) -> None:
        categories = {
            "video": 10,
            "user": 2,
            "live": 4,
            "article": 6,
            "bangumi": 7,
            "pgc": 8,
        }
        for name, category_type in categories.items():
            with self.subTest(name=name):
                result = search_app_by_type(
                    None,  # type: ignore[arg-type]
                    "python",
                    category=name,
                    order="4",
                    limit=0,
                    page_size=50,
                    pagination_token="opaque:start",
                )
                self.assertEqual(result["category_type"], category_type)
                self.assertEqual(result["pagination_token"], "opaque:start")
                self.assertEqual(result["pages"], 0)

    def test_validation_and_wire_errors_stop_at_the_boundary(self) -> None:
        fetch_calls = 0

        def fetch(_: str, __: bytes) -> bytes:
            nonlocal fetch_calls
            fetch_calls += 1
            return b""

        cases = [
            {"keyword": " ", "category": "video"},
            {"keyword": "python", "category": "audio"},
            {"keyword": "python", "category": "video", "order": 5},
            {"keyword": "python", "category": "video", "page_size": 0},
            {"keyword": "python", "category": "video", "limit": -1},
            {
                "keyword": "python",
                "category": "video",
                "pagination_token": "bad\n",
            },
        ]
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(BilibiliInputError):
                    search_app_by_type(fetch, **values)
        self.assertEqual(fetch_calls, 0)

        with self.assertRaisesRegex(BilibiliResponseError, "未推进"):
            search_app_by_type(
                lambda _path, _payload: _page("same", _item(37, "one", "one")),
                "python",
                limit=2,
                page_size=1,
                pagination_token="same",
            )
        with self.assertRaisesRegex(BilibiliResponseError, "解析失败"):
            search_app_by_type(
                lambda _path, _payload: b"\x0a\x80",
                "python",
                limit=1,
            )

    def test_deduplication_allows_distinct_card_types(self) -> None:
        result = search_app_by_type(
            lambda _path, _payload: _page(
                "",
                _item(37, "shared", "video"),
                _item(23, "shared", "author"),
            ),
            "python",
            limit=2,
            page_size=1,
        )
        self.assertEqual(
            [item["card_type"] for item in result["items"]],
            ["av", "author_new"],
        )

    def test_stagnant_search_pages_are_bounded(self) -> None:
        tokens = iter(("one", "two", "three"))
        with self.assertRaisesRegex(BilibiliResponseError, "3 页没有新增"):
            search_app_by_type(
                lambda _path, _payload: _page(next(tokens)),
                "python",
                limit=1,
            )

    def test_search_wire_field_item_and_raw_budgets(self) -> None:
        unknown = _integer_field(66, 0)
        malformed = (
            (unknown * 513, "字段数量"),
            (b"".join(_field(6, b"") for _ in range(101)), "items 超过"),
            (_integer_field(1, 1), "wire type"),
        )
        for payload, message in malformed:
            with self.subTest(message=message):
                with self.assertRaisesRegex(BilibiliResponseError, message):
                    search_app_by_type(
                        lambda _path, _request, payload=payload: payload,
                        "python",
                        limit=1,
                    )

        with (
            patch.object(app_catalog, "_SEARCH_MAX_RAW_BYTES", 1),
            self.assertRaisesRegex(BilibiliResponseError, "原始 protobuf 输出超过"),
        ):
            search_app_by_type(
                lambda _path, _payload: _page("", _item(37, "id", "title")),
                "python",
                limit=1,
            )

    def test_unknown_oneof_merge_and_signed_fields_are_preserved(self) -> None:
        card_title = _field(1, b"title")
        card_cover = _field(2, b"cover")
        item = (
            _field(2, b"id")
            + _integer_field(5, (1 << 32) - 1)
            + _integer_field(56, (1 << 64) - 1)
            + _field(66, b"opaque")
            + _field(37, card_title)
            + _field(37, card_cover)
        )

        result = search_app_by_type(
            lambda _path, _payload: _page("", item),
            "python",
            limit=1,
        )
        parsed = result["items"][0]

        self.assertEqual(parsed["title"], "title")
        self.assertEqual(parsed["cover"], "cover")
        self.assertEqual(parsed["position"], -1)
        self.assertEqual(parsed["spread_id"], "-1")
        self.assertEqual(
            parsed["raw"]["unknown_fields"][0],
            {
                "field": 66,
                "wire_type": 2,
                "protobuf_base64": base64.b64encode(b"opaque").decode(),
            },
        )


class AppPGCCatalogTest(unittest.TestCase):
    def test_pinned_cinema_and_bangumi_fixtures(self) -> None:
        functions = {
            "cinema": get_app_cinema_tab,
            "bangumi": get_app_bangumi_tab,
        }
        for name, function in functions.items():
            with self.subTest(name=name):
                fixture = _fixture("app_pgc_tabs.json")[name]
                calls: list[tuple[str, str, Mapping[str, Any]]] = []

                def fetch(
                    base_url: str,
                    path: str,
                    params: Mapping[str, Any],
                ) -> Mapping[str, Any]:
                    calls.append((base_url, path, params))
                    return fixture["response"]

                result = function(fetch)
                self.assertEqual(calls, [(APP_API_BASE, fixture["path"], {})])
                self.assertEqual(result["tab"], name)
                self.assertEqual(result["total_modules"], 1)
                self.assertTrue(result["has_more"])
                self.assertEqual(
                    result["next_cursor"],
                    fixture["response"]["result"]["next_cursor"],
                )
                self.assertEqual(
                    result["result"]["modules"][0]["items"][0]["title"],
                    fixture["response"]["result"]["modules"][0]["items"][0]["title"],
                )

    def test_cursor_is_opaque_and_must_advance(self) -> None:
        calls: list[Mapping[str, Any]] = []

        def response(next_cursor: str) -> dict[str, Any]:
            return {
                "code": 0,
                "result": {
                    "has_next": 1,
                    "next_cursor": next_cursor,
                    "modules": [{"module_id": "continued"}],
                    "regions": [],
                },
            }

        result = get_app_cinema_tab(
            lambda _base, _path, params: calls.append(params) or response("opaque:16"),
            pagination_token="opaque:8",
        )
        self.assertEqual(calls, [{"cursor": "opaque:8"}])
        self.assertEqual(result["start_cursor"], "opaque:8")
        self.assertEqual(result["next_cursor"], "opaque:16")

        with self.assertRaisesRegex(BilibiliResponseError, "未推进"):
            get_app_cinema_tab(
                lambda _base, _path, _params: response("same"),
                pagination_token="same",
            )

    def test_float_cursor_keeps_round_trip_decimal_precision(self) -> None:
        cursor = 1234567.890123
        result = get_app_cinema_tab(
            lambda _base, _path, _params: {
                "code": 0,
                "result": {
                    "has_next": 1,
                    "next_cursor": cursor,
                    "modules": [{"module_id": "continued"}],
                    "regions": [],
                },
            }
        )
        self.assertEqual(result["next_cursor"], str(cursor))

    def test_response_boundaries_and_tracking_field_cleanup(self) -> None:
        malformed = [
            ({}, "缺 code"),
            ({"code": -400, "message": "请求错误"}, "code -400"),
            ({"code": 0}, "缺 result"),
            ({"code": 0, "result": {"has_next": 0}}, "缺 modules"),
            (
                {
                    "code": 0,
                    "result": {
                        "modules": [],
                        "regions": "bad",
                        "has_next": 0,
                    },
                },
                "regions 不是数组",
            ),
            (
                {
                    "code": 0,
                    "result": {"modules": [], "has_next": 2},
                },
                "has_next 非法",
            ),
            (
                {
                    "code": 0,
                    "result": {"modules": [], "has_next": 1},
                },
                "缺 next_cursor",
            ),
        ]
        for payload, message in malformed:
            with self.subTest(message=message):
                with self.assertRaisesRegex(BilibiliResponseError, message):
                    get_app_bangumi_tab(lambda _base, _path, _params: payload)

        payload = {
            "code": 0,
            "result": {
                "has_next": 0,
                "next_cursor": "",
                "regions": [],
                "modules": [
                    {
                        "request_id": "removed",
                        "report": {
                            "client_ip": "192.0.2.1",
                            "ogv_session_id": "removed",
                            "module_id": "kept",
                        },
                    }
                ],
            },
        }
        result = get_app_cinema_tab(lambda _base, _path, _params: payload)
        module = result["result"]["modules"][0]
        self.assertNotIn("request_id", module)
        self.assertEqual(module["report"], {"module_id": "kept"})


if __name__ == "__main__":
    unittest.main()
