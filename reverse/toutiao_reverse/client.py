from __future__ import annotations

import base64
import html
import json
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from curl_cffi import requests

from .errors import ToutiaoInputError, ToutiaoResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
CRAWLER_USER_AGENT = "Googlebot/2.1 (+http://www.google.com/bot.html)"

_MOBILE_BASE = "https://m.toutiao.com"
_WEB_BASE = "https://www.toutiao.com"
_SEARCH_URL = "https://so.toutiao.com/search"
_HOT_URL = f"{_WEB_BASE}/hot-event/hot-board/"
_COMMENTS_URL = f"{_WEB_BASE}/article/v2/tab_comments/"
_VOD_URL = "https://vod.bytedanceapi.com/"
_USER_INFO_URL = "https://ib.snssdk.com/user/profile/homepage/v6/"
_APP_USER_AGENT = "com.ss.android.article.news/999900 (Linux; U; Android 13; zh_CN)"
_CONTENT_HOSTS = {"toutiao.com", "www.toutiao.com", "m.toutiao.com"}
_ID_RE = re.compile(r"^[1-9][0-9]{9,21}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._=-]{16,300}$")
_URL_IN_TEXT_RE = re.compile(
    r"(?<![A-Za-z0-9.-])(?:https?://)?(?:www\.|m\.)?toutiao\.com"
    r"(?![A-Za-z0-9.-])(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)
_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>\uff0c\u3002\uff1b\uff1a\uff01\uff1f\uff09\u3011\u300b\u3001"
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


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


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _integer(value)
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _absolute_url(value: Any, base: str = _WEB_BASE) -> str:
    source = html.unescape(str(value or "").strip())
    if not source:
        return ""
    if source.startswith("//"):
        return f"https:{source}"
    if source.startswith("/"):
        return urljoin(base, source)
    return source


def _clean_markup(value: Any) -> str:
    source = str(value or "")
    if not source:
        return ""
    parser = _ArticleHTMLParser()
    parser.feed(source.replace("\x00", ""))
    parser.close()
    return parser.text


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _walk_mappings(child)


def _reference_url(source: str) -> str:
    for match in _HTTP_URL_RE.finditer(source):
        candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        if "toutiao.com" in candidate.lower():
            return candidate
    match = _URL_IN_TEXT_RE.search(source)
    if not match:
        raise ToutiaoInputError("expected a Toutiao URL")
    candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
    return candidate if candidate.lower().startswith(("https://", "http://")) else f"https://{candidate}"


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[dict[str, Any]] = []
        self.video_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        lower = tag.lower()
        if lower in {"p", "div", "br", "li", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")
        if lower == "img" and values.get("src"):
            self.images.append(
                {
                    "url": _absolute_url(values.get("src")),
                    "width": _integer(values.get("img_width") or values.get("width")),
                    "height": _integer(values.get("img_height") or values.get("height")),
                    "alt": values.get("alt", ""),
                }
            )
        video_id = values.get("tt-videoid") or values.get("data-video-id")
        if video_id and video_id not in self.video_ids:
            self.video_ids.append(video_id)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @property
    def text(self) -> str:
        lines = [
            re.sub(r"[ \t\r\f\v]+", " ", line).strip()
            for line in "".join(self.parts).split("\n")
        ]
        return "\n".join(line for line in lines if line and line != "\u89c6\u9891\u52a0\u8f7d\u4e2d...")


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[dict[str, str], str]] = []
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.links: list[str] = []
        self.images: list[str] = []
        self.text_parts: list[str] = []
        self._script_attrs: dict[str, str] | None = None
        self._script_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        lower = tag.lower()
        if lower == "script":
            self._script_attrs = values
            self._script_parts = []
        elif lower == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = values.get("content", "")
        elif lower == "title":
            self._in_title = True
        elif lower == "a" and values.get("href"):
            self.links.append(_absolute_url(values["href"]))
        elif lower == "img" and values.get("src"):
            self.images.append(_absolute_url(values["src"]))

    def handle_data(self, data: str) -> None:
        if self._script_attrs is not None:
            self._script_parts.append(data)
        else:
            self.text_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "script" and self._script_attrs is not None:
            self.scripts.append((self._script_attrs, "".join(self._script_parts)))
            self._script_attrs = None
            self._script_parts = []
        elif lower == "title":
            self._in_title = False


class _ProfileCollector(HTMLParser):
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.profile_depth: int | None = None
        self.feed_depth: int | None = None
        self.name_depth: int | None = None
        self.stat_depth: int | None = None
        self.name_parts: list[str] = []
        self.stat_parts: list[str] = []
        self.name = ""
        self.avatar_url = ""
        self.content_links: list[str] = []
        self.stats = {"likes": 0, "followers": 0, "following": 0}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower not in self._VOID_TAGS:
            self.depth += 1
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        classes = set(values.get("class", "").split())
        if self.feed_depth is None and "profile-tab-feed" in classes:
            self.feed_depth = self.depth
        if self.feed_depth is not None and lower == "a" and values.get("href"):
            self.content_links.append(_absolute_url(values["href"]))
        if self.profile_depth is None and (
            "profile-info-wrapper" in classes or values.get("aria-label") == "\u4f5c\u8005\u4fe1\u606f"
        ):
            self.profile_depth = self.depth
        if self.profile_depth is None:
            return
        if "name" in classes:
            self.name_depth = self.depth
            self.name_parts = []
        if "stat-item" in classes:
            self.stat_depth = self.depth
            self.stat_parts = []
        if lower == "img" and values.get("src") and not self.avatar_url:
            self.avatar_url = _absolute_url(values["src"])

    def handle_data(self, data: str) -> None:
        if self.name_depth is not None:
            self.name_parts.append(data)
        if self.stat_depth is not None:
            self.stat_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in self._VOID_TAGS:
            return
        if self.name_depth is not None and self.depth == self.name_depth:
            value = re.sub(r"\s+", " ", "".join(self.name_parts)).strip()
            if value:
                self.name = value
            self.name_depth = None
            self.name_parts = []
        if self.stat_depth is not None and self.depth == self.stat_depth:
            self._store_stat(" ".join(self.stat_parts))
            self.stat_depth = None
            self.stat_parts = []
        if self.profile_depth is not None and self.depth == self.profile_depth:
            self.profile_depth = None
        if self.feed_depth is not None and self.depth == self.feed_depth:
            self.feed_depth = None
        self.depth = max(0, self.depth - 1)

    def _store_stat(self, source: str) -> None:
        text = re.sub(r"\s+", " ", source).strip()
        match = re.search(r"([0-9][0-9.,]*\s*[\u4e07\u4ebf]?)\s*(\u83b7\u8d5e|\u7c89\u4e1d|\u5173\u6ce8)", text)
        if not match:
            return
        value = match.group(1).replace(",", "")
        multiplier = 100_000_000 if value.endswith("\u4ebf") else 10_000 if value.endswith("\u4e07") else 1
        number = int(float(value.rstrip("\u4e07\u4ebf")) * multiplier)
        key = {"\u83b7\u8d5e": "likes", "\u7c89\u4e1d": "followers", "\u5173\u6ce8": "following"}[match.group(2)]
        self.stats[key] = number


class ToutiaoClient:
    """仅通过 Python HTTP 和本地解析读取今日头条公开数据。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
    ) -> None:
        self.session = session or requests.Session(impersonate="chrome")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def resolve_content_id(reference: str | int) -> str:
        source = str(reference or "").strip()
        if _ID_RE.fullmatch(source):
            return source
        try:
            raw_url = _reference_url(source)
        except ToutiaoInputError as exc:
            raise ToutiaoInputError("expected a Toutiao content URL or numeric content ID") from exc
        try:
            parsed = urlsplit(raw_url)
            port = parsed.port
        except ValueError as exc:
            raise ToutiaoInputError("invalid Toutiao URL") from exc
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ToutiaoInputError("invalid Toutiao URL authority")
        if (parsed.hostname or "").lower() not in _CONTENT_HOSTS or port not in {None, 80, 443}:
            raise ToutiaoInputError("URL is not on an allowed Toutiao host")
        path = re.sub(r"/{2,}", "/", parsed.path)
        patterns = (
            r"/(?:article|video|group)/(\d{10,22})/?",
            r"/i(\d{10,22})(?:/info)?/?",
            r"/a(\d{10,22})/?",
        )
        for pattern in patterns:
            route = re.fullmatch(pattern, path)
            if route and _ID_RE.fullmatch(route.group(1)):
                return route.group(1)
        raise ToutiaoInputError("unsupported Toutiao content URL route")

    @staticmethod
    def parse_user_reference(reference: str) -> dict[str, str]:
        source = str(reference or "").strip()
        if _TOKEN_RE.fullmatch(source):
            token = source
        else:
            try:
                raw_url = _reference_url(source)
            except ToutiaoInputError as exc:
                raise ToutiaoInputError("expected a Toutiao public user URL or token") from exc
            try:
                parsed = urlsplit(raw_url)
                port = parsed.port
            except ValueError as exc:
                raise ToutiaoInputError("invalid Toutiao user URL") from exc
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username
                or parsed.password
                or (parsed.hostname or "").lower() not in _CONTENT_HOSTS
                or port not in {None, 80, 443}
            ):
                raise ToutiaoInputError("invalid Toutiao user URL authority")
            route = re.fullmatch(r"/c/user/token/([A-Za-z0-9._=-]{16,300})/?", parsed.path)
            if not route:
                raise ToutiaoInputError("unsupported Toutiao user URL route")
            token = route.group(1)
        return {"token": token, "url": f"{_WEB_BASE}/c/user/token/{token}/"}

    @staticmethod
    def parse_info_payload(payload: Mapping[str, Any], *, expected_id: str | None = None) -> dict[str, Any]:
        data = _mapping(payload.get("data"))
        if payload.get("success") is not True or not data:
            raise ToutiaoResponseError("Toutiao public info response did not contain content data")
        content_id = str(data.get("gid") or "")
        if not _ID_RE.fullmatch(content_id):
            raise ToutiaoResponseError("Toutiao public info response is missing a valid content ID")
        if expected_id and content_id != expected_id:
            raise ToutiaoResponseError(f"Toutiao returned content {content_id}, expected {expected_id}")

        body_html = str(data.get("content") or "")
        body_parser = _ArticleHTMLParser()
        body_parser.feed(body_html.replace("\x00", ""))
        body_parser.close()
        media_user = _mapping(data.get("media_user"))
        auth = _mapping(media_user.get("user_auth_info"))
        video_id = str(data.get("video_id") or (body_parser.video_ids[0] if body_parser.video_ids else ""))
        is_video = bool(video_id or data.get("play_auth_token_v2") or data.get("biz_tag") in {"\u4e2d\u89c6\u9891", "\u5c0f\u89c6\u9891"})
        published_timestamp = _integer(data.get("publish_time"))
        creator_uid = str(data.get("creator_uid") or "")
        author_id = str(creator_uid or media_user.get("id") or "")
        media_id = str(data.get("media_id") or media_user.get("id") or "")
        cover_url = _absolute_url(data.get("poster_url"))
        images = body_parser.images
        return {
            "id": content_id,
            "url": f"{_WEB_BASE}/{'video' if is_video else 'article'}/{content_id}/",
            "mobile_info_url": f"{_MOBILE_BASE}/i{content_id}/info/",
            "media_type": "video" if is_video else "article",
            "biz_tag": str(data.get("biz_tag") or ""),
            "title": str(data.get("title") or ""),
            "text": body_parser.text,
            "content_html": body_html,
            "source": str(data.get("detail_source") or data.get("source") or ""),
            "source_url": _absolute_url(data.get("url")),
            "author": {
                "id": author_id,
                "creator_uid": creator_uid,
                "media_id": media_id,
                "name": str(media_user.get("screen_name") or data.get("source") or ""),
                "avatar_url": _absolute_url(media_user.get("avatar_url")),
                "follower_count": _integer(media_user.get("follower_count") or data.get("follower_count")),
                "verified": bool(auth),
                "verification": str(auth.get("auth_info") or ""),
            },
            "images": images,
            "cover_url": cover_url,
            "video": {
                "id": video_id or None,
                "duration_seconds": _integer(data.get("video_duration")),
                "play_count": _integer(data.get("video_play_count")),
                "poster_url": cover_url,
                "streams": [],
            },
            "stats": {
                "views": _integer(data.get("impression_count")),
                "video_plays": _integer(data.get("video_play_count")),
                "likes": _integer(data.get("digg_count")),
                "comments": _integer(data.get("comment_count")),
                "reposts": _integer(data.get("repost_count")),
                "saves": _integer(data.get("repin_count")),
            },
            "published_timestamp": published_timestamp,
            "published_at": _timestamp_iso(published_timestamp),
            "flags": {
                "original": bool(data.get("is_original")),
                "pgc_article": bool(data.get("is_pgc_article")),
                "rumor": bool(data.get("is_rumor")),
                "hot": bool(data.get("is_toutiao_hot")),
                "top_pick": bool(data.get("is_toutiao_top_pick")),
            },
            "_play_auth_token_v2": str(data.get("play_auth_token_v2") or ""),
        }

    @staticmethod
    def decode_play_auth_token(token: str, *, expected_video_id: str | None = None) -> str:
        source = str(token or "").strip()
        if not source:
            raise ToutiaoResponseError("video response is missing play_auth_token_v2")
        try:
            padding = "=" * (-len(source) % 4)
            decoded = base64.b64decode(source + padding, validate=True)
            payload = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToutiaoResponseError("invalid Toutiao VOD play token") from exc
        query = str(_mapping(payload).get("GetPlayInfoToken") or "")
        params = parse_qs(query, keep_blank_values=True)
        if params.get("Action") != ["GetPlayInfo"] or params.get("Version") != ["2019-03-15"]:
            raise ToutiaoResponseError("unexpected Toutiao VOD token action")
        video_id = (params.get("video_id") or [""])[0]
        if expected_video_id and video_id != expected_video_id:
            raise ToutiaoResponseError("Toutiao VOD token video ID does not match the content")
        if not video_id:
            raise ToutiaoResponseError("Toutiao VOD token is missing video_id")
        return query

    @staticmethod
    def parse_vod_payload(payload: Mapping[str, Any], *, expected_video_id: str | None = None) -> dict[str, Any]:
        metadata = _mapping(payload.get("ResponseMetadata"))
        if _mapping(metadata.get("Error")):
            error = _mapping(metadata.get("Error"))
            raise ToutiaoResponseError(str(error.get("Message") or error.get("Code") or "VOD request failed"))
        data = _mapping(_mapping(payload.get("Result")).get("Data"))
        video_id = str(data.get("VideoID") or "")
        if not data or not video_id:
            raise ToutiaoResponseError("Toutiao VOD response did not contain play data")
        if expected_video_id and video_id != expected_video_id:
            raise ToutiaoResponseError(f"Toutiao VOD returned {video_id}, expected {expected_video_id}")
        streams: list[dict[str, Any]] = []
        for value in _list(data.get("PlayInfoList")):
            item = _mapping(value)
            url = _absolute_url(item.get("MainPlayUrl"))
            if not url:
                continue
            streams.append(
                {
                    "definition": str(item.get("Definition") or ""),
                    "quality": str(item.get("Quality") or ""),
                    "format": str(item.get("Format") or ""),
                    "codec": str(item.get("Codec") or ""),
                    "width": _integer(item.get("Width")),
                    "height": _integer(item.get("Height")),
                    "size": _integer(item.get("Size")),
                    "duration_seconds": _integer(item.get("Duration")),
                    "bitrate": _integer(item.get("Bitrate")),
                    "url": url,
                    "backup_url": _absolute_url(item.get("BackupPlayUrl")) or None,
                    "expires_timestamp": _integer(item.get("UrlExpire")),
                }
            )
        streams.sort(key=lambda item: (item["height"], item["bitrate"]))
        if not streams:
            raise ToutiaoResponseError("Toutiao VOD response did not contain public streams")
        return {
            "id": video_id,
            "duration_seconds": _integer(data.get("Duration")),
            "cover_url": _absolute_url(data.get("CoverUrl")),
            "media_type": str(data.get("MediaType") or "video"),
            "adaptive": bool(data.get("EnableAdaptive")),
            "streams": streams,
        }

    @staticmethod
    def parse_comments_payload(payload: Mapping[str, Any], *, content_id: str) -> dict[str, Any]:
        if payload.get("message") != "success" or _integer(payload.get("err_no")) != 0:
            raise ToutiaoResponseError(str(payload.get("message") or "Toutiao comments request failed"))
        comments: list[dict[str, Any]] = []
        for wrapper in _list(payload.get("data")):
            raw = _mapping(_mapping(wrapper).get("comment"))
            comment_id = str(raw.get("id_str") or raw.get("id") or "")
            if not comment_id:
                continue
            replies: list[dict[str, Any]] = []
            for reply_value in _list(raw.get("new_reply_list") or raw.get("reply_list")):
                reply = _mapping(reply_value)
                replies.append(
                    {
                        "id": str(reply.get("id_str") or reply.get("id") or ""),
                        "text": str(reply.get("text") or ""),
                        "user_id": str(reply.get("user_id") or ""),
                        "user_name": str(reply.get("user_name") or ""),
                        "likes": _integer(reply.get("digg_count")),
                        "created_timestamp": _integer(reply.get("create_time")),
                        "created_at": _timestamp_iso(reply.get("create_time")),
                    }
                )
            comments.append(
                {
                    "id": comment_id,
                    "text": str(raw.get("text") or ""),
                    "user": {
                        "id": str(raw.get("user_id") or ""),
                        "name": str(raw.get("user_name") or ""),
                        "avatar_url": _absolute_url(raw.get("user_profile_image_url")),
                        "verified": bool(raw.get("user_verified")),
                    },
                    "likes": _integer(raw.get("digg_count")),
                    "reply_count": _integer(raw.get("reply_count")),
                    "replies": replies,
                    "location": str(raw.get("publish_loc_info") or ""),
                    "created_timestamp": _integer(raw.get("create_time")),
                    "created_at": _timestamp_iso(raw.get("create_time")),
                }
            )
        return {
            "content_id": content_id,
            "comments": comments,
            "count": len(comments),
            "total": _integer(payload.get("total_number")),
            "offset": _integer(payload.get("offset")),
            "has_more": bool(payload.get("has_more")),
        }

    @staticmethod
    def parse_user_info_payload(payload: Mapping[str, Any], *, expected_user_id: str | None = None) -> dict[str, Any]:
        data = _mapping(payload.get("data"))
        if payload.get("message") != "success" or not data:
            raise ToutiaoResponseError(str(payload.get("message") or "Toutiao user info response is invalid"))
        user_id = str(data.get("user_id") or "")
        if not _ID_RE.fullmatch(user_id):
            raise ToutiaoResponseError("Toutiao user info response is missing a valid user ID")
        if expected_user_id and user_id != expected_user_id:
            raise ToutiaoResponseError(f"Toutiao returned user {user_id}, expected {expected_user_id}")
        raw_auth = data.get("user_auth_info")
        if isinstance(raw_auth, str):
            try:
                auth = _mapping(json.loads(raw_auth))
            except json.JSONDecodeError:
                auth = {}
        else:
            auth = _mapping(raw_auth)
        return {
            "id": user_id,
            "creator_id": str(data.get("creator_id") or ""),
            "media_id": str(data.get("media_id") or data.get("ugc_publish_media_id") or ""),
            "name": str(data.get("name") or data.get("screen_name") or ""),
            "screen_name": str(data.get("screen_name") or data.get("name") or ""),
            "description": str(data.get("description") or ""),
            "avatar_url": _absolute_url(data.get("big_avatar_url") or data.get("avatar_url")),
            "background_url": _absolute_url(data.get("bg_img_url")),
            "share_url": _absolute_url(data.get("share_url")),
            "area": str(data.get("area") or ""),
            "industry": str(data.get("industry") or ""),
            "gender": _integer(data.get("gender")),
            "verified": bool(data.get("user_verified") or auth),
            "verification": str(data.get("verified_content") or auth.get("auth_info") or ""),
            "stats": {
                "followers": _integer(data.get("followers_count")),
                "following": _integer(data.get("followings_count")),
                "platform_followers": _integer(data.get("mplatform_followers_count")),
                "likes_received": _integer(data.get("pgc_like_count")),
            },
            "tabs": {
                "top": [dict(item) for item in _list(data.get("top_tab")) if isinstance(item, Mapping)],
                "bottom": [dict(item) for item in _list(data.get("bottom_tab")) if isinstance(item, Mapping)],
            },
        }

    @staticmethod
    def extract_search_cards(source: str) -> list[dict[str, Any]]:
        collector = _ScriptCollector()
        collector.feed(str(source or "").replace("\x00", ""))
        collector.close()
        decoder = json.JSONDecoder()
        cards: list[dict[str, Any]] = []
        marker = "T.flow({ data:"
        for attrs, script in collector.scripts:
            if attrs.get("data-for") != "ala-data":
                continue
            start = script.find(marker)
            if start < 0:
                continue
            start += len(marker)
            while start < len(script) and script[start].isspace():
                start += 1
            try:
                value, _ = decoder.raw_decode(script, start)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                cards.append(dict(value))
        return cards

    @classmethod
    def parse_search_html(cls, source: str, *, query: str = "", limit: int | None = 20) -> dict[str, Any]:
        cards = cls.extract_search_cards(source)
        candidates: dict[str, tuple[int, dict[str, Any]]] = {}
        for card in cards:
            for raw in _walk_mappings(card):
                content_id = str(
                    raw.get("group_id")
                    or raw.get("group_id_str")
                    or raw.get("gid")
                    or raw.get("gidStr")
                    or raw.get("item_id_str")
                    or ""
                )
                if not _ID_RE.fullmatch(content_id):
                    continue
                title = _clean_markup(
                    raw.get("title")
                    or _mapping(raw.get("emphasis")).get("rich_content")
                    or raw.get("content")
                )
                raw_data = _mapping(raw.get("raw_data"))
                if not title:
                    title = _clean_markup(raw_data.get("title"))
                user = _mapping(_mapping(raw_data.get("user")).get("info"))
                media_user = _mapping(raw.get("media_user"))
                video = _mapping(raw_data.get("video") or raw.get("video"))
                group_source = _integer(raw_data.get("group_source") or raw.get("group_source"))
                is_video = bool(
                    video
                    or raw.get("video_id")
                    or raw.get("video_url")
                    or raw.get("has_video")
                    or group_source == 19
                )
                cover = _absolute_url(
                    raw.get("large_thumbnail_url")
                    or raw.get("thumbnail_url")
                    or _mapping(raw_data.get("stagger_feed_cover_image")).get("url")
                    or _mapping(video.get("origin_cover")).get("url")
                )
                item = {
                    "id": content_id,
                    "url": f"{_WEB_BASE}/{'video' if is_video else 'article'}/{content_id}/",
                    "media_type": "short_video" if group_source == 19 else ("video" if is_video else "article"),
                    "title": title,
                    "author": {
                        "id": str(user.get("user_id") or media_user.get("id") or raw.get("user_id") or raw.get("media_creator_id") or ""),
                        "name": str(user.get("name") or media_user.get("screen_name") or raw.get("media_name") or _mapping(raw.get("info")).get("user_nickname") or ""),
                        "avatar_url": _absolute_url(user.get("avatar_url") or media_user.get("avatar_url") or raw.get("media_avatar_url")),
                    },
                    "cover_url": cover,
                    "duration_seconds": _integer(video.get("duration") or raw.get("video_duration")),
                    "stats": {
                        "views": _integer(raw.get("impression_count") or raw.get("play_count")),
                        "likes": _integer(raw.get("digg_count") or _mapping(raw_data.get("action")).get("digg_count")),
                        "comments": _integer(raw.get("comment_count") or _mapping(raw_data.get("action")).get("comment_count")),
                    },
                    "published_timestamp": _integer(raw_data.get("publish_time") or raw.get("publish_time")),
                }
                score = sum(bool(value) for value in (title, cover, item["author"]["name"], video))
                if content_id not in candidates or score > candidates[content_id][0]:
                    candidates[content_id] = (score, item)
        items = [value[1] for value in candidates.values()]
        if limit is not None:
            items = items[: max(0, limit)]
        return {"query": query, "items": items, "count": len(items), "card_count": len(cards)}

    @staticmethod
    def parse_hot_board_payload(payload: Mapping[str, Any], *, limit: int | None = None) -> dict[str, Any]:
        if payload.get("status") != "success" or not isinstance(payload.get("data"), Sequence):
            raise ToutiaoResponseError("Toutiao hot board response is invalid")
        items: list[dict[str, Any]] = []
        for rank, value in enumerate(_list(payload.get("data")), start=1):
            raw = _mapping(value)
            content_id = str(raw.get("ClusterIdStr") or raw.get("ClusterId") or "")
            image = _mapping(raw.get("Image"))
            items.append(
                {
                    "rank": rank,
                    "id": content_id,
                    "title": str(raw.get("Title") or ""),
                    "query": str(raw.get("QueryWord") or ""),
                    "url": _absolute_url(raw.get("Url")),
                    "hot_value": _integer(raw.get("HotValue")),
                    "cluster_type": _integer(raw.get("ClusterType")),
                    "label": str(raw.get("LabelDesc") or raw.get("Label") or ""),
                    "categories": [str(item) for item in _list(raw.get("InterestCategory"))],
                    "image": {
                        "url": _absolute_url(image.get("url")),
                        "width": _integer(image.get("width")),
                        "height": _integer(image.get("height")),
                    },
                }
            )
        if limit is not None:
            items = items[: max(0, limit)]
        return {"items": items, "count": len(items), "impression_id": str(payload.get("impr_id") or "")}

    @classmethod
    def parse_profile_html(cls, source: str, *, token: str, page_url: str = "") -> dict[str, Any]:
        collector = _ScriptCollector()
        collector.feed(str(source or "").replace("\x00", ""))
        collector.close()
        profile_collector = _ProfileCollector()
        profile_collector.feed(str(source or "").replace("\x00", ""))
        profile_collector.close()
        title = "".join(collector.title_parts).strip() or collector.meta.get("og:title", "")
        name = profile_collector.name or re.sub(
            r"\s*\u7684(?:\u5934\u6761)?\u4e3b\u9875\s*-?\s*\u4eca\u65e5\u5934\u6761\s*$",
            "",
            title,
        ).strip()
        if not name:
            name = title.strip()
        content_ids: list[str] = []
        for link in profile_collector.content_links:
            try:
                content_id = cls.resolve_content_id(link)
            except ToutiaoInputError:
                continue
            if content_id not in content_ids:
                content_ids.append(content_id)
        stats = profile_collector.stats
        avatar = profile_collector.avatar_url or _absolute_url(collector.meta.get("og:image"))
        if not avatar:
            avatar = next((url for url in collector.images if "avatar" in url), collector.images[0] if collector.images else "")
        if not name and not avatar and not content_ids:
            raise ToutiaoResponseError("Toutiao public profile SSR did not contain author data")
        return {
            "id": "",
            "token": token,
            "url": page_url or f"{_WEB_BASE}/c/user/token/{token}/",
            "name": name,
            "avatar_url": avatar,
            "description": str(collector.meta.get("description") or collector.meta.get("og:description") or ""),
            "stats": stats,
            "content_ids": content_ids,
        }

    def get_article_info(self, reference: str | int) -> dict[str, Any]:
        content_id, payload = self._get_info_payload(reference)
        result = self.parse_info_payload(payload, expected_id=content_id)
        if result["media_type"] == "video":
            raise ToutiaoResponseError("content is a video; use get_video_info")
        result.pop("_play_auth_token_v2", None)
        return result

    def get_content_info(self, reference: str | int) -> dict[str, Any]:
        content_id, payload = self._get_info_payload(reference)
        result = self.parse_info_payload(payload, expected_id=content_id)
        result.pop("_play_auth_token_v2", None)
        return result

    def get_video_info(self, reference: str | int) -> dict[str, Any]:
        content_id, payload = self._get_info_payload(reference)
        result = self.parse_info_payload(payload, expected_id=content_id)
        if result["media_type"] != "video":
            raise ToutiaoResponseError("content is not a Toutiao video")
        token = result.pop("_play_auth_token_v2", "")
        video_id = str(result["video"].get("id") or "")
        query = self.decode_play_auth_token(token, expected_video_id=video_id)
        response = self._get(_VOD_URL, query=query, headers={"Referer": result["url"]})
        vod = self.parse_vod_payload(self._decode_json(response, "Toutiao VOD"), expected_video_id=video_id)
        result["video"].update(vod)
        if vod.get("cover_url"):
            result["cover_url"] = vod["cover_url"]
        return result

    def get_comments(self, reference: str | int, *, offset: int = 0, count: int = 20) -> dict[str, Any]:
        content_id = self.resolve_content_id(reference)
        if offset < 0:
            raise ToutiaoInputError("offset must be zero or greater")
        if count < 1 or count > 100:
            raise ToutiaoInputError("count must be between 1 and 100")
        response = self._get(
            _COMMENTS_URL,
            params={
                "aid": 24,
                "app_name": "toutiao_web",
                "offset": offset,
                "count": count,
                "group_id": content_id,
                "item_id": content_id,
            },
            headers={"Referer": f"{_WEB_BASE}/article/{content_id}/"},
        )
        return self.parse_comments_payload(self._decode_json(response, "Toutiao comments"), content_id=content_id)

    def search(self, keyword: str, *, limit: int | None = 20) -> dict[str, Any]:
        query = str(keyword or "").strip()
        if not query or len(query) > 120:
            raise ToutiaoInputError("keyword must contain between 1 and 120 characters")
        if limit is not None and (limit < 1 or limit > 100):
            raise ToutiaoInputError("limit must be between 1 and 100")
        response = self._get(
            _SEARCH_URL,
            params={"keyword": query, "source": "input"},
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        return self.parse_search_html(response.text, query=query, limit=limit)

    def get_hot_board(self, *, limit: int | None = None) -> dict[str, Any]:
        if limit is not None and (limit < 1 or limit > 100):
            raise ToutiaoInputError("limit must be between 1 and 100")
        response = self._get(_HOT_URL, params={"origin": "toutiao_pc"}, headers={"Referer": f"{_WEB_BASE}/"})
        return self.parse_hot_board_payload(self._decode_json(response, "Toutiao hot board"), limit=limit)

    def get_user_profile(self, reference: str, *, resolve_id: bool = True) -> dict[str, Any]:
        parsed = self.parse_user_reference(reference)
        response = self._get(
            parsed["url"],
            headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": CRAWLER_USER_AGENT},
        )
        profile = self.parse_profile_html(response.text, token=parsed["token"], page_url=str(response.url or parsed["url"]))
        if resolve_id and profile["content_ids"]:
            _, payload = self._get_info_payload(profile["content_ids"][0])
            content = self.parse_info_payload(payload, expected_id=profile["content_ids"][0])
            profile["id"] = content["author"]["id"]
            if not profile["name"]:
                profile["name"] = content["author"]["name"]
            if not profile["avatar_url"]:
                profile["avatar_url"] = content["author"]["avatar_url"]
            if not profile["stats"]["followers"]:
                profile["stats"]["followers"] = content["author"]["follower_count"]
        return profile

    def get_user_info(self, user_id: str | int) -> dict[str, Any]:
        identifier = str(user_id or "").strip()
        if not _ID_RE.fullmatch(identifier):
            raise ToutiaoInputError("expected a numeric Toutiao user ID")
        response = self._get(
            _USER_INFO_URL,
            params={
                "user_id": identifier,
                "aid": 13,
                "app_name": "news_article",
                "version_code": 999900,
            },
            headers={"User-Agent": _APP_USER_AGENT},
        )
        return self.parse_user_info_payload(
            self._decode_json(response, "Toutiao user info"),
            expected_user_id=identifier,
        )

    def get_user_id(self, reference: str) -> str:
        profile = self.get_user_profile(reference, resolve_id=True)
        user_id = str(profile.get("id") or "")
        if not user_id:
            raise ToutiaoResponseError("public profile has no content from which to resolve a numeric user ID")
        return user_id

    def _get_info_payload(self, reference: str | int) -> tuple[str, Mapping[str, Any]]:
        content_id = self.resolve_content_id(reference)
        response = self._get(
            f"{_MOBILE_BASE}/i{content_id}/info/",
            headers={"Referer": f"{_MOBILE_BASE}/i{content_id}/"},
        )
        return content_id, self._decode_json(response, "Toutiao public info")

    def _get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        query: str = "",
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response:
        request_url = f"{url}?{query}" if query else url
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    request_url,
                    params=dict(params or {}),
                    headers=dict(headers or {}),
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise ToutiaoResponseError(f"Toutiao HTTP request failed: {exc}") from exc
            else:
                if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                    last_error = ToutiaoResponseError(f"temporary Toutiao HTTP {response.status_code}")
                elif response.status_code < 200 or response.status_code >= 300:
                    raise ToutiaoResponseError(f"Toutiao returned HTTP {response.status_code} for {urlsplit(url).path}")
                else:
                    return response
            if attempt < self.retries:
                time.sleep(0.25 * (2**attempt))
        raise ToutiaoResponseError(f"Toutiao HTTP request failed: {last_error}")

    @staticmethod
    def _decode_json(response: requests.Response, context: str) -> Mapping[str, Any]:
        try:
            value = json.loads(response.text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ToutiaoResponseError(f"{context} returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise ToutiaoResponseError(f"{context} returned a non-object JSON value")
        return value
