from __future__ import annotations

import html
import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import PiPiXiaInputError, PiPiXiaResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)
APP_ID = 1319
APP_NAME = "super"

_API_BASE = "https://api.pipix.com"
_SHARE_BASE = "https://h5.pipix.com"
_COMMENTS_URL = f"{_API_BASE}/bds/cell/cell_comment/"
_PROFILE_URL = f"{_API_BASE}/bds/user/user_profile/"
_FOLLOWERS_URL = f"{_API_BASE}/bds/user/follower/"
_FOLLOWING_URL = f"{_API_BASE}/bds/user/following/"
_HOT_URL = f"{_API_BASE}/bds/search/hot/"
_HASHTAG_URL = f"{_API_BASE}/bds/hashtag/detail/"
_SHORT_URL = f"{_API_BASE}/bds/share/short_url/"

_SHARE_HOSTS = frozenset({"pipix.com", "www.pipix.com", "h5.pipix.com"})
_CELL_ID_RE = re.compile(r"^[1-9][0-9]{9,21}$")
_USER_ID_RE = re.compile(r"^[1-9][0-9]{4,21}$")
_HASHTAG_ID_RE = re.compile(r"^[1-9][0-9]{0,18}$")
_ITEM_PATH_RE = re.compile(r"^/(?:item|video)/([1-9][0-9]{9,21})/?$")
_USER_PATH_RE = re.compile(r"^/(?:user|profile)/([1-9][0-9]{4,21})/?$")
_HASHTAG_PATH_RE = re.compile(r"^/(?:hashtag|topic)/([1-9][0-9]{0,18})/?$")
_SHORT_PATH_RE = re.compile(r"^/s/([A-Za-z0-9_-]{3,64})/?$")
_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SHARE_URL_RE = re.compile(
    r"(?<![A-Za-z0-9.-])(?:https?://)?"
    r"(?:(?:h5|www)\.)?pipix\.com/[^\s<>\"']+",
    re.IGNORECASE,
)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>，。；：！？）】》、"
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _number(value: Any) -> int | float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return int(result) if result.is_integer() else result


def _timestamp(value: Any) -> int:
    result = _integer(value)
    while result >= 10_000_000_000:
        result //= 1000
    return max(0, result)


def _timestamp_iso(value: Any) -> str | None:
    result = _timestamp(value)
    if not result:
        return None
    try:
        return datetime.fromtimestamp(result, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _url(value: Any) -> str:
    source = html.unescape(str(value or "").strip())
    if source.startswith("//"):
        return f"https:{source}"
    if source.startswith("http://"):
        return f"https://{source[7:]}"
    return source


def _asset_urls(value: Any, *, include_download: bool = False) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    def add(candidate: Any) -> None:
        normalized = _url(candidate)
        if normalized.startswith("https://") and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)

    if isinstance(value, str):
        add(value)
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            for candidate in _asset_urls(item, include_download=include_download):
                add(candidate)
        return output
    asset = _mapping(value)
    add(asset.get("url"))
    for item in _list(asset.get("url_list")):
        add(_mapping(item).get("url") if isinstance(item, Mapping) else item)
    if include_download:
        for item in _list(asset.get("download_list")):
            add(_mapping(item).get("url") if isinstance(item, Mapping) else item)
    return output


def _asset(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    urls = _asset_urls(source)
    downloads = _asset_urls(source.get("download_list"))
    return {
        "url": urls[0] if urls else (downloads[0] if downloads else ""),
        "urls": urls,
        "download_urls": downloads,
        "uri": str(source.get("uri") or ""),
        "width": _integer(source.get("width")),
        "height": _integer(source.get("height")),
        "is_gif": bool(source.get("is_gif")),
    }


def _normalize_user(value: Any) -> dict[str, Any]:
    user = _mapping(value)
    identifier = str(user.get("id_str") or user.get("id") or "")
    certification = _mapping(user.get("certify_info"))
    authentication = user.get("authentication")
    if isinstance(authentication, Mapping):
        authentication_text = str(
            authentication.get("description") or authentication.get("name") or ""
        )
    else:
        authentication_text = str(authentication or "")
    verification = str(certification.get("description") or authentication_text)
    author_info = _mapping(user.get("author_info"))
    medal_info = _mapping(user.get("medal_info"))
    return {
        "id": identifier,
        "name": str(user.get("name") or author_info.get("username") or ""),
        "description": str(user.get("description") or ""),
        "avatar": _asset(user.get("avatar")),
        "large_avatar": _asset(user.get("large_avatar")),
        "background": _asset(user.get("background")),
        "followers": _integer(user.get("followers_count")),
        "following": _integer(user.get("followings_count")),
        "likes": _integer(user.get("like_count")),
        "posts": _integer(user.get("article_count")),
        "god_comments": _integer(user.get("god_comment_count")),
        "votes": _integer(user.get("vote_count")),
        "gender": _integer(user.get("gender")),
        "age": str(user.get("age") or ""),
        "horoscope": str(user.get("horoscope") or ""),
        "city": str(user.get("city_name") or user.get("city") or ""),
        "region": str(user.get("region") or ""),
        "language": str(user.get("language") or ""),
        "created_timestamp": _timestamp(user.get("create_time")),
        "created_at": _timestamp_iso(user.get("create_time")),
        "verified": bool(certification or authentication_text),
        "verification": verification,
        "verification_type": _integer(certification.get("certify_type")),
        "recommend_tag": str(user.get("recommend_tag") or ""),
        "medal_count": _integer(medal_info.get("total_medal")),
        "is_live": bool(user.get("liveing_info")),
        "profile_schema": str(user.get("profile_schema") or ""),
        "status": _integer(user.get("status")),
    }


def _normalize_video(value: Any) -> tuple[list[dict[str, Any]], str]:
    video = _mapping(value)
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in (
        "video_download",
        "video_high",
        "video_medium",
        "video_low",
        "video_fallback",
    ):
        raw = _mapping(video.get(key))
        urls = _asset_urls(raw)
        if not urls:
            continue
        unique = [item for item in urls if item not in seen]
        seen.update(unique)
        if not unique:
            continue
        variants.append(
            {
                "quality": key.removeprefix("video_"),
                "url": unique[0],
                "urls": unique,
                "uri": str(raw.get("uri") or ""),
                "width": _integer(raw.get("width")),
                "height": _integer(raw.get("height")),
                "duration_seconds": _number(raw.get("duration")),
                "definition": _integer(raw.get("definition")),
                "codec_type": _integer(raw.get("codec_type")),
            }
        )
    direct_urls = _asset_urls(video.get("video_god_comment_urls"))
    unique_direct = [item for item in direct_urls if item not in seen]
    if unique_direct:
        variants.append(
            {
                "quality": "god_comment",
                "url": unique_direct[0],
                "urls": unique_direct,
                "uri": "",
                "width": 0,
                "height": 0,
                "duration_seconds": _number(video.get("duration")),
                "definition": 0,
                "codec_type": 0,
            }
        )
    return variants, variants[0]["url"] if variants else ""


def _normalize_comment(value: Any) -> dict[str, Any]:
    wrapper = _mapping(value)
    comment = _mapping(wrapper.get("comment_info")) or wrapper
    identifier = str(comment.get("comment_id_str") or comment.get("comment_id") or "")
    replies = [
        _normalize_comment(item)
        for item in _list(comment.get("replies"))
        if isinstance(item, Mapping)
    ]
    return {
        "id": identifier,
        "cell_id": str(wrapper.get("cell_id_str") or wrapper.get("cell_id") or identifier),
        "text": str(comment.get("text") or ""),
        "created_timestamp": _timestamp(comment.get("create_time")),
        "created_at": _timestamp_iso(comment.get("create_time")),
        "user": _normalize_user(comment.get("user")),
        "likes": _integer(comment.get("like_count")),
        "replies_count": _integer(comment.get("reply_count")),
        "shares": _integer(comment.get("share_count")),
        "buries": _integer(comment.get("bury_count")),
        "favorites": _integer(comment.get("favorite_count")),
        "root_cell_id": str(comment.get("root_cell_id") or ""),
        "has_author_like": bool(comment.get("has_author_like")),
        "highlighted": bool(comment.get("highlight")),
        "pinned": bool(wrapper.get("stickup")),
        "city": str(wrapper.get("city_name") or ""),
        "replies": replies,
    }


class PiPiXiaClient:
    """面向 PiPiXia 公开 App JSON 接口的匿名纯 HTTP 客户端。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
    ) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise PiPiXiaInputError("timeout must be a positive finite number")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise PiPiXiaInputError("retries must be a non-negative integer")
        if (
            not isinstance(user_agent, str)
            or not user_agent.strip()
            or "\n" in user_agent
            or "\r" in user_agent
        ):
            raise PiPiXiaInputError("user_agent must be a non-empty single-line string")
        self.session = session if session is not None else requests.Session(impersonate="chrome")
        self.timeout = float(timeout)
        self.retries = retries
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def resolve_cell_id(value: str | int) -> str:
        return PiPiXiaClient._resolve_identifier(
            value,
            label="post",
            identifier_re=_CELL_ID_RE,
            path_re=_ITEM_PATH_RE,
        )

    @staticmethod
    def resolve_user_id(value: str | int) -> str:
        return PiPiXiaClient._resolve_identifier(
            value,
            label="user",
            identifier_re=_USER_ID_RE,
            path_re=_USER_PATH_RE,
        )

    @staticmethod
    def resolve_hashtag_id(value: str | int) -> str:
        return PiPiXiaClient._resolve_identifier(
            value,
            label="hashtag",
            identifier_re=_HASHTAG_ID_RE,
            path_re=_HASHTAG_PATH_RE,
        )

    @classmethod
    def _resolve_identifier(
        cls,
        value: str | int,
        *,
        label: str,
        identifier_re: re.Pattern[str],
        path_re: re.Pattern[str],
    ) -> str:
        if isinstance(value, bool):
            raise PiPiXiaInputError(f"invalid {label} reference")
        source = str(value).strip()
        if identifier_re.fullmatch(source):
            return source
        candidate = cls._extract_share_url(source)
        parsed = cls._validate_share_url(candidate, label=label)
        match = path_re.fullmatch(parsed.path)
        if not match:
            if label == "post" and _SHORT_PATH_RE.fullmatch(parsed.path):
                raise PiPiXiaInputError("short share URL must be resolved with a client instance")
            raise PiPiXiaInputError(f"unsupported PiPiXia {label} URL path")
        return match.group(1)

    def resolve_share(self, value: str | int) -> dict[str, Any]:
        if isinstance(value, bool):
            raise PiPiXiaInputError("invalid post reference")
        source = str(value).strip()
        if _CELL_ID_RE.fullmatch(source):
            canonical = f"{_SHARE_BASE}/item/{source}"
            return {
                "cell_id": source,
                "short_code": None,
                "source_url": canonical,
                "resolved_url": canonical,
                "redirect_chain": [canonical],
            }

        source_url = self._extract_share_url(source)
        parsed = self._validate_share_url(source_url, label="post")
        direct = _ITEM_PATH_RE.fullmatch(parsed.path)
        if direct:
            return {
                "cell_id": direct.group(1),
                "short_code": None,
                "source_url": source_url,
                "resolved_url": source_url,
                "redirect_chain": [source_url],
            }
        short = _SHORT_PATH_RE.fullmatch(parsed.path)
        if not short:
            raise PiPiXiaInputError("unsupported PiPiXia post URL path")

        chain = [source_url]
        current = source_url
        for _ in range(6):
            response = self._request(current, allow_redirect_status=True, allow_redirects=False)
            if response.status_code < 300 or response.status_code >= 400:
                raise PiPiXiaResponseError("short share stopped before exposing a post id")
            location = str(response.headers.get("location") or "").strip()
            if not location:
                raise PiPiXiaResponseError("short share redirect did not include Location")
            current = urljoin(current, location)
            target = self._validate_share_url(current, label="redirect")
            current = urlunsplit((target.scheme, target.netloc, target.path, target.query, ""))
            chain.append(current)
            item = _ITEM_PATH_RE.fullmatch(target.path)
            if item:
                return {
                    "cell_id": item.group(1),
                    "short_code": short.group(1),
                    "source_url": source_url,
                    "resolved_url": current,
                    "redirect_chain": chain,
                }
        raise PiPiXiaResponseError("short share exceeded the redirect limit")

    def get_post(self, reference: str | int, *, cell_type: int = 1) -> dict[str, Any]:
        normalized_type = self._cell_type(cell_type)
        resolution = self.resolve_share(reference)
        payload = self._get_json(
            _COMMENTS_URL,
            params={
                **self._common_params(),
                "offset": 0,
                "count": 10,
                "cell_type": normalized_type,
                "api_version": 1,
                "cell_id": resolution["cell_id"],
            },
        )
        result = self.parse_post_payload(payload, expected_id=resolution["cell_id"])
        result.update(resolution)
        return result

    def get_comments(
        self,
        reference: str | int,
        *,
        offset: str | int = 0,
        count: int = 20,
        cell_type: int = 1,
    ) -> dict[str, Any]:
        normalized_type = self._cell_type(cell_type)
        normalized_offset = self._cursor(offset, "offset")
        normalized_count = self._limit(count, maximum=50)
        resolution = self.resolve_share(reference)
        payload = self._get_json(
            _COMMENTS_URL,
            params={
                **self._common_params(),
                "offset": normalized_offset,
                "count": normalized_count,
                "cell_type": normalized_type,
                "api_version": 1,
                "cell_id": resolution["cell_id"],
            },
        )
        result = self.parse_comments_payload(payload, cell_id=resolution["cell_id"])
        result.update(
            {
                "source_url": resolution["source_url"],
                "resolved_url": resolution["resolved_url"],
            }
        )
        return result

    def get_user(self, reference: str | int) -> dict[str, Any]:
        user_id = self.resolve_user_id(reference)
        payload = self._get_json(
            _PROFILE_URL,
            params={**self._common_params(), "user_id": user_id},
        )
        return self.parse_user_payload(payload, expected_id=user_id)

    def get_followers(
        self,
        reference: str | int,
        *,
        cursor: str | int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._get_user_list(
            reference,
            kind="followers",
            url=_FOLLOWERS_URL,
            cursor=cursor,
            limit=limit,
        )

    def get_following(
        self,
        reference: str | int,
        *,
        cursor: str | int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._get_user_list(
            reference,
            kind="following",
            url=_FOLLOWING_URL,
            cursor=cursor,
            limit=limit,
        )

    def get_hot_search_words(self, *, limit: int = 20) -> dict[str, Any]:
        normalized_limit = self._limit(limit, maximum=50)
        payload = self._get_json(_HOT_URL, params=self._common_params())
        return self.parse_hot_payload(payload, limit=normalized_limit)

    def get_hashtag(self, reference: str | int) -> dict[str, Any]:
        hashtag_id = self.resolve_hashtag_id(reference)
        payload = self._get_json(
            _HASHTAG_URL,
            params={**self._common_params(), "hashtag_id": hashtag_id},
        )
        return self.parse_hashtag_payload(payload, expected_id=hashtag_id)

    def get_short_url(self, original_url: str) -> dict[str, Any]:
        normalized = self._original_url(original_url)
        payload = self._post_json(
            _SHORT_URL,
            params=self._common_params(),
            data={"url": normalized},
        )
        return self.parse_short_url_payload(payload, original_url=normalized)

    @staticmethod
    def parse_post_payload(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        data = PiPiXiaClient._api_data(payload, "post detail")
        candidates: list[Mapping[str, Any]] = []
        for entry in _list(data.get("cell_comments")):
            item = _mapping(_mapping(entry).get("comment_info")).get("item")
            if isinstance(item, Mapping):
                candidates.append(item)
        if not candidates:
            raise PiPiXiaResponseError("post detail response did not include an item")
        selected = None
        if expected_id is not None:
            selected = next(
                (
                    item
                    for item in candidates
                    if str(item.get("item_id_str") or item.get("item_id") or "")
                    == expected_id
                ),
                None,
            )
            if selected is None:
                found = str(candidates[0].get("item_id_str") or candidates[0].get("item_id") or "")
                raise PiPiXiaResponseError(
                    f"post response ID mismatch: expected {expected_id}, got {found or 'missing'}"
                )
        else:
            selected = candidates[0]
        item = _mapping(selected)
        identifier = str(item.get("item_id_str") or item.get("item_id") or "")
        if not _CELL_ID_RE.fullmatch(identifier):
            raise PiPiXiaResponseError("post detail response has an invalid item id")

        video = _mapping(item.get("video"))
        video_variants, video_url = _normalize_video(video)
        note = _mapping(item.get("note"))
        image_values = _list(note.get("multi_image") or item.get("images"))
        images = [_asset(value) for value in image_values if isinstance(value, Mapping)]
        cover = _asset(item.get("cover") or video.get("cover_image"))
        media_type = "video" if video else ("album" if images else "text")
        comments = [
            _normalize_comment(entry)
            for entry in _list(data.get("cell_comments"))
            if isinstance(entry, Mapping)
        ]
        return {
            "id": identifier,
            "item_type": _integer(item.get("item_type")),
            "cell_type": _integer(item.get("item_cell_type")),
            "media_type": media_type,
            "content": str(item.get("content") or video.get("text") or ""),
            "url": f"{_SHARE_BASE}/item/{identifier}",
            "created_timestamp": _timestamp(item.get("create_time")),
            "created_at": _timestamp_iso(item.get("create_time")),
            "duration_seconds": _number(item.get("duration") or video.get("duration")),
            "author": _normalize_user(item.get("author")),
            "cover": cover,
            "cover_url": cover["url"],
            "video_id": str(video.get("video_id") or ""),
            "video_url": video_url,
            "videos": video_variants,
            "images": images,
            "statistics": {
                "comments": _integer(data.get("count") or item.get("comment_count")),
                "likes": _integer(item.get("like_count") or item.get("digg_count")),
                "shares": _integer(item.get("share_count")),
                "favorites": _integer(item.get("favorite_count")),
            },
            "can_download": bool(item.get("can_download")),
            "status": _integer(item.get("status")),
            "comments_preview": comments,
            "comments_next_offset": str(data.get("offset") or "0"),
            "comments_has_more": bool(data.get("has_more")),
        }

    @staticmethod
    def parse_comments_payload(payload: Any, *, cell_id: str) -> dict[str, Any]:
        if not _CELL_ID_RE.fullmatch(str(cell_id or "")):
            raise PiPiXiaInputError("cell_id must be a decimal PiPiXia post id")
        data = PiPiXiaClient._api_data(payload, "comments")
        comments = [
            _normalize_comment(entry)
            for entry in _list(data.get("cell_comments"))
            if isinstance(entry, Mapping)
        ]
        for entry in _list(data.get("cell_comments")):
            item = _mapping(_mapping(entry).get("comment_info")).get("item")
            if isinstance(item, Mapping):
                item_id = str(item.get("item_id_str") or item.get("item_id") or "")
                if item_id and item_id != cell_id:
                    raise PiPiXiaResponseError(
                        f"comments response ID mismatch: expected {cell_id}, got {item_id}"
                    )
        return {
            "cell_id": cell_id,
            "total": _integer(data.get("count")),
            "count": len(comments),
            "next_offset": str(data.get("offset") or "0"),
            "has_more": bool(data.get("has_more")),
            "comments": comments,
        }

    @staticmethod
    def parse_user_payload(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        data = PiPiXiaClient._api_data(payload, "user profile")
        raw = _mapping(data.get("user_info"))
        if not raw:
            raise PiPiXiaResponseError("user profile response did not include user_info")
        user = _normalize_user(raw)
        if not _USER_ID_RE.fullmatch(user["id"]):
            raise PiPiXiaResponseError("user profile response has an invalid user id")
        if expected_id is not None and user["id"] != expected_id:
            raise PiPiXiaResponseError(
                f"user response ID mismatch: expected {expected_id}, got {user['id']}"
            )
        user["profile_ban"] = bool(data.get("profile_ban"))
        return user

    @staticmethod
    def parse_user_list_payload(
        payload: Any,
        *,
        user_id: str,
        kind: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        if kind not in {"followers", "following"}:
            raise PiPiXiaInputError("kind must be followers or following")
        if not _USER_ID_RE.fullmatch(str(user_id or "")):
            raise PiPiXiaInputError("user_id must be a decimal PiPiXia user id")
        normalized_limit = PiPiXiaClient._limit(limit, maximum=50)
        data = PiPiXiaClient._api_data(payload, kind)
        users = [
            _normalize_user(value)
            for value in _list(data.get("users"))[:normalized_limit]
            if isinstance(value, Mapping)
        ]
        cursor = _mapping(data.get("cursor"))
        return {
            "user_id": user_id,
            "kind": kind,
            "count": len(users),
            "users": users,
            "cursor": {
                "refresh": str(cursor.get("refresh_cursor") or "0"),
                "loadmore": str(cursor.get("loadmore_cursor") or "0"),
                "previous": str(cursor.get("previous_cursor") or "0"),
                "has_more": bool(cursor.get("has_more")),
            },
        }

    @staticmethod
    def parse_hot_payload(payload: Any, *, limit: int = 20) -> dict[str, Any]:
        normalized_limit = PiPiXiaClient._limit(limit, maximum=50)
        data = PiPiXiaClient._api_data(payload, "hot search")
        words: list[dict[str, Any]] = []
        for value in _list(data.get("words"))[:normalized_limit]:
            item = _mapping(value)
            text = str(item.get("tip") or "").strip()
            if text:
                words.append(
                    {
                        "text": text,
                        "hot_type": _integer(item.get("hot_type")),
                        "schema": str(item.get("schema") or ""),
                        "write_history": bool(item.get("write_history")),
                        "logo": _asset(item.get("hot_logo_image")),
                    }
                )
        keywords = [
            str(value)
            for value in _list(data.get("hot_keywords"))[:normalized_limit]
            if str(value).strip()
        ]
        return {
            "tip": str(data.get("tip") or ""),
            "keywords": keywords,
            "count": len(words),
            "words": words,
        }

    @staticmethod
    def parse_hashtag_payload(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        data = PiPiXiaClient._api_data(payload, "hashtag detail")
        hashtag = _mapping(data.get("hashtag"))
        base = _mapping(hashtag.get("base_hashtag"))
        identifier = str(base.get("id_str") or base.get("id") or hashtag.get("id_str") or "")
        if not _HASHTAG_ID_RE.fullmatch(identifier):
            raise PiPiXiaResponseError("hashtag response has an invalid hashtag id")
        if expected_id is not None and identifier != expected_id:
            raise PiPiXiaResponseError(
                f"hashtag response ID mismatch: expected {expected_id}, got {identifier}"
            )
        categories = [
            {
                "id": str(_mapping(value).get("id") or ""),
                "name": str(_mapping(value).get("name") or ""),
            }
            for value in _list(base.get("category_list"))
            if isinstance(value, Mapping)
        ]
        hosts = [
            _normalize_user(value)
            for value in _list(data.get("host_list"))
            if isinstance(value, Mapping)
        ]
        return {
            "id": identifier,
            "name": str(base.get("name") or ""),
            "intro": str(base.get("intro") or hashtag.get("intro") or ""),
            "schema": str(hashtag.get("schema") or ""),
            "icon": _asset(base.get("icon") or hashtag.get("icon")),
            "background": _asset(
                base.get("background_image") or hashtag.get("background_image")
            ),
            "status": _integer(base.get("status") or hashtag.get("status")),
            "type": _integer(base.get("hashtag_type")),
            "atmosphere": str(base.get("atmosphere") or ""),
            "created_timestamp": _timestamp(base.get("create_time")),
            "created_at": _timestamp_iso(base.get("create_time")),
            "modified_timestamp": _timestamp(base.get("modify_time")),
            "modified_at": _timestamp_iso(base.get("modify_time")),
            "statistics": {
                "works": _integer(hashtag.get("works_num")),
                "followers": _integer(hashtag.get("followers_num")),
                "views": _integer(hashtag.get("show_num")),
                "enters": _integer(hashtag.get("enter_num")),
                "new_items": _integer(hashtag.get("new_item_num")),
            },
            "categories": categories,
            "host_user_ids": [
                str(value) for value in _list(hashtag.get("host_user_ids")) if value
            ],
            "hosts": hosts,
            "top_item_ids": [
                str(value) for value in _list(base.get("top_item_ids")) if str(value).strip()
            ],
            "signed_in": bool(data.get("signin_status")),
        }

    @staticmethod
    def parse_short_url_payload(
        payload: Any,
        *,
        original_url: str = "",
    ) -> dict[str, Any]:
        data = PiPiXiaClient._api_data(payload, "short URL")
        normalized_original = (
            PiPiXiaClient._original_url(original_url) if original_url else ""
        )
        short_url = str(data.get("short_url") or "").strip()
        try:
            parsed = PiPiXiaClient._validate_share_url(short_url, label="short URL")
        except PiPiXiaInputError as exc:
            raise PiPiXiaResponseError(
                "short URL response has an invalid short_url"
            ) from exc
        match = _SHORT_PATH_RE.fullmatch(parsed.path)
        if not match:
            raise PiPiXiaResponseError("short URL response has an unsupported path")
        return {
            "original_url": normalized_original,
            "short_url": short_url,
            "short_code": match.group(1),
        }

    def _get_user_list(
        self,
        reference: str | int,
        *,
        kind: str,
        url: str,
        cursor: str | int,
        limit: int,
    ) -> dict[str, Any]:
        user_id = self.resolve_user_id(reference)
        normalized_cursor = self._cursor(cursor, "cursor")
        normalized_limit = self._limit(limit, maximum=50)
        payload = self._get_json(
            url,
            params={
                **self._common_params(),
                "user_id": user_id,
                "cursor": normalized_cursor,
                "count": normalized_limit,
            },
        )
        return self.parse_user_list_payload(
            payload,
            user_id=user_id,
            kind=kind,
            limit=normalized_limit,
        )

    @staticmethod
    def _api_data(payload: Any, label: str) -> Mapping[str, Any]:
        root = _mapping(payload)
        if not root:
            raise PiPiXiaResponseError(f"{label} response root is not an object")
        status = root.get("status_code")
        if status != 0:
            message = str(root.get("prompt") or root.get("message") or "unknown error")
            raise PiPiXiaResponseError(f"{label} API error {status}: {message}")
        data = root.get("data")
        if not isinstance(data, Mapping):
            raise PiPiXiaResponseError(f"{label} response did not include a data object")
        return data

    @staticmethod
    def _common_params() -> dict[str, Any]:
        return {
            "aid": APP_ID,
            "app_name": APP_NAME,
            "channel": "huawei_1319_64",
            "ac": "wifi",
        }

    @staticmethod
    def _extract_share_url(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PiPiXiaInputError("PiPiXia reference is empty")
        source = value.strip()
        for complete in _HTTP_URL_RE.finditer(source):
            candidate = complete.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
            try:
                hostname = (urlsplit(candidate).hostname or "").lower()
            except ValueError:
                continue
            if hostname in _SHARE_HOSTS:
                return candidate
        match = _SHARE_URL_RE.search(source)
        if not match:
            raise PiPiXiaInputError("reference does not contain a supported PiPiXia URL")
        candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        return candidate

    @staticmethod
    def _validate_share_url(value: str, *, label: str) -> Any:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise PiPiXiaInputError(f"invalid PiPiXia {label} URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or (parsed.hostname or "").lower() not in _SHARE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 80, 443}
            or parsed.fragment
        ):
            raise PiPiXiaInputError(f"invalid PiPiXia {label} URL")
        return parsed

    @staticmethod
    def _original_url(value: str) -> str:
        if not isinstance(value, str):
            raise PiPiXiaInputError("original URL must be a valid HTTP(S) URL")
        source = value.strip()
        if (
            not source
            or len(source) > 4096
            or any(character in source for character in ("\r", "\n", "\x00"))
        ):
            raise PiPiXiaInputError("original URL must be a valid HTTP(S) URL")
        try:
            parsed = urlsplit(source)
            _ = parsed.port
        except ValueError as exc:
            raise PiPiXiaInputError(
                "original URL must be a valid HTTP(S) URL"
            ) from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise PiPiXiaInputError("original URL must be a valid HTTP(S) URL")
        return source

    @staticmethod
    def _cell_type(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20:
            raise PiPiXiaInputError("cell_type must be an integer from 1 to 20")
        return value

    @staticmethod
    def _cursor(value: str | int, label: str) -> str:
        if isinstance(value, bool):
            raise PiPiXiaInputError(f"{label} must be a decimal cursor")
        source = str(value).strip()
        if not re.fullmatch(r"[0-9]{1,20}", source):
            raise PiPiXiaInputError(f"{label} must be a decimal cursor")
        return source

    @staticmethod
    def _limit(value: int, *, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise PiPiXiaInputError(f"limit/count must be an integer from 1 to {maximum}")
        return value

    def _get_json(self, url: str, *, params: Mapping[str, Any]) -> Any:
        response = self._request(url, params=dict(params))
        try:
            return response.json()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise PiPiXiaResponseError(f"invalid JSON from {urlsplit(url).path}") from exc

    def _post_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        data: Mapping[str, Any],
    ) -> Any:
        response = self._request(
            url,
            method="POST",
            params=dict(params),
            data=dict(data),
        )
        try:
            return response.json()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise PiPiXiaResponseError(f"invalid JSON from {urlsplit(url).path}") from exc

    def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        allow_redirect_status: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = self.session.post if method == "POST" else self.session.get
                response = request(url, **kwargs)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise PiPiXiaResponseError(f"request failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            if allow_redirect_status and 300 <= response.status_code < 400:
                return response
            if response.status_code < 200 or response.status_code >= 300:
                raise PiPiXiaResponseError(
                    f"HTTP {response.status_code} from {urlsplit(url).path}"
                )
            return response
        raise PiPiXiaResponseError(f"request failed: {last_error or 'unknown error'}")
