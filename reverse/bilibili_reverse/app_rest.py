from __future__ import annotations

import base64
import binascii
import math
import re
import struct
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeAlias
from urllib.parse import urlsplit

from .app_wire import _proto_bytes, _proto_varint, _wire_fields
from .errors import BilibiliInputError, BilibiliResponseError

APP_BASE = "https://app.bilibili.com"
API_BASE = "https://api.bilibili.com"
APP_VIDEO_DETAIL_PATH = "/x/v2/view"
APP_COMMENTS_PATH = "/x/v2/reply/main"
APP_COMMENT_REPLIES_PATH = "/bilibili.main.community.reply.v1.Reply/DetailList"

RESTFetcher: TypeAlias = Callable[[str, str, Mapping[str, str]], Mapping[str, Any]]
GRPCFetcher: TypeAlias = Callable[[str, bytes], bytes]

_BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_AID_RE = re.compile(r"(?:av)?([0-9]+)", re.IGNORECASE)
_UINT64_MAX = (1 << 64) - 1
_GRPC_REPLY_MODE_TIME = 2
_GRPC_DEFAULT_PAGE_SIZE = 20
_GRPC_MAX_PAGE_SIZE = 50
_GRPC_MAX_TOKEN_SIZE = 4096
_MAX_PROTO_MESSAGE_SIZE = 16 * 1024 * 1024
_MAX_PROTO_REPLIES = 5000
_MAX_PROTO_DEPTH = 8
_MAX_PROTO_FIELDS = 65_536


def get_app_video_detail(
    target: str | int,
    rest_fetch: RESTFetcher,
) -> dict[str, Any]:
    """查询 Android ``/x/v2/view``，并保留原始响应数据。"""

    bvid, aid = _resolve_video_target(target)
    payload = rest_fetch(
        APP_BASE,
        APP_VIDEO_DETAIL_PATH,
        _video_id_params(bvid, aid),
    )
    data = _response_data(payload, APP_VIDEO_DETAIL_PATH)
    response_bvid = _scalar_string(data.get("bvid"))
    response_aid = _scalar_string(data.get("aid"))
    if not response_bvid or not response_aid:
        raise BilibiliResponseError("App 视频响应缺 aid/bvid")
    _response_positive_uint64(response_aid, "App 视频响应 aid")
    return {
        "source": "bilibili_android_rest",
        "transport": "mobile_protocol",
        "endpoint": APP_VIDEO_DETAIL_PATH,
        "video": _normalize_video(data),
        "data": dict(data),
    }


def get_app_comments(
    target: str | int,
    *,
    rest_fetch: RESTFetcher,
    limit: int = 20,
    page_size: int = 20,
    order: str = "hot",
    offset: int = 0,
) -> dict[str, Any]:
    """按 Android 评论游标分页查询根评论。"""

    bvid, aid = _resolve_video_target(target)
    mode = _comment_mode(order)
    normalized_limit = _limit(limit)
    normalized_page_size = _page_size(page_size, maximum=49)
    cursor = _offset(offset)
    if normalized_limit == 0:
        return _empty_comments(bvid, aid, mode, cursor)

    if aid is None:
        detail = _response_data(
            rest_fetch(
                APP_BASE,
                APP_VIDEO_DETAIL_PATH,
                _video_id_params(bvid, None),
            ),
            APP_VIDEO_DETAIL_PATH,
        )
        raw_aid = _scalar_string(detail.get("aid"))
        aid = (
            str(_response_positive_uint64(raw_aid, "App 视频响应 aid"))
            if raw_aid
            else None
        )
        bvid = _scalar_string(detail.get("bvid")) or bvid
        if aid is None:
            raise BilibiliResponseError("App 视频响应缺 aid")

    start_cursor = cursor
    seen_cursors: set[str] = set()
    seen_ids: set[str] = set()
    comments: list[dict[str, Any]] = []
    available = 0
    has_more = True
    pages = 0
    while has_more and len(comments) < normalized_limit:
        if cursor in seen_cursors:
            raise BilibiliResponseError(f"App 评论翻页游标重复 {cursor}")
        seen_cursors.add(cursor)

        request_size = min(
            normalized_page_size,
            normalized_limit - len(comments),
        )
        data = _response_data(
            rest_fetch(
                API_BASE,
                APP_COMMENTS_PATH,
                {
                    "oid": aid,
                    "type": "1",
                    "mode": str(mode),
                    "next": cursor,
                    "ps": str(request_size),
                    "plat": "2",
                },
            ),
            APP_COMMENTS_PATH,
        )
        page_cursor = _mapping(data.get("cursor"))
        if not page_cursor:
            raise BilibiliResponseError("App 评论响应缺 cursor")
        count = _optional_integer(page_cursor.get("all_count"))
        if count is not None:
            available = count

        items = _list(data.get("replies"))
        for item in items:
            if not isinstance(item, Mapping):
                continue
            comment = _normalize_comment(item)
            comment_id = comment["id"]
            if not comment_id or comment_id in seen_ids:
                continue
            seen_ids.add(comment_id)
            comments.append(comment)
            if len(comments) >= normalized_limit:
                break
        pages += 1

        next_cursor = _scalar_string(page_cursor.get("next"))
        is_end = _rest_bool(page_cursor.get("is_end"), "App 评论响应 is_end")
        if not is_end and not items:
            raise BilibiliResponseError("App 评论响应为空但未结束")
        has_more = not is_end
        if has_more and (not next_cursor or next_cursor in seen_cursors):
            raise BilibiliResponseError("App 评论响应未推进游标")
        if next_cursor:
            cursor = next_cursor

    return {
        "source": "bilibili_android_rest",
        "transport": "mobile_protocol",
        "endpoint": APP_COMMENTS_PATH,
        "bvid": bvid,
        "aid": aid,
        "mode": mode,
        "start_offset": start_cursor,
        "next_offset": cursor,
        "available": available,
        "total": len(comments),
        "pages": pages,
        "has_more": has_more,
        "comments": comments,
    }


def get_app_comment_replies(
    target: str | int,
    root_id: str | int,
    *,
    rest_fetch: RESTFetcher | None,
    grpc_fetch: GRPCFetcher,
    limit: int = 20,
    page_size: int = _GRPC_DEFAULT_PAGE_SIZE,
    offset: int = 0,
    pagination_token: str | None = None,
) -> dict[str, Any]:
    """通过 Android gRPC ``DetailList`` 查询一条根评论的回复。"""

    bvid, aid = _resolve_video_target(target)
    oid = _positive_uint64(aid, "aid") if aid is not None else None
    root = _positive_uint64(root_id, "root_id")
    normalized_limit = _limit(limit)
    normalized_page_size = _page_size(
        page_size,
        maximum=_GRPC_MAX_PAGE_SIZE,
    )
    start_offset = _uint64(offset, "offset")
    token = _pagination_token(pagination_token)
    if token and start_offset:
        raise BilibiliInputError("offset 与 pagination_token 只能使用一个")
    if start_offset and normalized_page_size != _GRPC_DEFAULT_PAGE_SIZE:
        raise BilibiliInputError("从整数 offset 恢复时 page_size 必须为 20")
    if normalized_limit == 0:
        return _empty_comment_replies(
            bvid=bvid,
            aid=aid,
            root_id=str(root),
            start_offset=str(start_offset),
            start_token=token,
            page_size=normalized_page_size,
        )

    if aid is None:
        if rest_fetch is None:
            raise BilibiliInputError("解析 BV 目标需要 App REST fetcher")
        detail = _response_data(
            rest_fetch(
                APP_BASE,
                APP_VIDEO_DETAIL_PATH,
                _video_id_params(bvid, None),
            ),
            APP_VIDEO_DETAIL_PATH,
        )
        raw_aid = _scalar_string(detail.get("aid"))
        aid = (
            str(_response_positive_uint64(raw_aid, "App 视频响应 aid"))
            if raw_aid
            else None
        )
        bvid = _scalar_string(detail.get("bvid")) or bvid
        if aid is None:
            raise BilibiliResponseError("App 视频响应缺 aid")
        oid = _positive_uint64(aid, "aid")
    if oid is None:
        raise BilibiliResponseError("App 视频响应缺 aid")

    cursor_next = start_offset
    start_token = token
    seen_pages: set[str] = set()
    seen_ids: set[str] = set()
    replies: list[dict[str, Any]] = []
    available = 0
    normalized_root: dict[str, Any] | None = None
    has_more = True
    pages = 0

    while has_more and len(replies) < normalized_limit:
        use_cursor = pages == 0 and not token and cursor_next != 0
        page_key = f"cursor:{cursor_next}" if use_cursor else f"token:{token}"
        if page_key in seen_pages:
            raise BilibiliResponseError("App gRPC 回复分页游标重复")
        seen_pages.add(page_key)

        request_size = min(
            normalized_page_size,
            normalized_limit - len(replies),
        )
        request = _encode_detail_request(
            oid=oid,
            root=root,
            cursor_next=cursor_next,
            page_size=request_size,
            pagination_token=token,
            use_cursor=use_cursor,
        )
        response = grpc_fetch(APP_COMMENT_REPLIES_PATH, request)
        page = _parse_detail_reply(response)
        page_root = page["root"]
        if page_root["id"] != root:
            raise BilibiliResponseError(
                f"App gRPC root 不匹配: got {page_root['id']} want {root}"
            )
        if page_root["oid"] not in (0, oid):
            raise BilibiliResponseError(
                f"App gRPC oid 不匹配: got {page_root['oid']} want {oid}"
            )

        available = page_root["count"]
        normalized_root = _normalize_grpc_reply(page_root)
        raw_replies = page_root["replies"]
        for raw_reply in raw_replies:
            reply_id = str(raw_reply["id"])
            if raw_reply["id"] == 0 or reply_id in seen_ids:
                continue
            seen_ids.add(reply_id)
            replies.append(_normalize_grpc_reply(raw_reply))
            if len(replies) >= normalized_limit:
                break
        pages += 1

        next_token = page["pagination"]["next_offset"]
        next_cursor = page["cursor"]["next"]
        has_more = not page["cursor"]["is_end"]
        if has_more and not raw_replies:
            raise BilibiliResponseError("App gRPC 回复页为空但未结束")
        if has_more and not next_token:
            raise BilibiliResponseError("App gRPC 响应缺下一页 pagination token")
        if has_more and next_token == token and not use_cursor:
            raise BilibiliResponseError("App gRPC 响应未推进 pagination token")
        cursor_next = next_cursor
        token = next_token

    return {
        "source": "bilibili_android_grpc",
        "transport": "mobile_protocol",
        "endpoint": APP_COMMENT_REPLIES_PATH,
        "bvid": bvid,
        "aid": aid,
        "root_id": str(root),
        "mode": _GRPC_REPLY_MODE_TIME,
        "page_size": normalized_page_size,
        "start_offset": str(start_offset),
        "next_offset": str(cursor_next),
        "start_pagination_token": start_token or None,
        "pagination_token": token or None,
        "available": available,
        "total": len(replies),
        "pages": pages,
        "has_more": has_more,
        "root": normalized_root,
        "replies": replies,
    }


def _empty_comments(
    bvid: str | None,
    aid: str | None,
    mode: int,
    cursor: str,
) -> dict[str, Any]:
    return {
        "source": "bilibili_android_rest",
        "transport": "mobile_protocol",
        "endpoint": APP_COMMENTS_PATH,
        "bvid": bvid,
        "aid": aid,
        "mode": mode,
        "start_offset": cursor,
        "next_offset": cursor,
        "available": 0,
        "total": 0,
        "pages": 0,
        "has_more": False,
        "comments": [],
    }


def _empty_comment_replies(
    *,
    bvid: str | None,
    aid: str | None,
    root_id: str,
    start_offset: str,
    start_token: str,
    page_size: int,
) -> dict[str, Any]:
    return {
        "source": "bilibili_android_grpc",
        "transport": "mobile_protocol",
        "endpoint": APP_COMMENT_REPLIES_PATH,
        "bvid": bvid,
        "aid": aid,
        "root_id": root_id,
        "mode": _GRPC_REPLY_MODE_TIME,
        "page_size": page_size,
        "start_offset": start_offset,
        "next_offset": start_offset,
        "start_pagination_token": start_token or None,
        "pagination_token": start_token or None,
        "available": 0,
        "total": 0,
        "pages": 0,
        "has_more": False,
        "root": None,
        "replies": [],
    }


def _resolve_video_target(
    target: str | int,
) -> tuple[str | None, str | None]:
    text = str(target).strip()
    bvid_match = _BVID_RE.fullmatch(text)
    if bvid_match:
        return bvid_match.group(0), None
    aid_match = _AID_RE.fullmatch(text)
    if aid_match:
        return None, str(_positive_uint64(aid_match.group(1), "视频 aid"))

    url = text if "://" in text else f"https://{text}"
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except (UnicodeError, ValueError) as exc:
        raise BilibiliInputError("视频链接格式错误") from exc
    if not (
        host == "bilibili.com"
        or host.endswith(".bilibili.com")
        or host == "b23.tv"
        or host.endswith(".b23.tv")
    ):
        raise BilibiliInputError("视频链接必须使用 bilibili.com 或 b23.tv 域名")
    bvid_match = _BVID_RE.search(parsed.path)
    if bvid_match:
        return bvid_match.group(0), None
    for part in parsed.path.split("/"):
        aid_match = _AID_RE.fullmatch(part)
        if aid_match:
            return None, str(_positive_uint64(aid_match.group(1), "视频 aid"))
    raise BilibiliInputError("视频输入中没有有效的 BV 或 AV id")


def _video_id_params(
    bvid: str | None,
    aid: str | None,
) -> dict[str, str]:
    return {"bvid": bvid} if bvid is not None else {"aid": aid or ""}


def _response_data(
    payload: Mapping[str, Any],
    endpoint: str,
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise BilibiliResponseError(f"App 接口 {endpoint} 响应为空")
    code = _optional_integer(payload.get("code"))
    if code is None:
        raise BilibiliResponseError(f"App 接口 {endpoint} 响应缺 code")
    if code != 0:
        message = _scalar_string(payload.get("message"))
        raise BilibiliResponseError(f"App API code {code}: {message}")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise BilibiliResponseError(f"App 接口 {endpoint} 响应缺 data")
    return data


def _comment_mode(value: str) -> int:
    normalized = str(value).strip().lower()
    if normalized in ("", "3", "hot"):
        return 3
    if normalized in ("2", "time", "new", "latest"):
        return 2
    raise BilibiliInputError("App 评论 order 仅支持 hot|time|3|2")


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BilibiliInputError("limit 必须是大于等于 0 的整数")
    return value


def _page_size(value: int, *, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise BilibiliInputError(f"page_size 必须在 1..{maximum}")
    return value


def _offset(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BilibiliInputError("offset 必须是大于等于 0 的整数")
    return str(value)


def _uint64(value: str | int, field: str) -> int:
    if isinstance(value, bool):
        raise BilibiliInputError(f"{field} 必须是 uint64 整数")
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal():
        raise BilibiliInputError(f"{field} 必须是 uint64 整数")
    canonical = text.lstrip("0") or "0"
    maximum = str(_UINT64_MAX)
    if len(canonical) > len(maximum) or (
        len(canonical) == len(maximum) and canonical > maximum
    ):
        raise BilibiliInputError(f"{field} 超出 uint64 范围")
    return int(canonical)


def _positive_uint64(value: str | int, field: str) -> int:
    parsed = _uint64(value, field)
    if parsed == 0:
        raise BilibiliInputError(f"{field} 必须是正整数")
    return parsed


def _response_positive_uint64(value: str | int, field: str) -> int:
    try:
        return _positive_uint64(value, field)
    except BilibiliInputError as exc:
        raise BilibiliResponseError(f"{field} 非法") from exc


def _rest_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    raise BilibiliResponseError(f"{field} 非法: 必须是 bool 或 0/1")


def _pagination_token(value: str | None) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise BilibiliInputError("pagination_token 必须是字符串")
    return _validate_pagination_token(value, BilibiliInputError)


def _response_pagination_token(value: str) -> str:
    if not value:
        return ""
    return _validate_pagination_token(value, BilibiliResponseError)


def _validate_pagination_token(
    value: str,
    error_type: type[BilibiliInputError] | type[BilibiliResponseError],
) -> str:
    if value != value.strip():
        raise error_type("pagination_token 不能包含首尾空白")
    if len(value.encode()) > _GRPC_MAX_TOKEN_SIZE:
        raise error_type(f"pagination_token 超过 {_GRPC_MAX_TOKEN_SIZE} 字节")
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        try:
            padding = "=" * (-len(value) % 4)
            base64.b64decode(value + padding, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise error_type("pagination_token 不是合法 Base64") from exc
    return value


def _normalize_video(item: Mapping[str, Any]) -> dict[str, Any]:
    bvid = _scalar_string(item.get("bvid"))
    aid = _scalar_string(item.get("aid") or item.get("id"))
    owner = _mapping(item.get("owner"))
    stat = _mapping(item.get("stat"))
    dimension = _mapping(item.get("dimension"))
    pages = [
        dict(page) for page in _list(item.get("pages")) if isinstance(page, Mapping)
    ]
    cid = _scalar_string(item.get("cid") or (pages[0].get("cid") if pages else None))
    reference = bvid or f"av{aid}"
    return {
        "id": bvid or aid,
        "bvid": bvid,
        "aid": aid,
        "url": f"https://www.bilibili.com/video/{reference}",
        "title": _scalar_string(item.get("title")),
        "description": _scalar_string(item.get("desc")),
        "create_time": _integer(item.get("ctime")),
        "publish_time": _integer(item.get("pubdate")),
        "duration": _integer(item.get("duration")),
        "cid": cid,
        "category": _scalar_string(item.get("tname")),
        "owner": {
            "id": _scalar_string(owner.get("mid")),
            "name": _scalar_string(owner.get("name")),
            "avatar": _scalar_string(owner.get("face")),
        },
        "stats": {
            "views": _integer(stat.get("view")),
            "danmaku": _integer(stat.get("danmaku")),
            "comments": _integer(stat.get("reply")),
            "favorites": _integer(stat.get("favorite")),
            "coins": _integer(stat.get("coin")),
            "shares": _integer(stat.get("share")),
            "likes": _integer(stat.get("like")),
        },
        "media": {
            "cover": _scalar_string(item.get("pic")),
            "width": _integer(dimension.get("width")),
            "height": _integer(dimension.get("height")),
        },
        "pages": pages,
    }


def _normalize_comment(item: Mapping[str, Any]) -> dict[str, Any]:
    member = _mapping(item.get("member"))
    content = _mapping(item.get("content"))
    level = _mapping(member.get("level_info"))
    return {
        "id": _first_scalar(item, "rpid_str", "rpid"),
        "text": _scalar_string(content.get("message")),
        "create_time": _integer(item.get("ctime")),
        "likes": _integer(item.get("like")),
        "reply_count": _integer(
            item.get("rcount") if item.get("rcount") is not None else item.get("count")
        ),
        "root_id": _first_scalar(item, "root_str", "root"),
        "parent_id": _first_scalar(item, "parent_str", "parent"),
        "user": {
            "id": _scalar_string(member.get("mid") or item.get("mid")),
            "name": _scalar_string(member.get("uname")),
            "avatar": _scalar_string(member.get("avatar")),
            "sign": _scalar_string(member.get("sign")),
            "level": _integer(level.get("current_level")),
        },
    }


def _normalize_grpc_reply(reply: Mapping[str, Any]) -> dict[str, Any]:
    content = _mapping(reply.get("content"))
    member = _mapping(reply.get("member"))
    pictures = [
        {
            "url": picture["url"],
            "width": picture["width"],
            "height": picture["height"],
            "size_kb": picture["size_kb"],
        }
        for picture in _list(content.get("pictures"))
        if isinstance(picture, Mapping)
    ]
    return {
        "id": str(reply.get("id", 0)),
        "text": _scalar_string(content.get("message")),
        "create_time": _integer(reply.get("ctime")),
        "likes": _integer(reply.get("like")),
        "reply_count": _integer(reply.get("count")),
        "root_id": str(reply.get("root", 0)),
        "parent_id": str(reply.get("parent", 0)),
        "pictures": pictures,
        "user": {
            "id": str(member.get("mid", 0)),
            "name": _scalar_string(member.get("name")),
            "avatar": _scalar_string(member.get("face")),
            "sign": "",
            "level": _integer(member.get("level")),
        },
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return list(value)
    return []


def _integer(value: Any) -> int:
    parsed = _optional_integer(value)
    return parsed if parsed is not None else 0


def _optional_integer(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _scalar_string(value: Any) -> str:
    if (
        value is None
        or isinstance(value, (Mapping, Sequence))
        and not isinstance(
            value,
            (str, bytes, bytearray),
        )
    ):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value)


def _first_scalar(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _scalar_string(item.get(key))
        if value:
            return value
    return ""


def _encode_detail_request(
    *,
    oid: int,
    root: int,
    cursor_next: int,
    page_size: int,
    pagination_token: str,
    use_cursor: bool,
) -> bytes:
    if oid <= 0:
        raise BilibiliInputError("gRPC DetailList oid 必须大于 0")
    if root <= 0:
        raise BilibiliInputError("gRPC DetailList root 必须大于 0")
    if page_size < 1 or page_size > _GRPC_MAX_PAGE_SIZE:
        raise BilibiliInputError("gRPC DetailList page_size 必须在 1..50")
    payload = (
        _proto_varint(1, oid)
        + _proto_varint(2, 1)
        + _proto_varint(3, root)
        + _proto_varint(7, _GRPC_REPLY_MODE_TIME)
    )
    if use_cursor:
        cursor = _proto_varint(1, cursor_next) + _proto_varint(
            4,
            _GRPC_REPLY_MODE_TIME,
        )
        return payload + _proto_bytes(5, cursor)
    pagination = _proto_varint(1, page_size)
    if pagination_token:
        pagination += _proto_bytes(2, pagination_token.encode())
    return payload + _proto_bytes(8, pagination)


def _parse_detail_reply(payload: bytes) -> dict[str, Any]:
    fields = _parse_proto(payload)
    cursor_raw = _last_bytes(fields, 1)
    root_raw = _last_bytes(fields, 3)
    if cursor_raw is None:
        raise BilibiliResponseError("gRPC DetailList 响应缺 cursor")
    if root_raw is None:
        raise BilibiliResponseError("gRPC DetailList 响应缺 root")
    pagination_raw = _last_bytes(fields, 8)
    return {
        "cursor": _parse_grpc_cursor(cursor_raw),
        "root": _parse_grpc_reply(root_raw, depth=0),
        "mode": _last_varint(fields, 6, 0),
        "pagination": _parse_grpc_pagination(pagination_raw or b""),
    }


def _parse_grpc_cursor(payload: bytes) -> dict[str, Any]:
    fields = _parse_proto(payload)
    return {
        "next": _last_varint(fields, 1, 0),
        "is_end": bool(_last_varint(fields, 4, 0)),
    }


def _parse_grpc_pagination(payload: bytes) -> dict[str, str]:
    fields = _parse_proto(payload)
    return {
        "next_offset": _response_pagination_token(_last_text(fields, 1)),
        "previous_offset": _last_text(fields, 2),
        "last_read_offset": _last_text(fields, 3),
    }


def _parse_grpc_reply(payload: bytes, *, depth: int) -> dict[str, Any]:
    if depth > _MAX_PROTO_DEPTH:
        raise BilibiliResponseError(f"gRPC ReplyInfo 嵌套超过 {_MAX_PROTO_DEPTH} 层")
    fields = _parse_proto(payload)
    raw_replies = _all_bytes(fields, 1)
    if len(raw_replies) > _MAX_PROTO_REPLIES:
        raise BilibiliResponseError(f"gRPC 单页回复超过 {_MAX_PROTO_REPLIES}")
    content_raw = _last_bytes(fields, 12)
    member_raw = _last_bytes(fields, 13)
    return {
        "replies": [_parse_grpc_reply(raw, depth=depth + 1) for raw in raw_replies],
        "id": _last_varint(fields, 2, 0),
        "oid": _last_varint(fields, 3, 0),
        "type": _last_varint(fields, 4, 0),
        "mid": _last_varint(fields, 5, 0),
        "root": _last_varint(fields, 6, 0),
        "parent": _last_varint(fields, 7, 0),
        "dialog": _last_varint(fields, 8, 0),
        "like": _last_varint(fields, 9, 0),
        "ctime": _last_varint(fields, 10, 0),
        "count": _last_varint(fields, 11, 0),
        "content": _parse_grpc_content(content_raw or b""),
        "member": _parse_grpc_member(member_raw or b""),
    }


def _parse_grpc_content(payload: bytes) -> dict[str, Any]:
    fields = _parse_proto(payload)
    return {
        "message": _last_text(fields, 1),
        "pictures": [_parse_grpc_picture(raw) for raw in _all_bytes(fields, 9)],
    }


def _parse_grpc_picture(payload: bytes) -> dict[str, Any]:
    fields = _parse_proto(payload)
    return {
        "url": _last_text(fields, 1),
        "width": _last_double(fields, 2),
        "height": _last_double(fields, 3),
        "size_kb": _last_double(fields, 4),
    }


def _parse_grpc_member(payload: bytes) -> dict[str, Any]:
    fields = _parse_proto(payload)
    return {
        "mid": _last_varint(fields, 1, 0),
        "name": _last_text(fields, 2),
        "sex": _last_text(fields, 3),
        "face": _last_text(fields, 4),
        "level": _last_varint(fields, 5, 0),
        "official_verify_type": _last_varint(fields, 6, 0),
        "vip_type": _last_varint(fields, 7, 0),
        "vip_status": _last_varint(fields, 8, 0),
    }


ProtoField: TypeAlias = tuple[int, int, int, bytes]


def _parse_proto(payload: bytes) -> list[ProtoField]:
    if not isinstance(payload, bytes):
        raise BilibiliResponseError("protobuf 响应必须是 bytes")
    if len(payload) > _MAX_PROTO_MESSAGE_SIZE:
        raise BilibiliResponseError("protobuf 响应超过大小限制")
    return _wire_fields(payload, _MAX_PROTO_FIELDS, "回复")


def _last_varint(
    fields: list[ProtoField],
    number: int,
    fallback: int,
) -> int:
    result = fallback
    for field_number, wire_type, scalar, _ in fields:
        if field_number != number:
            continue
        if wire_type != 0:
            raise BilibiliResponseError(f"protobuf 字段 {number} wire type 非法")
        result = scalar
    return result


def _last_bytes(
    fields: list[ProtoField],
    number: int,
) -> bytes | None:
    result: bytes | None = None
    for field_number, wire_type, _, raw in fields:
        if field_number != number:
            continue
        if wire_type != 2:
            raise BilibiliResponseError(f"protobuf 字段 {number} wire type 非法")
        result = raw
    return result


def _all_bytes(
    fields: list[ProtoField],
    number: int,
) -> list[bytes]:
    result: list[bytes] = []
    for field_number, wire_type, _, raw in fields:
        if field_number != number:
            continue
        if wire_type != 2:
            raise BilibiliResponseError(f"protobuf 字段 {number} wire type 非法")
        result.append(raw)
    return result


def _last_text(fields: list[ProtoField], number: int) -> str:
    raw = _last_bytes(fields, number)
    if raw is None:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BilibiliResponseError(f"protobuf 字段 {number} 不是 UTF-8") from exc


def _last_double(fields: list[ProtoField], number: int) -> float:
    result = 0.0
    for field_number, wire_type, scalar, _ in fields:
        if field_number != number:
            continue
        if wire_type != 1:
            raise BilibiliResponseError(f"protobuf 字段 {number} wire type 非法")
        result = struct.unpack("<d", scalar.to_bytes(8, "little"))[0]
    return result
