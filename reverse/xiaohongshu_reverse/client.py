from __future__ import annotations

import json
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import XiaohongshuInputError, XiaohongshuResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_BASE_URL = "https://www.xiaohongshu.com"
_NOTE_ID_RE = re.compile(r"^[a-fA-F0-9]{24}$")
_USER_ID_RE = re.compile(r"^[a-fA-F0-9]{24}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
_URL_RE = re.compile(
    r"https?://[^\s<>\"'，。；：！？）】》」』]+",
    re.IGNORECASE,
)
_INITIAL_STATE_RE = re.compile(r"(?:window\s*\.\s*)?__INITIAL_STATE__\s*=\s*")
_DIRECT_NOTE_PATH_RE = re.compile(
    r"^/(?:explore|discovery/item)/([a-fA-F0-9]{24})(?:/|$)"
)
_PROFILE_PATH_RE = re.compile(r"^/user/profile/([a-fA-F0-9]{24})(?:/|$)")
_XIAOHONGSHU_HOSTS = {
    "xiaohongshu.com",
    "www.xiaohongshu.com",
    "m.xiaohongshu.com",
}
_SHORT_LINK_HOSTS = {"xhslink.com", "www.xhslink.com"}
_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>，。；：！？）】》」』"
_PGY_REFERER = "https://pgy.xiaohongshu.com/"
_PGY_GOOD_CASE_CLASSES_PATH = (
    "/bridge/v1/xiaohongshu-pgy/good-case-classes"
)
_PGY_GOOD_NOTES_PATH = "/bridge/v1/xiaohongshu-pgy/good-notes"
_PGY_GOOD_LIVES_PATH = "/bridge/v1/xiaohongshu-pgy/good-lives"
_PGY_TOP_BLOGGERS_PATH = "/bridge/v1/xiaohongshu-pgy/top-bloggers"
_PGY_INDUSTRIES_PATH = "/bridge/v1/xiaohongshu-pgy/industries"
_SEARCH_NOTES_PATH = "/api/sns/web/v2/search/notes"
_SEARCH_USERS_PATH = "/api/sns/web/v1/search/usersearch"
_SEARCH_SUGGEST_PATH = "/api/sns/web/v1/search/recommend"
_SEARCH_FILTER_PATH = "/api/sns/web/v1/search/filter"
_HOT_LIST_PATH = "/api/sns/web/v1/search/trending/query"
_USER_POSTED_PATH = "/api/sns/web/v1/user_posted"
_COMMENT_PATH = "/api/sns/web/v2/comment/page"
_SUB_COMMENT_PATH = "/api/sns/web/v2/comment/sub/page"
_WIDGETS_PATH = "/api/sns/web/v2/widgets"
_SEARCH_REFERER = f"{_BASE_URL}/search_result"
_SEARCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_SEARCH_SORTS = {
    "general",
    "popularity_descending",
    "time_descending",
    "comment_descending",
    "collect_descending",
}
_SEARCH_NOTE_TYPES = {
    "": "0",
    "0": "0",
    "all": "0",
    "1": "1",
    "video": "1",
    "2": "2",
    "image": "2",
    "normal": "2",
}
_SEARCH_AUXILIARY_MODELS = {
    "activity",
    "hot_query",
    "rec_query",
    "hot_list",
    "ai_trace_source",
    "outlink",
    "relevant_text",
    "live_v2",
}
_SEARCH_MAX_ITEMS = 200
_SEARCH_MAX_STALE_PAGES = 3
_BROWSER_ENVELOPE_DEPTH = 4


def _first_present(value: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in value and value[name] is not None:
            return value[name]
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            text = str(value)
        else:
            continue
        if text:
            return text
    return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _number(value: Any) -> int | float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return int(number) if number.is_integer() else number


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    source = (
        str(value or "")
        .strip()
        .replace("\xa0", "")
        .replace(" ", "")
        .replace(",", "")
    )
    if not source:
        return 0
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)([KMBT\u4e07\u4ebf]?)", source, re.IGNORECASE)
    if not match:
        return 0
    multiplier = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "T": 1_000_000_000_000,
        "\u4e07": 10_000,
        "\u4ebf": 100_000_000,
    }.get(match.group(2).upper(), 1)
    try:
        return max(0, int(Decimal(match.group(1)) * multiplier))
    except (InvalidOperation, ValueError):
        return 0


def _timestamp(value: Any) -> int:
    timestamp = _integer(value)
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return timestamp if timestamp > 0 else 0


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _timestamp(value)
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _secure_url(value: Any) -> str:
    source = str(value or "").strip()
    if not source:
        return ""
    if source.startswith("//"):
        return f"https:{source}"
    parsed = urlsplit(source)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and (
        host.endswith(".xhscdn.com")
        or host.endswith(".xiaohongshu.com")
        or host in _XIAOHONGSHU_HOSTS
        or host in _SHORT_LINK_HOSTS
    ):
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return source


class XiaohongshuClient:
    """使用普通 Python HTTP 请求读取小红书公开 SSR 页面。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
        browser_fetch: (
            Callable[
                [str, Sequence[tuple[str, str]], str],
                Mapping[str, Any],
            ]
            | None
        ) = None,
        pgy_fetch: (
            Callable[
                [str, Sequence[tuple[str, str]], str],
                Mapping[str, Any],
            ]
            | None
        ) = None,
    ) -> None:
        self.session = session or requests.Session(impersonate="chrome")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.browser_fetch = browser_fetch
        self.pgy_fetch = pgy_fetch
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    def resolve_note_reference(
        self,
        note_url_or_id: str,
        *,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        value = self._reference_text(note_url_or_id)
        token_override = self._token(xsec_token) if xsec_token is not None else None
        source_override = self._source(xsec_source) if xsec_source is not None else None

        if _NOTE_ID_RE.fullmatch(value):
            note_id = value.lower()
            source = source_override or ("pc_feed" if token_override else "")
            return self._note_reference(
                note_id,
                token_override,
                source,
                page_url=f"{_BASE_URL}/explore/{note_id}",
                source_url=value,
                short_url=None,
            )

        candidate = self._candidate_url(value)
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host in _SHORT_LINK_HOSTS:
            resolved_url = self._resolve_short_url(candidate)
            direct = self._direct_note_parts(resolved_url)
            if direct is None:
                raise XiaohongshuResponseError(
                    "Xiaohongshu short link did not resolve to a public note URL"
                )
            note_id, token, source, page_url = direct
            return self._note_reference(
                note_id,
                token_override or token,
                source_override or source or ("pc_feed" if (token_override or token) else ""),
                page_url=page_url,
                source_url=resolved_url,
                short_url=candidate,
            )
        if host not in _XIAOHONGSHU_HOSTS:
            raise XiaohongshuInputError("note URL must use xiaohongshu.com or xhslink.com")
        direct = self._direct_note_parts(candidate)
        if direct is None:
            raise XiaohongshuInputError("URL is not a Xiaohongshu public note URL")
        note_id, token, source, page_url = direct
        return self._note_reference(
            note_id,
            token_override or token,
            source_override or source or ("pc_feed" if (token_override or token) else ""),
            page_url=page_url,
            source_url=candidate,
            short_url=None,
        )

    def get_note(
        self,
        note_url_or_id: str,
        *,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        reference = self.resolve_note_reference(
            note_url_or_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        params: dict[str, str] = {}
        if reference["xsec_token"]:
            params["xsec_token"] = reference["xsec_token"]
            params["xsec_source"] = reference["xsec_source"] or "pc_feed"
        response = self._request(
            reference["page_url"],
            params=params,
            headers={"Referer": f"{_BASE_URL}/explore"},
        )
        note = self.parse_note_html(
            response.text,
            expected_note_id=reference["note_id"],
            xsec_token=reference["xsec_token"],
            xsec_source=reference["xsec_source"],
            source_url=reference["source_url"],
        )
        note["short_url"] = reference["short_url"]
        return note

    def get_profile(
        self,
        profile_url_or_user_id: str,
        *,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        reference = self.resolve_profile_reference(
            profile_url_or_user_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        params: dict[str, str] = {}
        if reference["xsec_token"]:
            params["xsec_token"] = reference["xsec_token"]
            params["xsec_source"] = reference["xsec_source"] or "pc_note"
        response = self._request(
            reference["page_url"],
            params=params,
            headers={"Referer": f"{_BASE_URL}/explore"},
        )
        return self.parse_profile_html(
            response.text,
            expected_user_id=reference["user_id"],
            xsec_token=reference["xsec_token"],
            xsec_source=reference["xsec_source"],
        )

    def search_notes(
        self,
        keyword: str,
        *,
        limit: int = 20,
        page_size: int = 20,
        page: int = 1,
        search_id: str | None = None,
        sort: str = "general",
        note_type: str = "all",
    ) -> dict[str, Any]:
        """通过 Chrome 登录态搜索笔记，并跨页去重。"""
        query = self._search_text(keyword, allow_empty=False)
        maximum = self._search_limit(limit)
        size = self._search_page_size(page_size, maximum=20)
        if size != 20:
            raise XiaohongshuInputError(
                "search-notes page_size 必须为 20"
            )
        start_page = self._search_page(page)
        session_id = self._search_id(search_id)
        order = str(sort).strip().lower()
        if order not in _SEARCH_SORTS:
            raise XiaohongshuInputError(
                "sort 必须为 general、popularity_descending、time_descending、"
                "comment_descending 或 collect_descending"
            )
        normalized_type = _SEARCH_NOTE_TYPES.get(str(note_type).strip().lower())
        if normalized_type is None:
            raise XiaohongshuInputError(
                "note_type 必须为 all、video 或 image"
            )
        return self._collect_search(
            operation="search-notes",
            path=_SEARCH_NOTES_PATH,
            kind="search_notes",
            source="web_search_notes",
            fields=("items", "notes"),
            keyword=query,
            limit=maximum,
            page_size=size,
            page=start_page,
            search_id=session_id,
            extra_entries=(
                ("sort", order),
                ("note_type", normalized_type),
            ),
        )

    def search_users(
        self,
        keyword: str,
        *,
        limit: int = 20,
        page_size: int = 20,
        page: int = 1,
        search_id: str | None = None,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态搜索用户，并跨页去重。"""
        return self._collect_search(
            operation="search-users",
            path=_SEARCH_USERS_PATH,
            kind="search_users",
            source="web_search_users",
            fields=("users", "items"),
            keyword=self._search_text(keyword, allow_empty=False),
            limit=self._search_limit(limit),
            page_size=self._search_page_size(page_size, maximum=50),
            page=self._search_page(page),
            search_id=self._search_id(search_id),
        )

    def search_suggest(
        self,
        keyword: str = "",
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        """读取搜索框联想词；空关键词用于读取默认建议。"""
        query = self._search_text(keyword, allow_empty=True)
        return self._collect_single_search(
            operation="search-suggest",
            path=_SEARCH_SUGGEST_PATH,
            kind="search_suggestions",
            source="web_search_recommend",
            fields=("sug_items", "sugItems", "items", "queries"),
            limit=self._search_limit(limit),
            entries=(("keyword", query),),
            keyword=query,
        )

    def get_search_filters(
        self,
        keyword: str,
        *,
        search_id: str | None = None,
    ) -> dict[str, Any]:
        """读取当前关键词可用的搜索筛选器和动态地域选项。"""
        query = self._search_text(keyword, allow_empty=False)
        session_id = self._search_id(search_id)
        payload = self._browser_request(
            _SEARCH_FILTER_PATH,
            (
                ("keyword", query),
                ("search_id", session_id),
            ),
        )
        container = self._browser_envelope(
            payload,
            ("filters", "filter_list", "filterList", "items"),
        )
        raw_items = self._browser_items(
            container,
            ("filters", "filter_list", "filterList", "items"),
            allow_missing=False,
            operation="search-filters",
        )
        return {
            "kind": "search_filters",
            "result_type": "search_filters",
            "source": "web_search_filter",
            "platform": "xiaohongshu",
            "transport": "browser_web",
            "keyword": query,
            "search_id": session_id,
            "items": [
                self._normalize_filter_group(item, index=index)
                for index, item in enumerate(raw_items)
            ],
            "count": len(raw_items),
        }

    def get_hot_list(self, *, limit: int = 20) -> dict[str, Any]:
        """读取当前登录态可见的搜索热榜。"""
        return self._collect_single_search(
            operation="hot-list",
            path=_HOT_LIST_PATH,
            kind="hot_list",
            source="web_search_hotlist",
            fields=("items", "queries", "hot_list", "hotList"),
            limit=self._search_limit(limit),
        )

    def get_user_posts(
        self,
        profile_url_or_user_id: str,
        *,
        limit: int = 30,
        cursor: str | int | None = None,
        page_size: int = 30,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        """通过资料页上下文读取作者作品历史。"""
        maximum = self._search_limit(limit)
        size = self._search_page_size(page_size, maximum=100)
        current = self._browser_cursor(cursor)
        reference = self.resolve_profile_reference(
            profile_url_or_user_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        referer = self._context_referer(
            reference["page_url"],
            reference.get("xsec_token"),
            reference.get("xsec_source"),
            default_source="pc_profile",
        )
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        has_more = maximum > 0

        while has_more and len(items) < maximum:
            count = min(size, maximum - len(items))
            payload = self._browser_request(
                _USER_POSTED_PATH,
                (
                    ("user_id", reference["user_id"]),
                    ("cursor", current),
                    ("num", str(count)),
                    ("image_formats", "jpg,webp,avif"),
                ),
                referer=referer,
            )
            container = self._browser_envelope(payload, ("notes", "items"))
            raw_items = self._browser_items(
                container,
                ("notes", "items"),
                allow_missing=False,
                operation="user-posts",
            )
            before = len(items)
            for index, raw in enumerate(raw_items):
                try:
                    item = self._normalize_search_note(raw)
                except XiaohongshuResponseError as exc:
                    raise XiaohongshuResponseError(
                        f"user-posts items[{index}] 非法: {exc}"
                    ) from exc
                note_id = item["note_id"]
                if note_id in seen:
                    continue
                seen.add(note_id)
                items.append(item)
                if len(items) >= maximum:
                    break
            next_cursor = self._browser_next_cursor(container)
            page_has_more, present = self._browser_has_more(
                _mapping(container),
                operation="user-posts",
            )
            if not present:
                page_has_more = bool(raw_items) and bool(next_cursor)
            if page_has_more and (
                not next_cursor
                or next_cursor == current
                or len(items) == before
            ):
                raise XiaohongshuResponseError(
                    "user-posts 分页游标没有前进"
                )
            current = next_cursor
            has_more = page_has_more

        return {
            "kind": "user_posts",
            "result_type": "user_posts",
            "source": "web_user_posted",
            "platform": "xiaohongshu",
            "transport": "browser_web",
            "user_id": reference["user_id"],
            "items": items,
            "count": len(items),
            "cursor": current,
            "has_more": has_more,
        }

    def get_note_comments(
        self,
        note_url_or_id: str,
        *,
        limit: int = 50,
        cursor: str | int | None = None,
        include_replies: bool = False,
        reply_limit: int = 100,
        reply_page_size: int = 20,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        """通过笔记页上下文读取评论，可选补齐楼中楼回复。"""
        maximum = self._search_limit(limit)
        current = self._browser_cursor(cursor)
        if not isinstance(include_replies, bool):
            raise XiaohongshuInputError("include_replies 必须是布尔值")
        replies_maximum = self._search_limit(reply_limit)
        replies_size = self._search_page_size(reply_page_size, maximum=100)
        reference = self.resolve_note_reference(
            note_url_or_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        has_more = maximum > 0

        while has_more and len(items) < maximum:
            payload = self._browser_request(
                _COMMENT_PATH,
                (
                    ("note_id", reference["note_id"]),
                    ("cursor", current),
                    ("top_comment_id", ""),
                    ("image_formats", "jpg,webp,avif"),
                ),
                referer=reference["url"],
            )
            container = self._browser_envelope(payload, ("comments",))
            raw_items = self._browser_items(
                container,
                ("comments",),
                allow_missing=False,
                operation="note-comments",
            )
            before = len(items)
            for index, raw in enumerate(raw_items):
                try:
                    item = self._normalize_comment(raw, include_nested=True)
                except XiaohongshuResponseError as exc:
                    raise XiaohongshuResponseError(
                        f"note-comments items[{index}] 非法: {exc}"
                    ) from exc
                comment_id = item["comment_id"]
                if comment_id in seen:
                    continue
                seen.add(comment_id)
                if include_replies and replies_maximum:
                    item = self._complete_comment_replies(
                        item,
                        note_id=reference["note_id"],
                        referer=reference["url"],
                        limit=replies_maximum,
                        page_size=replies_size,
                    )
                items.append(item)
                if len(items) >= maximum:
                    break
            next_cursor = self._browser_next_cursor(container)
            page_has_more, present = self._browser_has_more(
                _mapping(container),
                operation="note-comments",
            )
            if not present:
                page_has_more = bool(raw_items) and bool(next_cursor)
            if page_has_more and (
                not next_cursor
                or next_cursor == current
                or len(items) == before
            ):
                raise XiaohongshuResponseError(
                    "note-comments 分页游标没有前进"
                )
            current = next_cursor
            has_more = page_has_more

        return {
            "kind": "note_comments",
            "result_type": "note_comments",
            "source": "web_comment_page",
            "platform": "xiaohongshu",
            "transport": "browser_web",
            "note_id": reference["note_id"],
            "items": items,
            "count": len(items),
            "cursor": current,
            "has_more": has_more,
        }

    def get_note_related_searches(
        self,
        note_url_or_id: str,
        *,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        """读取笔记页“猜你想搜”关联词，用于从素材反查搜索需求。"""
        reference = self.resolve_note_reference(
            note_url_or_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
        )
        payload = self._browser_request(
            _WIDGETS_PATH,
            (("note_id", reference["note_id"]),),
            referer=reference["url"],
        )
        container = self._browser_envelope(payload, ("widgets", "items"))
        raw_items = self._browser_items(
            container,
            ("widgets", "items"),
            allow_missing=False,
            operation="note-related-searches",
        )
        items = [
            item
            for item in (
                self._normalize_related_search(raw, index=index)
                for index, raw in enumerate(raw_items)
            )
            if item is not None
        ]
        return {
            "kind": "note_related_searches",
            "result_type": "note_related_searches",
            "source": "web_note_widgets",
            "platform": "xiaohongshu",
            "transport": "browser_web",
            "note_id": reference["note_id"],
            "items": items,
            "count": len(items),
        }

    def _complete_comment_replies(
        self,
        comment: Mapping[str, Any],
        *,
        note_id: str,
        referer: str,
        limit: int,
        page_size: int,
    ) -> dict[str, Any]:
        result = dict(comment)
        replies = [
            dict(item)
            for item in _list(result.get("replies"))
            if isinstance(item, Mapping)
        ][:limit]
        seen = {
            str(item.get("comment_id") or "")
            for item in replies
            if item.get("comment_id")
        }
        root_comment_id = str(result.get("comment_id") or "")
        has_more = bool(result.get("reply_has_more")) or (
            _integer(result.get("sub_comment_count")) > len(replies)
        )
        cursor = str(result.get("reply_cursor") or "")
        if not _NOTE_ID_RE.fullmatch(root_comment_id):
            result["replies"] = replies
            result["reply_count"] = len(replies)
            result["reply_has_more"] = has_more
            return result

        while has_more and len(replies) < limit:
            count = min(page_size, limit - len(replies))
            payload = self._browser_request(
                _SUB_COMMENT_PATH,
                (
                    ("note_id", note_id),
                    ("root_comment_id", root_comment_id),
                    ("num", str(count)),
                    ("cursor", cursor),
                    ("top_comment_id", ""),
                    ("image_formats", "jpg,webp,avif"),
                ),
                referer=referer,
            )
            container = self._browser_envelope(payload, ("comments",))
            raw_items = self._browser_items(
                container,
                ("comments",),
                allow_missing=False,
                operation="comment-replies",
            )
            before = len(replies)
            for index, raw in enumerate(raw_items):
                try:
                    item = self._normalize_comment(raw, include_nested=False)
                except XiaohongshuResponseError as exc:
                    raise XiaohongshuResponseError(
                        f"comment-replies items[{index}] 非法: {exc}"
                    ) from exc
                comment_id = item["comment_id"]
                if comment_id in seen:
                    continue
                seen.add(comment_id)
                replies.append(item)
                if len(replies) >= limit:
                    break
            next_cursor = self._browser_next_cursor(container)
            page_has_more, present = self._browser_has_more(
                _mapping(container),
                operation="comment-replies",
            )
            if not present:
                page_has_more = bool(raw_items) and bool(next_cursor)
            if page_has_more and (
                not next_cursor
                or next_cursor == cursor
                or len(replies) == before
            ):
                raise XiaohongshuResponseError(
                    "comment-replies 分页游标没有前进"
                )
            cursor = next_cursor
            has_more = page_has_more

        result["replies"] = replies
        result["reply_count"] = len(replies)
        result["reply_cursor"] = cursor
        result["reply_has_more"] = has_more
        return result

    @classmethod
    def _normalize_comment(
        cls,
        value: Any,
        *,
        include_nested: bool,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError("评论条目必须是对象")
        comment_id = _first_text(
            value.get("id"),
            value.get("comment_id"),
            value.get("commentId"),
        )
        if (
            not comment_id
            or len(comment_id) > 128
            or any(character in comment_id for character in "\r\n\0")
        ):
            raise XiaohongshuResponseError("评论条目缺少有效 comment_id")
        raw_user = _mapping(
            _first_present(value, "user_info", "userInfo", "user")
        )
        user_id = _first_text(
            raw_user.get("user_id"),
            raw_user.get("userId"),
            raw_user.get("id"),
        )
        pictures: list[str] = []
        for raw_picture in _list(
            _first_present(value, "pictures", "image_list", "imageList")
        ):
            picture = _mapping(raw_picture)
            url = _secure_url(
                _first_present(
                    picture,
                    "url_default",
                    "urlDefault",
                    "url",
                    "original",
                )
            )
            if url:
                pictures.append(url)
        tags: list[str] = []
        for raw_tag in _list(
            _first_present(value, "show_tags", "showTags", "tags")
        ):
            if isinstance(raw_tag, str):
                text = raw_tag.strip()
            else:
                tag = _mapping(raw_tag)
                text = _first_text(
                    tag.get("name"),
                    tag.get("title"),
                    tag.get("text"),
                    tag.get("type"),
                )
            if text:
                tags.append(text)
        raw_replies = (
            _list(
                _first_present(
                    value,
                    "sub_comments",
                    "subComments",
                    "replies",
                )
            )
            if include_nested
            else []
        )
        replies = [
            cls._normalize_comment(item, include_nested=False)
            for item in raw_replies
        ]
        target = _mapping(
            _first_present(value, "target_comment", "targetComment")
        )
        timestamp = _timestamp(
            _first_present(value, "create_time", "createTime", "time")
        )
        return {
            "kind": "comment",
            "comment_id": comment_id,
            "content": _first_text(
                value.get("content"),
                value.get("text"),
            ),
            "like_count": _count(
                _first_present(value, "like_count", "likeCount")
            ),
            "created_at": _timestamp_iso(timestamp),
            "created_timestamp": timestamp,
            "ip_location": _first_text(
                value.get("ip_location"),
                value.get("ipLocation"),
            ),
            "user": {
                "user_id": user_id,
                "nickname": _first_text(
                    raw_user.get("nickname"),
                    raw_user.get("nick_name"),
                    raw_user.get("nickName"),
                    raw_user.get("name"),
                ),
                "avatar": _secure_url(
                    _first_present(
                        raw_user,
                        "image",
                        "avatar",
                        "avatar_url",
                        "avatarUrl",
                    )
                ),
                "url": (
                    f"{_BASE_URL}/user/profile/{user_id}"
                    if _USER_ID_RE.fullmatch(user_id)
                    else ""
                ),
            },
            "pictures": pictures,
            "tags": tags,
            "target_comment": (
                {
                    "comment_id": _first_text(
                        target.get("id"),
                        target.get("comment_id"),
                        target.get("commentId"),
                    ),
                    "content": _first_text(
                        target.get("content"),
                        target.get("text"),
                    ),
                }
                if target
                else None
            ),
            "sub_comment_count": _count(
                _first_present(
                    value,
                    "sub_comment_count",
                    "subCommentCount",
                )
            ),
            "replies": replies,
            "reply_count": len(replies),
            "reply_cursor": _first_text(
                value.get("sub_comment_cursor"),
                value.get("subCommentCursor"),
            ),
            "reply_has_more": bool(
                cls._strict_browser_bool(
                    _first_present(
                        value,
                        "sub_comment_has_more",
                        "subCommentHasMore",
                    )
                )
            ),
        }

    @staticmethod
    def _normalize_filter_group(
        value: Any,
        *,
        index: int,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError(
                f"search-filters items[{index}] 必须是对象"
            )
        raw_options = _list(
            _first_present(
                value,
                "filters",
                "options",
                "items",
                "values",
                "children",
            )
        )
        options: list[dict[str, Any]] = []
        for option_index, raw_option in enumerate(raw_options):
            if isinstance(raw_option, str):
                option = {"name": raw_option}
            elif isinstance(raw_option, Mapping):
                option = raw_option
            else:
                raise XiaohongshuResponseError(
                    "search-filters "
                    f"items[{index}].options[{option_index}] 必须是对象或字符串"
                )
            name = _first_text(
                option.get("name"),
                option.get("title"),
                option.get("text"),
                option.get("label"),
            )
            options.append(
                {
                    "id": _first_text(
                        option.get("id"),
                        option.get("value"),
                        option.get("filter_id"),
                        option.get("filterId"),
                    ),
                    "name": name,
                    "value": _first_present(
                        option,
                        "value",
                        "filter_value",
                        "filterValue",
                    ),
                    "selected": bool(
                        _first_present(
                            option,
                            "selected",
                            "is_selected",
                            "isSelected",
                        )
                    ),
                }
            )
        return {
            "id": _first_text(
                value.get("id"),
                value.get("filter_id"),
                value.get("filterId"),
                str(index),
            ),
            "name": _first_text(
                value.get("name"),
                value.get("title"),
                value.get("text"),
                value.get("label"),
            ),
            "type": _first_text(
                value.get("type"),
                value.get("filter_type"),
                value.get("filterType"),
            ),
            "options": options,
        }

    @staticmethod
    def _normalize_related_search(
        value: Any,
        *,
        index: int,
    ) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError(
                f"note-related-searches items[{index}] 必须是对象"
            )
        model = _mapping(value.get("model"))
        business_type = _first_text(
            value.get("biz_type"),
            value.get("bizType"),
            model.get("biz_type"),
            model.get("bizType"),
        )
        if business_type and business_type != "video_related_search":
            return None
        link = _secure_url(
            _first_text(
                model.get("link"),
                value.get("link"),
                value.get("url"),
            )
        )
        query = ""
        if link:
            parsed_query = parse_qs(urlsplit(link).query)
            query = _first_text(
                *(parsed_query.get("keyword") or []),
                *(parsed_query.get("query") or []),
                *(parsed_query.get("search_word") or []),
            )
        extra = _mapping(
            _first_present(model, "biz_extra", "bizExtra")
        )
        title = _first_text(model.get("title"), value.get("title"))
        subtitle = _first_text(
            model.get("sub_title"),
            model.get("subTitle"),
            value.get("sub_title"),
            value.get("subTitle"),
        )
        text = query or subtitle or title
        if not text and not link:
            return None
        return {
            "id": _first_text(
                extra.get("word_request_id"),
                extra.get("wordRequestId"),
                value.get("id"),
                link,
                text,
            ),
            "text": text,
            "title": title,
            "subtitle": subtitle,
            "url": link,
            "biz_type": business_type or "video_related_search",
            "word_request_id": _first_text(
                extra.get("word_request_id"),
                extra.get("wordRequestId"),
            ),
        }

    def _collect_search(
        self,
        *,
        operation: str,
        path: str,
        kind: str,
        source: str,
        fields: Sequence[str],
        keyword: str,
        limit: int,
        page_size: int,
        page: int,
        search_id: str,
        extra_entries: Sequence[tuple[str, str]] = (),
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        current_page = page
        has_more = limit > 0
        stale_pages = 0

        while has_more and len(items) < limit:
            entries = [
                ("keyword", keyword),
                ("page", str(current_page)),
                ("page_size", str(page_size)),
                ("search_id", search_id),
                *extra_entries,
            ]
            payload = self._browser_request(path, entries)
            container = self._browser_envelope(payload, fields)
            if not isinstance(container, Mapping):
                raise XiaohongshuResponseError(
                    f"{operation} 响应的列表容器必须是对象"
                )
            raw_items = self._browser_items(
                container,
                fields,
                allow_missing=operation == "search-notes",
                operation=operation,
            )
            page_has_more, present = self._browser_has_more(
                container,
                operation=operation,
            )
            if not present:
                if operation == "search-notes":
                    page_has_more = False
                else:
                    raise XiaohongshuResponseError(
                        f"{operation} 响应缺少 has_more"
                    )

            before = len(items)
            self._append_search_items(
                items,
                seen,
                raw_items,
                operation=operation,
                limit=limit,
            )
            if page_has_more and len(items) == before:
                stale_pages += 1
                if stale_pages >= _SEARCH_MAX_STALE_PAGES:
                    raise XiaohongshuResponseError(
                        f"{operation} 连续 {_SEARCH_MAX_STALE_PAGES} 页没有新增条目"
                    )
            else:
                stale_pages = 0
            has_more = page_has_more
            current_page += 1
            if (
                has_more
                and len(items) < limit
                and current_page > 10_000
            ):
                raise XiaohongshuResponseError(
                    f"{operation} 下一页超过接口允许的最大页码"
                )

        return {
            "kind": kind,
            "result_type": kind,
            "source": source,
            "platform": "xiaohongshu",
            "transport": "browser_web",
            "keyword": keyword,
            "items": items,
            "count": len(items),
            "page": page,
            "next_page": current_page,
            "search_id": search_id,
            "has_more": has_more,
        }

    def _collect_single_search(
        self,
        *,
        operation: str,
        path: str,
        kind: str,
        source: str,
        fields: Sequence[str],
        limit: int,
        entries: Sequence[tuple[str, str]] = (),
        keyword: str | None = None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if limit:
            payload = self._browser_request(path, entries)
            container = self._browser_envelope(payload, fields)
            raw_items = self._browser_items(
                container,
                fields,
                allow_missing=False,
                operation=operation,
            )
            self._append_search_items(
                items,
                set(),
                raw_items,
                operation=operation,
                limit=limit,
            )
        result: dict[str, Any] = {
            "kind": kind,
            "result_type": kind,
            "source": source,
            "platform": "xiaohongshu",
            "transport": "browser_web",
            "items": items,
            "count": len(items),
        }
        if keyword is not None:
            result["keyword"] = keyword
        return result

    def _browser_request(
        self,
        path: str,
        entries: Sequence[tuple[str, str]],
        *,
        referer: str = _SEARCH_REFERER,
    ) -> Mapping[str, Any]:
        if self.browser_fetch is None:
            raise XiaohongshuInputError(
                "小红书登录态数据需要 Chrome 浏览器桥接"
            )
        payload = self.browser_fetch(path, entries, referer)
        if not isinstance(payload, Mapping) or not payload:
            raise XiaohongshuResponseError("小红书浏览器 API 响应为空")
        return payload

    @classmethod
    def _browser_envelope(
        cls,
        payload: Mapping[str, Any],
        fields: Sequence[str],
    ) -> Any:
        value: Any = payload
        for depth in range(_BROWSER_ENVELOPE_DEPTH + 2):
            if not isinstance(value, Mapping):
                return value
            cls._validate_browser_status(value)
            if any(field in value for field in fields):
                return value
            if "data" not in value or value["data"] is None:
                return value
            if depth >= _BROWSER_ENVELOPE_DEPTH:
                raise XiaohongshuResponseError(
                    "小红书浏览器 API 响应 data envelope 层级过深"
                )
            value = value["data"]
        raise XiaohongshuResponseError(
            "小红书浏览器 API 响应 data envelope 层级过深"
        )

    @staticmethod
    def _validate_browser_status(payload: Mapping[str, Any]) -> None:
        if "success" in payload:
            success = payload["success"]
            if not isinstance(success, bool):
                raise XiaohongshuResponseError(
                    "小红书浏览器 API 响应 success 必须是布尔值"
                )
            if not success:
                raise XiaohongshuResponseError(
                    "小红书浏览器 API 错误: "
                    f"{XiaohongshuClient._browser_message(payload, 'success=false')}"
                )
        if "code" in payload:
            code = payload["code"]
            valid_integer = (
                isinstance(code, int)
                and not isinstance(code, bool)
            ) or (
                isinstance(code, float)
                and math.isfinite(code)
                and code.is_integer()
            )
            if not valid_integer:
                raise XiaohongshuResponseError(
                    "小红书浏览器 API 响应 code 必须是整数"
                )
            if int(code) != 0:
                raise XiaohongshuResponseError(
                    "小红书浏览器 API 错误: "
                    f"{XiaohongshuClient._browser_message(payload, f'code={int(code)}')}"
                )

    @staticmethod
    def _browser_message(
        payload: Mapping[str, Any],
        fallback: str,
    ) -> str:
        return _first_text(payload.get("msg"), payload.get("message")) or fallback

    @staticmethod
    def _browser_items(
        value: Any,
        fields: Sequence[str],
        *,
        allow_missing: bool,
        operation: str,
    ) -> list[Any]:
        if isinstance(value, list):
            return value
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError(
                f"{operation} 列表响应必须是对象或数组"
            )
        for field in fields:
            if field not in value:
                continue
            raw_items = value[field]
            if not isinstance(raw_items, list):
                raise XiaohongshuResponseError(
                    f"{operation} 响应 {field} 必须是数组"
                )
            return raw_items
        if allow_missing:
            return []
        raise XiaohongshuResponseError(
            f"{operation} 响应缺少列表字段 {'/'.join(fields)}"
        )

    @classmethod
    def _browser_has_more(
        cls,
        value: Mapping[str, Any],
        *,
        operation: str,
    ) -> tuple[bool, bool]:
        for field in ("has_more", "hasMore"):
            if field not in value:
                continue
            parsed = cls._strict_browser_bool(value[field])
            if parsed is None:
                raise XiaohongshuResponseError(
                    f"{operation} 响应 {field} 必须是布尔值或 0/1"
                )
            return parsed, True
        return False, False

    @staticmethod
    def _strict_browser_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value in (0, 1):
                return bool(value)
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1"}:
                return True
            if normalized in {"false", "0"}:
                return False
        return None

    @classmethod
    def _append_search_items(
        cls,
        destination: list[dict[str, Any]],
        seen: set[str],
        raw_items: Sequence[Any],
        *,
        operation: str,
        limit: int,
    ) -> None:
        for index, raw in enumerate(raw_items):
            if len(destination) >= limit:
                break
            if operation == "search-notes" and cls._skip_search_note(raw):
                continue
            try:
                if operation == "search-notes":
                    item = cls._normalize_search_note(raw)
                elif operation == "search-users":
                    item = cls._normalize_search_user(raw)
                elif operation == "hot-list":
                    item = cls._normalize_hot_item(raw)
                    if not item["rank"]:
                        item["rank"] = index + 1
                elif operation == "search-suggest":
                    item = cls._normalize_suggestion(raw)
                else:
                    raise XiaohongshuResponseError(
                        f"{operation} 没有响应归一化器"
                    )
            except XiaohongshuResponseError as exc:
                raise XiaohongshuResponseError(
                    f"{operation} items[{index}] 非法: {exc}"
                ) from exc
            identity = _first_text(
                item.get("id"),
                item.get("note_id"),
                item.get("user_id"),
                item.get("text"),
            )
            if not identity:
                raise XiaohongshuResponseError(
                    f"{operation} items[{index}] 缺少稳定 ID"
                )
            if identity in seen:
                continue
            seen.add(identity)
            destination.append(item)

    @staticmethod
    def _skip_search_note(value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        field = (
            "model_type"
            if "model_type" in value
            else "modelType" if "modelType" in value else ""
        )
        if not field:
            return False
        model_type = value[field]
        if (
            not isinstance(model_type, str)
            or not model_type
            or model_type != model_type.strip()
        ):
            raise XiaohongshuResponseError(
                "modelType 必须是非空字符串"
            )
        if model_type == "note":
            return False
        if model_type in _SEARCH_AUXILIARY_MODELS:
            return True
        raise XiaohongshuResponseError(
            f"未知 modelType {model_type!r}"
        )

    @classmethod
    def _normalize_search_note(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError("笔记条目必须是对象")
        card = _mapping(_first_present(value, "note_card", "noteCard"))
        if not card:
            card = value
        note_id = _first_text(
            card.get("note_id"),
            card.get("noteId"),
            card.get("id"),
            value.get("id"),
        ).lower()
        if not _NOTE_ID_RE.fullmatch(note_id):
            raise XiaohongshuResponseError(
                "note_id 必须是 24 位十六进制 ID"
            )
        raw_user = _mapping(
            _first_present(card, "user", "user_info", "userInfo")
        )
        user_id = _first_text(
            raw_user.get("user_id"),
            raw_user.get("userId"),
            raw_user.get("id"),
        ).lower()
        author = {
            "id": user_id,
            "user_id": user_id,
            "nickname": _first_text(
                raw_user.get("nickname"),
                raw_user.get("nick_name"),
                raw_user.get("nickName"),
                raw_user.get("name"),
            ),
            "avatar": _secure_url(
                _first_present(
                    raw_user,
                    "image",
                    "avatar",
                    "avatar_url",
                    "avatarUrl",
                )
            ),
        }
        cover = _mapping(card.get("cover"))
        interaction = _mapping(
            _first_present(card, "interact_info", "interactInfo")
        )
        return {
            "kind": "note",
            "result_type": "note",
            "id": note_id,
            "note_id": note_id,
            "url": f"{_BASE_URL}/explore/{note_id}",
            "title": _first_text(
                card.get("display_title"),
                card.get("displayTitle"),
                card.get("title"),
            ),
            "description": _first_text(
                card.get("desc"),
                card.get("description"),
            ),
            "type": _first_text(
                card.get("type"),
                value.get("model_type"),
                value.get("modelType"),
            ),
            "author": author,
            "cover": _secure_url(
                _first_present(cover, "url_default", "urlDefault", "url")
            ),
            "like_count": _count(
                _first_present(interaction, "liked_count", "likedCount")
            ),
            "collect_count": _count(
                _first_present(
                    interaction,
                    "collected_count",
                    "collectedCount",
                )
            ),
            "comment_count": _count(
                _first_present(interaction, "comment_count", "commentCount")
            ),
            "share_count": _count(
                _first_present(
                    interaction,
                    "share_count",
                    "shareCount",
                    "shared_count",
                    "sharedCount",
                )
            ),
        }

    @staticmethod
    def _normalize_search_user(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError("用户条目必须是对象")
        raw = _mapping(
            _first_present(value, "user", "user_info", "userInfo")
        )
        if not raw:
            raw = value
        user_id = _first_text(
            raw.get("user_id"),
            raw.get("userId"),
            raw.get("id"),
        ).lower()
        if not _USER_ID_RE.fullmatch(user_id):
            raise XiaohongshuResponseError(
                "user_id 必须是 24 位十六进制 ID"
            )
        return {
            "kind": "user",
            "result_type": "user",
            "id": user_id,
            "user_id": user_id,
            "url": f"{_BASE_URL}/user/profile/{user_id}",
            "nickname": _first_text(
                raw.get("nickname"),
                raw.get("nick_name"),
                raw.get("nickName"),
                raw.get("name"),
            ),
            "avatar": _secure_url(
                _first_present(
                    raw,
                    "image",
                    "avatar",
                    "avatar_url",
                    "avatarUrl",
                )
            ),
            "red_id": _first_text(raw.get("red_id"), raw.get("redId")),
            "description": _first_text(
                raw.get("desc"),
                raw.get("description"),
                raw.get("sub_title"),
                raw.get("subTitle"),
                raw.get("reason"),
            ),
            "followers": _count(
                _first_present(
                    raw,
                    "fans",
                    "followers",
                    "fans_count",
                    "fansCount",
                )
            ),
            "note_count": _count(
                _first_present(raw, "note_count", "noteCount")
            ),
        }

    @staticmethod
    def _normalize_hot_item(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError("热榜条目必须是对象")
        search_word = _first_text(
            value.get("search_word"),
            value.get("searchWord"),
            value.get("query"),
            value.get("word"),
            value.get("title"),
        )
        title = _first_text(
            value.get("title"),
            value.get("name"),
            value.get("text"),
            search_word,
        )
        if not title:
            raise XiaohongshuResponseError("热榜条目缺少标题")
        identity = _first_text(
            value.get("id"),
            value.get("query_id"),
            value.get("queryId"),
            search_word,
            title,
        )
        return {
            "kind": "hot_item",
            "result_type": "hot_item",
            "id": identity,
            "title": title,
            "search_word": search_word,
            "type": _first_text(
                value.get("type"),
                value.get("word_type"),
                value.get("wordType"),
            ),
            "display_type": _first_text(
                value.get("display_type"),
                value.get("displayType"),
            ),
            "rank": _count(_first_present(value, "rank", "position")),
            "hot_value": _count(
                _first_present(value, "hot_value", "hotValue", "score")
            ),
            "trend": _first_text(value.get("trend"), value.get("icon")),
            "url": _secure_url(
                _first_text(value.get("url"), value.get("link"))
            ),
        }

    @staticmethod
    def _normalize_suggestion(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise XiaohongshuResponseError("联想词为空")
            return {
                "kind": "suggestion",
                "result_type": "suggestion",
                "id": text,
                "text": text,
            }
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError(
                "联想词条目必须是字符串或对象"
            )
        text = _first_text(
            value.get("text"),
            value.get("title"),
            value.get("keyword"),
            value.get("query"),
        )
        if not text:
            raise XiaohongshuResponseError("联想词为空")
        return {
            "kind": "suggestion",
            "result_type": "suggestion",
            "id": _first_text(value.get("id"), text),
            "text": text,
            "type": _first_text(
                value.get("type"),
                value.get("display_type"),
                value.get("displayType"),
            ),
        }

    @staticmethod
    def _search_text(value: Any, *, allow_empty: bool) -> str:
        if not isinstance(value, str):
            raise XiaohongshuInputError("搜索关键词必须是字符串")
        keyword = value.strip()
        if not keyword and not allow_empty:
            raise XiaohongshuInputError("搜索关键词不能为空")
        if len(keyword) > 200 or any(
            character in keyword for character in "\r\n\0"
        ):
            raise XiaohongshuInputError(
                "搜索关键词必须不超过 200 个字符且不含控制字符"
            )
        return keyword

    @staticmethod
    def _browser_cursor(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise XiaohongshuInputError("cursor 必须是字符串或整数")
        cursor = str(value).strip()
        if (
            len(cursor) > 1024
            or any(character in cursor for character in "\r\n\0")
        ):
            raise XiaohongshuInputError(
                "cursor 必须不超过 1024 个字符且不含控制字符"
            )
        return cursor

    @staticmethod
    def _browser_next_cursor(value: Any) -> str:
        if not isinstance(value, Mapping):
            return ""
        return _first_text(
            value.get("cursor"),
            value.get("next_cursor"),
            value.get("nextCursor"),
        )

    @staticmethod
    def _context_referer(
        page_url: str,
        token: Any,
        source: Any,
        *,
        default_source: str,
    ) -> str:
        query: dict[str, str] = {}
        if token:
            query["xsec_token"] = str(token)
            query["xsec_source"] = str(source or default_source)
        return f"{page_url}?{urlencode(query)}" if query else page_url

    @staticmethod
    def _search_limit(value: Any) -> int:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= _SEARCH_MAX_ITEMS
        ):
            raise XiaohongshuInputError(
                f"limit 必须在 0 到 {_SEARCH_MAX_ITEMS} 之间"
            )
        return value

    @staticmethod
    def _search_page_size(value: Any, *, maximum: int) -> int:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= maximum
        ):
            raise XiaohongshuInputError(
                f"page_size 必须在 1 到 {maximum} 之间"
            )
        return value

    @staticmethod
    def _search_page(value: Any) -> int:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= 10_000
        ):
            raise XiaohongshuInputError(
                "page 必须在 1 到 10000 之间"
            )
        return value

    @staticmethod
    def _search_id(value: Any) -> str:
        if value is None or value == "":
            number = (time.time_ns() // 1_000_000) << 64
            number += secrets.randbits(31)
            alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
            encoded = ""
            while number:
                number, remainder = divmod(number, 36)
                encoded = alphabet[remainder] + encoded
            return encoded
        if not isinstance(value, str):
            raise XiaohongshuInputError("search_id 必须是字符串")
        normalized = value.strip()
        if not _SEARCH_ID_RE.fullmatch(normalized):
            raise XiaohongshuInputError(
                "search_id 必须为 8 到 128 位字母、数字、下划线或连字符"
            )
        return normalized

    def get_pgy_good_case_classes(self) -> dict[str, Any]:
        """读取蒲公英首页优质案例的行业分类。"""
        return self._pgy_request(
            kind="pgy_good_case_classes",
            operation="good_case_classes",
            path=_PGY_GOOD_CASE_CLASSES_PATH,
            entries=[],
        )

    def get_pgy_good_notes(self, category: str) -> dict[str, Any]:
        """读取蒲公英首页固定展示的优质笔记案例。"""
        normalized = self._pgy_category(category)
        return self._pgy_request(
            kind="pgy_good_notes",
            operation="good_notes",
            path=_PGY_GOOD_NOTES_PATH,
            entries=[("category", normalized)],
            metadata={
                "category": normalized,
                "page": 1,
                "page_size": 6,
            },
        )

    def get_pgy_good_lives(self, category: str) -> dict[str, Any]:
        """读取蒲公英首页固定展示的优质直播案例。"""
        normalized = self._pgy_category(category)
        return self._pgy_request(
            kind="pgy_good_lives",
            operation="good_lives",
            path=_PGY_GOOD_LIVES_PATH,
            entries=[("category", normalized)],
            metadata={
                "category": normalized,
                "page": 1,
                "page_size": 6,
            },
        )

    def get_pgy_top_bloggers(self, *, rank_type: int = 6) -> dict[str, Any]:
        """读取蒲公英首页固定展示的达人榜。"""
        if (
            not isinstance(rank_type, int)
            or isinstance(rank_type, bool)
            or not 0 <= rank_type <= 9999
        ):
            raise XiaohongshuInputError("rank_type 必须在 0 到 9999 之间")
        return self._pgy_request(
            kind="pgy_top_bloggers",
            operation="top_bloggers",
            path=_PGY_TOP_BLOGGERS_PATH,
            entries=[("rank_type", str(rank_type))],
            metadata={
                "rank_type": rank_type,
                "page": 1,
                "page_size": 3,
            },
        )

    def get_pgy_industries(self) -> dict[str, Any]:
        """读取蒲公英首页商业行业数据。"""
        return self._pgy_request(
            kind="pgy_industries",
            operation="industries",
            path=_PGY_INDUSTRIES_PATH,
            entries=[],
        )

    def _pgy_request(
        self,
        *,
        kind: str,
        operation: str,
        path: str,
        entries: Sequence[tuple[str, str]],
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.pgy_fetch is None:
            raise XiaohongshuInputError("蒲公英商业数据需要 Chrome 浏览器桥接")
        payload = self.pgy_fetch(path, entries, _PGY_REFERER)
        if not isinstance(payload, Mapping) or not payload:
            raise XiaohongshuResponseError(
                f"小红书蒲公英 {operation} 响应为空"
            )
        for name in ("success",):
            if name not in payload:
                continue
            success = payload[name]
            if not isinstance(success, bool):
                raise XiaohongshuResponseError(
                    f"小红书蒲公英 {operation} 响应 success 必须是布尔值"
                )
            if not success:
                raise XiaohongshuResponseError(
                    f"小红书蒲公英 {operation} API 错误: "
                    f"{self._pgy_message(payload)}"
                )
        for name in ("code", "err_code", "error_code", "result_code"):
            if name not in payload:
                continue
            code = payload[name]
            if (
                not isinstance(code, int)
                or isinstance(code, bool)
            ):
                raise XiaohongshuResponseError(
                    f"小红书蒲公英 {operation} 响应 {name} 必须是整数"
                )
            if code not in {0, 200}:
                raise XiaohongshuResponseError(
                    f"小红书蒲公英 {operation} API 错误: "
                    f"{self._pgy_message(payload, fallback=f'{name}={code}')}"
                )
        if "data" in payload and not isinstance(payload["data"], (Mapping, list)):
            raise XiaohongshuResponseError(
                f"小红书蒲公英 {operation} 响应 data 必须是对象或数组"
            )
        result = {
            "kind": kind,
            "source": "xiaohongshu_pgy",
            "platform": "xiaohongshu_pgy",
            "transport": "browser_web",
            "operation": operation,
            "endpoint": path,
            "payload": dict(payload),
        }
        result.update(dict(metadata or {}))
        return result

    @staticmethod
    def _pgy_category(value: str) -> str:
        category = str(value)
        if (
            category != category.strip()
            or not category
            or len(category) > 64
            or any(character in category for character in "\r\n\0")
        ):
            raise XiaohongshuInputError("category 必须为 1 到 64 个字符")
        return category

    @staticmethod
    def _pgy_message(
        payload: Mapping[str, Any],
        *,
        fallback: str = "请求失败",
    ) -> str:
        for name in ("msg", "message"):
            value = str(payload.get(name) or "").strip()
            if value:
                return value
        return fallback

    @classmethod
    def parse_note_html(
        cls,
        source: str,
        *,
        expected_note_id: str | None = None,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
        source_url: str = "",
    ) -> dict[str, Any]:
        state = cls.extract_initial_state(source)
        note_store = _mapping(state.get("note"))
        detail_map = _mapping(note_store.get("noteDetailMap"))
        note_id = str(expected_note_id or note_store.get("currentNoteId") or "").lower()
        entry: Mapping[str, Any] = {}
        if note_id:
            entry = _mapping(detail_map.get(note_id))
        if not entry and detail_map:
            note_id, value = next(iter(detail_map.items()))
            note_id = str(note_id).lower()
            entry = _mapping(value)
        raw_note = _mapping(entry.get("note")) if "note" in entry else entry
        if not raw_note:
            request_info = _mapping(note_store.get("serverRequestInfo"))
            message = str(request_info.get("errMsg") or "").strip()
            suffix = f": {message}" if message else ""
            raise XiaohongshuResponseError(
                "Xiaohongshu SSR does not expose public note data; "
                f"the xsec_token may be missing or expired{suffix}"
            )
        actual_id = str(raw_note.get("noteId") or note_id).lower()
        if not _NOTE_ID_RE.fullmatch(actual_id):
            raise XiaohongshuResponseError("Xiaohongshu SSR contains an invalid note id")
        if expected_note_id and actual_id != expected_note_id.lower():
            raise XiaohongshuResponseError(
                f"Xiaohongshu SSR returned note {actual_id}, expected {expected_note_id.lower()}"
            )
        return cls._normalize_note(
            raw_note,
            note_id=actual_id,
            xsec_token=xsec_token,
            xsec_source=xsec_source,
            source_url=source_url,
        )

    @classmethod
    def parse_profile_html(
        cls,
        source: str,
        *,
        expected_user_id: str,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        state = cls.extract_initial_state(source)
        page_data = _mapping(_mapping(state.get("user")).get("userPageData"))
        result = _mapping(page_data.get("result"))
        basic = _mapping(page_data.get("basicInfo"))
        if result and not bool(result.get("success", result.get("code") == 0)):
            message = str(result.get("message") or result.get("msg") or "request failed")
            raise XiaohongshuResponseError(f"Xiaohongshu profile response failed: {message}")
        if not basic:
            raise XiaohongshuResponseError(
                "Xiaohongshu SSR does not expose public profile data"
            )

        counters: dict[str, int] = {}
        counter_text: dict[str, str] = {}
        for item in _list(page_data.get("interactions")):
            interaction = _mapping(item)
            kind = str(interaction.get("type") or interaction.get("name") or "").strip()
            if not kind:
                continue
            source_count = str(interaction.get("count") or "")
            counters[kind] = _count(source_count)
            counter_text[kind] = source_count

        tags: list[dict[str, str]] = []
        for item in _list(page_data.get("tags")):
            tag = _mapping(item)
            tags.append(
                {
                    "type": str(tag.get("tagType") or tag.get("type") or ""),
                    "name": str(tag.get("name") or ""),
                    "icon": _secure_url(tag.get("icon")),
                }
            )
        user_id = expected_user_id.lower()
        token = str(xsec_token or "") or None
        source_name = str(xsec_source or "") or None
        profile_url = f"{_BASE_URL}/user/profile/{user_id}"
        return {
            "id": user_id,
            "user_id": user_id,
            "url": profile_url,
            "xsec_token": token,
            "xsec_source": source_name,
            "nickname": str(basic.get("nickname") or ""),
            "red_id": str(basic.get("redId") or ""),
            "description": str(basic.get("desc") or ""),
            "avatar": _secure_url(basic.get("images") or basic.get("imageb")),
            "avatar_large": _secure_url(basic.get("imageb") or basic.get("images")),
            "gender": basic.get("gender"),
            "location": str(basic.get("ipLocation") or ""),
            "following": counters.get("follows", 0),
            "followers": counters.get("fans", 0),
            "likes_and_collections": counters.get("interaction", 0),
            "counters": counters,
            "counter_text": counter_text,
            "tags": tags,
            "tab_public": dict(_mapping(page_data.get("tabPublic"))),
        }

    @staticmethod
    def extract_initial_state(source: str) -> dict[str, Any]:
        if not isinstance(source, str) or not source:
            raise XiaohongshuResponseError("Xiaohongshu HTML is empty")
        match = _INITIAL_STATE_RE.search(source)
        if not match:
            raise XiaohongshuResponseError(
                "Xiaohongshu HTML does not contain window.__INITIAL_STATE__"
            )
        start = source.find("{", match.end())
        if start < 0:
            raise XiaohongshuResponseError("Xiaohongshu initial state has no object")
        raw = XiaohongshuClient._balanced_object(source, start)
        sanitized = XiaohongshuClient._replace_javascript_literals(raw)
        try:
            value = json.loads(sanitized)
        except json.JSONDecodeError as exc:
            raise XiaohongshuResponseError(
                f"Xiaohongshu initial state is malformed at offset {exc.pos}"
            ) from exc
        if not isinstance(value, Mapping):
            raise XiaohongshuResponseError("Xiaohongshu initial state is not an object")
        return dict(value)

    @classmethod
    def resolve_profile_reference(
        cls,
        profile_url_or_user_id: str,
        *,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict[str, Any]:
        value = cls._reference_text(profile_url_or_user_id)
        token_override = cls._token(xsec_token) if xsec_token is not None else None
        source_override = cls._source(xsec_source) if xsec_source is not None else None
        if _USER_ID_RE.fullmatch(value):
            user_id = value.lower()
            return {
                "user_id": user_id,
                "xsec_token": token_override,
                "xsec_source": source_override,
                "page_url": f"{_BASE_URL}/user/profile/{user_id}",
            }
        candidate = cls._candidate_url(value)
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in _XIAOHONGSHU_HOSTS:
            raise XiaohongshuInputError("profile URL must use xiaohongshu.com")
        path_match = _PROFILE_PATH_RE.match(parsed.path)
        if not path_match:
            raise XiaohongshuInputError("URL is not a Xiaohongshu public profile URL")
        query = parse_qs(parsed.query)
        token = token_override or cls._token((query.get("xsec_token") or [None])[0])
        source_name = source_override or cls._source((query.get("xsec_source") or [None])[0])
        user_id = path_match.group(1).lower()
        return {
            "user_id": user_id,
            "xsec_token": token,
            "xsec_source": source_name,
            "page_url": f"{_BASE_URL}/user/profile/{user_id}",
        }

    def _resolve_short_url(self, short_url: str) -> str:
        current = short_url
        seen: set[str] = set()
        for _ in range(6):
            if current in seen:
                raise XiaohongshuResponseError("Xiaohongshu short-link redirect loop")
            seen.add(current)
            response = self._request(
                current,
                params={},
                allow_redirects=False,
                accepted_status=_REDIRECT_STATUS | {200},
            )
            if response.status_code not in _REDIRECT_STATUS:
                direct = self._direct_note_parts(str(response.url or current))
                if direct:
                    return str(response.url or current)
                raise XiaohongshuResponseError(
                    "Xiaohongshu short link returned no note redirect"
                )
            location = str(response.headers.get("Location") or "").strip()
            if not location:
                raise XiaohongshuResponseError(
                    "Xiaohongshu short-link redirect has no Location header"
                )
            current = urljoin(current, location)
            parsed = urlsplit(current)
            host = (parsed.hostname or "").lower().rstrip(".")
            if host not in _SHORT_LINK_HOSTS | _XIAOHONGSHU_HOSTS:
                raise XiaohongshuResponseError(
                    "Xiaohongshu short link redirected to an unexpected host"
                )
            if self._direct_note_parts(current):
                return current
        raise XiaohongshuResponseError("Xiaohongshu short link exceeded redirect limit")

    def _request(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str] | None = None,
        allow_redirects: bool = True,
        accepted_status: set[int] | None = None,
    ) -> requests.Response:
        accepted = accepted_status or {200}
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=allow_redirects,
                )
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise XiaohongshuResponseError(
                        f"Xiaohongshu request failed: {exc}"
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code in accepted:
                return response
            if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            raise XiaohongshuResponseError(
                f"Xiaohongshu returned HTTP {response.status_code}"
            )
        raise XiaohongshuResponseError("Xiaohongshu request exhausted all retries")

    @staticmethod
    def _balanced_object(source: str, start: int) -> str:
        depth = 0
        inside_string = False
        escaped = False
        for index in range(start, len(source)):
            character = source[index]
            if inside_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    inside_string = False
                continue
            if character == '"':
                inside_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return source[start : index + 1]
                if depth < 0:
                    break
        raise XiaohongshuResponseError("Xiaohongshu initial state is truncated")

    @staticmethod
    def _replace_javascript_literals(source: str) -> str:
        replacements = {
            "undefined": "null",
            "NaN": "null",
            "Infinity": "null",
        }
        output: list[str] = []
        index = 0
        inside_string = False
        escaped = False
        while index < len(source):
            character = source[index]
            if inside_string:
                output.append(character)
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    inside_string = False
                index += 1
                continue
            if character == '"':
                inside_string = True
                output.append(character)
                index += 1
                continue
            if source.startswith("-Infinity", index):
                output.append("null")
                index += len("-Infinity")
                continue
            replaced = False
            for token, replacement in replacements.items():
                if not source.startswith(token, index):
                    continue
                before = source[index - 1] if index else ""
                after_offset = index + len(token)
                after = source[after_offset] if after_offset < len(source) else ""
                if (before and (before.isalnum() or before in "_$")) or (
                    after and (after.isalnum() or after in "_$")
                ):
                    continue
                output.append(replacement)
                index += len(token)
                replaced = True
                break
            if not replaced:
                output.append(character)
                index += 1
        return "".join(output)

    @classmethod
    def _normalize_note(
        cls,
        raw: Mapping[str, Any],
        *,
        note_id: str,
        xsec_token: str | None,
        xsec_source: str | None,
        source_url: str,
    ) -> dict[str, Any]:
        token = str(xsec_token or raw.get("xsecToken") or "") or None
        source_name = str(xsec_source or "") or None
        interaction = _mapping(raw.get("interactInfo"))
        like_text = str(interaction.get("likedCount") or "")
        collect_text = str(interaction.get("collectedCount") or "")
        comment_text = str(interaction.get("commentCount") or "")
        share_text = str(interaction.get("shareCount") or "")
        images = [
            cls._normalize_image(_mapping(item), index=index)
            for index, item in enumerate(_list(raw.get("imageList")))
            if isinstance(item, Mapping)
        ]
        tags = [
            {
                "id": str(_mapping(item).get("id") or ""),
                "name": str(_mapping(item).get("name") or ""),
                "type": str(_mapping(item).get("type") or ""),
            }
            for item in _list(raw.get("tagList"))
            if isinstance(item, Mapping)
        ]
        mentions = [
            {
                "id": str(
                    _mapping(item).get("userId")
                    or _mapping(item).get("id")
                    or ""
                ),
                "nickname": str(
                    _mapping(item).get("nickname")
                    or _mapping(item).get("nickName")
                    or ""
                ),
                "xsec_token": str(_mapping(item).get("xsecToken") or "") or None,
            }
            for item in _list(raw.get("atUserList"))
            if isinstance(item, Mapping)
        ]
        author = _mapping(raw.get("user"))
        author_id = str(author.get("userId") or author.get("id") or "")
        author_token = str(author.get("xsecToken") or "") or None
        published_timestamp = _timestamp(raw.get("time"))
        updated_timestamp = _timestamp(raw.get("lastUpdateTime"))
        canonical_url = f"{_BASE_URL}/explore/{note_id}"
        query: dict[str, str] = {}
        if token:
            query["xsec_token"] = token
            query["xsec_source"] = source_name or "pc_feed"
        fetch_url = f"{canonical_url}?{urlencode(query)}" if query else canonical_url
        return {
            "id": note_id,
            "note_id": note_id,
            "url": canonical_url,
            "fetch_url": fetch_url,
            "source_url": source_url or fetch_url,
            "xsec_token": token,
            "xsec_source": source_name,
            "type": str(raw.get("type") or "normal"),
            "title": str(raw.get("title") or ""),
            "description": str(raw.get("desc") or ""),
            "author": {
                "id": author_id,
                "nickname": str(author.get("nickname") or author.get("nickName") or ""),
                "avatar": _secure_url(author.get("avatar")),
                "xsec_token": author_token,
                "url": f"{_BASE_URL}/user/profile/{author_id}" if author_id else "",
            },
            "like_count": _count(like_text),
            "collect_count": _count(collect_text),
            "comment_count": _count(comment_text),
            "share_count": _count(share_text),
            "interaction_text": {
                "likes": like_text,
                "collections": collect_text,
                "comments": comment_text,
                "shares": share_text,
            },
            "viewer_state": {
                "liked": bool(interaction.get("liked")),
                "collected": bool(interaction.get("collected")),
                "followed": bool(interaction.get("followed")),
                "relation": str(interaction.get("relation") or ""),
            },
            "tags": tags,
            "mentions": mentions,
            "images": images,
            "is_live_photo": any(bool(image.get("live_photo")) for image in images),
            "video": cls._normalize_video(_mapping(raw.get("video"))),
            "published_at": _timestamp_iso(raw.get("time")),
            "published_timestamp": published_timestamp,
            "updated_at": _timestamp_iso(raw.get("lastUpdateTime")),
            "updated_timestamp": updated_timestamp,
            "shareable": not bool(_mapping(raw.get("shareInfo")).get("unShare")),
        }

    @classmethod
    def _normalize_image(cls, raw: Mapping[str, Any], *, index: int) -> dict[str, Any]:
        variants: list[dict[str, str]] = []
        for item in _list(raw.get("infoList") or raw.get("info_list")):
            variant = _mapping(item)
            url = _secure_url(variant.get("url"))
            if url:
                variants.append(
                    {
                        "scene": str(
                            variant.get("imageScene") or variant.get("image_scene") or ""
                        ),
                        "url": url,
                    }
                )
        default_url = _secure_url(
            raw.get("urlDefault") or raw.get("url_default") or raw.get("url")
        )
        preview_url = _secure_url(raw.get("urlPre") or raw.get("url_pre"))
        if not default_url:
            default_url = next(
                (item["url"] for item in variants if item["scene"] == "WB_DFT"),
                variants[0]["url"] if variants else "",
            )
        if not preview_url:
            preview_url = next(
                (item["url"] for item in variants if item["scene"] == "WB_PRV"),
                default_url,
            )
        return {
            "index": index,
            "file_id": str(raw.get("fileId") or raw.get("file_id") or ""),
            "url": default_url,
            "preview_url": preview_url,
            "width": _integer(raw.get("width")),
            "height": _integer(raw.get("height")),
            "live_photo": bool(raw.get("livePhoto") or raw.get("live_photo")),
            "variants": variants,
            "live_photo_streams": cls._normalize_streams(_mapping(raw.get("stream"))),
        }

    @classmethod
    def _normalize_video(cls, raw: Mapping[str, Any]) -> dict[str, Any] | None:
        if not raw:
            return None
        media = _mapping(raw.get("media"))
        if not media and isinstance(raw.get("mediaV2"), str):
            try:
                decoded = json.loads(str(raw["mediaV2"]))
            except (json.JSONDecodeError, TypeError):
                decoded = None
            media = _mapping(decoded)
        video_meta = _mapping(media.get("video"))
        streams = cls._normalize_streams(_mapping(media.get("stream")))
        capa = _mapping(raw.get("capa"))
        raw_duration = _number(video_meta.get("duration") or capa.get("duration"))
        duration_seconds = float(raw_duration)
        if duration_seconds > 1000:
            duration_seconds /= 1000
        if duration_seconds.is_integer():
            duration: int | float = int(duration_seconds)
        else:
            duration = duration_seconds
        width = _integer(video_meta.get("width"))
        height = _integer(video_meta.get("height"))
        if streams:
            width = width or _integer(streams[0].get("width"))
            height = height or _integer(streams[0].get("height"))
        image = _mapping(raw.get("image"))
        primary = next((item for item in streams if item.get("default")), None)
        primary = primary or (streams[0] if streams else {})
        return {
            "id": str(media.get("videoId") or media.get("video_id") or ""),
            "duration": duration,
            "width": width,
            "height": height,
            "url": str(_mapping(primary).get("url") or ""),
            "backup_urls": list(_mapping(primary).get("backup_urls") or []),
            "thumbnail_file_id": str(
                image.get("thumbnailFileid") or image.get("thumbnail_fileid") or ""
            ),
            "first_frame_file_id": str(
                image.get("firstFrameFileid") or image.get("first_frame_fileid") or ""
            ),
            "streams": streams,
        }

    @staticmethod
    def _normalize_streams(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        streams: list[dict[str, Any]] = []
        codecs = ["h264", "h265", "h266", "av1"]
        codecs.extend(key for key in raw if key not in codecs)
        for codec in codecs:
            for item in _list(raw.get(codec)):
                stream = _mapping(item)
                url = _secure_url(stream.get("masterUrl") or stream.get("master_url"))
                if not url:
                    continue
                duration_ms = _integer(
                    stream.get("videoDuration")
                    or stream.get("video_duration")
                    or stream.get("duration")
                )
                streams.append(
                    {
                        "codec": str(
                            stream.get("videoCodec")
                            or stream.get("video_codec")
                            or codec
                        ),
                        "format": str(stream.get("format") or "mp4"),
                        "url": url,
                        "backup_urls": [
                            _secure_url(value)
                            for value in _list(
                                stream.get("backupUrls") or stream.get("backup_urls")
                            )
                            if value
                        ],
                        "width": _integer(stream.get("width")),
                        "height": _integer(stream.get("height")),
                        "duration_ms": duration_ms,
                        "duration": duration_ms / 1000 if duration_ms else 0,
                        "fps": _number(stream.get("fps")),
                        "size": _integer(stream.get("size")),
                        "bitrate": _integer(
                            stream.get("avgBitrate") or stream.get("avg_bitrate")
                        ),
                        "quality": str(
                            stream.get("qualityType") or stream.get("quality_type") or ""
                        ),
                        "default": _integer(
                            stream.get("defaultStream") or stream.get("default_stream")
                        ) == 1,
                    }
                )
        return streams

    @classmethod
    def _direct_note_parts(
        cls, value: str
    ) -> tuple[str, str | None, str | None, str] | None:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in _XIAOHONGSHU_HOSTS:
            return None
        match = _DIRECT_NOTE_PATH_RE.match(parsed.path)
        if not match:
            return None
        query = parse_qs(parsed.query)
        token = cls._token((query.get("xsec_token") or [None])[0])
        source_name = cls._source((query.get("xsec_source") or [None])[0])
        page_url = urlunsplit(
            ("https", "www.xiaohongshu.com", parsed.path.rstrip("/"), "", "")
        )
        return match.group(1).lower(), token, source_name, page_url

    @staticmethod
    def _note_reference(
        note_id: str,
        token: str | None,
        source: str | None,
        *,
        page_url: str,
        source_url: str,
        short_url: str | None,
    ) -> dict[str, Any]:
        query: dict[str, str] = {}
        if token:
            query["xsec_token"] = token
            query["xsec_source"] = source or "pc_feed"
        fetch_url = f"{page_url}?{urlencode(query)}" if query else page_url
        return {
            "note_id": note_id,
            "xsec_token": token,
            "xsec_source": source,
            "page_url": page_url,
            "url": fetch_url,
            "source_url": source_url,
            "short_url": short_url,
        }

    @staticmethod
    def _reference_text(value: str) -> str:
        if not isinstance(value, str):
            raise XiaohongshuInputError("reference must be a string")
        normalized = value.strip()
        if not normalized:
            raise XiaohongshuInputError("reference is empty")
        return normalized

    @staticmethod
    def _candidate_url(value: str) -> str:
        match = _URL_RE.search(value)
        candidate = (match.group(0) if match else value).rstrip(_TRAILING_URL_PUNCTUATION)
        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        elif "://" not in candidate and candidate.lower().startswith(
            (
                "xiaohongshu.com/",
                "www.xiaohongshu.com/",
                "xhslink.com/",
                "www.xhslink.com/",
            )
        ):
            candidate = f"https://{candidate}"
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise XiaohongshuInputError("reference is not a valid Xiaohongshu URL or id")
        return candidate

    @staticmethod
    def _token(value: Any) -> str | None:
        if value in (None, ""):
            return None
        token = str(value).strip()
        if len(token) > 512 or not _TOKEN_RE.fullmatch(token):
            raise XiaohongshuInputError("xsec_token contains invalid characters")
        return token

    @staticmethod
    def _source(value: Any) -> str | None:
        if value in (None, ""):
            return None
        source = str(value).strip()
        if len(source) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", source):
            raise XiaohongshuInputError("xsec_source contains invalid characters")
        return source
