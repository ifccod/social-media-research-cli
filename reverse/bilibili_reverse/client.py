from __future__ import annotations

import html
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from curl_cffi import requests

from . import app_catalog, app_rest
from .app_transport import (
    APP_USER_AGENT as APP_USER_AGENT,
    app_rest_headers,
    fetch_app_grpc,
)
from .errors import BilibiliInputError, BilibiliResponseError, BilibiliSignatureError
from .mobile_profile import MobileProfile, load_mobile_profile
from .signer import BilibiliAppSigner, BilibiliWbiSigner

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
_API_BASE = "https://api.bilibili.com"
_APP_BASE = "https://app.bilibili.com"
_LIVE_BASE = "https://api.live.bilibili.com"
_SEARCH_BASE = "https://s.search.bilibili.com"
_SPI_URL = f"{_API_BASE}/x/frontend/finger/spi"
_BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_AID_RE = re.compile(r"(?:av)?(\d+)", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WEB_HEADERS = {
    "Origin": "https://www.bilibili.com",
    "Referer": "https://www.bilibili.com/",
}
_LIVE_HEADERS = {
    "Origin": "https://live.bilibili.com",
    "Referer": "https://live.bilibili.com/",
}
_APP_PARAMS = {
    "build": "8180300",
    "mobi_app": "android",
    "platform": "android",
}
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _clean_title(value: Any) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", str(value or "")))


class BilibiliClient:
    def __init__(
        self,
        *,
        signer: BilibiliAppSigner | None = None,
        wbi_signer: BilibiliWbiSigner | None = None,
        session: requests.Session | None = None,
        app_session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
        mobile_profile: MobileProfile | None = None,
        mobile_profile_home: str | Path | None = None,
    ) -> None:
        self.signer = signer or BilibiliAppSigner()
        self.wbi_signer = wbi_signer
        self.session = session or requests.Session(impersonate="chrome")
        self.app_session = app_session or requests.Session(
            impersonate="chrome",
            default_headers=False,
        )
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(0, retries)
        self._identity_ready = False
        self._mobile_profile = mobile_profile
        self._mobile_profile_home = mobile_profile_home
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": user_agent,
            }
        )

    def get_video(self, video_url_or_id: str | int) -> dict[str, Any]:
        payload = self._get_video_payload(video_url_or_id)
        return self._normalize_video(payload)

    def get_video_parts(self, video_url_or_id: str | int) -> dict[str, Any]:
        bvid, aid = self._resolve_video(video_url_or_id)
        params = {"bvid": bvid} if bvid else {"aid": aid}
        payload = self._web_get("/x/player/pagelist", params)
        parts = _list(payload.get("data"))
        return {
            "bvid": bvid,
            "aid": aid,
            "total": len(parts),
            "parts": [dict(item) for item in parts if isinstance(item, Mapping)],
        }

    def get_video_playurl(
        self,
        video_url_or_id: str | int,
        *,
        cid: str | int | None = None,
        quality: int = 80,
        prefer_wbi: bool = False,
    ) -> dict[str, Any]:
        bvid, aid = self._resolve_video(video_url_or_id)
        detail: Mapping[str, Any] = {}
        if not bvid or not aid or cid is None:
            detail = self._get_video_payload(video_url_or_id)
            bvid = str(detail.get("bvid") or bvid or "")
            aid = str(detail.get("aid") or aid or "")
            cid = cid or detail.get("cid")
        if not bvid or not aid or not cid:
            raise BilibiliResponseError("video response does not contain aid, bvid, and cid")
        normalized_quality = max(16, quality)
        data: Mapping[str, Any] = {}
        source = "legacy"
        if prefer_wbi:
            try:
                payload = self._wbi_get(
                    "/x/player/wbi/playurl",
                    {
                        "avid": aid,
                        "bvid": bvid,
                        "cid": str(cid),
                        "qn": str(normalized_quality),
                        "fnver": "0",
                        "fnval": "4048",
                        "fourk": "1",
                        "gaia_source": "pre-load",
                        "from_client": "BROWSER",
                        "is_main_page": "true",
                        "need_fragment": "false",
                        "isGaiaAvoided": "false",
                        "web_location": "1315873",
                    },
                )
                candidate = _mapping(payload.get("data"))
                if candidate.get("dash") or candidate.get("durl"):
                    data = candidate
                    source = "wbi"
            except (BilibiliResponseError, BilibiliSignatureError):
                data = {}
        if not data:
            payload = self._web_get(
                "/x/player/playurl",
                {
                    "bvid": bvid,
                    "cid": str(cid),
                    "qn": str(normalized_quality),
                    "fnval": "4048",
                    "fourk": "1",
                },
            )
            data = _mapping(payload.get("data"))
        return {
            "bvid": bvid,
            "aid": aid,
            "cid": str(cid),
            "source": source,
            "playurl": dict(data),
        }

    def get_subtitles(
        self,
        video_url_or_id: str | int,
        *,
        cid: str | int | None = None,
    ) -> dict[str, Any]:
        bvid, aid = self._resolve_video(video_url_or_id)
        detail: Mapping[str, Any] = {}
        if not bvid or cid is None:
            detail = self._get_video_payload(video_url_or_id)
            bvid = str(detail.get("bvid") or bvid or "")
            aid = str(detail.get("aid") or aid or "")
            cid = cid or detail.get("cid")
        if not bvid or not cid:
            raise BilibiliResponseError("video response does not contain bvid and cid")
        payload = self._web_get("/x/player/v2", {"bvid": bvid, "cid": str(cid)})
        data = _mapping(payload.get("data"))
        subtitle = _mapping(data.get("subtitle"))
        items = _list(subtitle.get("subtitles"))
        return {
            "bvid": bvid,
            "aid": aid,
            "cid": str(cid),
            "allow_submit": bool(subtitle.get("allow_submit")),
            "total": len(items),
            "subtitles": [dict(item) for item in items if isinstance(item, Mapping)],
        }

    def get_video_danmaku(self, cid: str | int) -> dict[str, Any]:
        cid_value = self._positive_id(cid, "cid")
        response = self._request(f"https://comment.bilibili.com/{cid_value}.xml", params={})
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise BilibiliResponseError("Bilibili returned malformed danmaku XML") from exc
        items: list[dict[str, Any]] = []
        for element in root.findall("d"):
            fields = (element.attrib.get("p") or "").split(",")
            items.append(
                {
                    "text": element.text or "",
                    "time": _float(fields[0] if fields else 0),
                    "mode": _integer(fields[1] if len(fields) > 1 else 0),
                    "font_size": _integer(fields[2] if len(fields) > 2 else 0),
                    "color": _integer(fields[3] if len(fields) > 3 else 0),
                    "timestamp": _integer(fields[4] if len(fields) > 4 else 0),
                    "pool": _integer(fields[5] if len(fields) > 5 else 0),
                    "user_hash": fields[6] if len(fields) > 6 else "",
                    "id": fields[7] if len(fields) > 7 else "",
                }
            )
        return {"cid": cid_value, "total": len(items), "danmaku": items}

    def get_user_profile(self, user_id: str | int) -> dict[str, Any]:
        mid = self._positive_id(user_id, "user_id")
        payload = self._app_get("/x/v2/space", {"vmid": mid})
        data = _mapping(payload.get("data"))
        card = _mapping(data.get("card"))
        if not card.get("mid"):
            raise BilibiliResponseError("user response does not contain a profile card")
        level = _mapping(card.get("level_info"))
        likes = _mapping(card.get("likes"))
        archive = _mapping(data.get("archive"))
        return {
            "id": str(card.get("mid")),
            "name": str(card.get("name") or ""),
            "sign": str(card.get("sign") or ""),
            "avatar": str(card.get("face") or ""),
            "level": _integer(level.get("current_level")),
            "followers": _integer(card.get("fans")),
            "following": _integer(card.get("attention")),
            "likes": _integer(likes.get("like_num")),
            "archive_count": _integer(archive.get("count")),
            "official": dict(_mapping(card.get("official_verify"))),
            "vip": dict(_mapping(card.get("vip"))),
            "live": dict(_mapping(data.get("live"))),
            "profile": dict(card),
        }

    def get_user_videos(
        self,
        user_id: str | int,
        *,
        limit: int | None = None,
        page_size: int = 20,
        order: str = "pubdate",
    ) -> dict[str, Any]:
        mid = self._positive_id(user_id, "user_id")
        self._validate_limit(limit)
        if limit == 0:
            return {"user_id": mid, "total": 0, "cursor": "0", "has_more": False, "videos": []}
        size = min(max(page_size, 1), 30)
        cursor = "0"
        seen_cursors: set[str] = set()
        seen_ids: set[str] = set()
        videos: list[dict[str, Any]] = []
        has_more = True
        total_available = 0

        while has_more and (limit is None or len(videos) < limit):
            if cursor in seen_cursors:
                raise BilibiliResponseError(f"user video pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            payload = self._app_get(
                "/x/v2/space/archive/cursor",
                {"vmid": mid, "aid": cursor, "ps": size, "order": order},
            )
            data = _mapping(payload.get("data"))
            total_available = _integer(data.get("count"))
            items = _list(data.get("item"))
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                video = self._normalize_archive_video(item)
                identity = video["bvid"] or video["aid"]
                if not identity or identity in seen_ids:
                    continue
                seen_ids.add(identity)
                videos.append(video)
                if limit is not None and len(videos) >= limit:
                    break
            has_more = bool(data.get("has_next"))
            if not has_more:
                break
            next_cursor = str(_mapping(items[-1]).get("param") or "") if items else ""
            if not next_cursor or next_cursor == cursor:
                raise BilibiliResponseError("user video response did not advance its cursor")
            cursor = next_cursor

        return {
            "user_id": mid,
            "available": total_available,
            "total": len(videos),
            "cursor": cursor,
            "has_more": has_more,
            "videos": videos,
        }

    def get_home_feed(self, *, limit: int = 20) -> dict[str, Any]:
        self._validate_limit(limit)
        if limit == 0:
            return {"total": 0, "items": []}
        payload = self._app_get(
            "/x/v2/feed/index",
            {"idx": "0", "pull": "0", "flush": "0", "column": "4", "autoplay_card": "2"},
        )
        data = _mapping(payload.get("data"))
        items = [dict(item) for item in _list(data.get("items")) if isinstance(item, Mapping)]
        return {"total": min(len(items), limit), "items": items[:limit], "config": data.get("config")}

    def get_app_popular(self, *, limit: int = 20) -> dict[str, Any]:
        self._validate_limit(limit)
        if limit == 0:
            return {"total": 0, "cursor": "0", "has_more": False, "items": []}
        cursor = "0"
        seen_cursors: set[str] = set()
        seen_ids: set[str] = set()
        items: list[dict[str, Any]] = []
        has_more = True
        while has_more and len(items) < limit:
            if cursor in seen_cursors:
                raise BilibiliResponseError(f"app popular pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            payload = self._app_get(
                "/x/v2/show/popular/index",
                {"idx": cursor, "limit": min(max(limit - len(items), 1), 50)},
            )
            page_items = _list(payload.get("data"))
            for item in page_items:
                if not isinstance(item, Mapping):
                    continue
                identity = str(item.get("bvid") or item.get("param") or item.get("idx") or "")
                if not identity or identity in seen_ids:
                    continue
                seen_ids.add(identity)
                items.append(dict(item))
                if len(items) >= limit:
                    break
            has_more = bool(page_items)
            next_cursor = str(_mapping(page_items[-1]).get("idx") or "") if page_items else ""
            if not has_more:
                break
            if not next_cursor or next_cursor == cursor:
                raise BilibiliResponseError("app popular response did not advance its cursor")
            cursor = next_cursor
        return {
            "total": len(items),
            "cursor": cursor,
            "has_more": has_more,
            "items": items,
        }

    def get_app_video_detail(
        self,
        video_url_or_id: str | int,
    ) -> dict[str, Any]:
        return app_rest.get_app_video_detail(
            video_url_or_id,
            self._app_rest_fetch,
        )

    def get_app_comments(
        self,
        video_url_or_id: str | int,
        *,
        limit: int = 20,
        page_size: int = 20,
        order: str = "hot",
        offset: int = 0,
    ) -> dict[str, Any]:
        return app_rest.get_app_comments(
            video_url_or_id,
            rest_fetch=self._app_rest_fetch,
            limit=limit,
            page_size=page_size,
            order=order,
            offset=offset,
        )

    def get_app_comment_replies(
        self,
        video_url_or_id: str | int,
        root_id: str | int,
        *,
        limit: int = 20,
        page_size: int = 20,
        offset: int = 0,
        pagination_token: str | None = None,
    ) -> dict[str, Any]:
        return app_rest.get_app_comment_replies(
            video_url_or_id,
            root_id,
            rest_fetch=self._app_rest_fetch,
            grpc_fetch=self._app_grpc_fetch,
            limit=limit,
            page_size=page_size,
            offset=offset,
            pagination_token=pagination_token,
        )

    def search_app_by_type(
        self,
        keyword: str,
        *,
        category: str = "video",
        order: int | str = 0,
        limit: int = 20,
        page_size: int = 20,
        pagination_token: str = "",
    ) -> dict[str, Any]:
        return app_catalog.search_app_by_type(
            self._app_grpc_fetch,
            keyword,
            category=category,
            order=order,
            limit=limit,
            page_size=page_size,
            pagination_token=pagination_token,
        )

    def get_app_cinema_tab(
        self,
        *,
        pagination_token: str = "",
    ) -> dict[str, Any]:
        return app_catalog.get_app_cinema_tab(
            self._app_rest_fetch,
            pagination_token=pagination_token,
        )

    def get_app_bangumi_tab(
        self,
        *,
        pagination_token: str = "",
    ) -> dict[str, Any]:
        return app_catalog.get_app_bangumi_tab(
            self._app_rest_fetch,
            pagination_token=pagination_token,
        )

    def get_popular(
        self,
        *,
        limit: int = 20,
        page_size: int = 20,
    ) -> dict[str, Any]:
        self._validate_limit(limit)
        if limit == 0:
            return {"total": 0, "page": 1, "has_more": False, "videos": []}
        size = min(max(page_size, 1), 50)
        page = 1
        videos: list[dict[str, Any]] = []
        has_more = True
        while has_more and len(videos) < limit:
            payload = self._web_get("/x/web-interface/popular", {"pn": page, "ps": size})
            data = _mapping(payload.get("data"))
            items = _list(data.get("list"))
            for item in items:
                if isinstance(item, Mapping):
                    videos.append(self._normalize_video(item))
                    if len(videos) >= limit:
                        break
            no_more = bool(data.get("no_more"))
            has_more = bool(items) and not no_more
            page += 1
        return {"total": len(videos), "page": page - 1, "has_more": has_more, "videos": videos}

    def get_hot_search(self, *, limit: int = 20) -> dict[str, Any]:
        self._validate_limit(limit)
        if limit == 0:
            return {"total": 0, "items": []}
        payload = self._json_get(f"{_SEARCH_BASE}/main/hotword", {"limit": max(1, limit)})
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in _list(payload.get("top_list")) + _list(payload.get("list")):
            if not isinstance(candidate, Mapping):
                continue
            keyword = str(candidate.get("keyword") or candidate.get("show_name") or "")
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            items.append(dict(candidate))
            if len(items) >= limit:
                break
        return {"total": len(items), "items": items, "timestamp": payload.get("timestamp")}

    def search(
        self,
        keyword: str,
        *,
        limit: int = 20,
        page_size: int = 20,
    ) -> dict[str, Any]:
        normalized = keyword.strip()
        if not normalized:
            raise BilibiliInputError("keyword must not be empty")
        self._validate_limit(limit)
        if limit == 0:
            return {"keyword": normalized, "total": 0, "page": 0, "has_more": False, "items": []}
        size = min(max(page_size, 1), 50)
        page = 1
        results: list[dict[str, Any]] = []
        has_more = True
        while has_more and len(results) < limit:
            payload = self._app_get("/x/v2/search", {"keyword": normalized, "pn": page, "ps": size})
            data = _mapping(payload.get("data"))
            items = _list(data.get("item"))
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                normalized_item = dict(item)
                normalized_item["title"] = _clean_title(item.get("title"))
                results.append(normalized_item)
                if len(results) >= limit:
                    break
            has_more = bool(items) and len(items) >= size
            page += 1
        return {
            "keyword": normalized,
            "total": len(results),
            "page": page - 1,
            "has_more": has_more,
            "items": results,
        }

    def get_comments(
        self,
        video_url_or_id: str | int,
        *,
        include_replies: bool = False,
        reply_limit: int | None = None,
        reply_page_size: int = 20,
        limit: int | None = 20,
        page_size: int = 20,
        mode: int = 3,
    ) -> dict[str, Any]:
        self._validate_limit(limit)
        self._validate_limit(reply_limit, "reply_limit")
        bvid, aid = self._resolve_video(video_url_or_id)
        if not aid:
            detail = self._get_video_payload(video_url_or_id)
            aid = str(detail.get("aid") or "")
            bvid = str(detail.get("bvid") or bvid or "")
        if not aid:
            raise BilibiliResponseError("video response does not contain aid")
        if limit == 0:
            return {"bvid": bvid, "aid": aid, "total": 0, "cursor": "0", "has_more": False, "comments": []}
        size = min(max(page_size, 1), 49)
        cursor = "0"
        seen_cursors: set[str] = set()
        seen_ids: set[str] = set()
        comments: list[dict[str, Any]] = []
        has_more = True
        available = 0

        while has_more and (limit is None or len(comments) < limit):
            if cursor in seen_cursors:
                raise BilibiliResponseError(f"comment pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            payload = self._web_get(
                "/x/v2/reply/main",
                {
                    "oid": aid,
                    "type": "1",
                    "mode": str(mode),
                    "next": cursor,
                    "ps": size,
                    "plat": "1",
                    "web_location": "1315875",
                },
            )
            data = _mapping(payload.get("data"))
            page_cursor = _mapping(data.get("cursor"))
            available = _integer(page_cursor.get("all_count"))
            items = _list(data.get("replies"))
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                comment = self._normalize_comment(item)
                if not comment["id"] or comment["id"] in seen_ids:
                    continue
                seen_ids.add(comment["id"])
                if include_replies and comment["reply_count"]:
                    comment["replies"] = self.get_comment_replies(
                        aid,
                        comment["id"],
                        limit=reply_limit,
                        page_size=reply_page_size,
                    )["replies"]
                comments.append(comment)
                if limit is not None and len(comments) >= limit:
                    break
            has_more = not bool(page_cursor.get("is_end")) and bool(items)
            next_cursor = str(page_cursor.get("next") or "")
            if not has_more:
                cursor = next_cursor or cursor
                break
            if not next_cursor or next_cursor == cursor:
                raise BilibiliResponseError("comment response did not advance its cursor")
            cursor = next_cursor

        return {
            "bvid": bvid,
            "aid": aid,
            "available": available,
            "total": len(comments),
            "cursor": cursor,
            "has_more": has_more,
            "comments": comments,
        }

    def get_comment_replies(
        self,
        aid: str | int,
        root_id: str | int,
        *,
        limit: int | None = 20,
        page_size: int = 20,
    ) -> dict[str, Any]:
        aid_value = self._positive_id(aid, "aid")
        root_value = self._positive_id(root_id, "root_id")
        self._validate_limit(limit)
        if limit == 0:
            return {"aid": aid_value, "root_id": root_value, "total": 0, "page": 0, "has_more": False, "replies": []}
        size = min(max(page_size, 1), 49)
        page = 1
        available = 0
        replies: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        has_more = True
        while has_more and (limit is None or len(replies) < limit):
            payload = self._web_get(
                "/x/v2/reply/reply",
                {"oid": aid_value, "type": "1", "root": root_value, "pn": page, "ps": size},
            )
            data = _mapping(payload.get("data"))
            page_info = _mapping(data.get("page"))
            available = _integer(page_info.get("count"))
            items = _list(data.get("replies"))
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                reply = self._normalize_comment(item)
                if not reply["id"] or reply["id"] in seen_ids:
                    continue
                seen_ids.add(reply["id"])
                replies.append(reply)
                if limit is not None and len(replies) >= limit:
                    break
            has_more = bool(items) and page * size < available
            page += 1
        return {
            "aid": aid_value,
            "root_id": root_value,
            "available": available,
            "total": len(replies),
            "page": page - 1,
            "has_more": has_more,
            "replies": replies,
        }

    def get_relation_stats(self, user_id: str | int) -> dict[str, Any]:
        mid = self._positive_id(user_id, "user_id")
        payload = self._web_get("/x/relation/stat", {"vmid": mid})
        return dict(_mapping(payload.get("data")))

    def get_favorite_folders(self, user_id: str | int) -> dict[str, Any]:
        mid = self._positive_id(user_id, "user_id")
        payload = self._web_get("/x/v3/fav/folder/created/list-all", {"up_mid": mid})
        data = _mapping(payload.get("data"))
        folders = [dict(item) for item in _list(data.get("list")) if isinstance(item, Mapping)]
        return {"user_id": mid, "total": len(folders), "folders": folders}

    def get_collection_videos(
        self,
        folder_id: str | int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        media_id = self._positive_id(folder_id, "folder_id")
        payload = self._web_get(
            "/x/v3/fav/resource/list",
            {
                "media_id": media_id,
                "pn": max(1, page),
                "ps": min(max(page_size, 1), 40),
                "keyword": "",
                "order": "mtime",
                "type": "0",
                "tid": "0",
                "platform": "web",
            },
        )
        data = _mapping(payload.get("data"))
        items = [dict(item) for item in _list(data.get("medias")) if isinstance(item, Mapping)]
        return {"folder_id": media_id, "page": max(1, page), "total": len(items), "items": items, "has_more": bool(data.get("has_more"))}

    def get_live_room(self, room_id: str | int) -> dict[str, Any]:
        room = self._positive_id(room_id, "room_id")
        payload = self._live_get("/room/v1/Room/get_info", {"room_id": room})
        return dict(_mapping(payload.get("data")))

    def get_live_streams(
        self,
        room_id: str | int,
        *,
        quality: int = 10000,
    ) -> dict[str, Any]:
        room = self._positive_id(room_id, "room_id")
        payload = self._live_get(
            "/xlive/web-room/v2/index/getRoomPlayInfo",
            {
                "room_id": room,
                "protocol": "0,1",
                "format": "0,1,2",
                "codec": "0,1",
                "qn": max(80, quality),
                "platform": "web",
                "ptype": "8",
            },
        )
        return dict(_mapping(payload.get("data")))

    def get_live_areas(self) -> list[dict[str, Any]]:
        payload = self._live_get("/room/v1/Area/getList", {})
        return [dict(item) for item in _list(payload.get("data")) if isinstance(item, Mapping)]

    def get_live_streamers(
        self,
        area_id: str | int,
        *,
        parent_area_id: str | int = 0,
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        area = self._positive_id(area_id, "area_id", allow_zero=True)
        parent = self._positive_id(parent_area_id, "parent_area_id", allow_zero=True)
        payload = self._live_get(
            "/xlive/web-interface/v1/second/getList",
            {
                "platform": "web",
                "parent_area_id": parent,
                "area_id": area,
                "sort_type": "online",
                "page": max(1, page),
                "page_size": min(max(page_size, 1), 50),
            },
        )
        return dict(_mapping(payload.get("data")))

    def bv_to_aid(self, bvid: str) -> str:
        normalized, _ = self._resolve_video(bvid)
        if not normalized:
            raise BilibiliInputError("a BV id is required")
        return str(self._get_video_payload(normalized).get("aid") or "")

    def extract_user_id(self, value: str | int) -> str:
        text = str(value).strip()
        if text.isdigit() and int(text) > 0:
            return text
        url = text if "://" in text else f"https://{text}"
        parsed = urlsplit(url)
        if not self._is_bilibili_host(parsed.hostname):
            raise BilibiliInputError("user link must use a bilibili.com or b23.tv host")
        result = self._mid_from_path(parsed.path)
        if result:
            return result
        if (parsed.hostname or "").lower().endswith("b23.tv"):
            response = self._request(url, params={}, allow_redirects=True)
            final = urlsplit(str(response.url))
            result = self._mid_from_path(final.path)
            if result:
                return result
        raise BilibiliInputError("user link does not contain a numeric user id")

    def _get_video_payload(self, video_url_or_id: str | int) -> Mapping[str, Any]:
        bvid, aid = self._resolve_video(video_url_or_id)
        params = {"bvid": bvid} if bvid else {"aid": aid}
        payload = self._web_get("/x/web-interface/view", params)
        data = _mapping(payload.get("data"))
        if not data.get("aid") or not data.get("bvid"):
            raise BilibiliResponseError("video response does not contain aid and bvid")
        return data

    def _web_get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._ensure_identity()
        return self._json_get(f"{_API_BASE}{path}", params, headers=_WEB_HEADERS)

    def _app_get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        signed = self.signer.sign(_APP_PARAMS | dict(params))
        return self._json_get(
            f"{_APP_BASE}{path}",
            signed,
            headers={"User-Agent": APP_USER_AGENT},
        )

    def _app_rest_fetch(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        signed = self.signer.sign(_APP_PARAMS | dict(params))
        return self._json_get(
            f"{base_url.rstrip('/')}{path}",
            signed,
            headers=app_rest_headers(self._ensure_mobile_profile()),
            allow_redirects=False,
            session=self.app_session,
        )

    def _app_grpc_fetch(self, path: str, payload: bytes) -> bytes:
        return fetch_app_grpc(
            self.app_session,
            path,
            payload,
            profile=self._ensure_mobile_profile(),
            timeout=self.timeout,
            retries=self.retries,
        )

    def _live_get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._ensure_identity()
        return self._json_get(f"{_LIVE_BASE}{path}", params, headers=_LIVE_HEADERS)

    def _wbi_get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        signer = self._ensure_wbi_signer()
        return self._web_get(path, signer.sign(params))

    def _json_get(
        self,
        url: str,
        params: Mapping[str, Any],
        *,
        headers: Mapping[str, str | None] | None = None,
        allow_redirects: bool = True,
        session: requests.Session | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            url,
            params=params,
            headers=headers,
            allow_redirects=allow_redirects,
            session=session,
        )
        try:
            payload = response.json()
        except (requests.exceptions.JSONDecodeError, ValueError) as exc:
            raise BilibiliResponseError(f"Bilibili returned non-JSON data for {urlsplit(url).path}") from exc
        if not isinstance(payload, dict):
            raise BilibiliResponseError(f"Bilibili returned a non-object payload for {urlsplit(url).path}")
        code = payload.get("code", 0)
        if code not in (0, "0", None):
            message = payload.get("message") or payload.get("msg") or "unknown error"
            data = _mapping(payload.get("data"))
            voucher = data.get("v_voucher")
            detail = f"; voucher={voucher}" if voucher else ""
            raise BilibiliResponseError(f"Bilibili API code {code}: {message}{detail}")
        return payload

    def _request(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str | None] | None = None,
        allow_redirects: bool = True,
        session: requests.Session | None = None,
    ) -> requests.Response:
        last_error: Exception | None = None
        clean_headers = {key: value for key, value in (headers or {}).items() if value is not None}
        transport = self.session if session is None else session
        for attempt in range(self.retries + 1):
            try:
                response = transport.get(
                    url,
                    params=dict(params),
                    headers=clean_headers or None,
                    timeout=self.timeout,
                    allow_redirects=allow_redirects,
                )
            except requests.RequestsError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.35 * (2**attempt))
                continue
            if response.status_code in _RETRYABLE_STATUS:
                last_error = BilibiliResponseError(
                    f"Bilibili returned HTTP {response.status_code} for {urlsplit(url).path}"
                )
                if attempt >= self.retries:
                    raise last_error
                time.sleep(0.35 * (2**attempt))
                continue
            if response.status_code != 200:
                raise BilibiliResponseError(
                    f"Bilibili returned HTTP {response.status_code} for {urlsplit(url).path}"
                )
            return response
        raise BilibiliResponseError(f"request failed for {urlsplit(url).path}: {last_error}") from last_error

    def _ensure_identity(self) -> None:
        if self._identity_ready:
            return
        payload = self._json_get(_SPI_URL, {}, headers=_WEB_HEADERS)
        data = _mapping(payload.get("data"))
        buvid3 = str(data.get("b_3") or "")
        buvid4 = str(data.get("b_4") or "")
        if not buvid3 or not buvid4:
            raise BilibiliResponseError("fingerprint response does not contain buvid3 and buvid4")
        cookie_jar = getattr(self.session, "cookies", None)
        if cookie_jar is not None and hasattr(cookie_jar, "set"):
            cookie_jar.set("buvid3", buvid3, domain=".bilibili.com")
            cookie_jar.set("buvid4", buvid4, domain=".bilibili.com")
            cookie_jar.set("b_nut", str(int(time.time())), domain=".bilibili.com")
        self._identity_ready = True

    def _ensure_mobile_profile(self) -> MobileProfile:
        if self._mobile_profile is None:
            self._mobile_profile = load_mobile_profile(
                home=self._mobile_profile_home,
            )
        return self._mobile_profile

    def _ensure_wbi_signer(self) -> BilibiliWbiSigner:
        if (
            self.wbi_signer is not None
            and self.wbi_signer.img_key
            and self.wbi_signer.sub_key
        ):
            return self.wbi_signer
        self._ensure_identity()
        url = f"{_API_BASE}/x/web-interface/nav"
        response = self._request(url, params={}, headers=_WEB_HEADERS)
        try:
            payload = response.json()
        except (requests.exceptions.JSONDecodeError, ValueError) as exc:
            raise BilibiliSignatureError("navigation response is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise BilibiliSignatureError("navigation response is not an object")
        wbi_img = _mapping(_mapping(payload.get("data")).get("wbi_img"))
        img_url = str(wbi_img.get("img_url") or "")
        sub_url = str(wbi_img.get("sub_url") or "")
        if not img_url or not sub_url:
            raise BilibiliSignatureError("navigation response does not contain WBI keys")
        self.wbi_signer = BilibiliWbiSigner(img_url, sub_url)
        return self.wbi_signer

    def _resolve_video(self, value: str | int) -> tuple[str | None, str | None]:
        text = str(value).strip()
        bvid_match = _BVID_RE.fullmatch(text)
        if bvid_match:
            return bvid_match.group(0), None
        aid_match = _AID_RE.fullmatch(text)
        if aid_match and int(aid_match.group(1)) > 0:
            return None, aid_match.group(1)

        url = text if "://" in text else f"https://{text}"
        parsed = urlsplit(url)
        if not self._is_bilibili_host(parsed.hostname):
            raise BilibiliInputError("video link must use a bilibili.com or b23.tv host")
        if (parsed.hostname or "").lower().endswith("b23.tv"):
            response = self._request(url, params={}, allow_redirects=True)
            parsed = urlsplit(str(response.url))
        bvid_match = _BVID_RE.search(parsed.path)
        if bvid_match:
            return bvid_match.group(0), None
        for part in parsed.path.split("/"):
            aid_match = _AID_RE.fullmatch(part)
            if aid_match and int(aid_match.group(1)) > 0:
                return None, aid_match.group(1)
        raise BilibiliInputError("video input does not contain a valid BV or AV id")

    @staticmethod
    def _normalize_video(item: Mapping[str, Any]) -> dict[str, Any]:
        return app_rest._normalize_video(item)

    @staticmethod
    def _normalize_archive_video(item: Mapping[str, Any]) -> dict[str, Any]:
        bvid = str(item.get("bvid") or "")
        aid = str(item.get("param") or item.get("aid") or "")
        return {
            "id": bvid or aid,
            "bvid": bvid,
            "aid": aid,
            "url": f"https://www.bilibili.com/video/{bvid or 'av' + aid}",
            "title": str(item.get("title") or ""),
            "cover": str(item.get("cover") or ""),
            "author": str(item.get("author") or ""),
            "category": str(item.get("tname") or ""),
            "duration": _integer(item.get("duration")),
            "create_time": _integer(item.get("ctime")),
            "views": _integer(item.get("play")),
            "danmaku": _integer(item.get("danmaku")),
            "cid": str(item.get("first_cid") or ""),
        }

    @staticmethod
    def _normalize_comment(item: Mapping[str, Any]) -> dict[str, Any]:
        return app_rest._normalize_comment(item)

    @staticmethod
    def _validate_limit(value: int | None, name: str = "limit") -> None:
        if value is not None and value < 0:
            raise BilibiliInputError(f"{name} must be non-negative")

    @staticmethod
    def _positive_id(value: str | int, name: str, *, allow_zero: bool = False) -> str:
        text = str(value).strip()
        if not text.isdigit() or (int(text) < 0 if allow_zero else int(text) <= 0):
            qualifier = "non-negative" if allow_zero else "positive"
            raise BilibiliInputError(f"{name} must be a {qualifier} integer")
        return text

    @staticmethod
    def _is_bilibili_host(hostname: str | None) -> bool:
        host = (hostname or "").lower().rstrip(".")
        return host == "bilibili.com" or host.endswith(".bilibili.com") or host == "b23.tv" or host.endswith(".b23.tv")

    @staticmethod
    def _mid_from_path(path: str) -> str | None:
        parts = [part for part in path.split("/") if part]
        if parts and parts[0].isdigit() and int(parts[0]) > 0:
            return parts[0]
        return None
