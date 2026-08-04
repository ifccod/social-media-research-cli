from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

from curl_cffi import requests

from .errors import WeiboInputError, WeiboResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
DEFAULT_CHANNEL_ID = "102803"

_BASE_URL = "https://m.weibo.cn"
_CONFIG_URL = f"{_BASE_URL}/api/config/list"
_VISITOR_HOST = "visitor.passport.weibo.cn"
_VISITOR_ORIGIN = f"https://{_VISITOR_HOST}"
_VISITOR_GENERATE_URL = f"{_VISITOR_ORIGIN}/visitor/genvisitor2"
_HOT_SEARCH_CONTAINER = "106003type=25&t=3&disable_hot=1&filter_type=realtimehot"
_ALLOWED_HOSTS = {"m.weibo.cn", _VISITOR_HOST}
_WEIBO_REFERENCE_HOSTS = {"m.weibo.cn", "weibo.cn"}
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_SEARCH_TYPES = {"1", "61", "3", "60", "64", "63", "21"}
_TIME_SCOPES = {"", "hour", "day", "week", "month"}
_ID_RE = re.compile(r"^[0-9]{1,20}$")
_POSITIVE_ID_RE = re.compile(r"^[0-9]{1,20}$")
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9_=&.-]{1,180}$")
_SEARCH_CONTAINER_RE = re.compile(
    r"^100103type=(?:1|61|3|60|64|63|21)&q=(?:[A-Za-z0-9_.~-]|%[0-9A-F]{2}){1,1200}$"
)
_REQUEST_ID_RE = re.compile(
    r"\bvar\s+request_id\s*=\s*(['\"])(?P<value>[0-9A-Fa-f]{16,64})\1\s*;?"
)
_VISITOR_CALLBACK = "visitor_gray_callback"


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
        result = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return int(result) if result.is_integer() else result


def _absolute_url(value: Any) -> str:
    raw = html.unescape(str(value or "").strip())
    if raw.startswith("//"):
        return f"https:{raw}"
    return raw


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        values = {str(name).lower(): str(value or "") for name, value in attrs}
        if lower in {"br", "p", "div", "li"}:
            self.parts.append("\n")
        elif lower == "img" and values.get("alt"):
            self.parts.append(values["alt"])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = [
            re.sub(r"[ \t\r\f\v]+", " ", line).strip()
            for line in "".join(self.parts).split("\n")
        ]
        return "\n".join(line for line in lines if line)


def _plain_text(value: Any) -> str:
    source = str(value or "")
    if not source:
        return ""
    parser = _HTMLTextParser()
    try:
        parser.feed(source.replace("\x00", ""))
        parser.close()
    except (TypeError, ValueError):
        return html.unescape(re.sub(r"<[^>]+>", "", source)).strip()
    return parser.text()


def _created_at_iso(value: Any) -> str | None:
    source = str(value or "").strip()
    if not source:
        return None
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(source)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.strptime(source, "%a %b %d %H:%M:%S %z %Y")
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.astimezone(timezone.utc).isoformat()


def _approximate_count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    source = str(value or "").strip().replace(",", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([万亿]?)", source)
    if not match:
        return _integer(source)
    multiplier = {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    return max(0, int(float(match.group(1)) * multiplier))


class WeiboClient:
    """使用纯 HTTP 访客会话读取 m.weibo.cn 公开数据。"""

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
        self._identity_ready = False
        self._visitor_tid = ""
        self._config: dict[str, Any] | None = None
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": user_agent,
            }
        )

    def initialize_session(self, *, force: bool = False) -> None:
        if self._identity_ready and not force:
            return
        response = self._request("GET", _CONFIG_URL, params={})
        payload = self._decode_json(response, "/api/config/list")
        data = self._api_data(payload, "config list")
        self._config = dict(data)
        self._identity_ready = True

    def get_config(self, *, force: bool = False) -> dict[str, Any]:
        self.initialize_session(force=force)
        raw = _mapping(self._config)
        channels: list[dict[str, Any]] = []
        for value in _list(raw.get("channel")):
            channel = _mapping(value)
            identifier = str(channel.get("gid") or "")
            name = str(channel.get("name") or "")
            if identifier and name:
                channels.append(
                    {
                        "id": identifier,
                        "name": name,
                        "type": str(channel.get("type") or ""),
                    }
                )
        hot = _mapping(raw.get("hot"))
        return {
            "channels": channels,
            "groups": [
                dict(item)
                for item in _list(raw.get("groups"))
                if isinstance(item, Mapping)
            ],
            "hot": {
                "keyword": str(hot.get("hotWord") or ""),
                "scheme": _absolute_url(hot.get("scheme")),
            },
        }

    def get_channel_feed(
        self,
        channel_name: str | None = None,
        *,
        page: int = 1,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        config = self.get_config()
        channels = _list(config.get("channels"))
        requested = str(channel_name or "").strip()
        selected: Mapping[str, Any] = {}
        if requested:
            for value in channels:
                channel = _mapping(value)
                if requested in {str(channel.get("id") or ""), str(channel.get("name") or "")}:
                    selected = channel
                    break
            if not selected:
                raise WeiboInputError(f"unknown Weibo channel: {requested}")
        else:
            selected = next(
                (
                    _mapping(value)
                    for value in channels
                    if _mapping(value).get("id") == DEFAULT_CHANNEL_ID
                ),
                _mapping(channels[0]) if channels else {},
            )
        container_id = str(selected.get("id") or DEFAULT_CHANNEL_ID)
        return self._collect_posts(
            container_id,
            page=page,
            since_id=None,
            limit=limit,
            context={
                "channel": str(selected.get("name") or channel_name or ""),
                "container_id": container_id,
            },
        )

    def get_trend_top(
        self,
        container_id: str,
        *,
        page: int = 1,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        identifier = self._container_id(container_id)
        return self._collect_posts(
            identifier,
            page=page,
            since_id=None,
            limit=limit,
            context={"container_id": identifier},
        )

    def get_user(self, uid_or_url: str | int) -> dict[str, Any]:
        uid = self.resolve_uid(uid_or_url)
        payload = self._json_get(
            "/api/container/getIndex",
            params={
                "type": "uid",
                "value": uid,
                "containerid": f"100505{uid}",
            },
        )
        data = self._api_data(payload, f"user {uid}")
        user = _mapping(data.get("userInfo"))
        if not user.get("id"):
            raise WeiboResponseError(f"Weibo user {uid} was not returned")
        result = self._normalize_user(user)
        tabs = _list(_mapping(data.get("tabsInfo")).get("tabs"))
        post_container = ""
        normalized_tabs: list[dict[str, Any]] = []
        for value in tabs:
            tab = _mapping(value)
            item = {
                "key": str(tab.get("tabKey") or ""),
                "title": str(tab.get("title") or ""),
                "type": str(tab.get("tab_type") or ""),
                "container_id": str(tab.get("containerid") or ""),
            }
            if item["key"] == "weibo" or item["type"] == "weibo":
                post_container = item["container_id"]
            normalized_tabs.append(item)
        result["post_container_id"] = post_container or f"107603{uid}"
        result["tabs"] = normalized_tabs
        return result

    get_user_profile = get_user

    def get_user_posts(
        self,
        uid_or_url: str | int,
        *,
        page: int = 1,
        since_id: str | int | None = None,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        uid = self.resolve_uid(uid_or_url)
        cursor = self._cursor(since_id, "since_id", allow_none=True)
        container_id = f"107603{uid}"
        return self._collect_posts(
            container_id,
            page=page,
            since_id=cursor,
            limit=limit,
            context={"user_id": uid, "container_id": container_id},
        )

    def get_post(self, post_id_or_url: str | int) -> dict[str, Any]:
        post_id = self.resolve_post_id(post_id_or_url)
        payload = self._json_get("/statuses/show", params={"id": post_id})
        data = self._api_data(payload, f"post {post_id}")
        post = self._normalize_post(data)
        if post["id"] != post_id:
            raise WeiboResponseError(
                f"post response ID mismatch: expected {post_id}, got {post['id'] or '(missing)'}"
            )
        return post

    def get_comments(
        self,
        post_id_or_url: str | int,
        *,
        mid: str | int | None = None,
        max_id: str | int | None = None,
        max_id_type: int = 0,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        post_id = self.resolve_post_id(post_id_or_url)
        mid_value = self._positive_id(mid if mid is not None else post_id, "mid")
        cursor = self._cursor(max_id, "max_id", allow_none=True)
        cursor_type = self._cursor_type(max_id_type)
        self._validate_limit(limit)
        if limit == 0:
            return {
                "post_id": post_id,
                "mid": mid_value,
                "total": 0,
                "total_available": 0,
                "max_id": cursor,
                "max_id_type": cursor_type,
                "has_more": False,
                "comments": [],
            }

        comments: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        total_available = 0
        has_more = True
        next_cursor = cursor
        next_type = cursor_type
        while has_more and (limit is None or len(comments) < limit):
            cursor_key = next_cursor or "first"
            if cursor_key in seen_cursors:
                raise WeiboResponseError(f"comment pagination repeated max_id {cursor_key}")
            seen_cursors.add(cursor_key)
            params: dict[str, Any] = {
                "id": post_id,
                "mid": mid_value,
                "max_id_type": next_type,
            }
            if next_cursor is not None:
                params["max_id"] = next_cursor
            payload = self._json_get("/comments/hotflow", params=params)
            data = self._api_data(payload, f"comments for post {post_id}")
            total_available = max(total_available, _integer(data.get("total_number")))
            for value in _list(data.get("data")):
                comment = self._normalize_comment(_mapping(value))
                if not comment["id"] or comment["id"] in seen_ids:
                    continue
                seen_ids.add(comment["id"])
                comments.append(comment)
                if limit is not None and len(comments) >= limit:
                    break
            raw_cursor = str(data.get("max_id") or "0")
            raw_type = self._cursor_type(_integer(data.get("max_id_type")))
            has_more = bool(raw_cursor and raw_cursor != "0")
            if has_more and raw_cursor == (next_cursor or ""):
                raise WeiboResponseError("comment response did not advance max_id")
            next_cursor = raw_cursor if has_more else None
            next_type = raw_type
            if not _list(data.get("data")):
                has_more = False
                next_cursor = None
        return {
            "post_id": post_id,
            "mid": mid_value,
            "total": len(comments),
            "total_available": total_available,
            "max_id": next_cursor,
            "max_id_type": next_type,
            "has_more": has_more,
            "comments": comments,
        }

    def get_comment_replies(
        self,
        cid: str | int,
        *,
        max_id: str | int = "0",
        max_id_type: int = 0,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        comment_id = self._positive_id(cid, "cid")
        cursor = self._cursor(max_id, "max_id", allow_none=False) or "0"
        cursor_type = self._cursor_type(max_id_type)
        self._validate_limit(limit)
        if limit == 0:
            return {
                "comment_id": comment_id,
                "total": 0,
                "total_available": 0,
                "max_id": cursor if cursor != "0" else None,
                "max_id_type": cursor_type,
                "has_more": False,
                "root_comment": None,
                "replies": [],
            }

        replies: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        total_available = 0
        root_comment: dict[str, Any] | None = None
        has_more = True
        next_cursor = cursor
        next_type = cursor_type
        while has_more and (limit is None or len(replies) < limit):
            if next_cursor in seen_cursors:
                raise WeiboResponseError(f"reply pagination repeated max_id {next_cursor}")
            seen_cursors.add(next_cursor)
            payload = self._json_get(
                "/comments/hotFlowChild",
                params={
                    "cid": comment_id,
                    "max_id": next_cursor,
                    "max_id_type": next_type,
                },
            )
            values = _list(payload.get("data"))
            total_available = max(total_available, _integer(payload.get("total_number")))
            if root_comment is None and isinstance(payload.get("rootComment"), Mapping):
                root_comment = self._normalize_comment(_mapping(payload.get("rootComment")))
            for value in values:
                reply = self._normalize_comment(_mapping(value))
                if not reply["id"] or reply["id"] in seen_ids:
                    continue
                seen_ids.add(reply["id"])
                replies.append(reply)
                if limit is not None and len(replies) >= limit:
                    break
            raw_cursor = str(payload.get("max_id") or "0")
            raw_type = self._cursor_type(_integer(payload.get("max_id_type")))
            has_more = bool(raw_cursor and raw_cursor != "0")
            if has_more and raw_cursor == next_cursor:
                raise WeiboResponseError("reply response did not advance max_id")
            next_cursor = raw_cursor if has_more else "0"
            next_type = raw_type
            if not values:
                has_more = False
                next_cursor = "0"
        return {
            "comment_id": comment_id,
            "total": len(replies),
            "total_available": total_available,
            "max_id": next_cursor if next_cursor != "0" else None,
            "max_id_type": next_type,
            "has_more": has_more,
            "root_comment": root_comment,
            "replies": replies,
        }

    def search(
        self,
        keyword: str,
        *,
        page: int = 1,
        search_type: str | int = "1",
        time_scope: str | None = None,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        query = str(keyword or "").strip()
        if not query or len(query) > 100:
            raise WeiboInputError("keyword must contain 1 to 100 characters")
        normalized_type = str(search_type or "").strip()
        if normalized_type not in _SEARCH_TYPES:
            raise WeiboInputError(
                f"search_type must be one of: {', '.join(sorted(_SEARCH_TYPES))}"
            )
        normalized_scope = str(time_scope or "").strip().lower()
        if normalized_scope not in _TIME_SCOPES:
            raise WeiboInputError("time_scope must be hour, day, week, month, or empty")
        cutoff = self._scope_cutoff(normalized_scope)
        # containerid 自身包含查询字符串，之后还会作为外层 HTTP 参数再次编码。
        # 此处先编码 q，避免关键字分隔符在外层解码后变成新的容器控制参数。
        container_id = f"100103type={normalized_type}&q={quote(query, safe='')}"
        result = self._collect_posts(
            container_id,
            page=page,
            since_id=None,
            limit=limit,
            context={
                "keyword": query,
                "search_type": normalized_type,
                "time_scope": normalized_scope or None,
            },
            predicate=(
                (lambda post: self._post_after(post, cutoff)) if cutoff is not None else None
            ),
            collect_users=True,
        )
        return result

    def get_hot_search(self) -> dict[str, Any]:
        payload = self._json_get(
            "/api/container/getIndex",
            params={"containerid": _HOT_SEARCH_CONTAINER},
        )
        data = self._api_data(payload, "hot search")
        trends: list[dict[str, Any]] = []
        seen: set[str] = set()
        for card_value in _list(data.get("cards")):
            card = _mapping(card_value)
            for value in _list(card.get("card_group")):
                item = _mapping(value)
                keyword = str(item.get("desc") or "").strip()
                if not keyword or keyword in seen:
                    continue
                seen.add(keyword)
                item_id = str(item.get("itemid") or "")
                match = re.search(r"(?:^|\|)realpos:([0-9]+)(?:\||$)", item_id)
                rank = _integer(match.group(1)) if match else None
                extra = str(item.get("desc_extr") or "").strip()
                heat_match = re.search(r"([0-9][0-9,]*)\s*$", extra)
                heat = _integer(heat_match.group(1).replace(",", "")) if heat_match else 0
                label = extra[: heat_match.start()].strip() if heat_match else ""
                trends.append(
                    {
                        "rank": rank,
                        "keyword": keyword,
                        "heat": heat,
                        "heat_text": extra,
                        "label": label,
                        "icon": _absolute_url(item.get("icon")),
                        "rank_image": _absolute_url(item.get("pic")),
                        "scheme": _absolute_url(item.get("scheme")),
                        "pinned": rank is None,
                    }
                )
        return {"total": len(trends), "trends": trends}

    def _collect_posts(
        self,
        container_id: str,
        *,
        page: int,
        since_id: str | None,
        limit: int | None,
        context: Mapping[str, Any],
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        collect_users: bool = False,
    ) -> dict[str, Any]:
        identifier = self._container_id(container_id)
        current_page = self._page(page)
        first_page = current_page
        current_since = since_id
        self._validate_limit(limit)
        if limit == 0:
            empty: dict[str, Any] = {
                **dict(context),
                "page": first_page,
                "next_page": current_page,
                "since_id": current_since,
                "total": 0,
                "total_available": 0,
                "has_more": False,
                "posts": [],
            }
            if collect_users:
                empty.update({"post_total": 0, "user_total": 0, "users": []})
            return empty

        posts: list[dict[str, Any]] = []
        users: list[dict[str, Any]] = []
        seen_post_ids: set[str] = set()
        seen_user_ids: set[str] = set()
        seen_tokens: set[tuple[int, str]] = set()
        total_available = 0
        next_page: int | None = current_page
        next_since: str | None = current_since
        has_more = True
        pages_fetched = 0

        def collected_count() -> int:
            return len(posts) + len(users) if collect_users else len(posts)

        while has_more and (limit is None or collected_count() < limit):
            token = (current_page, current_since or "")
            if token in seen_tokens:
                raise WeiboResponseError(f"feed pagination repeated cursor {token}")
            seen_tokens.add(token)
            params: dict[str, Any] = {"containerid": identifier, "page": current_page}
            if current_since is not None:
                params["since_id"] = current_since
            payload = self._json_get("/api/container/getIndex", params=params)
            data = self._api_data(payload, f"container {identifier}")
            cards = _list(data.get("cards"))
            info = _mapping(data.get("cardlistInfo"))
            total_available = max(total_available, _integer(info.get("total")))
            raw_posts = self._extract_mblogs(cards)
            for raw in raw_posts:
                post = self._normalize_post(raw)
                if not post["id"] or post["id"] in seen_post_ids:
                    continue
                seen_post_ids.add(post["id"])
                if predicate is not None and not predicate(post):
                    continue
                posts.append(post)
                if limit is not None and collected_count() >= limit:
                    break
            if collect_users:
                for raw_user in self._extract_card_users(cards):
                    user = self._normalize_user(raw_user)
                    if not user["id"] or user["id"] in seen_user_ids:
                        continue
                    seen_user_ids.add(user["id"])
                    users.append(user)
                    if limit is not None and collected_count() >= limit:
                        break

            raw_since = str(info.get("since_id") or "")
            candidate_since = raw_since if raw_since and raw_since != "0" else None
            raw_page = _integer(info.get("page"))
            candidate_page = raw_page if raw_page > 0 else None
            if candidate_since is not None:
                if candidate_since == (current_since or ""):
                    raise WeiboResponseError("feed response did not advance since_id")
                next_since = candidate_since
                next_page = candidate_page or current_page
            elif candidate_page is not None:
                if candidate_page <= current_page:
                    raise WeiboResponseError("feed response did not advance page")
                next_since = None
                next_page = candidate_page
            else:
                next_since = None
                next_page = None
            has_more = bool(next_since is not None or next_page is not None)
            pages_fetched += 1
            if not cards:
                has_more = False
                next_since = None
                next_page = None
            if limit is not None and collected_count() >= limit:
                break
            if not has_more:
                break
            if pages_fetched >= 100:
                raise WeiboResponseError("feed pagination exceeded 100 pages")
            current_since = next_since
            current_page = next_page or current_page

        result: dict[str, Any] = {
            **dict(context),
            "page": first_page,
            "next_page": next_page,
            "since_id": next_since,
            "total": len(posts) + len(users) if collect_users else len(posts),
            "total_available": total_available,
            "has_more": has_more,
            "posts": posts,
        }
        if collect_users:
            result["post_total"] = len(posts)
            result["user_total"] = len(users)
            result["users"] = users
        return result

    def _json_get(self, path: str, *, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if not path.startswith("/") or "?" in path or "#" in path:
            raise WeiboInputError("internal Weibo API path is malformed")
        self.initialize_session()
        url = f"{_BASE_URL}{path}"
        request_params = dict(params)
        response = self._request(
            "GET",
            url,
            params=request_params,
            headers={"Referer": f"{_BASE_URL}/"},
            accepted_statuses={302, 432},
        )
        if self._is_visitor_gate(response):
            target_url = self._url_with_params(url, request_params)
            self._bootstrap_visitor(response, target_url=target_url)
            response = self._request(
                "GET",
                url,
                params=request_params,
                headers={"Referer": f"{_BASE_URL}/"},
                accepted_statuses={302, 432},
            )
            if self._is_visitor_gate(response):
                raise WeiboResponseError("Weibo visitor refresh did not unlock the API response")
        if not 200 <= _integer(response.status_code) < 300:
            raise WeiboResponseError(f"Weibo returned HTTP {response.status_code} for {path}")
        payload = self._decode_json(response, path)
        ok = payload.get("ok")
        if ok is not None and _integer(ok) != 1:
            message = payload.get("msg") or payload.get("message") or "unknown error"
            raise WeiboResponseError(f"Weibo API error {ok}: {message}")
        return payload

    def _bootstrap_visitor(self, gate: requests.Response, *, target_url: str) -> None:
        location = str(gate.headers.get("location") or "").strip()
        page = gate
        page_url = str(getattr(gate, "url", "") or _VISITOR_ORIGIN)
        if location:
            visitor_url = urljoin(page_url, location)
            self._validate_url(visitor_url, hosts={_VISITOR_HOST}, response=True)
            page = self._request("GET", visitor_url, params={})
            page_url = str(getattr(page, "url", "") or visitor_url)
        source = str(getattr(page, "text", "") or "")
        match = _REQUEST_ID_RE.search(source)
        if not match:
            raise WeiboResponseError("Weibo visitor page does not contain a valid request_id")
        self._validate_url(target_url, hosts={"m.weibo.cn"}, response=True)
        referer = (
            page_url
            if urlsplit(page_url).hostname == _VISITOR_HOST
            else f"{_VISITOR_ORIGIN}/visitor/visitor"
        )
        response = self._request(
            "POST",
            _VISITOR_GENERATE_URL,
            data={
                "cb": _VISITOR_CALLBACK,
                "ver": "20250916",
                "request_id": match.group("value"),
                "tid": self._visitor_tid,
                "from": "weibo",
                "webdriver": "false",
                "rid": str(int(time.time() * 1000)),
                "return_url": target_url,
            },
            headers={
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": _VISITOR_ORIGIN,
                "Referer": referer,
            },
        )
        payload = self.parse_visitor_jsonp(response.text)
        if _integer(payload.get("retcode")) != 20_000_000:
            raise WeiboResponseError(
                f"Weibo visitor API error {payload.get('retcode')}: "
                f"{payload.get('msg') or 'unknown error'}"
            )
        data = _mapping(payload.get("data"))
        required = {name: str(data.get(name) or "") for name in ("sub", "subp", "tid")}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise WeiboResponseError(
                f"Weibo visitor response is missing: {', '.join(missing)}"
            )
        self._visitor_tid = required["tid"]

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> requests.Response:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "POST"}:
            raise WeiboInputError(f"unsupported HTTP method: {method}")
        self._validate_url(url, hosts=_ALLOWED_HOSTS)
        accepted = accepted_statuses or set()
        path = urlsplit(url).path
        for attempt in range(self.retries + 1):
            try:
                if normalized_method == "GET":
                    response = self.session.get(
                        url,
                        params=dict(params or {}),
                        headers=dict(headers) if headers else None,
                        timeout=self.timeout,
                        allow_redirects=False,
                    )
                else:
                    response = self.session.post(
                        url,
                        data=dict(data or {}),
                        headers=dict(headers) if headers else None,
                        timeout=self.timeout,
                        allow_redirects=False,
                    )
            except requests.RequestsError as exc:
                if attempt >= self.retries:
                    raise WeiboResponseError(f"Weibo request failed for {path}: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            final_url = str(getattr(response, "url", "") or url)
            self._validate_url(final_url, hosts=_ALLOWED_HOSTS, response=True)
            status = _integer(getattr(response, "status_code", 0))
            if 200 <= status < 300 or status in accepted:
                return response
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            raise WeiboResponseError(f"Weibo returned HTTP {status} for {path}")
        raise WeiboResponseError(f"Weibo request exhausted retries for {path}")

    @staticmethod
    def parse_visitor_jsonp(source: str) -> Mapping[str, Any]:
        text = str(source or "").strip()
        prefix = re.compile(
            rf"^(?:window\.)?{_VISITOR_CALLBACK}\s*&&\s*{_VISITOR_CALLBACK}\s*\("
        )
        match = prefix.match(text)
        if not match:
            raise WeiboResponseError("Weibo visitor response has an unexpected JSONP callback")
        decoder = json.JSONDecoder()
        try:
            payload, end = decoder.raw_decode(text, match.end())
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WeiboResponseError("Weibo visitor response contains invalid JSON") from exc
        suffix = text[end:].strip()
        if suffix not in {")", ");"}:
            raise WeiboResponseError("Weibo visitor response contains trailing JSONP content")
        if not isinstance(payload, Mapping):
            raise WeiboResponseError("Weibo visitor JSONP payload is not an object")
        return payload

    @staticmethod
    def _decode_json(response: requests.Response, context: str) -> Mapping[str, Any]:
        try:
            payload = json.loads(response.text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WeiboResponseError(f"Weibo returned invalid JSON for {context}") from exc
        if not isinstance(payload, Mapping):
            raise WeiboResponseError(f"Weibo JSON root is not an object for {context}")
        return payload

    @staticmethod
    def _api_data(payload: Mapping[str, Any], context: str) -> Mapping[str, Any]:
        if _integer(payload.get("ok")) != 1:
            message = payload.get("msg") or payload.get("message") or "unknown error"
            raise WeiboResponseError(f"Weibo did not return {context}: {message}")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise WeiboResponseError(f"Weibo {context} data is not an object")
        return data

    @staticmethod
    def _is_visitor_gate(response: requests.Response) -> bool:
        status = _integer(getattr(response, "status_code", 0))
        if status in {302, 432}:
            return True
        content_type = str(response.headers.get("content-type") or "").lower()
        if "json" in content_type:
            return False
        source = str(getattr(response, "text", "") or "")[:50_000]
        return "request_id" in source and (
            "visitor_gray_callback" in source or "Sina Visitor System" in source
        )

    @staticmethod
    def _validate_url(
        url: str,
        *,
        hosts: set[str],
        response: bool = False,
    ) -> None:
        parsed = urlsplit(str(url or ""))
        host = (parsed.hostname or "").lower().rstrip(".")
        try:
            port = parsed.port
        except ValueError:
            port = -1
        label = "response URL" if response else "request URL"
        if (
            parsed.scheme.lower() != "https"
            or host not in hosts
            or parsed.username
            or parsed.password
            or port not in (None, 443)
        ):
            raise WeiboResponseError(
                f"Weibo {label} has an invalid authority: {host or '(missing)'}"
            )

    @staticmethod
    def _url_with_params(url: str, params: Mapping[str, Any]) -> str:
        query = urlencode([(str(key), str(value)) for key, value in params.items()])
        return f"{url}?{query}" if query else url

    @staticmethod
    def _extract_mblogs(cards: Sequence[Any]) -> list[Mapping[str, Any]]:
        output: list[Mapping[str, Any]] = []
        for value in cards:
            card = _mapping(value)
            mblog = card.get("mblog")
            if isinstance(mblog, Mapping):
                output.append(mblog)
            output.extend(WeiboClient._extract_mblogs(_list(card.get("card_group"))))
        return output

    @staticmethod
    def _extract_card_users(cards: Sequence[Any]) -> list[Mapping[str, Any]]:
        output: list[Mapping[str, Any]] = []
        for value in cards:
            card = _mapping(value)
            if not isinstance(card.get("mblog"), Mapping) and isinstance(card.get("user"), Mapping):
                output.append(_mapping(card.get("user")))
            output.extend(WeiboClient._extract_card_users(_list(card.get("card_group"))))
        return output

    @classmethod
    def _normalize_post(cls, raw: Mapping[str, Any], *, depth: int = 0) -> dict[str, Any]:
        post_id = str(raw.get("idstr") or raw.get("id") or raw.get("mid") or "")
        text_html = str(raw.get("text") or raw.get("raw_text") or "")
        repost = _mapping(raw.get("retweeted_status"))
        return {
            "id": post_id,
            "mid": str(raw.get("mid") or post_id),
            "bid": str(raw.get("bid") or ""),
            "url": f"{_BASE_URL}/detail/{post_id}" if post_id else "",
            "text": _plain_text(text_html),
            "text_html": text_html,
            "created_at": _created_at_iso(raw.get("created_at")),
            "created_at_raw": str(raw.get("created_at") or ""),
            "source": _plain_text(raw.get("source")),
            "author": cls._normalize_user(_mapping(raw.get("user"))),
            "stats": {
                "reposts": _integer(raw.get("reposts_count")),
                "comments": _integer(raw.get("comments_count")),
                "likes": _integer(raw.get("attitudes_count")),
                "favorites": _integer(raw.get("favorites_count")),
            },
            "favorited": bool(raw.get("favorited")),
            "is_long_text": bool(raw.get("isLongText")),
            "region": str(raw.get("region_name") or ""),
            "images": cls._normalize_images(raw),
            "video": cls._normalize_video(raw),
            "reposted_post": cls._normalize_post(repost, depth=depth + 1)
            if repost and depth < 1
            else None,
        }

    @staticmethod
    def _normalize_user(raw: Mapping[str, Any]) -> dict[str, Any]:
        user_id = str(raw.get("idstr") or raw.get("id") or raw.get("uid") or "")
        followers_text = str(
            raw.get("followers_count_str") or raw.get("followers_count") or "0"
        )
        profile_url = _absolute_url(raw.get("profile_url"))
        if profile_url.startswith("/"):
            profile_url = f"{_BASE_URL}{profile_url}"
        return {
            "id": user_id,
            "screen_name": str(raw.get("screen_name") or raw.get("name") or ""),
            "url": profile_url or (f"{_BASE_URL}/u/{user_id}" if user_id else ""),
            "bio": str(raw.get("description") or ""),
            "avatar_url": _absolute_url(raw.get("avatar_hd") or raw.get("profile_image_url")),
            "profile_image_url": _absolute_url(raw.get("profile_image_url")),
            "cover_url": _absolute_url(raw.get("cover_image_phone")),
            "verified": bool(raw.get("verified")),
            "verified_type": _integer(raw.get("verified_type")),
            "verified_reason": str(raw.get("verified_reason") or ""),
            "gender": str(raw.get("gender") or ""),
            "following": bool(raw.get("following")),
            "stats": {
                "followers": _approximate_count(followers_text),
                "followers_text": followers_text,
                "following": _integer(raw.get("follow_count")),
                "posts": _integer(raw.get("statuses_count")),
            },
        }

    @staticmethod
    def _normalize_images(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in _list(raw.get("pics")):
            image = _mapping(value)
            large = _mapping(image.get("large"))
            preview_geo = _mapping(image.get("geo"))
            large_geo = _mapping(large.get("geo"))
            url = _absolute_url(large.get("url") or image.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            output.append(
                {
                    "id": str(image.get("pid") or ""),
                    "url": url,
                    "preview_url": _absolute_url(image.get("url")),
                    "width": _integer(large_geo.get("width") or preview_geo.get("width")),
                    "height": _integer(large_geo.get("height") or preview_geo.get("height")),
                    "type": str(image.get("type") or "image"),
                    "duration_seconds": _number(image.get("duration")),
                    "video_url": _absolute_url(image.get("videoSrc")),
                }
            )
        return output

    @staticmethod
    def _normalize_video(raw: Mapping[str, Any]) -> dict[str, Any] | None:
        page = _mapping(raw.get("page_info"))
        media = _mapping(page.get("media_info"))
        urls = _mapping(page.get("urls"))
        streams: dict[str, str] = {}
        for name, value in {**dict(urls), **dict(media)}.items():
            if isinstance(value, str) and value.startswith(("http://", "https://", "//")) and (
                "stream" in str(name).lower() or "mp4" in str(name).lower()
            ):
                streams[str(name)] = _absolute_url(value)
        if not streams:
            for value in _list(raw.get("pics")):
                image = _mapping(value)
                if image.get("videoSrc"):
                    streams["picture_video"] = _absolute_url(image.get("videoSrc"))
                    break
        page_type = str(page.get("type") or "")
        if not streams and page_type not in {"video", "live"}:
            return None
        preferred = (
            streams.get("stream_url_hd")
            or streams.get("mp4_720p_mp4")
            or streams.get("stream_url")
            or streams.get("mp4_hd_mp4")
            or next(iter(streams.values()), "")
        )
        cover = _mapping(page.get("page_pic"))
        return {
            "type": page_type or "video",
            "url": preferred,
            "streams": streams,
            "cover_url": _absolute_url(cover.get("url")),
            "width": _integer(cover.get("width")),
            "height": _integer(cover.get("height")),
            "duration_seconds": _number(media.get("duration")),
            "play_count": _approximate_count(page.get("play_count")),
            "title": str(page.get("page_title") or page.get("title") or ""),
            "page_url": _absolute_url(page.get("page_url")),
        }

    @classmethod
    def _normalize_comment(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        text_html = str(raw.get("text") or "")
        nested: list[dict[str, Any]] = []
        for value in _list(raw.get("comments")):
            nested.append(cls._normalize_comment(_mapping(value)))
        return {
            "id": str(raw.get("idstr") or raw.get("id") or ""),
            "root_id": str(raw.get("rootidstr") or raw.get("rootid") or ""),
            "mid": str(raw.get("mid") or ""),
            "text": _plain_text(text_html),
            "text_html": text_html,
            "created_at": _created_at_iso(raw.get("created_at")),
            "created_at_raw": str(raw.get("created_at") or ""),
            "source": str(raw.get("source") or ""),
            "author": cls._normalize_user(_mapping(raw.get("user"))),
            "likes": _integer(raw.get("like_count")),
            "liked": bool(raw.get("liked")),
            "reply_count": _integer(raw.get("total_number")),
            "floor": _integer(raw.get("floor_number")),
            "is_post_author": bool(raw.get("is_mblog_author")),
            "replies": nested,
        }

    @staticmethod
    def resolve_post_id(value: str | int) -> str:
        text = str(value or "").strip()
        if _POSITIVE_ID_RE.fullmatch(text) and _integer(text) > 0:
            return text
        parsed = urlsplit(text if "://" in text else f"https://{text}")
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in _WEIBO_REFERENCE_HOSTS:
            raise WeiboInputError("post URL must use an m.weibo.cn or weibo.cn host")
        parts = [part for part in parsed.path.split("/") if part]
        candidate = ""
        if len(parts) >= 2 and parts[-2].lower() in {"detail", "status"}:
            candidate = parts[-1]
        elif parsed.path.rstrip("/").lower() == "/statuses/show":
            query = parse_qs(parsed.query)
            candidate = str((query.get("id") or query.get("mid") or [""])[0])
        if not _POSITIVE_ID_RE.fullmatch(candidate) or _integer(candidate) <= 0:
            raise WeiboInputError("post URL does not contain a numeric Weibo post ID")
        return candidate

    @staticmethod
    def resolve_uid(value: str | int) -> str:
        text = str(value or "").strip()
        if _POSITIVE_ID_RE.fullmatch(text) and _integer(text) > 0:
            return text
        parsed = urlsplit(text if "://" in text else f"https://{text}")
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in _WEIBO_REFERENCE_HOSTS:
            raise WeiboInputError("user URL must use an m.weibo.cn or weibo.cn host")
        parts = [part for part in parsed.path.split("/") if part]
        candidate = ""
        if len(parts) >= 2 and parts[-2].lower() in {"u", "profile"}:
            candidate = parts[-1]
        if not _POSITIVE_ID_RE.fullmatch(candidate) or _integer(candidate) <= 0:
            raise WeiboInputError("user URL does not contain a numeric Weibo user ID")
        return candidate

    @staticmethod
    def _positive_id(value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not _POSITIVE_ID_RE.fullmatch(text) or _integer(text) <= 0:
            raise WeiboInputError(f"{label} must be a positive numeric ID")
        return text

    @staticmethod
    def _cursor(value: Any, label: str, *, allow_none: bool) -> str | None:
        if value is None and allow_none:
            return None
        text = str(value or "").strip()
        if not _ID_RE.fullmatch(text):
            raise WeiboInputError(f"{label} must be a numeric pagination cursor")
        return text

    @staticmethod
    def _container_id(value: Any) -> str:
        identifier = str(value or "").strip()
        if not (
            _CONTAINER_RE.fullmatch(identifier)
            or _SEARCH_CONTAINER_RE.fullmatch(identifier)
        ):
            raise WeiboInputError("container_id contains unsupported characters")
        return identifier

    @staticmethod
    def _page(value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise WeiboInputError("page must be a positive integer")
        return value

    @staticmethod
    def _cursor_type(value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value not in {0, 1}:
            raise WeiboInputError("max_id_type must be 0 or 1")
        return value

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        ):
            raise WeiboInputError("limit must be a non-negative integer or None")

    @staticmethod
    def _scope_cutoff(scope: str) -> datetime | None:
        if not scope:
            return None
        delta = {
            "hour": timedelta(hours=1),
            "day": timedelta(days=1),
            "week": timedelta(days=7),
            "month": timedelta(days=30),
        }[scope]
        return datetime.now(timezone.utc) - delta

    @staticmethod
    def _post_after(post: Mapping[str, Any], cutoff: datetime) -> bool:
        value = str(post.get("created_at") or "")
        try:
            created = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created >= cutoff
