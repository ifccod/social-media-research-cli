from __future__ import annotations

import html
import json
import math
import re
import secrets
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import DouyinError, DouyinInputError, DouyinResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

_MAIN_BASE = "https://www.douyin.com"
_SHARE_BASE = "https://www.iesdouyin.com"
_PROFILE_API = f"{_SHARE_BASE}/web/api/v2/user/info/"
_WEB_API_PATHS = {
    "user_posts": "/aweme/v1/web/aweme/post/",
    "comments": "/aweme/v1/web/comment/list/",
    "comment_replies": "/aweme/v1/web/comment/list/reply/",
    "search_videos": "/aweme/v1/web/search/item/",
    "hot": "/aweme/v1/web/hot/search/list/",
}
_BROWSER_WEB_PATHS = frozenset(
    {
        _WEB_API_PATHS["user_posts"],
        _WEB_API_PATHS["comments"],
        _WEB_API_PATHS["comment_replies"],
        _WEB_API_PATHS["search_videos"],
    }
)
_INDEX_KEYWORD_TREND_PATH = "/api/v2/index/get_multi_keyword_hot_trend"
_INDEX_KEYWORD_TREND_REFERER = (
    "https://creator.douyin.com/creator-micro/creator-count/arithmetic-index"
)
_INDEX_TREND_FIELDS = (
    "hot_list",
    "search_hot_list",
    "top_point_list",
    "search_top_point_list",
)
_MAX_COMMENT_STALE_PAGES = 3
_WEB_QUERY_DEFAULTS = (
    ("device_platform", "webapp"),
    ("aid", "6383"),
    ("channel", "channel_pc_web"),
    ("update_version_code", "170400"),
    ("pc_client_type", "1"),
    ("pc_libra_divert", "Windows"),
    ("support_h265", "1"),
    ("support_dash", "0"),
    ("version_code", "190600"),
    ("version_name", "19.6.0"),
    ("cookie_enabled", "true"),
    ("screen_width", "1920"),
    ("screen_height", "1080"),
    ("browser_language", "zh-CN"),
    ("browser_platform", "Win32"),
    ("browser_name", "Chrome"),
    ("browser_version", "146.0.0.0"),
    ("browser_online", "true"),
    ("engine_name", "Blink"),
    ("engine_version", "146.0.0.0"),
    ("os_name", "Windows"),
    ("os_version", "10"),
    ("cpu_core_num", "8"),
    ("device_memory", "8"),
    ("platform", "PC"),
    ("downlink", "10"),
    ("effective_type", "4g"),
    ("round_trip_time", "50"),
)
_OWNED_HOSTS = frozenset(
    {
        "douyin.com",
        "www.douyin.com",
        "m.douyin.com",
        "v.douyin.com",
        "iesdouyin.com",
        "www.iesdouyin.com",
    }
)
_AWEME_ID_RE = re.compile(r"^[1-9][0-9]{9,21}$")
_AWEME_ID_FIND_RE = re.compile(r"(?<![0-9])[1-9][0-9]{9,21}(?![0-9])")
_SEC_UID_RE = re.compile(r"^MS4wLjAB[A-Za-z0-9_-]{16,180}$")
_SEC_UID_FIND_RE = re.compile(r"MS4wLjAB[A-Za-z0-9_-]{16,180}")
_SHORT_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,80}$")
_URL_IN_TEXT_RE = re.compile(
    r"https?://[^\s<>\"'，。；：！？）】》」』]+", re.IGNORECASE
)
_AWEME_PATH_RE = re.compile(r"^/(video|note|slides)/([1-9][0-9]{9,21})/?$")
_SHARE_AWEME_PATH_RE = re.compile(
    r"^/share/(video|note|slides)/([1-9][0-9]{9,21})/?$"
)
_USER_PATH_RE = re.compile(r"^/user/(MS4wLjAB[A-Za-z0-9_-]{16,180})/?$")
_SHARE_USER_PATH_RE = re.compile(
    r"^/share/user(?:/(MS4wLjAB[A-Za-z0-9_-]{16,180}))?/?$"
)
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_ROUTER_DATA_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError, OverflowError):
        return None


def _utc_parts(value: Any) -> tuple[str | None, int | None]:
    timestamp = _optional_int(value)
    if timestamp is None or timestamp < 0:
        return None, timestamp
    try:
        result = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, timestamp
    return result.isoformat(), timestamp


def _unique_strings(values: Any) -> list[str]:
    source = _list(values) if not isinstance(values, str) else [values]
    output: list[str] = []
    seen: set[str] = set()
    for value in source:
        item = html.unescape(_text(value))
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _resource(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    if isinstance(value, str):
        urls = [html.unescape(value)]
        return {"uri": None, "url": urls[0], "urls": urls, "width": None, "height": None}
    urls = _unique_strings(raw.get("url_list"))
    if not urls:
        for key in ("url", "src", "download_url"):
            candidate = html.unescape(_text(raw.get(key)))
            if candidate:
                urls.append(candidate)
                break
    return {
        "uri": _text(raw.get("uri")) or None,
        "url": urls[0] if urls else None,
        "urls": urls,
        "width": _optional_int(raw.get("width")),
        "height": _optional_int(raw.get("height")),
    }


def _decode_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return value


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.poster = ""
        self.title = ""
        self._title = False
        self._title_buffer: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lower = tag.lower()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if lower == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = values.get("content", "")
        elif lower == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "") or self.canonical
        elif lower == "img" and "poster" in values.get("class", "").lower().split():
            self.poster = values.get("src", "") or self.poster
        elif lower == "title":
            self._title = True
            self._title_buffer = []

    def handle_data(self, data: str) -> None:
        if self._title:
            self._title_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title" and self._title:
            self.title = "".join(self._title_buffer).strip()
            self._title = False
            self._title_buffer = []


class DouyinClient:
    """读取 Douyin 匿名移动分享页和公开用户元数据。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        web_user_agent: str = WEB_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
        max_redirects: int = 4,
        proxy: str | None = None,
        web_signer: Callable[..., Any] | None = None,
        web_fetch: (
            Callable[
                [str, Sequence[tuple[str, str]], str],
                Mapping[str, Any],
            ]
            | None
        ) = None,
        index_fetch: (
            Callable[
                [str, Sequence[tuple[str, str]], str],
                Mapping[str, Any],
            ]
            | None
        ) = None,
        web_id: str | None = None,
    ) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise DouyinInputError("timeout must be a positive finite number")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise DouyinInputError("retries must be a non-negative integer")
        if (
            isinstance(max_redirects, bool)
            or not isinstance(max_redirects, int)
            or max_redirects < 1
        ):
            raise DouyinInputError("max_redirects must be a positive integer")
        for field, value in (
            ("user_agent", user_agent),
            ("web_user_agent", web_user_agent),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or "\r" in value
                or "\n" in value
            ):
                raise DouyinInputError(f"{field} must be a non-empty single-line string")
        self.session = session or requests.Session(impersonate="safari_ios")
        self.timeout = float(timeout)
        self.retries = retries
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self.web_user_agent = web_user_agent
        self.proxy = str(proxy).strip() if proxy else None
        self.web_signer = web_signer
        self.web_fetch = web_fetch
        self.index_fetch = index_fetch
        if web_id is not None and not _AWEME_ID_RE.fullmatch(str(web_id).strip()):
            raise DouyinInputError("web_id must be 10 to 22 decimal digits")
        self.web_id = str(web_id).strip() if web_id else ""
        self._web_identity_ready = bool(self.web_id)
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    @classmethod
    def parse_aweme_reference(cls, value: str | int) -> dict[str, Any]:
        source = cls._reference(value, "aweme")
        if source.isdecimal():
            return cls._aweme_reference(cls._aweme_id(source), "video")

        url = cls._douyin_url(source)
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host == "v.douyin.com":
            code = path.strip("/")
            if not _SHORT_CODE_RE.fullmatch(code):
                raise DouyinInputError("Douyin short URL contains an invalid code")
            return {
                "kind": "aweme",
                "aweme_id": None,
                "content_type": None,
                "url": urlunsplit(("https", host, f"/{code}/", "", "")),
                "short_url": urlunsplit(("https", host, f"/{code}/", "", "")),
            }

        match = _AWEME_PATH_RE.fullmatch(path) or _SHARE_AWEME_PATH_RE.fullmatch(path)
        if match:
            return cls._aweme_reference(match.group(2), match.group(1))

        query = parse_qs(parsed.query, keep_blank_values=False)
        for key in ("modal_id", "aweme_id", "object_id"):
            candidate = (query.get(key) or [""])[0]
            if _AWEME_ID_RE.fullmatch(candidate):
                return cls._aweme_reference(candidate, "video")
        raise DouyinInputError("reference is not a Douyin public aweme URL or id")

    @classmethod
    def parse_user_reference(cls, value: str) -> dict[str, Any]:
        source = cls._reference(value, "user")
        if _SEC_UID_RE.fullmatch(source):
            return cls._user_reference(source)

        url = cls._douyin_url(source)
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host == "v.douyin.com":
            code = path.strip("/")
            if not _SHORT_CODE_RE.fullmatch(code):
                raise DouyinInputError("Douyin short URL contains an invalid code")
            short_url = urlunsplit(("https", host, f"/{code}/", "", ""))
            return {"kind": "user", "sec_uid": None, "url": short_url, "short_url": short_url}

        match = _USER_PATH_RE.fullmatch(path) or _SHARE_USER_PATH_RE.fullmatch(path)
        sec_uid = match.group(1) if match else None
        query = parse_qs(parsed.query, keep_blank_values=False)
        sec_uid = sec_uid or (query.get("sec_uid") or [None])[0]
        if not sec_uid or not _SEC_UID_RE.fullmatch(sec_uid):
            raise DouyinInputError("reference is not a Douyin public user URL or sec_uid")
        return cls._user_reference(sec_uid)

    def resolve_aweme_reference(self, value: str | int) -> dict[str, Any]:
        reference = self.parse_aweme_reference(value)
        if reference["aweme_id"]:
            return reference
        return self._resolve_short(reference["short_url"], self.parse_aweme_reference, "aweme_id")

    def resolve_user_reference(self, value: str) -> dict[str, Any]:
        reference = self.parse_user_reference(value)
        if reference["sec_uid"]:
            return reference
        return self._resolve_short(reference["short_url"], self.parse_user_reference, "sec_uid")

    def get_aweme(self, value: str | int) -> dict[str, Any]:
        reference = self.resolve_aweme_reference(value)
        response = self._request(
            reference["share_page_url"],
            headers={"Referer": f"{_SHARE_BASE}/"},
            allow_redirects=True,
        )
        self._validate_final_url(str(response.url or reference["share_page_url"]))
        result = self.parse_aweme_html(
            response.text,
            expected_aweme_id=reference["aweme_id"],
            page_url=str(response.url or reference["share_page_url"]),
        )
        result["requested_url"] = reference["share_page_url"]
        if reference.get("short_url"):
            result["short_url"] = reference["short_url"]
        return result

    def get_video(self, value: str | int) -> dict[str, Any]:
        return self.get_aweme(value)

    def get_user_profile(self, value: str) -> dict[str, Any]:
        reference = self.resolve_user_reference(value)
        response = self._request(
            _PROFILE_API,
            params={"sec_uid": reference["sec_uid"]},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": reference["share_page_url"],
            },
            allow_redirects=True,
        )
        self._validate_final_url(str(response.url or _PROFILE_API))
        result = self.parse_profile_payload(
            response.text, expected_sec_uid=reference["sec_uid"]
        )
        result["requested_url"] = str(response.url or _PROFILE_API)
        if reference.get("short_url"):
            result["short_url"] = reference["short_url"]
        return result

    def get_profile(self, value: str) -> dict[str, Any]:
        return self.get_user_profile(value)

    def get_author_profile(self, aweme_reference: str | int) -> dict[str, Any]:
        aweme = self.get_aweme(aweme_reference)
        sec_uid = _text(_mapping(aweme.get("author")).get("sec_uid"))
        if not sec_uid:
            raise DouyinResponseError("Douyin aweme has no public author sec_uid")
        profile = self.get_user_profile(sec_uid)
        profile["source_aweme_id"] = aweme["aweme_id"]
        return profile

    @classmethod
    def extract_aweme_ids(cls, value: str) -> dict[str, Any]:
        source = cls._input_text(value)
        ids = list(dict.fromkeys(_AWEME_ID_FIND_RE.findall(source)))
        return {"kind": "aweme_ids", "items": ids, "count": len(ids)}

    @classmethod
    def extract_sec_uids(cls, value: str) -> dict[str, Any]:
        source = cls._input_text(value)
        ids = list(dict.fromkeys(_SEC_UID_FIND_RE.findall(source)))
        return {"kind": "sec_uids", "items": ids, "count": len(ids)}

    def get_aweme_statistics(self, value: str | int) -> dict[str, Any]:
        aweme = self.get_aweme(value)
        return self._statistics_result(aweme)

    def get_awemes(self, values: Sequence[str | int]) -> dict[str, Any]:
        return self._batch(values, self.get_aweme, kind="batch_awemes")

    def get_profiles(self, values: Sequence[str]) -> dict[str, Any]:
        return self._batch(values, self.get_profile, kind="batch_profiles")

    def get_aweme_statistics_batch(
        self, values: Sequence[str | int]
    ) -> dict[str, Any]:
        return self._batch(
            values, self.get_aweme_statistics, kind="batch_aweme_statistics"
        )

    @staticmethod
    def _statistics_result(aweme: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "kind": "aweme_statistics",
            "aweme_id": _text(aweme.get("aweme_id")),
            "url": aweme.get("url"),
            "statistics": dict(_mapping(aweme.get("statistics"))),
        }

    @staticmethod
    def _batch(
        values: Sequence[Any],
        operation: Callable[[Any], dict[str, Any]],
        *,
        kind: str,
    ) -> dict[str, Any]:
        if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
            raise DouyinInputError("batch input must be a sequence")
        inputs = list(values)
        if not inputs:
            raise DouyinInputError("batch input must not be empty")
        if len(inputs) > 20:
            raise DouyinInputError("batch input must not exceed 20 items")
        results: list[dict[str, Any]] = []
        success_count = 0
        for value in inputs:
            try:
                data = operation(value)
            except (DouyinInputError, DouyinResponseError) as exc:
                results.append(
                    {"input": str(value), "ok": False, "data": None, "error": str(exc)}
                )
                continue
            success_count += 1
            results.append(
                {"input": str(value), "ok": True, "data": data, "error": None}
            )
        return {
            "kind": kind,
            "items": results,
            "count": len(results),
            "success_count": success_count,
            "error_count": len(results) - success_count,
        }

    def initialize_web_session(self, *, force: bool = False) -> None:
        """预热第一方 Cookie 并创建公开 Web 访客 id。"""
        if self._web_identity_ready and not force:
            return
        self._web_identity_ready = False
        self._request(
            f"{_MAIN_BASE}/",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{_MAIN_BASE}/",
            },
            allow_redirects=True,
            impersonate="chrome146",
            user_agent=self.web_user_agent,
        )
        # Web ID 是无符号十进制访客标识。Cookie 由第一方页面提供，
        # 此本地 id 仅用于填写对应查询字段。
        self.web_id = str(secrets.randbelow(900_000_000_000_000_000) + 7_000_000_000_000_000_000)
        self._web_identity_ready = True

    def get_user_posts(
        self,
        value: str,
        *,
        limit: int = 20,
        cursor: str | int | None = None,
        page_size: int = 18,
    ) -> dict[str, Any]:
        limit = self._bounded_limit(limit, maximum=200)
        page_size = self._web_page_size(page_size, default=18, maximum=20)
        current = self._web_cursor(cursor)
        reference = (
            self.parse_user_reference(value)
            if limit == 0
            else self.resolve_user_reference(value)
        )
        sec_uid = _text(reference.get("sec_uid"))
        if limit:
            sec_uid = self._sec_uid(sec_uid)
        items: list[dict[str, Any]] = []
        seen_items: set[str] = set()
        seen_cursors: set[str] = set()
        has_more = limit > 0

        while has_more and len(items) < limit:
            self._track_cursor(current, seen_cursors)
            count = min(page_size, limit - len(items))
            payload = self._request_web_json(
                _WEB_API_PATHS["user_posts"],
                [
                    ("sec_user_id", sec_uid),
                    ("max_cursor", current),
                    ("locate_query", "false"),
                    ("show_live_replay_strategy", "1"),
                    ("need_time_list", "1"),
                    ("time_list_query", "0"),
                    ("whale_cut_token", ""),
                    ("cut_version", "1"),
                    ("count", str(count)),
                    ("publish_video_strategy_type", "2"),
                    ("from_user_page", "1"),
                ],
                referer=f"{_MAIN_BASE}/user/{sec_uid}",
            )
            self._check_web_payload(payload, "user posts")
            for raw in _list(payload.get("aweme_list")):
                item = self._normalize_aweme(_mapping(raw), "")
                item["source"] = "web_user_posts"
                item_id = _text(item.get("aweme_id"))
                if not item_id or item_id in seen_items:
                    continue
                seen_items.add(item_id)
                items.append(item)
                if len(items) >= limit:
                    break
            next_cursor = self._response_cursor(payload.get("max_cursor"), "max_cursor")
            has_more = self._web_bool(payload.get("has_more"))
            current = self._advance_cursor(current, next_cursor, has_more, seen_cursors)

        return {
            "kind": "user_posts",
            "source": "web_aweme_post",
            "sec_uid": sec_uid,
            "items": items,
            "count": len(items),
            "cursor": current,
            "has_more": has_more,
        }

    def get_comments(
        self,
        value: str | int,
        *,
        limit: int = 20,
        cursor: str | int | None = None,
        page_size: int = 20,
        include_replies: bool = False,
        reply_limit: int = 200,
        reply_page_size: int = 20,
    ) -> dict[str, Any]:
        if not isinstance(include_replies, bool):
            raise DouyinInputError("include_replies 必须是布尔值")
        limit = self._bounded_limit(limit, maximum=200)
        page_size = self._web_page_size(page_size, default=20, maximum=50)
        current = self._web_cursor(cursor)
        reply_limit, reply_page_size = self._reply_options(
            include_replies,
            reply_limit,
            reply_page_size,
        )
        reference = (
            self.parse_aweme_reference(value)
            if limit == 0
            else self.resolve_aweme_reference(value)
        )
        aweme_id = _text(reference.get("aweme_id"))
        return self._collect_comments(
            aweme_id=aweme_id,
            comment_id=None,
            limit=limit,
            cursor=current,
            page_size=page_size,
            include_replies=include_replies,
            reply_limit=reply_limit,
            reply_page_size=reply_page_size,
        )

    def get_comment_replies(
        self,
        value: str | int,
        comment_id: str | int,
        *,
        limit: int = 20,
        cursor: str | int | None = None,
        page_size: int = 20,
    ) -> dict[str, Any]:
        parent_id = self._entity_id(comment_id, "comment")
        limit = self._bounded_limit(limit, maximum=200)
        page_size = self._web_page_size(page_size, default=20, maximum=50)
        current = self._web_cursor(cursor)
        reference = (
            self.parse_aweme_reference(value)
            if limit == 0
            else self.resolve_aweme_reference(value)
        )
        aweme_id = _text(reference.get("aweme_id"))
        return self._collect_comments(
            aweme_id=aweme_id,
            comment_id=parent_id,
            limit=limit,
            cursor=current,
            page_size=page_size,
        )

    def search_videos(
        self,
        keyword: str,
        *,
        limit: int = 20,
        cursor: str | int | None = None,
        page_size: int = 10,
        sort_type: int = 0,
        publish_time: int = 0,
    ) -> dict[str, Any]:
        query = _text(keyword)
        if not query:
            raise DouyinInputError("Douyin search keyword must not be empty")
        if sort_type not in {0, 1, 2}:
            raise DouyinInputError("sort_type must be 0, 1, or 2")
        if publish_time not in {0, 1, 7, 30, 180}:
            raise DouyinInputError("publish_time must be 0, 1, 7, 30, or 180")
        limit = self._bounded_limit(limit, maximum=100)
        page_size = self._web_page_size(page_size, default=10, maximum=20)
        current = self._web_cursor(cursor)
        search_id = ""
        items: list[dict[str, Any]] = []
        seen_items: set[str] = set()
        seen_cursors: set[str] = set()
        has_more = limit > 0

        while has_more and len(items) < limit:
            self._track_cursor(current, seen_cursors)
            count = min(page_size, limit - len(items))
            payload = self._request_web_json(
                _WEB_API_PATHS["search_videos"],
                [
                    ("keyword", query),
                    ("search_channel", "aweme_video_web"),
                    ("search_source", "normal_search"),
                    ("query_correct_type", "1"),
                    ("is_filter_search", "1" if sort_type or publish_time else "0"),
                    ("from_group_id", ""),
                    ("offset", current),
                    ("count", str(count)),
                    ("sort_type", str(sort_type)),
                    ("publish_time", str(publish_time)),
                    ("search_id", search_id),
                ],
                referer=f"{_MAIN_BASE}/search/{quote(query, safe='')}?type=video",
            )
            self._check_web_payload(payload, "video search")
            for wrapper in _list(payload.get("data")):
                item_raw = _mapping(wrapper).get("aweme_info")
                if not isinstance(item_raw, Mapping):
                    continue
                item = self._normalize_aweme(item_raw, "")
                item["source"] = "web_video_search"
                item_id = _text(item.get("aweme_id"))
                if not item_id or item_id in seen_items:
                    continue
                seen_items.add(item_id)
                items.append(item)
                if len(items) >= limit:
                    break
            search_id = _text(payload.get("search_id")) or search_id
            next_cursor = self._response_cursor(
                payload.get("cursor", int(current) + count), "cursor"
            )
            has_more = self._web_bool(payload.get("has_more"))
            current = self._advance_cursor(current, next_cursor, has_more, seen_cursors)

        return {
            "kind": "video_search",
            "source": "web_search_item",
            "keyword": query,
            "items": items,
            "count": len(items),
            "cursor": current,
            "search_id": search_id or None,
            "has_more": has_more,
        }

    def get_keyword_trend(
        self,
        keywords: Sequence[str],
        *,
        start_date: str,
        end_date: str,
        regions: Sequence[str] = (),
        app_name: str = "aweme",
    ) -> dict[str, Any]:
        """通过创作者中心算数指数读取最多五个关键词的趋势曲线。"""
        requested = self._index_string_list(
            keywords,
            maximum_items=5,
            maximum_length=50,
            label="关键词",
        )
        normalized_regions = self._index_string_list(
            regions,
            maximum_items=34,
            maximum_length=32,
            label="地区",
            allow_empty=True,
        )
        start = self._index_date(start_date, "start_date")
        end = self._index_date(end_date, "end_date")
        if end < start:
            raise DouyinInputError("end_date 不能早于 start_date")
        if (end - start).days > 366:
            raise DouyinInputError("关键词趋势日期跨度最多为 366 天")
        normalized_app = str(app_name).strip()
        if normalized_app not in {"aweme", "toutiao"}:
            raise DouyinInputError("app_name 必须为 aweme 或 toutiao")
        if self.index_fetch is None:
            raise DouyinInputError("关键词趋势需要 Chrome 浏览器桥接")
        requested_by_key: dict[str, str] = {}
        for keyword in requested:
            key = self._index_keyword_key(keyword)
            if key in requested_by_key:
                raise DouyinInputError("关键词去除空白后必须唯一")
            requested_by_key[key] = keyword

        entries = [
            (
                "keyword_list",
                json.dumps(requested, ensure_ascii=False, separators=(",", ":")),
            ),
            ("start_date", start.strftime("%Y%m%d")),
            ("end_date", end.strftime("%Y%m%d")),
            ("app_name", normalized_app),
        ]
        if normalized_regions:
            entries.append(
                (
                    "region",
                    json.dumps(
                        normalized_regions,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        payload = self.index_fetch(
            _INDEX_KEYWORD_TREND_PATH,
            entries,
            _INDEX_KEYWORD_TREND_REFERER,
        )
        body = self._index_trend_body(payload)
        raw_items = body.get("hot_list")
        if not isinstance(raw_items, list) or len(raw_items) > len(requested):
            raise DouyinResponseError("抖音关键词趋势响应 hot_list 非法")

        found: set[str] = set()
        items: list[dict[str, Any]] = []
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise DouyinResponseError(
                    f"抖音关键词趋势 hot_list 第 {index} 项必须是对象"
                )
            upstream_keyword = str(raw_item.get("keyword") or "").strip()
            keyword = requested_by_key.get(
                self._index_keyword_key(upstream_keyword)
            )
            if not upstream_keyword or keyword is None or keyword in found:
                raise DouyinResponseError(
                    f"抖音关键词趋势 hot_list 第 {index} 项 keyword 非法"
                )
            item = dict(raw_item)
            item["keyword"] = keyword
            if upstream_keyword != keyword:
                item["upstream_keyword"] = upstream_keyword
            for field in _INDEX_TREND_FIELDS:
                values = item.get(field)
                if not isinstance(values, list) or len(values) > 1000:
                    raise DouyinResponseError(
                        f"抖音关键词趋势 {keyword}.{field} "
                        "必须是至多 1000 项的数组"
                    )
            found.add(keyword)
            items.append(item)

        return {
            "kind": "keyword_trend",
            "source": "douyin_creator_index_browser",
            "transport": "browser_web",
            "endpoint": _INDEX_KEYWORD_TREND_PATH,
            "app_name": normalized_app,
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "regions": normalized_regions,
            "requested": requested,
            "items": items,
            "count": len(items),
            "missing_keywords": [
                keyword for keyword in requested if keyword not in found
            ],
        }

    @staticmethod
    def _index_string_list(
        values: Sequence[str],
        *,
        maximum_items: int,
        maximum_length: int,
        label: str,
        allow_empty: bool = False,
    ) -> list[str]:
        if isinstance(values, (str, bytes, bytearray)):
            values = [str(values)]
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value)
            if (
                item != item.strip()
                or not item
                or len(item) > maximum_length
                or any(character in item for character in "\r\n\0")
                or item in seen
            ):
                raise DouyinInputError(
                    f"{label}必须唯一且每项为 1 到 {maximum_length} 个字符"
                )
            seen.add(item)
            result.append(item)
        minimum = 0 if allow_empty else 1
        if not minimum <= len(result) <= maximum_items:
            raise DouyinInputError(
                f"{label}数量必须在 {minimum} 到 {maximum_items} 之间"
            )
        return result

    @staticmethod
    def _index_keyword_key(value: str) -> str:
        return "".join(str(value).split())

    @staticmethod
    def _index_date(value: str, name: str) -> datetime:
        source = str(value)
        if re.fullmatch(r"[0-9]{8}", source) is None:
            raise DouyinInputError(f"{name} 必须为有效 YYYYMMDD 日期")
        try:
            return datetime.strptime(source, "%Y%m%d")
        except ValueError as exc:
            raise DouyinInputError(
                f"{name} 必须为有效 YYYYMMDD 日期"
            ) from exc

    @staticmethod
    def _index_trend_body(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping):
            raise DouyinResponseError("抖音关键词趋势浏览器响应不是对象")
        body: Mapping[str, Any] = payload
        for _ in range(3):
            if "BaseResp" in body:
                base_response = body["BaseResp"]
                if not isinstance(base_response, Mapping):
                    raise DouyinResponseError(
                        "抖音关键词趋势 BaseResp 非法"
                    )
                status = base_response.get("StatusCode")
                if not isinstance(status, int) or isinstance(status, bool):
                    raise DouyinResponseError(
                        "抖音关键词趋势 BaseResp.StatusCode 非法"
                    )
                if status != 0:
                    message = str(
                        base_response.get("StatusMessage") or "<empty>"
                    ).strip()
                    raise DouyinResponseError(
                        "抖音关键词趋势业务错误 "
                        f"StatusCode={status}: {message}"
                    )
            if "status_code" in body:
                status = body["status_code"]
                if not isinstance(status, int) or isinstance(status, bool):
                    raise DouyinResponseError(
                        "抖音关键词趋势 status_code 非法"
                    )
                if status != 0:
                    message = next(
                        (
                            str(body.get(name)).strip()
                            for name in ("status_message", "message", "msg")
                            if str(body.get(name) or "").strip()
                        ),
                        "<empty>",
                    )
                    raise DouyinResponseError(
                        f"抖音关键词趋势业务错误 "
                        f"status_code={status}: {message}"
                    )
            if "hot_list" in body:
                return body
            nested = body.get("data")
            if not isinstance(nested, Mapping):
                break
            body = nested
        raise DouyinResponseError("抖音关键词趋势浏览器响应缺少 hot_list")

    def get_hot_searches(self, *, limit: int = 50) -> dict[str, Any]:
        limit = self._bounded_limit(limit, maximum=100)
        if limit == 0:
            return {"kind": "hot_searches", "source": "web_hot_search", "items": [], "count": 0}
        payload = self._request_web_json(
            _WEB_API_PATHS["hot"], [], referer=f"{_MAIN_BASE}/hot"
        )
        self._check_web_payload(payload, "hot search")
        values = payload.get("data")
        if isinstance(values, Mapping):
            values = values.get("word_list") or values.get("data")
        items = [self._normalize_hot_item(_mapping(raw)) for raw in _list(values)]
        items = [item for item in items if item["word"]][:limit]
        return {
            "kind": "hot_searches",
            "source": "web_hot_search",
            "items": items,
            "count": len(items),
        }

    def _collect_comments(
        self,
        *,
        aweme_id: str,
        comment_id: str | None,
        limit: int,
        cursor: str | int | None,
        page_size: int,
        include_replies: bool = False,
        reply_limit: int = 0,
        reply_page_size: int = 20,
    ) -> dict[str, Any]:
        limit = self._bounded_limit(limit, maximum=200)
        page_size = self._page_size(page_size, maximum=50)
        current = self._web_cursor(cursor)
        items: list[dict[str, Any]] = []
        seen_items: set[str] = set()
        seen_cursors: set[str] = set()
        has_more = limit > 0
        stale_pages = 0
        endpoint = "comment_replies" if comment_id else "comments"

        while has_more and len(items) < limit:
            self._track_cursor(current, seen_cursors)
            count = min(page_size, limit - len(items))
            specific: list[tuple[str, str]]
            if comment_id:
                specific = [
                    ("item_id", aweme_id),
                    ("comment_id", comment_id),
                    ("whale_cut_token", ""),
                    ("cut_version", "1"),
                    ("cursor", current),
                    ("count", str(count)),
                    ("item_type", "0"),
                ]
            else:
                specific = [
                    ("aweme_id", aweme_id),
                    ("pc_img_format", "webp"),
                    ("cursor", current),
                    ("count", str(count)),
                    ("item_type", "0"),
                    ("insert_ids", ""),
                    ("whale_cut_token", ""),
                    ("cut_version", "1"),
                    ("rcFT", ""),
                ]
            payload = self._request_web_json(
                _WEB_API_PATHS[endpoint],
                specific,
                referer=f"{_MAIN_BASE}/video/{aweme_id}",
            )
            raw_comments, next_cursor, has_more = self._validate_comments_payload(
                payload
            )
            items_before_page = len(items)
            for raw in raw_comments:
                item = self._normalize_comment(_mapping(raw), aweme_id=aweme_id)
                item_id = _text(item.get("id"))
                if not item_id or item_id in seen_items:
                    continue
                seen_items.add(item_id)
                items.append(item)
                if len(items) >= limit:
                    break
            if has_more and len(items) == items_before_page:
                stale_pages += 1
                if stale_pages >= _MAX_COMMENT_STALE_PAGES:
                    label = "回复" if comment_id else "评论"
                    raise DouyinResponseError(
                        f"抖音{label}分页连续 {_MAX_COMMENT_STALE_PAGES} 页"
                        "没有新增条目"
                    )
            else:
                stale_pages = 0
            current = self._advance_cursor(current, next_cursor, has_more, seen_cursors)

        result = {
            "kind": "comment_replies" if comment_id else "comments",
            "source": "web_comment_list_reply" if comment_id else "web_comment_list",
            "aweme_id": aweme_id,
            "items": items,
            "count": len(items),
            "cursor": current,
            "has_more": has_more,
        }
        if comment_id:
            result["comment_id"] = comment_id
        if include_replies:
            for comment in items:
                count = _optional_int(comment.get("reply_count")) or 0
                if count <= 0:
                    continue
                parent_id = _text(comment.get("comment_id"))
                try:
                    replies = self._collect_comments(
                        aweme_id=aweme_id,
                        comment_id=parent_id,
                        limit=reply_limit,
                        cursor="0",
                        page_size=reply_page_size,
                    )
                except DouyinError as exc:
                    raise DouyinResponseError(
                        f"获取评论 {parent_id} 的回复失败: {exc}"
                    ) from exc
                comment["replies"] = replies["items"]
        return result

    @classmethod
    def parse_aweme_html(
        cls,
        source: str,
        *,
        expected_aweme_id: str,
        page_url: str = "",
    ) -> dict[str, Any]:
        expected_aweme_id = cls._aweme_id(expected_aweme_id)
        if not isinstance(source, str) or not source.strip():
            raise DouyinResponseError("Douyin aweme HTML is empty")
        page = _MetadataParser()
        try:
            page.feed(source.replace("\x00", ""))
            page.close()
        except (TypeError, ValueError) as exc:
            raise DouyinResponseError("Douyin aweme HTML could not be parsed") from exc

        canonical = cls._canonical_url(
            page.canonical or page.meta.get("og:url", ""), page_url
        )
        canonical_id = cls._aweme_id_from_url(canonical)
        if canonical_id and canonical_id != expected_aweme_id:
            raise DouyinResponseError(
                f"Douyin returned aweme {canonical_id}, expected {expected_aweme_id}"
            )

        router_data = cls.extract_router_data(source)
        if router_data is None:
            if "_$jsvmprt" in source or "bdms" in source and not page.meta:
                raise DouyinResponseError("Douyin returned its JavaScript challenge page")
            if canonical_id != expected_aweme_id:
                raise DouyinResponseError(
                    "Douyin OpenGraph response has no verifiable aweme identity"
                )
            return cls._open_graph_aweme(page, expected_aweme_id, canonical)

        video_info = cls._find_mapping_with_key(router_data, "videoInfoRes")
        if video_info is None:
            errors = router_data.get("errors")
            message = _text(errors) or "Douyin router data has no public video response"
            raise DouyinResponseError(message)
        response = _mapping(video_info.get("videoInfoRes"))
        status_code = _optional_int(response.get("status_code"))
        if status_code not in (None, 0):
            message = _text(response.get("status_msg")) or f"status_code={status_code}"
            raise DouyinResponseError(f"Douyin aweme API error: {message}")
        items = [_mapping(item) for item in _list(response.get("item_list"))]
        item = next(
            (item for item in items if _text(item.get("aweme_id")) == expected_aweme_id),
            None,
        )
        if item is None:
            actual = _text(items[0].get("aweme_id")) if items else "missing"
            raise DouyinResponseError(
                f"Douyin returned aweme {actual}, expected {expected_aweme_id}"
            )
        return cls._normalize_aweme(item, canonical or page_url)

    @classmethod
    def extract_router_data(cls, source: str) -> Mapping[str, Any] | None:
        match = _ROUTER_DATA_RE.search(source)
        if not match:
            return None
        try:
            value, _ = json.JSONDecoder().raw_decode(source[match.end() :])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DouyinResponseError("Douyin _ROUTER_DATA is malformed") from exc
        if not isinstance(value, Mapping):
            raise DouyinResponseError("Douyin _ROUTER_DATA is not an object")
        return value

    @classmethod
    def parse_profile_payload(
        cls, source: str | Mapping[str, Any], *, expected_sec_uid: str
    ) -> dict[str, Any]:
        expected_sec_uid = cls._sec_uid(expected_sec_uid)
        if isinstance(source, str):
            if not source.strip():
                raise DouyinResponseError("Douyin user response is empty")
            try:
                payload = json.loads(source)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                if "_$jsvmprt" in source or "Access Denied" in source:
                    raise DouyinResponseError("Douyin returned a user access gate") from exc
                raise DouyinResponseError("Douyin user response is not JSON") from exc
        else:
            payload = source
        data = _mapping(payload)
        status_code = _optional_int(data.get("status_code"))
        if status_code not in (None, 0):
            message = _text(data.get("status_msg")) or f"status_code={status_code}"
            raise DouyinResponseError(f"Douyin user API error: {message}")
        user = _mapping(data.get("user_info"))
        if not user:
            raise DouyinResponseError("Douyin user response has no user_info")
        actual = _text(user.get("sec_uid"))
        if actual != expected_sec_uid:
            raise DouyinResponseError(
                f"Douyin returned user {actual or 'missing'}, expected {expected_sec_uid}"
            )
        result = cls._normalize_user(user)
        result.update(
            {
                "kind": "profile",
                "source": "public_user_info",
                "url": f"{_MAIN_BASE}/user/{expected_sec_uid}",
            }
        )
        return result

    @classmethod
    def _normalize_aweme(
        cls, item: Mapping[str, Any], page_url: str
    ) -> dict[str, Any]:
        aweme_id = _text(item.get("aweme_id"))
        published_at, published_timestamp = _utc_parts(item.get("create_time"))
        images = cls._normalize_images(item.get("images") or item.get("image_infos"))
        video = cls._normalize_video(item.get("video"))
        stats = _mapping(item.get("statistics"))
        text_extra = [_mapping(value) for value in _list(item.get("text_extra"))]
        hashtags: list[dict[str, Any]] = []
        seen_hashtags: set[str] = set()
        for value in text_extra:
            name = _text(value.get("hashtag_name"))
            if name and name not in seen_hashtags:
                seen_hashtags.add(name)
                hashtags.append(
                    {
                        "id": _text(value.get("hashtag_id")) or None,
                        "name": name,
                        "start": _optional_int(value.get("start")),
                        "end": _optional_int(value.get("end")),
                    }
                )
        for value in _list(item.get("cha_list")):
            challenge = _mapping(value)
            name = _text(challenge.get("cha_name"))
            if name and name not in seen_hashtags:
                seen_hashtags.add(name)
                hashtags.append({"id": _text(challenge.get("cid")) or None, "name": name})

        mentions = [
            {
                "nickname": _text(value.get("user_nickname")) or None,
                "user_id": _text(value.get("user_id")) or None,
                "sec_uid": _text(value.get("sec_uid")) or None,
                "start": _optional_int(value.get("start")),
                "end": _optional_int(value.get("end")),
            }
            for value in text_extra
            if value.get("user_id") or value.get("sec_uid")
        ]
        return {
            "kind": "aweme",
            "source": "mobile_share_router_data",
            "aweme_id": aweme_id,
            "id": aweme_id,
            "group_id": _text(item.get("group_id_str")) or aweme_id,
            "url": f"{_MAIN_BASE}/{'note' if images else 'video'}/{aweme_id}",
            "page_url": page_url or None,
            "description": _text(item.get("desc")),
            "aweme_type": _optional_int(item.get("aweme_type")),
            "media_type": "images" if images else ("video" if video else "unknown"),
            "published_at": published_at,
            "published_timestamp": published_timestamp,
            "author": cls._normalize_user(_mapping(item.get("author"))),
            "statistics": {
                "likes": _optional_int(stats.get("digg_count")),
                "comments": _optional_int(stats.get("comment_count")),
                "shares": _optional_int(stats.get("share_count")),
                "collects": _optional_int(stats.get("collect_count")),
                "plays": _optional_int(stats.get("play_count")),
            },
            "video": video,
            "images": images,
            "music": cls._normalize_music(item.get("music")),
            "hashtags": hashtags,
            "mentions": mentions,
            "risk": dict(_mapping(item.get("risk_infos"))),
            "share": dict(_mapping(item.get("share_info"))),
            "location": cls._normalize_location(item.get("poi_info")),
        }

    @classmethod
    def _normalize_user(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        follower_count = _optional_int(value.get("follower_count"))
        if follower_count is None:
            follower_count = _optional_int(value.get("mplatform_followers_count"))
        sec_uid = _text(value.get("sec_uid"))
        verification = _text(
            value.get("enterprise_verify_reason") or value.get("custom_verify")
        )
        return {
            "uid": _text(value.get("uid")) or None,
            "sec_uid": sec_uid or None,
            "short_id": _text(value.get("short_id")) or None,
            "unique_id": _text(value.get("unique_id")) or None,
            "nickname": _text(value.get("nickname")),
            "signature": _text(value.get("signature")),
            "url": f"{_MAIN_BASE}/user/{sec_uid}" if sec_uid else None,
            "avatar": _resource(value.get("avatar_medium") or value.get("avatar_thumb")),
            "avatar_thumb": _resource(value.get("avatar_thumb")),
            "followers": follower_count,
            "following": _optional_int(value.get("following_count")),
            "aweme_count": _optional_int(value.get("aweme_count")),
            "liked_total": _optional_int(value.get("total_favorited")),
            "favorites": _optional_int(value.get("favoriting_count")),
            "verification": verification or None,
            "verification_type": _optional_int(value.get("verification_type")),
            "verified": bool(verification or _optional_int(value.get("verification_type"))),
            "show_favorite_list": value.get("show_favorite_list"),
            "account_cert_info": _decode_json_string(value.get("account_cert_info")),
            "mix_info": dict(_mapping(value.get("mix_info"))),
        }

    @staticmethod
    def _normalize_video(value: Any) -> dict[str, Any] | None:
        video = _mapping(value)
        if not video:
            return None
        duration_ms = _optional_int(video.get("duration"))
        bit_rates: list[dict[str, Any]] = []
        for raw in _list(video.get("bit_rate")):
            item = _mapping(raw)
            bit_rates.append(
                {
                    "gear_name": _text(item.get("gear_name")) or None,
                    "quality_type": _optional_int(item.get("quality_type")),
                    "bit_rate": _optional_int(item.get("bit_rate")),
                    "fps": _optional_int(item.get("FPS") or item.get("fps")),
                    "play": _resource(item.get("play_addr")),
                }
            )
        return {
            "duration_ms": duration_ms,
            "duration": duration_ms / 1000 if duration_ms is not None else None,
            "width": _optional_int(video.get("width")),
            "height": _optional_int(video.get("height")),
            "ratio": _text(video.get("ratio")) or None,
            "play": _resource(video.get("play_addr") or video.get("play_addr_h264")),
            "download": _resource(video.get("download_addr")),
            "cover": _resource(video.get("cover")),
            "origin_cover": _resource(video.get("origin_cover")),
            "dynamic_cover": _resource(video.get("dynamic_cover")),
            "bit_rates": bit_rates,
        }

    @staticmethod
    def _normalize_images(value: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in _list(value):
            image = _mapping(raw)
            source = image.get("display_image") or image.get("owner_watermark_image") or image
            normalized = _resource(source)
            normalized["download_urls"] = _unique_strings(image.get("download_url_list"))
            normalized["video"] = (
                DouyinClient._normalize_video(image.get("video")) if image.get("video") else None
            )
            if normalized["url"] or normalized["uri"]:
                output.append(normalized)
        return output

    @staticmethod
    def _normalize_music(value: Any) -> dict[str, Any] | None:
        music = _mapping(value)
        if not music:
            return None
        return {
            "id": _text(music.get("mid") or music.get("id")) or None,
            "title": _text(music.get("title")),
            "author": _text(music.get("author")),
            "duration": _optional_int(music.get("duration")),
            "status": _optional_int(music.get("status")),
            "cover": _resource(
                music.get("cover_hd") or music.get("cover_large") or music.get("cover_medium")
            ),
            "play": _resource(music.get("play_url")),
        }

    @staticmethod
    def _normalize_location(value: Any) -> dict[str, Any] | None:
        location = _mapping(value)
        if not location:
            return None
        return {
            "id": _text(location.get("poi_id")) or None,
            "name": _text(location.get("poi_name")) or None,
            "address": _text(location.get("address_info")) or None,
            "city": _text(location.get("city")) or None,
            "country": _text(location.get("country")) or None,
        }

    @classmethod
    def _normalize_comment(
        cls, value: Mapping[str, Any], *, aweme_id: str
    ) -> dict[str, Any]:
        comment_id = _text(value.get("cid") or value.get("comment_id") or value.get("id"))
        created_at, created_timestamp = _utc_parts(value.get("create_time"))
        images = [
            _resource(_mapping(item).get("medium_url") or item)
            for item in _list(value.get("image_list"))
        ]
        images = [item for item in images if item["url"] or item["uri"]]
        reply_to = _mapping(value.get("reply_to_user"))
        return {
            "kind": "comment",
            "id": comment_id,
            "comment_id": comment_id,
            "aweme_id": _text(value.get("aweme_id")) or aweme_id,
            "text": _text(value.get("text")),
            "created_at": created_at,
            "created_timestamp": created_timestamp,
            "user": cls._normalize_user(_mapping(value.get("user"))),
            "likes": _optional_int(value.get("digg_count")),
            "reply_count": _optional_int(value.get("reply_comment_total")),
            "reply_id": _text(value.get("reply_id")) or None,
            "reply_to_comment_id": _text(
                value.get("reply_to_reply_id") or value.get("reply_to_comment_id")
            )
            or None,
            "reply_to_user": cls._normalize_user(reply_to) if reply_to else None,
            "ip_label": _text(value.get("ip_label")) or None,
            "status": _optional_int(value.get("status")),
            "is_author_liked": cls._web_bool(value.get("is_author_digged")),
            "images": images,
        }

    @staticmethod
    def _normalize_hot_item(value: Mapping[str, Any]) -> dict[str, Any]:
        cover = value.get("word_cover") or value.get("cover")
        return {
            "word": _text(value.get("word") or value.get("sentence")),
            "position": _optional_int(value.get("position")),
            "hot_value": _optional_int(value.get("hot_value")),
            "view_count": _optional_int(value.get("view_count")),
            "video_count": _optional_int(value.get("video_count")),
            "sentence_id": _text(value.get("sentence_id")) or None,
            "word_type": _optional_int(value.get("word_type")),
            "event_time": _optional_int(value.get("event_time")),
            "cover": _resource(cover),
        }

    @staticmethod
    def _web_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value != 0
        return bool(value)

    @staticmethod
    def _bounded_limit(value: Any, *, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DouyinInputError("limit must be a non-negative integer")
        if value > maximum:
            raise DouyinInputError(f"limit must not exceed {maximum}")
        return value

    @staticmethod
    def _page_size(value: Any, *, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise DouyinInputError(f"page_size must be between 1 and {maximum}")
        return value

    @classmethod
    def _web_page_size(
        cls,
        value: Any,
        *,
        default: int,
        maximum: int,
    ) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and value == 0:
            value = default
        return cls._page_size(value, maximum=maximum)

    @staticmethod
    def _reply_options(
        enabled: bool,
        reply_limit: Any,
        reply_page_size: Any,
    ) -> tuple[int, int]:
        if (
            isinstance(reply_limit, bool)
            or not isinstance(reply_limit, int)
            or not 0 <= reply_limit <= 200
        ):
            raise DouyinInputError("reply_limit 必须在 0 到 200 之间")
        if (
            isinstance(reply_page_size, bool)
            or not isinstance(reply_page_size, int)
            or not 1 <= reply_page_size <= 50
        ):
            raise DouyinInputError("reply_page_size 必须在 1 到 50 之间")
        return (
            (reply_limit, reply_page_size)
            if enabled
            else (0, reply_page_size)
        )

    @staticmethod
    def _entity_id(value: Any, label: str) -> str:
        result = _text(value)
        if not _AWEME_ID_RE.fullmatch(result):
            raise DouyinInputError(f"Douyin {label} id must be 10 to 22 decimal digits")
        return result

    @staticmethod
    def _web_cursor(value: Any) -> str:
        if value in (None, ""):
            return "0"
        if isinstance(value, bool):
            raise DouyinInputError("cursor must be a non-negative decimal integer")
        result = _text(value)
        if (
            not result
            or len(result) > 30
            or re.fullmatch(r"[0-9]+", result) is None
        ):
            raise DouyinInputError("cursor must be a non-negative decimal integer")
        return result

    @staticmethod
    def _strict_integer(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        return None

    @classmethod
    def _strict_response_cursor(cls, value: Any) -> str | None:
        if isinstance(value, str):
            cursor = value.strip()
        else:
            number = cls._strict_integer(value)
            if number is None:
                return None
            cursor = str(number)
        if (
            not cursor
            or len(cursor) > 30
            or re.fullmatch(r"[0-9]+", cursor) is None
        ):
            return None
        return cursor

    @classmethod
    def _strict_has_more(cls, value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        number = cls._strict_integer(value)
        if number not in {0, 1}:
            return None
        return number == 1

    @classmethod
    def _validate_comments_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> tuple[list[Any], str, bool]:
        status_code = cls._strict_integer(payload.get("status_code"))
        if status_code is None or not -(1 << 63) <= status_code < (1 << 63):
            raise DouyinResponseError(
                "抖音 comments API 响应 status_code 必须是整数"
            )
        if status_code != 0:
            message = _text(payload.get("status_msg")) or (
                f"status_code={status_code}"
            )
            raise DouyinResponseError(f"抖音 comments API 错误: {message}")

        if "comments" in payload:
            field = "comments"
        elif "data" in payload:
            field = "data"
        else:
            raise DouyinResponseError(
                "抖音 comments API 响应缺少 comments/data 数组"
            )
        items = payload[field]
        if not isinstance(items, list):
            raise DouyinResponseError(
                f"抖音 comments API 响应 {field} 必须是数组"
            )

        if "cursor" not in payload:
            raise DouyinResponseError("抖音 comments API 响应缺少 cursor")
        cursor = cls._strict_response_cursor(payload["cursor"])
        if cursor is None:
            raise DouyinResponseError(
                "抖音 comments API 响应 cursor 必须是非负十进制值"
            )

        if "has_more" not in payload:
            raise DouyinResponseError("抖音 comments API 响应缺少 has_more")
        has_more = cls._strict_has_more(payload["has_more"])
        if has_more is None:
            raise DouyinResponseError(
                "抖音 comments API 响应 has_more 必须是布尔值或数值 0/1"
            )
        return items, cursor, has_more

    @classmethod
    def _response_cursor(cls, value: Any, field: str) -> str:
        try:
            return cls._web_cursor(value)
        except DouyinInputError as exc:
            raise DouyinResponseError(f"Douyin returned invalid {field}") from exc

    @staticmethod
    def _track_cursor(cursor: str, seen: set[str]) -> None:
        if cursor in seen:
            raise DouyinResponseError(f"Douyin pagination cursor repeated: {cursor}")
        seen.add(cursor)

    @staticmethod
    def _advance_cursor(
        current: str, next_cursor: str, has_more: bool, seen: set[str]
    ) -> str:
        if not has_more:
            return next_cursor
        if next_cursor == current:
            raise DouyinResponseError("Douyin pagination cursor did not advance")
        if next_cursor in seen:
            raise DouyinResponseError(
                f"Douyin pagination cursor repeated: {next_cursor}"
            )
        return next_cursor

    @staticmethod
    def _check_web_payload(payload: Mapping[str, Any], label: str) -> None:
        status_code = _optional_int(payload.get("status_code"))
        if status_code not in (None, 0):
            message = _text(payload.get("status_msg")) or f"status_code={status_code}"
            raise DouyinResponseError(f"Douyin {label} API error: {message}")

    def _request_web_json(
        self,
        path: str,
        specific: Sequence[tuple[str, str]],
        *,
        referer: str,
    ) -> Mapping[str, Any]:
        if path not in _WEB_API_PATHS.values():
            raise DouyinInputError("unknown Douyin Web API path")
        if self.web_fetch is not None and path in _BROWSER_WEB_PATHS:
            try:
                payload = self.web_fetch(path, list(specific), referer)
            except DouyinError:
                raise
            except Exception as exc:
                raise DouyinResponseError(
                    f"抖音浏览器请求失败: {exc}"
                ) from exc
            if not isinstance(payload, Mapping):
                raise DouyinResponseError("抖音浏览器响应不是对象")
            return payload
        self.initialize_web_session()
        raw_query = urlencode(
            [*specific, *_WEB_QUERY_DEFAULTS, ("webid", self.web_id)],
            doseq=False,
        )
        signed_query = self._sign_web_query(raw_query)
        url = f"{_MAIN_BASE}{path}"
        request_options: dict[str, Any] = {
            "headers": {
                "Accept": "application/json, text/plain, */*",
                "Referer": referer,
                "User-Agent": self.web_user_agent,
            },
            "timeout": self.timeout,
            "allow_redirects": False,
            "impersonate": "chrome146",
        }
        if self.proxy:
            request_options["proxy"] = self.proxy

        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(f"{url}?{signed_query}", **request_options)
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise DouyinResponseError(f"Douyin Web request failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                signed_query = self._sign_web_query(raw_query)
                continue
            self._validate_final_url(str(response.url or url))
            if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                signed_query = self._sign_web_query(raw_query)
                continue
            if response.status_code != 200:
                raise DouyinResponseError(
                    f"Douyin returned HTTP {response.status_code} for {path}"
                )
            source = response.text
            if not source.strip() or source.strip() == "blocked":
                raise DouyinResponseError("Douyin Web returned an access gate")
            try:
                payload = json.loads(source)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise DouyinResponseError("Douyin Web response is not JSON") from exc
            if not isinstance(payload, Mapping):
                raise DouyinResponseError("Douyin Web response is not an object")
            return payload
        raise DouyinResponseError("Douyin Web request exhausted retries")

    def _sign_web_query(self, raw_query: str) -> str:
        payload = {
            "raw_query": raw_query,
            "user_agent": self.web_user_agent,
            "body": "",
        }
        if self.web_signer is None:
            from .signing import a_bogus

            result = a_bogus(payload)
        else:
            result = self.web_signer(payload)
        if not isinstance(result, Mapping):
            raise DouyinResponseError("Douyin signer returned an invalid result")
        query = result.get("query")
        signature = result.get("a_bogus")
        if isinstance(query, str) and query.startswith(f"{raw_query}&a_bogus="):
            return query
        if not isinstance(signature, str) or not signature:
            raise DouyinResponseError("Douyin signer returned no a_bogus")
        return f"{raw_query}&a_bogus={signature}"

    @classmethod
    def _open_graph_aweme(
        cls, page: _MetadataParser, aweme_id: str, canonical: str
    ) -> dict[str, Any]:
        description = page.meta.get("og:description") or page.meta.get("description") or ""
        title = page.meta.get("og:title") or page.title
        image = page.meta.get("og:image") or page.poster
        if not description and not title and not image:
            raise DouyinResponseError("Douyin page has no public aweme metadata")
        return {
            "kind": "aweme",
            "source": "open_graph",
            "aweme_id": aweme_id,
            "id": aweme_id,
            "group_id": aweme_id,
            "url": canonical or f"{_MAIN_BASE}/video/{aweme_id}",
            "page_url": canonical or None,
            "description": description,
            "title": title,
            "aweme_type": None,
            "media_type": "image" if image else "unknown",
            "published_at": None,
            "published_timestamp": None,
            "author": cls._normalize_user({}),
            "statistics": {
                "likes": None,
                "comments": None,
                "shares": None,
                "collects": None,
                "plays": None,
            },
            "video": None,
            "images": [_resource(image)] if image else [],
            "music": None,
            "hashtags": [],
            "mentions": [],
            "risk": {},
            "share": {},
            "location": None,
        }

    def _resolve_short(
        self,
        short_url: str,
        parser: Callable[[str], dict[str, Any]],
        identity_key: str,
    ) -> dict[str, Any]:
        current = short_url
        seen: set[str] = set()
        for _ in range(self.max_redirects):
            if current in seen:
                raise DouyinResponseError("Douyin short URL entered a redirect loop")
            seen.add(current)
            response = self._request(
                current,
                headers={"Referer": f"{_SHARE_BASE}/"},
                allow_redirects=False,
            )
            self._validate_final_url(str(response.url or current))
            if response.status_code not in _REDIRECT_STATUS:
                raise DouyinResponseError("Douyin short URL did not return a target redirect")
            location = response.headers.get("Location") or response.headers.get("location")
            if not location:
                raise DouyinResponseError("Douyin short redirect has no Location header")
            target = urljoin(current, location)
            self._validate_final_url(target)
            try:
                result = parser(target)
            except DouyinInputError:
                current = target
                continue
            if result.get(identity_key):
                result["short_url"] = short_url
                result["redirect_url"] = target
                return result
            current = target
        raise DouyinResponseError("Douyin short URL exceeded the redirect limit")

    def _request(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        allow_redirects: bool,
        impersonate: str | None = None,
        user_agent: str | None = None,
    ) -> requests.Response:
        current = url
        request_params = dict(params or {})
        seen: set[str] = set()
        redirects = 0

        while True:
            self._validate_final_url(current)
            if current in seen:
                raise DouyinResponseError("Douyin request entered a redirect loop")
            seen.add(current)

            for attempt in range(self.retries + 1):
                try:
                    request_headers = dict(headers or {})
                    if user_agent is not None:
                        request_headers["User-Agent"] = user_agent
                    request_options: dict[str, Any] = {
                        "params": request_params,
                        "headers": request_headers,
                        "timeout": self.timeout,
                        "allow_redirects": False,
                    }
                    if impersonate is not None:
                        request_options["impersonate"] = impersonate
                    if self.proxy:
                        request_options["proxy"] = self.proxy
                    response = self.session.get(current, **request_options)
                except requests.exceptions.RequestException as exc:
                    if attempt >= self.retries:
                        raise DouyinResponseError(f"Douyin request failed: {exc}") from exc
                    time.sleep(0.4 * (2**attempt))
                    continue

                response_url = str(response.url or current)
                self._validate_final_url(response_url)
                if (
                    response.status_code in _RETRYABLE_STATUS
                    and attempt < self.retries
                ):
                    time.sleep(0.4 * (2**attempt))
                    continue
                break
            else:
                raise DouyinResponseError("Douyin request exhausted all retries")

            if response.status_code == 200:
                return response
            if response.status_code not in _REDIRECT_STATUS:
                raise DouyinResponseError(f"Douyin returned HTTP {response.status_code}")
            if not allow_redirects:
                return response

            location = response.headers.get("Location") or response.headers.get("location")
            if not location:
                raise DouyinResponseError("Douyin redirect has no Location header")
            if redirects >= self.max_redirects:
                raise DouyinResponseError("Douyin request exceeded the redirect limit")
            target = urljoin(response_url, location)
            self._validate_final_url(target)
            current = target
            request_params = {}
            redirects += 1

    @classmethod
    def _aweme_reference(cls, aweme_id: str, content_type: str) -> dict[str, Any]:
        aweme_id = cls._aweme_id(aweme_id)
        route = "note" if content_type in {"note", "slides"} else "video"
        share_route = "note" if content_type in {"note", "slides"} else "video"
        return {
            "kind": "aweme",
            "aweme_id": aweme_id,
            "content_type": route,
            "url": f"{_MAIN_BASE}/{route}/{aweme_id}",
            "share_page_url": f"{_SHARE_BASE}/share/{share_route}/{aweme_id}/",
            "short_url": None,
        }

    @classmethod
    def _user_reference(cls, sec_uid: str) -> dict[str, Any]:
        sec_uid = cls._sec_uid(sec_uid)
        return {
            "kind": "user",
            "sec_uid": sec_uid,
            "url": f"{_MAIN_BASE}/user/{sec_uid}",
            "share_page_url": f"{_SHARE_BASE}/share/user/?sec_uid={sec_uid}",
            "short_url": None,
        }

    @staticmethod
    def _reference(value: Any, label: str) -> str:
        if isinstance(value, bool):
            raise DouyinInputError(f"{label} reference must be a string or integer id")
        if isinstance(value, int):
            return str(value)
        if not isinstance(value, str) or not value.strip():
            raise DouyinInputError(f"{label} reference must be a non-empty string")
        source = html.unescape(value.strip())
        match = _URL_IN_TEXT_RE.search(source)
        return match.group(0) if match else source

    @staticmethod
    def _input_text(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DouyinInputError("text must be a non-empty string")
        return html.unescape(value.strip())

    @staticmethod
    def _aweme_id(value: Any) -> str:
        aweme_id = _text(value)
        if not _AWEME_ID_RE.fullmatch(aweme_id):
            raise DouyinInputError("Douyin aweme id must be 10 to 22 decimal digits")
        return aweme_id

    @staticmethod
    def _sec_uid(value: Any) -> str:
        sec_uid = _text(value)
        if not _SEC_UID_RE.fullmatch(sec_uid):
            raise DouyinInputError("Douyin sec_uid has an invalid format")
        return sec_uid

    @classmethod
    def _douyin_url(cls, value: str) -> str:
        candidate = value
        if "://" not in candidate and candidate.lower().startswith(
            (
                "douyin.com/",
                "www.douyin.com/",
                "v.douyin.com/",
                "iesdouyin.com/",
                "www.iesdouyin.com/",
                "m.douyin.com/",
            )
        ):
            candidate = f"https://{candidate}"
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise DouyinInputError("Douyin URL is malformed") from exc
        host = (parsed.hostname or "").lower().rstrip(".")
        scheme = parsed.scheme.lower()
        expected_port = 80 if scheme == "http" else 443
        if (
            scheme not in {"http", "https"}
            or not cls._owned_host(host)
            or parsed.username is not None
            or parsed.password is not None
            or (port is not None and port != expected_port)
        ):
            raise DouyinInputError("URL must use an owned Douyin HTTP host")
        return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))

    @staticmethod
    def _owned_host(host: str) -> bool:
        return host in _OWNED_HOSTS

    @classmethod
    def _validate_final_url(cls, value: str) -> None:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise DouyinResponseError("Douyin returned a malformed URL") from exc
        scheme = parsed.scheme.lower()
        if (
            scheme != "https"
            or not cls._owned_host((parsed.hostname or "").lower().rstrip("."))
            or parsed.username is not None
            or parsed.password is not None
            or (port is not None and port != 443)
        ):
            raise DouyinResponseError("Douyin request left the owned hosts")

    @classmethod
    def _canonical_url(cls, value: str, page_url: str) -> str:
        candidate = urljoin(page_url or f"{_MAIN_BASE}/", html.unescape(value)) if value else page_url
        if candidate:
            cls._validate_final_url(candidate)
        return candidate

    @staticmethod
    def _aweme_id_from_url(value: str) -> str | None:
        if not value:
            return None
        try:
            path = unquote(urlsplit(value).path)
        except ValueError:
            return None
        match = _AWEME_PATH_RE.fullmatch(path) or _SHARE_AWEME_PATH_RE.fullmatch(path)
        return match.group(2) if match else None

    @classmethod
    def _find_mapping_with_key(
        cls, value: Any, key: str
    ) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            if key in value:
                return value
            for child in value.values():
                result = cls._find_mapping_with_key(child, key)
                if result is not None:
                    return result
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for child in value:
                result = cls._find_mapping_with_key(child, key)
                if result is not None:
                    return result
        return None
