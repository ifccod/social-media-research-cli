from __future__ import annotations

import html
import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from curl_cffi import requests

from .crypto import decrypt_play_url
from .errors import XiguaInputError, XiguaResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)
APP_ID = 3586

_BASE_URL = "https://m.ixigua.com"
_VIDEO_DATA_URL = f"{_BASE_URL}/xg/api/wap/video/getInfoByGid"
_COMMENTS_URL = f"{_BASE_URL}/article/v1/tab_comments/"
_USER_URL = f"{_BASE_URL}/video/app/user/userhome/v8/"
_POSTS_URL = f"{_BASE_URL}/video/app/user/videolist_tab/v3/"
_SEARCH_URL = f"{_BASE_URL}/video/m/search/search_content/"
_HOT_URL = f"{_BASE_URL}/video/app/article/hot_recommend/v1/"
_VIDEO_HOSTS = frozenset({"ixigua.com", "www.ixigua.com", "m.ixigua.com"})
_VIDEO_ID_RE = re.compile(r"^[1-9][0-9]{9,21}$")
_USER_ID_RE = re.compile(r"^[1-9][0-9]{4,21}$")
_VIDEO_PATH_RE = re.compile(r"^/(?:video/|i)([1-9][0-9]{9,21})(?:/info/video)?/?$")
_USER_PATH_RE = re.compile(r"^/(?:user|home)/([1-9][0-9]{4,21})/?$")
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_SEARCH_ORDER = frozenset({"publish_time", "play_count"})


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
        number = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return int(number) if number.is_integer() else number


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _integer(value)
    if timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _absolute_url(value: Any) -> str:
    source = html.unescape(str(value or "").strip())
    if source.startswith("//"):
        return f"https:{source}"
    if source.startswith("/"):
        return urljoin(_BASE_URL, source)
    if source.startswith("http://"):
        return f"https://{source[7:]}"
    return source


def _image_url(value: Any) -> str:
    image = _mapping(value)
    direct = _absolute_url(image.get("url") or image.get("Url"))
    if direct:
        return direct
    for item in _list(image.get("url_list") or image.get("UrlList")):
        candidate = _absolute_url(_mapping(item).get("url") or item)
        if candidate:
            return candidate
    return ""


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._parts is not None:
            self.scripts.append("".join(self._parts))
            self._parts = None


def _normalized_author(value: Any) -> dict[str, Any]:
    author = _mapping(value)
    return {
        "id": str(author.get("id") or author.get("user_id") or ""),
        "name": str(author.get("screen_name") or author.get("name") or ""),
        "avatar_url": _absolute_url(author.get("avatar_url")),
        "followers": _integer(
            author.get("follower_count") or author.get("followers_count")
        ),
        "videos": _integer(
            author.get("video_count") or author.get("video_total_count")
        ),
        "verified": bool(author.get("user_verified") or author.get("verified")),
        "verification": str(
            author.get("verified_content")
            or author.get("auth_verified_info")
            or author.get("verify_reason")
            or ""
        ),
    }


def _normalized_video_item(value: Any) -> dict[str, Any] | None:
    item = _mapping(value)
    video_detail = _mapping(item.get("video_detail_info"))
    identifier = str(
        item.get("gid") or item.get("group_id_str") or item.get("group_id") or item.get("item_id") or ""
    )
    video_id = str(item.get("video_id") or video_detail.get("video_id") or "")
    title = str(item.get("title") or "")
    if not identifier or not title or not video_id:
        return None
    image = (
        video_detail.get("detail_video_large_image")
        or item.get("middle_image")
        or (_list(item.get("large_image_list")) or [{}])[0]
    )
    author_value = item.get("user_info")
    if not isinstance(author_value, Mapping):
        author_value = {
            "user_id": item.get("media_id"),
            "name": item.get("media_name") or item.get("source"),
        }
    return {
        "id": identifier,
        "video_id": video_id,
        "title": title,
        "abstract": str(item.get("abstract") or ""),
        "url": f"{_BASE_URL}/video/{identifier}",
        "cover_url": _image_url(image),
        "duration_seconds": _number(item.get("video_duration") or item.get("duration")),
        "published_at": _timestamp_iso(item.get("publish_time") or item.get("behot_time")),
        "author": _normalized_author(author_value),
        "stats": {
            "views": _integer(
                video_detail.get("video_watch_count")
                or item.get("video_watch_count")
                or item.get("play_count")
                or item.get("impression_count")
            ),
            "likes": _integer(item.get("digg_count") or item.get("video_like_count")),
            "comments": _integer(item.get("comment_count")),
            "shares": _integer(item.get("share_count") or item.get("repin_count")),
        },
        "behot_time": str(item.get("behot_time") or ""),
        "cursor": str(item.get("cursor") or ""),
    }


class XiguaClient:
    """面向西瓜视频移动端公开页面的纯 HTTP 匿名客户端。"""

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
            raise XiguaInputError("timeout must be a positive finite number")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise XiguaInputError("retries must be a non-negative integer")
        if not isinstance(user_agent, str) or not user_agent.strip() or "\n" in user_agent or "\r" in user_agent:
            raise XiguaInputError("user_agent must be a non-empty single-line string")
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
    def resolve_video_id(value: str | int) -> str:
        return XiguaClient._resolve_reference(value, "video", _VIDEO_ID_RE, _VIDEO_PATH_RE)

    @staticmethod
    def resolve_user_id(value: str | int) -> str:
        return XiguaClient._resolve_reference(value, "user", _USER_ID_RE, _USER_PATH_RE)

    @staticmethod
    def _resolve_reference(
        value: str | int,
        label: str,
        identifier_re: re.Pattern[str],
        path_re: re.Pattern[str],
    ) -> str:
        if isinstance(value, bool):
            raise XiguaInputError(f"invalid {label} reference")
        source = str(value).strip()
        if identifier_re.fullmatch(source):
            return source
        if not source:
            raise XiguaInputError(f"missing {label} reference")
        if not source.lower().startswith(("http://", "https://")):
            if source.lower().startswith(("www.ixigua.com/", "m.ixigua.com/", "ixigua.com/")):
                source = f"https://{source}"
            else:
                raise XiguaInputError(f"expected a public Xigua {label} URL or numeric id")
        parsed = urlsplit(source)
        try:
            port = parsed.port
        except ValueError as exc:
            raise XiguaInputError(f"invalid Xigua {label} URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or (parsed.hostname or "").lower() not in _VIDEO_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 80, 443}
            or parsed.fragment
        ):
            raise XiguaInputError(f"invalid Xigua {label} URL")
        match = path_re.fullmatch(parsed.path)
        if not match:
            raise XiguaInputError(f"unsupported Xigua {label} URL path")
        return match.group(1)

    @staticmethod
    def parse_video_data_payload(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        root = _mapping(payload)
        data = _mapping(root.get("data"))
        succeeded = root.get("success") is True or root.get("code") == 0
        if not succeeded or not data:
            message = str(root.get("message") or "").strip()
            suffix = f": {message}" if message else ""
            raise XiguaResponseError(f"video info response did not contain public data{suffix}")
        identifier = str(data.get("gid") or "")
        if not _VIDEO_ID_RE.fullmatch(identifier):
            raise XiguaResponseError("video info response has an invalid gid")
        if expected_id is not None and identifier != expected_id:
            raise XiguaResponseError(f"video response id {identifier} does not match expected {expected_id}")
        return dict(data)

    @staticmethod
    def parse_video_payload(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        data = XiguaClient.parse_video_data_payload(payload, expected_id=expected_id)
        identifier = str(data["gid"])
        return {
            "id": identifier,
            "video_id": str(data.get("video_id") or ""),
            "title": str(data.get("title") or ""),
            "abstract": str(data.get("abstract") or ""),
            "url": f"{_BASE_URL}/video/{identifier}",
            "cover_url": _absolute_url(data.get("cover_image_url")),
            "duration_seconds": _number(data.get("duration")),
            "published_at": _timestamp_iso(data.get("publish_time")),
            "author": _normalized_author(data.get("media_user")),
            "stats": {
                "views": _integer(data.get("play_count")),
                "likes": _integer(data.get("digg_count")),
                "comments": _integer(data.get("comment_count")),
            },
            "group_source": _integer(data.get("group_source")),
            "flags": {
                "robot_blocked": bool(data.get("is_ban_robot")),
                "hidden": str(data.get("hide_type") or "0") != "0",
                "item_status": _integer(data.get("item_status")),
            },
        }

    @staticmethod
    def extract_ssr_data(source: str) -> Mapping[str, Any]:
        if not isinstance(source, str) or not source:
            raise XiguaResponseError("empty video page")
        collector = _ScriptCollector()
        try:
            collector.feed(source.replace("\x00", ""))
            collector.close()
        except (TypeError, ValueError) as exc:
            raise XiguaResponseError("invalid video page HTML") from exc
        marker = "window._SSR_DATA"
        decoder = json.JSONDecoder()
        for script in collector.scripts:
            marker_at = script.find(marker)
            if marker_at < 0:
                continue
            equals_at = script.find("=", marker_at + len(marker))
            if equals_at < 0:
                continue
            try:
                value, _ = decoder.raw_decode(script[equals_at + 1 :].lstrip())
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(value, Mapping):
                return value
        raise XiguaResponseError("video page is missing window._SSR_DATA")

    @staticmethod
    def parse_play_page(source: str, *, expected_id: str | None = None) -> dict[str, Any]:
        ssr = XiguaClient.extract_ssr_data(source)
        result = _mapping(
            _mapping(
                _mapping(
                    _mapping(_mapping(ssr.get("data")).get("storeState")).get("detail")
                ).get("videoData")
            ).get("result")
        )
        if not result:
            raise XiguaResponseError("SSR response is missing detail.videoData.result")
        identifier = str(result.get("gid") or "")
        if not _VIDEO_ID_RE.fullmatch(identifier):
            raise XiguaResponseError("SSR response has an invalid gid")
        if expected_id is not None and identifier != expected_id:
            raise XiguaResponseError(f"SSR video id {identifier} does not match expected {expected_id}")
        return XiguaClient._playback_result(result, expected_id=expected_id)

    @staticmethod
    def parse_play_data_payload(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        data = XiguaClient.parse_video_data_payload(payload, expected_id=expected_id)
        return XiguaClient._playback_result(data, expected_id=expected_id)

    @staticmethod
    def _playback_result(data: Mapping[str, Any], *, expected_id: str | None) -> dict[str, Any]:
        identifier = str(data.get("gid") or "")
        if expected_id is not None and identifier != expected_id:
            raise XiguaResponseError(f"playback video id {identifier} does not match expected {expected_id}")
        play_url = decrypt_play_url(str(data.get("url") or ""))
        return {
            "id": identifier,
            "video_id": str(data.get("video_id") or ""),
            "url": play_url,
            "definitions": [str(item) for item in _list(data.get("definition")) if str(item)],
            "duration_seconds": _number(data.get("duration")),
            "cover_url": _absolute_url(data.get("cover_image_url")),
        }

    @staticmethod
    def parse_comments_payload(payload: Any, *, video_id: str) -> dict[str, Any]:
        root = _mapping(payload)
        if str(root.get("message") or "").lower() != "success" or _integer(root.get("err_no")) != 0:
            raise XiguaResponseError(
                f"comments API error {_integer(root.get('err_no'))}: {root.get('message') or 'unknown error'}"
            )
        comments: list[dict[str, Any]] = []
        for cell in _list(root.get("data")):
            comment = _mapping(_mapping(cell).get("comment"))
            identifier = str(comment.get("id_str") or comment.get("id") or "")
            if not identifier:
                continue
            replies: list[dict[str, Any]] = []
            for raw_reply in _list(comment.get("new_reply_list") or comment.get("reply_list")):
                reply = _mapping(raw_reply)
                replies.append(
                    {
                        "id": str(reply.get("id_str") or reply.get("id") or ""),
                        "text": str(reply.get("text") or ""),
                        "created_at": _timestamp_iso(reply.get("create_time")),
                        "likes": _integer(reply.get("digg_count")),
                        "user": {
                            "id": str(reply.get("user_id") or ""),
                            "name": str(reply.get("user_name") or ""),
                            "avatar_url": _absolute_url(reply.get("user_profile_image_url")),
                        },
                    }
                )
            comments.append(
                {
                    "id": identifier,
                    "text": str(comment.get("text") or ""),
                    "created_at": _timestamp_iso(comment.get("create_time")),
                    "location": str(comment.get("publish_loc_info") or ""),
                    "likes": _integer(comment.get("digg_count")),
                    "reply_count": _integer(comment.get("reply_count")),
                    "user": {
                        "id": str(comment.get("user_id") or ""),
                        "name": str(comment.get("user_name") or ""),
                        "avatar_url": _absolute_url(comment.get("user_profile_image_url")),
                        "verified": bool(comment.get("user_verified")),
                    },
                    "replies": replies,
                }
            )
        return {
            "video_id": video_id,
            "comments": comments,
            "count": len(comments),
            "total": _integer(root.get("total_number")),
            "offset": _integer(root.get("offset")),
            "has_more": bool(root.get("has_more")),
        }

    @staticmethod
    def parse_user_payload(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        root = _mapping(payload)
        status = str(root.get("status") or root.get("message") or "").lower()
        user = _mapping(
            _mapping(_mapping(root.get("data")).get("user_home_info")).get("user_info")
        )
        if status != "success" or not user:
            raise XiguaResponseError(f"user API error: {root.get('message') or root.get('status') or 'missing data'}")
        identifier = str(user.get("user_id") or "")
        if not _USER_ID_RE.fullmatch(identifier):
            raise XiguaResponseError("user response has an invalid user id")
        if expected_id is not None and identifier != expected_id:
            raise XiguaResponseError(f"user response id {identifier} does not match expected {expected_id}")
        author_info = _mapping(user.get("author_info"))
        diggs = _mapping(user.get("user_digg_count"))
        background = _mapping(user.get("bg_image"))
        return {
            "id": identifier,
            "name": str(user.get("name") or ""),
            "description": str(user.get("description") or user.get("author_desc") or ""),
            "avatar_url": _absolute_url(user.get("large_avatar_url") or user.get("avatar_url")),
            "background_url": _absolute_url(background.get("web_url") or background.get("url")),
            "url": _absolute_url(user.get("share_url")) or f"{_BASE_URL}/user/{identifier}",
            "location": str(_mapping(user.get("ip_info")).get("address") or ""),
            "verified": bool(user.get("auth_verified_info") or user.get("user_auth_info")),
            "verification": str(user.get("auth_verified_info") or user.get("user_auth_info") or ""),
            "stats": {
                "followers": _integer(user.get("followers_count")),
                "following": _integer(user.get("following_count")),
                "videos": _integer(author_info.get("video_total_count")),
                "video_plays": _integer(author_info.get("video_total_play_count")),
                "article_likes": _integer(diggs.get("article_digg_count")),
                "comment_likes": _integer(diggs.get("comment_digg_count")),
            },
            "media_id": str(user.get("media_id") or ""),
        }

    @staticmethod
    def parse_posts_payload(
        payload: Any,
        *,
        user_id: str,
        offset: int = 0,
    ) -> dict[str, Any]:
        root = _mapping(payload)
        if _integer(root.get("code")) != 0 or str(root.get("message") or "").lower() != "success":
            raise XiguaResponseError(
                f"user posts API error {_integer(root.get('code'))}: {root.get('message') or 'unknown error'}"
            )
        raw_items = _list(root.get("data"))
        items = [
            item
            for item in (_normalized_video_item(value) for value in raw_items)
            if item
        ]
        max_behot_time = str(items[-1].get("behot_time") or "") if items else ""
        return {
            "user_id": user_id,
            "items": items,
            "count": len(items),
            "offset": offset,
            "next_offset": offset + len(raw_items),
            "max_behot_time": max_behot_time,
            "has_more": bool(root.get("has_more")),
            "has_more_to_refresh": bool(root.get("has_more_to_refresh")),
        }

    @staticmethod
    def parse_search_payload(
        payload: Any,
        *,
        query: str,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        root = _mapping(payload)
        if str(root.get("message") or "").lower() != "success":
            raise XiguaResponseError(f"search API error: {root.get('message') or 'unknown error'}")
        items: list[dict[str, Any]] = []
        for value in _list(root.get("data")):
            item = _normalized_video_item(value)
            if item is not None:
                items.append(item)
            if len(items) >= limit:
                break
        response_offset = root.get("offset")
        if response_offset in {None, ""}:
            response_offset = offset
        next_offset = offset + len(_list(root.get("data")))
        return {
            "query": query,
            "items": items,
            "count": len(items),
            "offset": _integer(response_offset),
            "next_offset": next_offset,
            "has_more": bool(root.get("has_more")),
        }

    @staticmethod
    def parse_hot_payload(payload: Any, *, limit: int = 20) -> dict[str, Any]:
        root = _mapping(payload)
        data = _mapping(root.get("data"))
        if str(root.get("message") or "").lower() != "success" or not data:
            raise XiguaResponseError(f"hot recommendations API error: {root.get('message') or 'missing data'}")
        words = [
            {"id": str(_mapping(value).get("id_str") or ""), "text": str(_mapping(value).get("text") or "")}
            for value in _list(data.get("hot_search_words"))[:limit]
            if str(_mapping(value).get("text") or "")
        ]
        long_videos: list[dict[str, Any]] = []
        for value in _list(data.get("hot_lvideos"))[:limit]:
            item = _mapping(value)
            covers = _list(item.get("CoverInfoList"))
            long_videos.append(
                {
                    "id": str(item.get("AlbumId") or item.get("ArticleGroupId") or ""),
                    "title": str(item.get("Title") or item.get("Name") or ""),
                    "subtitle": str(item.get("SubTitle") or ""),
                    "description": str(item.get("Intro") or ""),
                    "cover_url": _image_url(covers[0]) if covers else "",
                    "duration_seconds": _number(item.get("Duration")),
                    "year": _integer(item.get("Year")),
                    "rating": _number(item.get("RatingScore")),
                    "stats": {
                        "views": _integer(item.get("PlayCount")),
                        "likes": _integer(item.get("DiggCount")),
                    },
                }
            )
        recommendations = [
            item
            for item in (_normalized_video_item(value) for value in _list(data.get("recommend_videos")))
            if item
        ][:limit]
        return {
            "hot_search_words": words,
            "hot_long_videos": long_videos,
            "recommendations": recommendations,
        }

    def get_video_data(self, value: str | int) -> dict[str, Any]:
        identifier = self.resolve_video_id(value)
        payload = self._get_json(_VIDEO_DATA_URL, params={"gid": identifier})
        return self.parse_video_data_payload(payload, expected_id=identifier)

    def get_video_info(self, value: str | int) -> dict[str, Any]:
        identifier = self.resolve_video_id(value)
        payload = self._get_json(f"{_BASE_URL}/i{identifier}/info/video/", params={"aid": APP_ID})
        return self.parse_video_payload(payload, expected_id=identifier)

    def get_video_info_v2(self, value: str | int) -> dict[str, Any]:
        identifier = self.resolve_video_id(value)
        payload = self._get_json(_VIDEO_DATA_URL, params={"gid": identifier})
        return self.parse_video_payload(payload, expected_id=identifier)

    def get_video_play_url(self, value: str | int) -> dict[str, Any]:
        identifier = self.resolve_video_id(value)
        payload = self._get_json(_VIDEO_DATA_URL, params={"gid": identifier})
        return self.parse_play_data_payload(payload, expected_id=identifier)

    def get_video_play_url_from_page(self, value: str | int) -> dict[str, Any]:
        identifier = self.resolve_video_id(value)
        response = self._request(
            f"{_BASE_URL}/video/{identifier}",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        return self.parse_play_page(response.text, expected_id=identifier)

    def get_comments(self, value: str | int, *, offset: int = 0, count: int = 20) -> dict[str, Any]:
        identifier = self.resolve_video_id(value)
        self._page_window(offset=offset, count=count, maximum=100)
        payload = self._get_json(
            _COMMENTS_URL,
            params={
                "aid": APP_ID,
                "group_id": identifier,
                "tab_index": 0,
                "count": count,
                "offset": offset,
            },
        )
        return self.parse_comments_payload(payload, video_id=identifier)

    def get_user(self, value: str | int) -> dict[str, Any]:
        identifier = self.resolve_user_id(value)
        payload = self._get_json(
            _USER_URL,
            params={"aid": APP_ID, "to_user_id": identifier, "app_id": 32},
        )
        return self.parse_user_payload(payload, expected_id=identifier)

    def get_user_posts(
        self,
        value: str | int,
        *,
        offset: int = 0,
        max_behot_time: str | int | None = None,
        count: int = 20,
    ) -> dict[str, Any]:
        identifier = self.resolve_user_id(value)
        self._page_window(offset=offset, count=count, maximum=100)
        cursor = self._optional_cursor(max_behot_time)
        params: dict[str, Any] = {
            "aid": APP_ID,
            "to_user_id": identifier,
            "app_id": 32,
            "orderby": "publishtime",
            "tab": 1,
            "count": count,
            "offset": offset,
        }
        if cursor:
            params["max_behot_time"] = cursor
        payload = self._get_json(_POSTS_URL, params=params)
        return self.parse_posts_payload(payload, user_id=identifier, offset=offset)

    def search(
        self,
        keyword: str,
        *,
        offset: int = 0,
        order_type: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        query = self._keyword(keyword)
        self._page_window(offset=offset, count=limit, maximum=100)
        if order_type is not None and order_type not in _SEARCH_ORDER:
            raise XiguaInputError("order_type must be publish_time or play_count")
        minimum = self._duration(min_duration, "min_duration")
        maximum = self._duration(max_duration, "max_duration")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise XiguaInputError("min_duration must not exceed max_duration")
        params: dict[str, Any] = {
            "aid": APP_ID,
            "keyword": query,
            "device_id": "",
            "offset": offset,
        }
        if order_type:
            params["order_type"] = order_type
        if minimum is not None:
            params["min_duration"] = minimum
        if maximum is not None:
            params["max_duration"] = maximum
        payload = self._get_json(_SEARCH_URL, params=params)
        return self.parse_search_payload(payload, query=query, offset=offset, limit=limit)

    def get_hot_recommendations(self, *, limit: int = 20) -> dict[str, Any]:
        self._page_window(offset=0, count=limit, maximum=100)
        payload = self._get_json(_HOT_URL, params={"aid": APP_ID, "device_id": ""})
        return self.parse_hot_payload(payload, limit=limit)

    @staticmethod
    def _page_window(*, offset: int, count: int, maximum: int) -> None:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise XiguaInputError("offset must be a non-negative integer")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= maximum:
            raise XiguaInputError(f"count/limit must be between 1 and {maximum}")

    @staticmethod
    def _optional_cursor(value: str | int | None) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, bool):
            raise XiguaInputError("max_behot_time must be a decimal cursor")
        cursor = str(value).strip()
        if not re.fullmatch(r"[0-9]{1,20}", cursor):
            raise XiguaInputError("max_behot_time must be a decimal cursor")
        return cursor

    @staticmethod
    def _keyword(value: str) -> str:
        if not isinstance(value, str):
            raise XiguaInputError("keyword must be text")
        keyword = value.strip()
        if not keyword or len(keyword) > 120 or "\x00" in keyword:
            raise XiguaInputError("keyword must contain 1 to 120 characters")
        return keyword

    @staticmethod
    def _duration(value: int | None, label: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 86_400:
            raise XiguaInputError(f"{label} must be an integer from 0 to 86400")
        return value

    def _get_json(self, url: str, *, params: Mapping[str, Any]) -> Any:
        response = self._request(url, params=dict(params))
        try:
            return response.json()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise XiguaResponseError(f"invalid JSON from {urlsplit(url).path}") from exc

    def _request(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, **kwargs)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise XiguaResponseError(f"request failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise XiguaResponseError(f"HTTP {response.status_code} from {urlsplit(url).path}")
            return response
        raise XiguaResponseError(f"request failed: {last_error or 'unknown error'}")
