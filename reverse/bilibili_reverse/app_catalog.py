from __future__ import annotations

import base64
import hashlib
import math
import struct
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .app_wire import _proto_bytes, _proto_varint, _wire_fields
from .errors import BilibiliInputError, BilibiliResponseError

APP_SEARCH_BY_TYPE_PATH = "/bilibili.polymer.app.search.v1.Search/SearchByType"
APP_CINEMA_TAB_PATH = "/pgc/page/cinema/tab"
APP_BANGUMI_TAB_PATH = "/pgc/page/bangumi"
APP_API_BASE = "https://api.bilibili.com"
APP_SEARCH_PROTO_COMMIT = "1b657de7788dec56871656932af9c92f285cc4be"
APP_SEARCH_PROTO_SHA256 = (
    "a8baa6a594756a77156b62579ab5343d964db3127980f0a4329a5b9236b06895"
)

AppGRPCFetcher = Callable[[str, bytes], bytes]
AppRESTFetcher = Callable[[str, str, Mapping[str, str]], Mapping[str, Any]]

_SEARCH_CATEGORIES = {
    "video": 10,
    "user": 2,
    "live": 4,
    "article": 6,
    "bangumi": 7,
    "pgc": 8,
}
_SEARCH_DEFAULT_PAGE_SIZE = 20
_SEARCH_MAX_PAGE_SIZE = 50
_SEARCH_MAX_LIMIT = 5000
_SEARCH_MAX_TOKEN_BYTES = 4096
_SEARCH_MAX_KEYWORD_BYTES = 512
_SEARCH_MAX_TEXT_BYTES = 64 << 10
_SEARCH_MAX_ITEM_BYTES = 512 << 10
_SEARCH_MAX_CARD_BYTES = 384 << 10
_SEARCH_MAX_RESPONSE_ITEMS = 100
_SEARCH_MAX_ANNOTATIONS = 128
_SEARCH_MAX_FIELDS = 512
_SEARCH_MAX_STAGNANT_PAGES = 3
_SEARCH_MAX_RAW_BYTES = 32 << 20
_PGC_MAX_CURSOR_BYTES = 4096

_CARD_VARIANTS = {
    7: "special",
    8: "article",
    9: "banner",
    10: "live",
    11: "game",
    12: "purchase",
    13: "recommend_word",
    14: "dynamic",
    15: "suggest_keyword",
    16: "special_guide",
    17: "comic",
    18: "channel_new",
    19: "ogv_card",
    20: "bangumi_relates",
    21: "find_more",
    22: "esport",
    23: "author_new",
    24: "tips",
    25: "cm",
    26: "pedia_card",
    27: "ugc_inline",
    28: "live_inline",
    29: "top_game",
    30: "sports",
    31: "pedia_card_inline",
    32: "recommend_tips",
    33: "collection_card",
    34: "ogv_channel",
    35: "ogv_inline",
    36: "author",
    37: "av",
    38: "bangumi",
    39: "esports_inline",
    40: "hot_banner",
    41: "subject",
    42: "dynamic_new",
    43: "article_new",
    44: "pedia_card_pic",
    45: "nps_card",
    46: "chat_gpt",
    47: "hot_recommend",
    48: "live_master",
    49: "live_room_title",
    50: "live_room",
    51: "cheese",
    52: "related_search",
    53: "qa_card",
    54: "double_column",
    55: "up_recommend",
    57: "comment_card",
    58: "playlist_card",
    59: "series_card",
    60: "music_card",
    61: "comment_cluster",
    62: "time_line",
    64: "double_opus",
    65: "ogv_cluster_card",
}


@dataclass(frozen=True, slots=True)
class _CardLayout:
    name: str
    title: int
    cover: int
    authors: tuple[int, ...] = ()
    descriptions: tuple[int, ...] = ()
    urls: tuple[int, ...] = ()
    url_names: Mapping[int, str] = field(default_factory=dict)
    ids: tuple[int, ...] = ()


_CARD_LAYOUTS = {
    7: _CardLayout("special", 1, 2, descriptions=(6,)),
    8: _CardLayout("article", 1, 2, (7, 11), (12,), ids=(9,)),
    10: _CardLayout("live", 1, 2, (4,), (10,), (7,), {7: "live_link"}),
    19: _CardLayout(
        "ogv", 1, 4, descriptions=(2, 3), urls=(7,), url_names={7: "cover_uri"}
    ),
    23: _CardLayout(
        "author_new",
        1,
        2,
        descriptions=(8,),
        urls=(4, 5),
        url_names={4: "live_uri", 5: "live_link"},
        ids=(11,),
    ),
    27: _CardLayout("ugc_inline", 1, 2, (3,), (5,)),
    28: _CardLayout(
        "live_inline", 1, 2, urls=(6,), url_names={6: "live_link"}, ids=(5,)
    ),
    35: _CardLayout("ogv_inline", 1, 2, (3,), (5,)),
    36: _CardLayout(
        "author", 1, 2, descriptions=(3,), urls=(18,), url_names={18: "live_link"}
    ),
    37: _CardLayout("av", 1, 2, (10,), (11,)),
    38: _CardLayout(
        "bangumi",
        1,
        2,
        (12,),
        (13,),
        (11,),
        {11: "target"},
        (20,),
    ),
    43: _CardLayout("article_new", 1, 2, (7, 11), (12,), ids=(9,)),
    48: _CardLayout(
        "live_master",
        1,
        3,
        (2,),
        urls=(4, 22),
        url_names={4: "uri", 22: "live_link"},
        ids=(17,),
    ),
    50: _CardLayout(
        "live_room",
        1,
        3,
        (2,),
        urls=(4, 14),
        url_names={4: "uri", 14: "live_link"},
        ids=(7,),
    ),
}


@dataclass(slots=True)
class _SearchCard:
    id: str = ""
    title: str = ""
    cover: str = ""
    author: str = ""
    description: str = ""
    url: str = ""
    url_kind: str = ""


@dataclass(slots=True)
class _UnknownField:
    number: int
    wire_type: int
    scalar: int
    raw: bytes


@dataclass(slots=True)
class _SearchItem:
    raw: bytes
    uri: str = ""
    param: str = ""
    goto: str = ""
    link_type: str = ""
    position: int = 0
    track_id: str = ""
    spread_id: int = 0
    user_act: str = ""
    card_field: int = 0
    card_type: str = ""
    card: _SearchCard = field(default_factory=_SearchCard)
    card_raw: bytes = b""
    unknown: list[_UnknownField] = field(default_factory=list)


@dataclass(slots=True)
class _SearchPage:
    track_id: str = ""
    pages: int = 0
    exp_str: str = ""
    keyword: str = ""
    result_is_recommend: int = 0
    real_exposure_ratio: float = 0.0
    page: int = 0
    items: list[_SearchItem] = field(default_factory=list)
    pagination_next: str = ""
    pagination_prev: str = ""
    annotations: dict[str, str] = field(default_factory=dict)


def search_app_by_type(
    fetch: AppGRPCFetcher,
    keyword: str,
    *,
    category: str = "video",
    order: int | str = 0,
    limit: int = _SEARCH_DEFAULT_PAGE_SIZE,
    page_size: int = _SEARCH_DEFAULT_PAGE_SIZE,
    pagination_token: str = "",
) -> dict[str, Any]:
    """通过 Android gRPC `SearchByType` 搜索指定类型并处理游标翻页。"""

    normalized_keyword = _search_keyword(keyword)
    category_name, category_type = _search_category(category)
    normalized_order = _search_order(order)
    normalized_page_size = _bounded_int(
        page_size, "page_size", 1, _SEARCH_MAX_PAGE_SIZE
    )
    normalized_limit = _bounded_int(limit, "limit", 0, _SEARCH_MAX_LIMIT)
    start_token = _opaque_text(
        pagination_token, "pagination_token", _SEARCH_MAX_TOKEN_BYTES
    )
    if normalized_limit == 0:
        return _empty_search_result(
            normalized_keyword,
            category_name,
            category_type,
            normalized_order,
            normalized_page_size,
            start_token,
        )
    if not callable(fetch):
        raise BilibiliInputError("App gRPC fetch 必须可调用")

    token = start_token
    seen_tokens: set[str] = set()
    seen_items: set[tuple[int, str]] = set()
    items: list[dict[str, Any]] = []
    raw_pages: list[dict[str, Any]] = []
    pages = 0
    stagnant_pages = 0
    total_raw_bytes = 0
    has_more = True

    while has_more and len(items) < normalized_limit:
        if token in seen_tokens:
            raise BilibiliResponseError("App 搜索 pagination token 循环")
        seen_tokens.add(token)
        request_size = min(normalized_page_size, normalized_limit - len(items))
        request = _encode_search_request(
            normalized_keyword,
            category_type,
            normalized_order,
            request_size,
            token,
        )
        response = fetch(APP_SEARCH_BY_TYPE_PATH, request)
        if not isinstance(response, (bytes, bytearray, memoryview)):
            raise BilibiliResponseError("App 搜索 gRPC 响应必须是字节串")
        parsed = _parse_search_response(bytes(response))
        next_token = parsed.pagination_next
        if next_token and next_token == token:
            raise BilibiliResponseError("App 搜索 pagination token 未推进")
        if next_token and next_token in seen_tokens:
            raise BilibiliResponseError("App 搜索 pagination token 循环")

        added = 0
        for raw_item in parsed.items:
            if len(items) >= normalized_limit:
                break
            item_id = _search_item_id(raw_item)
            identity = (raw_item.card_field, item_id)
            if identity in seen_items:
                continue
            addition = _search_item_raw_bytes(raw_item)
            if addition > _SEARCH_MAX_RAW_BYTES - total_raw_bytes:
                raise BilibiliResponseError(
                    f"App 搜索原始 protobuf 输出超过 {_SEARCH_MAX_RAW_BYTES} 字节"
                )
            seen_items.add(identity)
            total_raw_bytes += addition
            items.append(_normalize_search_item(raw_item))
            added += 1

        if added == 0 and next_token:
            stagnant_pages += 1
            if stagnant_pages >= _SEARCH_MAX_STAGNANT_PAGES:
                raise BilibiliResponseError(
                    f"App 搜索连续 {_SEARCH_MAX_STAGNANT_PAGES} 页没有新增结果"
                )
        else:
            stagnant_pages = 0

        raw_pages.append(
            {
                "track_id": parsed.track_id,
                "pages": parsed.pages,
                "page": parsed.page,
                "exp_str": parsed.exp_str,
                "keyword": parsed.keyword,
                "result_is_recommend": parsed.result_is_recommend,
                "real_exposure_ratio": parsed.real_exposure_ratio,
                "received_items": len(parsed.items),
                "accepted_items": added,
                "pagination": {
                    "next": next_token,
                    "prev": parsed.pagination_prev,
                },
                "annotations": dict(parsed.annotations),
            }
        )
        pages += 1
        token = next_token
        has_more = bool(token)

    return {
        "source": "bilibili_android_grpc",
        "transport": "mobile_protocol",
        "endpoint": APP_SEARCH_BY_TYPE_PATH,
        "schema_commit": APP_SEARCH_PROTO_COMMIT,
        "schema_sha256": APP_SEARCH_PROTO_SHA256,
        "keyword": normalized_keyword,
        "category": category_name,
        "category_type": category_type,
        "order": normalized_order,
        "page_size": normalized_page_size,
        "start_pagination_token": start_token or None,
        "pagination_token": token or None,
        "total": len(items),
        "raw_bytes": total_raw_bytes,
        "pages": pages,
        "has_more": has_more,
        "items": items,
        "raw_pages": raw_pages,
    }


def get_app_cinema_tab(
    fetch: AppRESTFetcher, *, pagination_token: str = ""
) -> dict[str, Any]:
    """读取 Android 客户端影视页的单页目录。"""

    return _get_app_pgc_tab(fetch, "cinema", APP_CINEMA_TAB_PATH, pagination_token)


def get_app_bangumi_tab(
    fetch: AppRESTFetcher, *, pagination_token: str = ""
) -> dict[str, Any]:
    """读取 Android 客户端番剧页的单页目录。"""

    return _get_app_pgc_tab(fetch, "bangumi", APP_BANGUMI_TAB_PATH, pagination_token)


def _empty_search_result(
    keyword: str,
    category: str,
    category_type: int,
    order: int,
    page_size: int,
    start_token: str,
) -> dict[str, Any]:
    return {
        "source": "bilibili_android_grpc",
        "transport": "mobile_protocol",
        "endpoint": APP_SEARCH_BY_TYPE_PATH,
        "schema_commit": APP_SEARCH_PROTO_COMMIT,
        "schema_sha256": APP_SEARCH_PROTO_SHA256,
        "keyword": keyword,
        "category": category,
        "category_type": category_type,
        "order": order,
        "page_size": page_size,
        "start_pagination_token": start_token or None,
        "pagination_token": start_token or None,
        "total": 0,
        "raw_bytes": 0,
        "pages": 0,
        "has_more": False,
        "items": [],
        "raw_pages": [],
    }


def _get_app_pgc_tab(
    fetch: AppRESTFetcher,
    name: str,
    path: str,
    pagination_token: str,
) -> dict[str, Any]:
    start_cursor = _opaque_text(
        pagination_token, "pagination_token", _PGC_MAX_CURSOR_BYTES
    )
    if not callable(fetch):
        raise BilibiliInputError("App REST fetch 必须可调用")
    params = {"cursor": start_cursor} if start_cursor else {}
    payload = fetch(APP_API_BASE, path, params)
    return _parse_pgc_response(payload, name, path, start_cursor)


def _parse_pgc_response(
    payload: Mapping[str, Any],
    name: str,
    path: str,
    start_cursor: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BilibiliResponseError(f"App PGC 接口 {path} 响应为空")
    if "code" not in payload:
        raise BilibiliResponseError(f"App PGC 接口 {path} 响应缺 code")
    code = _integer_value(payload["code"])
    if code is None:
        raise BilibiliResponseError(f"App PGC 接口 {path} 响应缺 code")
    if code:
        raise BilibiliResponseError(
            f"App API code {code}: {_scalar_text(payload.get('message'))}"
        )
    raw_result = payload.get("result")
    if not isinstance(raw_result, Mapping):
        raise BilibiliResponseError(f"App PGC 接口 {path} 响应缺 result")
    modules = raw_result.get("modules")
    if not isinstance(modules, list):
        raise BilibiliResponseError(f"App PGC 接口 {path} 响应缺 modules")
    if "regions" in raw_result and not isinstance(raw_result["regions"], list):
        raise BilibiliResponseError(f"App PGC 接口 {path} regions 不是数组")
    has_more = _pgc_bool(raw_result.get("has_next"), path)
    next_cursor = _opaque_text(
        _scalar_text(raw_result.get("next_cursor")),
        "next_cursor",
        _PGC_MAX_CURSOR_BYTES,
        response=True,
    )
    if has_more and not next_cursor:
        raise BilibiliResponseError(f"App PGC 接口 {path} 有下一页但缺 next_cursor")
    if has_more and not modules:
        raise BilibiliResponseError(f"App PGC 接口 {path} modules 为空但未结束")
    if has_more and next_cursor == start_cursor:
        raise BilibiliResponseError(f"App PGC 接口 {path} pagination cursor 未推进")

    return {
        "source": "bilibili_android_rest",
        "transport": "mobile_protocol",
        "endpoint": path,
        "tab": name,
        "total_modules": len(modules),
        "has_more": has_more,
        "start_cursor": start_cursor or None,
        "next_cursor": next_cursor or None,
        "result": _sanitize_pgc_value(raw_result),
    }


def _encode_search_request(
    keyword: str,
    category_type: int,
    order: int,
    page_size: int,
    pagination_token: str,
) -> bytes:
    payload = _proto_varint(1, category_type)
    payload += _proto_bytes(2, keyword.encode())
    payload += _proto_varint(3, order)
    pagination = _proto_varint(1, page_size)
    if pagination_token:
        pagination += _proto_bytes(2, pagination_token.encode())
    return payload + _proto_bytes(7, pagination)


def _parse_search_response(payload: bytes) -> _SearchPage:
    result = _SearchPage()
    annotation_count = 0
    for number, wire_type, scalar, raw in _wire_fields(
        payload, _SEARCH_MAX_FIELDS, "App 搜索响应"
    ):
        if number in (1, 3, 4):
            value = _wire_text(
                "SearchByTypeResponse.text", wire_type, raw, _SEARCH_MAX_TEXT_BYTES
            )
            if number == 1:
                result.track_id = value
            elif number == 3:
                result.exp_str = value
            else:
                result.keyword = value
        elif number in (2, 5):
            _require_wire("SearchByTypeResponse.integer", wire_type, 0)
            value = _signed(scalar, 32)
            if number == 2:
                result.pages = value
            else:
                result.result_is_recommend = value
        elif number == 6:
            _require_wire("SearchByTypeResponse.items", wire_type, 2)
            if len(result.items) >= _SEARCH_MAX_RESPONSE_ITEMS:
                raise BilibiliResponseError(
                    f"App 搜索单页 items 超过 {_SEARCH_MAX_RESPONSE_ITEMS}"
                )
            result.items.append(_parse_search_item(raw))
        elif number == 7:
            _require_wire("SearchByTypeResponse.pagination", wire_type, 2)
            next_token, previous_token = _parse_search_pagination(raw)
            if next_token is not None:
                result.pagination_next = next_token
            if previous_token is not None:
                result.pagination_prev = previous_token
        elif number == 8:
            _require_wire("SearchByTypeResponse.annotation", wire_type, 2)
            annotation_count += 1
            if annotation_count > _SEARCH_MAX_ANNOTATIONS:
                raise BilibiliResponseError(
                    f"App 搜索 annotation 超过 {_SEARCH_MAX_ANNOTATIONS}"
                )
            key, value = _parse_search_annotation(raw)
            if key:
                result.annotations[key] = value
        elif number == 9:
            _require_wire("SearchByTypeResponse.real_exposure_ratio", wire_type, 1)
            ratio = struct.unpack("<d", scalar.to_bytes(8, "little"))[0]
            if not math.isfinite(ratio):
                raise BilibiliResponseError("App 搜索 real_exposure_ratio 不是有限数")
            result.real_exposure_ratio = ratio
        elif number == 10:
            _require_wire("SearchByTypeResponse.page", wire_type, 0)
            result.page = _signed(scalar, 64)
    return result


def _parse_search_pagination(payload: bytes) -> tuple[str | None, str | None]:
    next_token: str | None = None
    previous_token: str | None = None
    for number, wire_type, _, raw in _wire_fields(payload, 8, "App 搜索 pagination"):
        if number not in (1, 2):
            continue
        value = _wire_text("PaginationReply", wire_type, raw, _SEARCH_MAX_TOKEN_BYTES)
        value = _opaque_text(
            value, "pagination_token", _SEARCH_MAX_TOKEN_BYTES, response=True
        )
        if number == 1:
            next_token = value
        else:
            previous_token = value
    return next_token, previous_token


def _parse_search_annotation(payload: bytes) -> tuple[str, str]:
    key = ""
    value = ""
    for number, wire_type, _, raw in _wire_fields(payload, 8, "App 搜索 annotation"):
        if number not in (1, 2):
            continue
        text = _wire_text(
            "SearchByTypeResponse.annotation",
            wire_type,
            raw,
            _SEARCH_MAX_TEXT_BYTES,
        )
        if number == 1:
            key = text
        else:
            value = text
    return key, value


def _parse_search_item(payload: bytes) -> _SearchItem:
    if len(payload) > _SEARCH_MAX_ITEM_BYTES:
        raise BilibiliResponseError(f"App 搜索 item 长度 {len(payload)} 非法")
    result = _SearchItem(raw=payload)
    for number, wire_type, scalar, raw in _wire_fields(
        payload, _SEARCH_MAX_FIELDS, "App 搜索 item"
    ):
        if number in (1, 2, 3, 4, 6, 63):
            value = _wire_text("Item.text", wire_type, raw, _SEARCH_MAX_TEXT_BYTES)
            if number == 1:
                result.uri = value
            elif number == 2:
                result.param = value
            elif number == 3:
                result.goto = value
            elif number == 4:
                result.link_type = value
            elif number == 6:
                result.track_id = value
            else:
                result.user_act = value
        elif number == 5:
            _require_wire("Item.position", wire_type, 0)
            result.position = _signed(scalar, 32)
        elif number == 56:
            _require_wire("Item.spread_id", wire_type, 0)
            result.spread_id = _signed(scalar, 64)
        elif number not in _CARD_VARIANTS:
            result.unknown.append(_UnknownField(number, wire_type, scalar, raw))
        else:
            _require_wire("Item.card_item", wire_type, 2)
            if len(raw) > _SEARCH_MAX_CARD_BYTES:
                raise BilibiliResponseError(f"App 搜索 card 长度 {len(raw)} 非法")
            card_raw = result.card_raw + raw if result.card_field == number else raw
            if len(card_raw) > _SEARCH_MAX_CARD_BYTES:
                raise BilibiliResponseError(
                    f"App 搜索 card 长度超过 {_SEARCH_MAX_CARD_BYTES}"
                )
            result.card_field = number
            result.card_type = _CARD_VARIANTS[number]
            result.card_raw = card_raw
            layout = _CARD_LAYOUTS.get(number)
            result.card = (
                _parse_search_card(card_raw, layout) if layout else _SearchCard()
            )
    return result


def _parse_search_card(payload: bytes, layout: _CardLayout) -> _SearchCard:
    text_fields: dict[int, str] = {}
    id_fields: dict[int, int] = {}
    selected_text = {
        layout.title,
        layout.cover,
        *layout.authors,
        *layout.descriptions,
        *layout.urls,
    }
    for number, wire_type, scalar, raw in _wire_fields(
        payload, _SEARCH_MAX_FIELDS, f"App 搜索 {layout.name} card"
    ):
        if number in layout.ids:
            _require_wire(f"{layout.name}.id", wire_type, 0)
            id_fields[number] = _signed(scalar, 64)
        elif number in selected_text:
            text_fields[number] = _wire_text(
                f"{layout.name}.field",
                wire_type,
                raw,
                _SEARCH_MAX_TEXT_BYTES,
            )

    card = _SearchCard(
        title=text_fields.get(layout.title, ""),
        cover=text_fields.get(layout.cover, ""),
        author=_first_text(text_fields, layout.authors),
        description=_first_text(text_fields, layout.descriptions),
        url=_first_text(text_fields, layout.urls),
    )
    for number in layout.urls:
        if text_fields.get(number):
            card.url_kind = layout.url_names.get(number, f"field_{number}")
            break
    for number in layout.ids:
        if number in id_fields:
            card.id = str(id_fields[number])
            break
    return card


def _normalize_search_item(item: _SearchItem) -> dict[str, Any]:
    unknown_fields: list[dict[str, Any]] = []
    for unknown in item.unknown:
        value: dict[str, Any] = {
            "field": unknown.number,
            "wire_type": unknown.wire_type,
        }
        if unknown.wire_type in (0, 1, 5):
            value["scalar"] = str(unknown.scalar)
        elif unknown.wire_type == 2:
            value["protobuf_base64"] = base64.b64encode(unknown.raw).decode()
        unknown_fields.append(value)
    return {
        "id": _search_item_id(item),
        "title": item.card.title,
        "cover": item.card.cover,
        "url": item.uri or item.card.url,
        "author": item.card.author,
        "description": item.card.description,
        "uri": item.uri,
        "card_url": item.card.url or None,
        "card_url_kind": item.card.url_kind or None,
        "param": item.param,
        "goto": item.goto,
        "link_type": item.link_type,
        "position": item.position,
        "track_id": item.track_id,
        "spread_id": str(item.spread_id),
        "user_act": item.user_act,
        "card_type": item.card_type,
        "raw": {
            "card_field": item.card_field,
            "protobuf_base64": base64.b64encode(item.raw).decode(),
            "card_protobuf_base64": base64.b64encode(item.card_raw).decode(),
            "unknown_fields": unknown_fields,
        },
    }


def _search_item_id(item: _SearchItem) -> str:
    return (
        item.card.id or item.param or item.uri or hashlib.sha256(item.raw).hexdigest()
    )


def _search_item_raw_bytes(item: _SearchItem) -> int:
    return (
        len(item.raw)
        + len(item.card_raw)
        + sum(len(unknown.raw) for unknown in item.unknown)
    )


def _wire_text(label: str, wire_type: int, raw: bytes, maximum: int) -> str:
    _require_wire(label, wire_type, 2)
    if len(raw) > maximum:
        raise BilibiliResponseError(f"protobuf {label} 超过 {maximum} 字节")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BilibiliResponseError(f"protobuf {label} 不是 UTF-8") from exc


def _require_wire(label: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise BilibiliResponseError(f"protobuf {label} wire type={actual} 非法")


def _signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def _first_text(fields: Mapping[int, str], order: tuple[int, ...]) -> str:
    return next((fields[number] for number in order if fields.get(number)), "")


def _search_category(value: str) -> tuple[str, int]:
    if not isinstance(value, str):
        raise BilibiliInputError("category 必须是字符串")
    name = value.strip().lower() or "video"
    try:
        return name, _SEARCH_CATEGORIES[name]
    except KeyError as exc:
        raise BilibiliInputError(
            "category 必须是 video|bangumi|pgc|live|article|user"
        ) from exc


def _search_keyword(value: str) -> str:
    if not isinstance(value, str):
        raise BilibiliInputError("keyword 必须是字符串")
    keyword = value.strip()
    if not keyword:
        raise BilibiliInputError("keyword 不能为空")
    return _opaque_text(keyword, "keyword", _SEARCH_MAX_KEYWORD_BYTES)


def _search_order(value: int | str) -> int:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        if not text.isascii() or not text.isdecimal():
            raise BilibiliInputError("order 必须是 0|1|2|3|4")
        value = int(text)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4:
        raise BilibiliInputError("order 必须是 0|1|2|3|4")
    return value


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise BilibiliInputError(f"{name} 必须在 {minimum}..{maximum}")
    return value


def _opaque_text(
    value: str,
    name: str,
    maximum: int,
    *,
    response: bool = False,
) -> str:
    error_type = BilibiliResponseError if response else BilibiliInputError
    if not isinstance(value, str):
        raise error_type(f"{name} 必须是字符串")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise error_type(f"{name} 不是 UTF-8") from exc
    if len(encoded) > maximum:
        raise error_type(f"{name} 超过 {maximum} 字节")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise error_type(f"{name} 包含控制字符")
    return value


def _integer_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if -(1 << 63) <= value < 1 << 63 else None
    if isinstance(value, float):
        if (
            math.isfinite(value)
            and value.is_integer()
            and -(1 << 63) <= value < 1 << 63
        ):
            return int(value)
        return None
    if isinstance(value, str):
        digits = value[1:] if value[:1] in {"+", "-"} else value
        if not digits.isascii() or not digits.isdecimal():
            return None
        try:
            parsed = int(value, 10)
        except ValueError:
            return None
        return parsed if -(1 << 63) <= parsed < 1 << 63 else None
    return None


def _scalar_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    return ""


def _pgc_bool(value: Any, path: str) -> bool:
    if isinstance(value, bool):
        return value
    integer = _integer_value(value)
    if integer in (0, 1):
        return integer == 1
    raise BilibiliResponseError(
        f"App PGC 接口 {path} has_next 非法: 必须是 bool 或 0/1"
    )


def _sanitize_pgc_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _sanitize_pgc_value(item)
            for key, item in value.items()
            if not (
                isinstance(key, str)
                and key.lower() in {"client_ip", "request_id", "ogv_session_id"}
            )
        }
    if isinstance(value, list):
        return [_sanitize_pgc_value(item) for item in value]
    return value


__all__ = [
    "APP_BANGUMI_TAB_PATH",
    "APP_CINEMA_TAB_PATH",
    "APP_API_BASE",
    "APP_SEARCH_BY_TYPE_PATH",
    "APP_SEARCH_PROTO_COMMIT",
    "APP_SEARCH_PROTO_SHA256",
    "AppGRPCFetcher",
    "AppRESTFetcher",
    "get_app_bangumi_tab",
    "get_app_cinema_tab",
    "search_app_by_type",
]
