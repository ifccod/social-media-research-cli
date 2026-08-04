from __future__ import annotations

import html
import logging
import math
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

from curl_cffi import requests

from .errors import RedditInputError, RedditRateLimited, RedditResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

_BASE_URL = "https://www.reddit.com"
_IDENTITY_URL = "https://old.reddit.com/"
_JSON_REFERER = f"{_BASE_URL}/"
_REDDIT_PROXY_ENV = "REDDIT_OPPORTUNITY_PROXY"
_REDDIT_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "new.reddit.com",
    "np.reddit.com",
    "redd.it",
    "www.redd.it",
}
_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_POST_ID_RE = re.compile(r"^[a-z0-9]{1,12}$", re.IGNORECASE)
_COMMENT_ID_RE = re.compile(r"^(?:t1_)?([a-z0-9]{1,12})$", re.IGNORECASE)
_PARENT_FULLNAME_RE = re.compile(r"^t[13]_[a-z0-9]{1,12}$", re.IGNORECASE)
_INFO_FULLNAME_RE = re.compile(r"^(t[13])_([a-z0-9]{1,12})$", re.IGNORECASE)
_SUBREDDIT_FULLNAME_RE = re.compile(r"^t5_[a-z0-9]+$", re.IGNORECASE)
_SORTS = {"hot", "new", "top", "rising", "controversial"}
_USER_COMMENT_SORTS = {"hot", "new", "top", "controversial"}
_SEARCH_SORTS = {"relevance", "hot", "top", "new", "comments"}
_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}
_SAFE_SEARCH_VALUES = {"unset", "strict"}

logger = logging.getLogger(__name__)

FetchCallback = Callable[[dict[str, Any]], None]


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


def _url(value: Any) -> str:
    return html.unescape(str(value or ""))


def _nullable_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _nullable_number(value: Any) -> int | float | None:
    return None if value is None else _number(value)


def _nullable_integer(value: Any) -> int | None:
    return None if value is None else _integer(value)


def _nullable_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


def _nullable_url(value: Any) -> str | None:
    return None if value is None else _url(value)


def _configured_reddit_proxy() -> str | None:
    """读取 Reddit 专用代理环境变量，不读取通用进程代理变量。"""
    return str(os.environ.get(_REDDIT_PROXY_ENV) or "").strip() or None


def _redact_proxy(value: Any, proxy: str | None) -> str:
    """从异常文本中移除完整代理 URL 及其认证片段。"""
    detail = str(value)
    if not proxy:
        return detail
    secrets = [proxy]
    try:
        parsed = urlsplit(proxy)
        if parsed.username:
            secrets.append(parsed.username)
        if parsed.password:
            secrets.append(parsed.password)
        if parsed.netloc:
            secrets.append(parsed.netloc)
    except ValueError:
        pass
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "<configured-proxy>")
    return detail


def _request_error_brief(exc: BaseException, *, proxy: str | None = None) -> str:
    return f"{type(exc).__name__}: {_redact_proxy(exc, proxy)[:300]}"


def _response_retry_after_seconds(response: Any) -> float | None:
    """解析 Retry-After，并将结果限制在一个后续任务可接受的范围内。"""
    headers = getattr(response, "headers", None)
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    for name in ("Retry-After", "retry-after", "X-Ratelimit-Reset", "x-ratelimit-reset"):
        value = get(name)
        if value is None:
            continue
        try:
            seconds = float(str(value).strip())
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(value))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = (
                    retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)
                ).total_seconds()
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
        if math.isfinite(seconds) and seconds >= 0:
            return min(seconds, 24 * 60 * 60)
    return None


class RedditClient:
    """通过纯 HTTP 访客初始化读取 Reddit 公开 JSON。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
        proxy: str | None = None,
        on_fetch: FetchCallback | None = None,
    ) -> None:
        self.session = session if session is not None else requests.Session(
            impersonate="chrome146",
            trust_env=False,
            proxies={"all": ""},
        )
        self.timeout = timeout
        self.retries = max(0, retries)
        self.proxy = (
            str(proxy).strip() if proxy is not None else _configured_reddit_proxy()
        ) or None
        self.user_agent = user_agent
        self.on_fetch = on_fetch
        self.fetch_records: list[dict[str, Any]] = []
        self._identity_ready = False
        self._identity_blocked = False
        self._rate_limited_until = 0.0
        self.session.headers.update(
            {
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": user_agent,
            }
        )

    def initialize_session(self, *, force: bool = False) -> bool:
        """尽力建立访客会话，bootstrap 失败也不跳过目标 JSON 请求。"""
        if self._identity_ready and not force:
            return True
        if self._identity_blocked and not force and not self.proxy:
            return False
        self._identity_ready = False
        try:
            response = self._request(
                _IDENTITY_URL,
                params={},
                request_kind="session_init",
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": self.user_agent,
                },
                retry_statuses={403},
            )
        except RedditRateLimited:
            raise
        except RedditResponseError:
            self._identity_blocked = True
            return False
        status = int(getattr(response, "status_code", 0) or 0)
        self._identity_ready = 200 <= status < 300
        self._identity_blocked = not self._identity_ready
        return self._identity_ready

    def get_subreddit(
        self,
        subreddit: str,
        *,
        sort: str = "hot",
        time_filter: str = "all",
        limit: int | None = 25,
        after: str | None = None,
    ) -> dict[str, Any]:
        name = self.resolve_subreddit(subreddit)
        normalized_sort = self._choice(sort, _SORTS, "sort")
        normalized_time = self._choice(time_filter, _TIME_FILTERS, "time_filter")
        return self._collect_listing(
            f"/r/{name}/{normalized_sort}/.json",
            limit=limit,
            after=after,
            extra={"t": normalized_time},
            context={"subreddit": name, "sort": normalized_sort, "time_filter": normalized_time},
        )

    def search(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        sort: str = "relevance",
        time_filter: str = "all",
        limit: int | None = 25,
        after: str | None = None,
    ) -> dict[str, Any]:
        keyword = str(query or "").strip()
        if not keyword:
            raise RedditInputError("query must not be empty")
        normalized_sort = self._choice(sort, _SEARCH_SORTS, "sort")
        normalized_time = self._choice(time_filter, _TIME_FILTERS, "time_filter")
        name = self.resolve_subreddit(subreddit) if subreddit is not None else None
        path = f"/r/{name}/search/.json" if name else "/search/.json"
        return self._collect_listing(
            path,
            limit=limit,
            after=after,
            extra={
                "q": keyword,
                "sort": normalized_sort,
                "t": normalized_time,
                "restrict_sr": "on" if name else "off",
            },
            context={
                "query": keyword,
                "subreddit": name,
                "sort": normalized_sort,
                "time_filter": normalized_time,
            },
        )

    def get_batch_info(self, fullnames: Sequence[str] | str) -> dict[str, Any]:
        """通过 Reddit 批量路由获取最多 30 条公开帖子或评论。"""
        requested = self._batch_fullnames(fullnames)
        payload = self._json_get(
            "/api/info.json",
            params={"id": ",".join(requested)},
        )
        if not isinstance(payload, Mapping):
            raise RedditResponseError("batch info JSON root is not an object")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise RedditResponseError("batch info JSON data is not an object")
        children = data.get("children")
        if not isinstance(children, Sequence) or isinstance(
            children, (str, bytes, bytearray)
        ):
            raise RedditResponseError("batch info JSON children is not an array")

        requested_set = set(requested)
        found: dict[str, dict[str, Any]] = {}
        for child in children:
            if not isinstance(child, Mapping):
                continue
            kind = str(child.get("kind") or "").strip().lower()
            if kind not in {"t1", "t3"}:
                continue
            child_data = child.get("data")
            if not isinstance(child_data, Mapping):
                continue
            fullname = str(child_data.get("name") or "").strip().lower()
            if not fullname:
                item_id = str(child_data.get("id") or "").strip().lower()
                if item_id:
                    fullname = f"{kind}_{item_id}"
            match = _INFO_FULLNAME_RE.fullmatch(fullname)
            if (
                match is None
                or match.group(1).lower() != kind
                or fullname not in requested_set
                or fullname in found
            ):
                continue

            normalized_input = dict(child_data)
            normalized_input["name"] = fullname
            normalized = (
                self._normalize_post(normalized_input)
                if kind == "t3"
                else self._normalize_user_comment(normalized_input)
            )
            found[fullname] = {"kind": kind, "data": normalized}

        items = [found[fullname] for fullname in requested if fullname in found]
        missing = [fullname for fullname in requested if fullname not in found]
        return {
            "requested": requested,
            "requested_total": len(requested),
            "total": len(items),
            "missing": missing,
            "missing_total": len(missing),
            "items": items,
        }

    def get_post(
        self,
        post_url_or_id: str,
        *,
        comment_limit: int = 100,
        depth: int | None = None,
        sort: str = "confidence",
    ) -> dict[str, Any]:
        post_id = self.resolve_post_id(post_url_or_id)
        size = self._page_size(comment_limit, "comment_limit", maximum=500)
        if depth is not None and (
            not isinstance(depth, int) or isinstance(depth, bool) or depth < 0
        ):
            raise RedditInputError("depth must be a non-negative integer or None")
        normalized_sort = self._choice(
            sort,
            {"confidence", "top", "new", "controversial", "old", "qa"},
            "sort",
        )
        params: dict[str, Any] = {
            "limit": size,
            "sort": normalized_sort,
        }
        if depth is not None:
            params["depth"] = depth
        payload = self._json_get(f"/comments/{post_id}/.json", params=params)
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
            raise RedditResponseError("post detail JSON root is not a listing pair")
        listings = list(payload)
        if not listings:
            raise RedditResponseError(f"Reddit post {post_id} was not returned")
        post_children = self._listing_children(listings[0])
        if not post_children:
            raise RedditResponseError(f"Reddit post {post_id} payload has no post")
        post = self._normalize_post(_mapping(_mapping(post_children[0]).get("data")))
        if post["id"].lower() != post_id.lower():
            raise RedditResponseError(
                f"post response ID mismatch: expected {post_id}, got {post['id']}"
            )
        comment_children = self._listing_children(listings[1]) if len(listings) > 1 else []
        comments: list[dict[str, Any]] = []
        more_ids: list[str] = []
        for child in comment_children:
            kind = str(_mapping(child).get("kind") or "")
            data = _mapping(_mapping(child).get("data"))
            if kind == "t1":
                comments.append(self._normalize_comment(data))
            elif kind == "more":
                more_ids.extend(str(item) for item in _list(data.get("children")) if item)
        return {
            "post": post,
            "comment_sort": normalized_sort,
            "comment_total": len(comments),
            "comments": comments,
            "more_comment_ids": more_ids,
        }

    def get_more_comments(
        self,
        post_url_or_id: str,
        comment_ids: Sequence[str] | str,
        *,
        sort: str = "confidence",
    ) -> dict[str, Any]:
        post_id = self.resolve_post_id(post_url_or_id)
        requested = self._more_comment_ids(comment_ids)
        normalized_sort = self._choice(
            sort,
            {"confidence", "top", "new", "controversial", "old", "qa"},
            "sort",
        )
        link_id = f"t3_{post_id}"
        pending = list(requested)
        scheduled = set(requested)
        attempted: set[str] = set()
        comments: dict[str, dict[str, Any]] = {}
        response_order: list[str] = []

        while pending:
            batch: list[str] = []
            while pending and len(batch) < 100:
                comment_id = pending.pop(0)
                if comment_id in attempted or comment_id in comments:
                    continue
                attempted.add(comment_id)
                batch.append(comment_id)
            if not batch:
                continue

            payload = self._json_get(
                "/api/morechildren.json",
                params={
                    "api_type": "json",
                    "link_id": link_id,
                    "children": ",".join(batch),
                    "sort": normalized_sort,
                },
            )
            things = self._morechildren_things(payload)
            new_comment_count = 0
            new_pending_count = 0
            work = list(things)
            index = 0
            while index < len(work):
                wrapper = work[index]
                index += 1
                if not isinstance(wrapper, Mapping):
                    raise RedditResponseError(
                        "morechildren things entries must be objects"
                    )
                kind = str(wrapper.get("kind") or "").lower()
                data = wrapper.get("data")
                if not isinstance(data, Mapping):
                    raise RedditResponseError(
                        "morechildren thing data must be an object"
                    )
                if kind == "t1":
                    comment_id = self._response_comment_id(data.get("id"))
                    response_name = str(data.get("name") or "").strip().lower()
                    if response_name and response_name != f"t1_{comment_id}":
                        raise RedditResponseError(
                            f"morechildren comment ID/name mismatch for {comment_id}"
                        )
                    response_link_id = str(data.get("link_id") or "").strip().lower()
                    if response_link_id != link_id:
                        raise RedditResponseError(
                            "morechildren comment link_id mismatch: "
                            f"expected {link_id}, got {response_link_id or '<empty>'}"
                        )
                    parent_id = str(data.get("parent_id") or "").strip().lower()
                    if _PARENT_FULLNAME_RE.fullmatch(parent_id) is None:
                        raise RedditResponseError(
                            f"morechildren comment {comment_id} has invalid parent_id"
                        )
                    if parent_id.startswith("t3_") and parent_id != link_id:
                        raise RedditResponseError(
                            f"morechildren comment {comment_id} parent post mismatch"
                        )

                    nested = data.get("replies")
                    if isinstance(nested, Mapping):
                        work.extend(self._listing_children(nested))
                    if comment_id in comments:
                        continue
                    normalized = self._normalize_comment(data)
                    normalized.update(
                        {
                            "id": comment_id,
                            "fullname": f"t1_{comment_id}",
                            "parent_id": parent_id,
                            "link_id": link_id,
                            "replies": [],
                            "more_reply_ids": [],
                        }
                    )
                    comments[comment_id] = normalized
                    response_order.append(comment_id)
                    new_comment_count += 1
                elif kind == "more":
                    raw_children = data.get("children")
                    if not isinstance(raw_children, Sequence) or isinstance(
                        raw_children, (str, bytes, bytearray)
                    ):
                        raise RedditResponseError(
                            "morechildren more.children must be an array"
                        )
                    for raw_child in raw_children:
                        child_id = self._response_comment_id(raw_child)
                        if child_id in scheduled or child_id in comments:
                            continue
                        scheduled.add(child_id)
                        pending.append(child_id)
                        new_pending_count += 1
                else:
                    raise RedditResponseError(
                        f"morechildren returned unsupported thing kind {kind or '<empty>'}"
                    )

            pending = [
                comment_id
                for comment_id in pending
                if comment_id not in comments and comment_id not in attempted
            ]
            if new_comment_count == 0 and new_pending_count == 0:
                raise RedditResponseError(
                    "morechildren response made no progress"
                )

        self._validate_comment_parent_cycles(comments)
        roots: list[dict[str, Any]] = []
        orphan_roots: list[dict[str, Any]] = []
        for comment_id in response_order:
            comment = comments[comment_id]
            parent_id = str(comment["parent_id"])
            if parent_id == link_id:
                roots.append(comment)
                continue
            parent_comment_id = parent_id[3:]
            parent = comments.get(parent_comment_id)
            if parent is None:
                orphan_roots.append(comment)
                continue
            parent["replies"].append(comment)

        missing = [
            comment_id for comment_id in requested if comment_id not in comments
        ]
        return {
            "post_id": post_id,
            "link_id": link_id,
            "sort": normalized_sort,
            "requested": requested,
            "requested_total": len(requested),
            "total": len(comments),
            "missing": missing,
            "missing_total": len(missing),
            "orphan_total": len(orphan_roots),
            "comments": roots,
            "orphan_comments": orphan_roots,
        }

    def get_user(self, username_or_url: str) -> dict[str, Any]:
        username = self.resolve_username(username_or_url)
        payload = self._json_get(f"/user/{username}/about.json", params={})
        data = _mapping(_mapping(payload).get("data"))
        if not data.get("name"):
            raise RedditResponseError(f"Reddit user {username} was not returned")
        subreddit = _mapping(data.get("subreddit"))
        return {
            "id": str(data.get("id") or ""),
            "name": str(data.get("name") or username),
            "url": f"https://www.reddit.com/user/{username}/",
            "created_utc": _number(data.get("created_utc")),
            "comment_karma": _integer(data.get("comment_karma")),
            "link_karma": _integer(data.get("link_karma")),
            "total_karma": _integer(data.get("total_karma")),
            "is_employee": bool(data.get("is_employee")),
            "is_mod": bool(data.get("is_mod")),
            "has_verified_email": bool(data.get("has_verified_email")),
            "profile": {
                "title": str(subreddit.get("title") or ""),
                "description": str(
                    subreddit.get("public_description")
                    or subreddit.get("description")
                    or ""
                ),
                "icon": _url(subreddit.get("icon_img")),
                "banner": _url(subreddit.get("banner_img")),
            },
        }

    def get_user_trophies(self, username_or_url: str) -> dict[str, Any]:
        username = self.resolve_username(username_or_url)
        payload = self._json_get(f"/user/{username}/trophies.json", params={})
        if not isinstance(payload, Mapping) or payload.get("kind") != "TrophyList":
            raise RedditResponseError("user trophies JSON root must be a TrophyList")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise RedditResponseError("user trophies JSON data is not an object")
        raw_trophies = data.get("trophies")
        if not isinstance(raw_trophies, Sequence) or isinstance(
            raw_trophies, (str, bytes, bytearray)
        ):
            raise RedditResponseError("user trophies JSON trophies is not an array")

        trophies: list[dict[str, Any]] = []
        for item in raw_trophies:
            if not isinstance(item, Mapping) or item.get("kind") != "t6":
                raise RedditResponseError("user trophies entries must be t6 objects")
            trophy = item.get("data")
            if not isinstance(trophy, Mapping):
                raise RedditResponseError("user trophy data is not an object")
            trophies.append(
                {
                    "id": _nullable_string(trophy.get("id")),
                    "name": _nullable_string(trophy.get("name")),
                    "description": _nullable_string(trophy.get("description")),
                    "award_id": _nullable_string(trophy.get("award_id")),
                    "url": _nullable_url(trophy.get("url")),
                    "icon_40": _nullable_url(trophy.get("icon_40")),
                    "icon_70": _nullable_url(trophy.get("icon_70")),
                    "granted_at": _nullable_number(trophy.get("granted_at")),
                }
            )
        return {
            "username": username,
            "total": len(trophies),
            "trophies": trophies,
        }

    def get_user_posts(
        self,
        username_or_url: str,
        *,
        limit: int | None = 25,
        after: str | None = None,
    ) -> dict[str, Any]:
        username = self.resolve_username(username_or_url)
        return self._collect_listing(
            f"/user/{username}/submitted/.json",
            limit=limit,
            after=after,
            extra={},
            context={"username": username},
        )

    def get_user_comments(
        self,
        username_or_url: str,
        *,
        sort: str = "new",
        time_filter: str = "all",
        limit: int | None = 25,
        after: str | None = None,
    ) -> dict[str, Any]:
        username = self.resolve_username(username_or_url)
        normalized_sort = self._choice(sort, _USER_COMMENT_SORTS, "sort")
        normalized_time = self._choice(time_filter, _TIME_FILTERS, "time_filter")
        return self._collect_listing(
            f"/user/{username}/comments/.json",
            limit=limit,
            after=after,
            extra={"sort": normalized_sort, "t": normalized_time},
            context={
                "username": username,
                "sort": normalized_sort,
                "time_filter": normalized_time,
            },
            item_kind="t1",
            items_key="comments",
            cursor_kind="t1",
            normalize=self._normalize_user_comment,
        )

    def get_subreddit_info(self, subreddit: str) -> dict[str, Any]:
        requested_name = self.resolve_subreddit(subreddit)
        payload = self._json_get(f"/r/{requested_name}/about.json", params={})
        data = _mapping(_mapping(payload).get("data"))
        if not data or not any(data.get(key) for key in ("id", "name", "display_name")):
            raise RedditResponseError(f"Reddit subreddit {requested_name} was not returned")

        subreddit_id = str(data.get("id") or "")
        fullname = str(data.get("name") or "")
        if not subreddit_id and fullname.lower().startswith("t5_"):
            subreddit_id = fullname[3:]
        if not fullname and subreddit_id:
            fullname = f"t5_{subreddit_id}"
        display_name = str(data.get("display_name") or requested_name)
        relative_url = _url(data.get("url")) or f"/r/{display_name}/"
        active_users = data.get("active_user_count")
        if active_users is None:
            active_users = data.get("accounts_active")
        return {
            "name": fullname,
            "id": subreddit_id,
            "title": str(data.get("title") or ""),
            "display_name": display_name,
            "description": str(data.get("description") or ""),
            "public_description": str(data.get("public_description") or ""),
            "subscribers": _integer(data.get("subscribers")),
            "active_users": _integer(active_users),
            "over18": bool(data.get("over18")),
            "subreddit_type": str(data.get("subreddit_type") or ""),
            "url": (
                f"{_BASE_URL}{relative_url}"
                if relative_url.startswith("/")
                else relative_url
            ),
            "icon_url": _url(data.get("community_icon") or data.get("icon_img")),
            "banner_url": _url(
                data.get("banner_background_image")
                or data.get("banner_img")
                or data.get("mobile_banner_image")
            ),
            "created_utc": _number(data.get("created_utc")),
        }

    def get_subreddit_rules(self, subreddit: str) -> dict[str, Any]:
        name = self.resolve_subreddit(subreddit)
        payload = self._json_get(f"/r/{name}/about/rules.json", params={})
        if not isinstance(payload, Mapping):
            raise RedditResponseError("subreddit rules JSON root is not an object")
        rules: list[dict[str, Any]] = []
        for value in _list(payload.get("rules")):
            if not isinstance(value, Mapping):
                continue
            rules.append(
                {
                    "kind": str(value.get("kind") or ""),
                    "short_name": str(value.get("short_name") or ""),
                    "description": str(value.get("description") or ""),
                    "violation_reason": str(value.get("violation_reason") or ""),
                    "created_utc": _number(value.get("created_utc")),
                    "priority": _integer(value.get("priority")),
                }
            )
        site_rules: list[str] = []
        for value in _list(payload.get("site_rules")):
            if value is None:
                continue
            text = str(value)
            if text:
                site_rules.append(text)
        return {
            "subreddit": name,
            "total": len(rules),
            "site_rules": site_rules,
            "rules": rules,
        }

    def get_subreddit_settings(self, subreddit_fullname: str) -> dict[str, Any]:
        requested_fullname = self.resolve_subreddit_fullname(subreddit_fullname)
        payload = self._json_get(
            "/api/info.json", params={"id": requested_fullname}
        )
        if not isinstance(payload, Mapping) or payload.get("kind") != "Listing":
            raise RedditResponseError("subreddit settings JSON root must be a Listing")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise RedditResponseError("subreddit settings JSON data is not an object")
        children = data.get("children")
        if not isinstance(children, Sequence) or isinstance(
            children, (str, bytes, bytearray)
        ):
            raise RedditResponseError("subreddit settings JSON children is not an array")
        if not children:
            raise RedditResponseError(
                f"Reddit subreddit {requested_fullname} was not returned"
            )
        child = children[0]
        if not isinstance(child, Mapping) or child.get("kind") != "t5":
            raise RedditResponseError("subreddit settings first entry must be a t5 object")
        subreddit = child.get("data")
        if not isinstance(subreddit, Mapping):
            raise RedditResponseError("subreddit settings t5 data is not an object")
        response_fullname = str(subreddit.get("name") or "").strip().lower()
        if response_fullname != requested_fullname:
            raise RedditResponseError(
                "subreddit settings response fullname mismatch: "
                f"expected {requested_fullname}, got {response_fullname or '<empty>'}"
            )

        user_flair_enabled = subreddit.get("user_flair_enabled")
        if user_flair_enabled is None:
            user_flair_enabled = subreddit.get("user_flair_enabled_in_sr")
        show_media_in_comments = subreddit.get(
            "should_show_media_in_comments_setting"
        )
        if show_media_in_comments is None:
            show_media_in_comments = subreddit.get("show_media_in_comments")
        allowed_media = [
            str(value)
            for value in _list(subreddit.get("allowed_media_in_comments"))
            if value is not None and str(value)
        ]
        return {
            "fullname": response_fullname,
            "id": str(subreddit.get("id") or requested_fullname[3:]),
            "display_name": str(subreddit.get("display_name") or ""),
            "subreddit_type": str(subreddit.get("subreddit_type") or ""),
            "submission_type": str(subreddit.get("submission_type") or ""),
            "suggested_comment_sort": _nullable_string(
                subreddit.get("suggested_comment_sort")
            ),
            "spoilers_enabled": bool(subreddit.get("spoilers_enabled")),
            "wiki_enabled": bool(subreddit.get("wiki_enabled")),
            "should_archive_posts": bool(subreddit.get("should_archive_posts")),
            "allow_discovery": bool(subreddit.get("allow_discovery")),
            "allow_galleries": bool(subreddit.get("allow_galleries")),
            "allow_images": bool(subreddit.get("allow_images")),
            "allow_polls": bool(subreddit.get("allow_polls")),
            "allow_videogifs": bool(subreddit.get("allow_videogifs")),
            "allow_videos": bool(subreddit.get("allow_videos")),
            "allow_talks": bool(subreddit.get("allow_talks")),
            "restrict_posting": bool(subreddit.get("restrict_posting")),
            "restrict_commenting": bool(subreddit.get("restrict_commenting")),
            "link_flair_enabled": bool(subreddit.get("link_flair_enabled")),
            "link_flair_position": str(
                subreddit.get("link_flair_position") or ""
            ),
            "user_flair_enabled": bool(user_flair_enabled),
            "user_flair_position": str(
                subreddit.get("user_flair_position") or ""
            ),
            "can_assign_link_flair": bool(
                subreddit.get("can_assign_link_flair")
            ),
            "can_assign_user_flair": bool(
                subreddit.get("can_assign_user_flair")
            ),
            "show_media": bool(subreddit.get("show_media")),
            "show_media_preview": bool(subreddit.get("show_media_preview")),
            "show_media_in_comments": bool(show_media_in_comments),
            "allowed_media_in_comments": allowed_media,
        }

    def typeahead(
        self,
        query: str,
        *,
        limit: int = 10,
        safe_search: str = "unset",
        allow_nsfw: bool = False,
    ) -> dict[str, Any]:
        keyword = str(query or "").strip()
        if not keyword:
            raise RedditInputError("query must not be empty")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= 10:
            raise RedditInputError("limit must be an integer from 0 to 10")
        normalized_safe_search = self._choice(
            safe_search, _SAFE_SEARCH_VALUES, "safe_search"
        )
        if not isinstance(allow_nsfw, bool):
            raise RedditInputError("allow_nsfw must be a boolean")
        if normalized_safe_search == "strict" and allow_nsfw:
            raise RedditInputError(
                "safe_search=strict conflicts with allow_nsfw=true"
            )
        context = {
            "query": keyword,
            "safe_search": normalized_safe_search,
            "allow_nsfw": allow_nsfw,
        }
        if limit == 0:
            return {**context, "total": 0, "suggestions": []}

        payload = self._json_get(
            "/api/subreddit_autocomplete_v2.json",
            params={
                "query": keyword,
                "limit": limit,
                "safe_search": normalized_safe_search,
                "include_profiles": "true",
                "include_over_18": "true" if allow_nsfw else "false",
            },
        )
        if not isinstance(payload, Mapping) or payload.get("kind") != "Listing":
            raise RedditResponseError("typeahead JSON root must be a Listing")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise RedditResponseError("typeahead JSON data is not an object")
        children = data.get("children")
        if not isinstance(children, Sequence) or isinstance(
            children, (str, bytes, bytearray)
        ):
            raise RedditResponseError("typeahead JSON children is not an array")

        suggestions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for child in children:
            if not isinstance(child, Mapping):
                continue
            source_kind = str(child.get("kind") or "").lower()
            if source_kind not in {"t2", "t5"}:
                continue
            item = child.get("data")
            if not isinstance(item, Mapping):
                continue
            item_id = str(item.get("id") or "").strip().lower()
            if not item_id:
                continue
            dedupe_key = f"{source_kind}:{item_id}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            if source_kind == "t2":
                name = str(item.get("name") or "")
                profile = _mapping(item.get("subreddit"))
                icon_url = _url(item.get("icon_img") or profile.get("icon_img"))
                suggestion = {
                    "type": "user",
                    "source_kind": source_kind,
                    "id": item_id,
                    "fullname": f"t2_{item_id}",
                    "name": name,
                    "title": "",
                    "url": f"{_BASE_URL}/user/{name}/" if name else "",
                    "icon_url": icon_url,
                    "subscribers": None,
                    "over18": None,
                }
            else:
                name = str(item.get("display_name") or "")
                fullname = str(item.get("name") or f"t5_{item_id}").lower()
                relative_url = _url(item.get("url")) or (
                    f"/r/{name}/" if name else ""
                )
                suggestion = {
                    "type": "subreddit",
                    "source_kind": source_kind,
                    "id": item_id,
                    "fullname": fullname,
                    "name": name,
                    "title": str(item.get("title") or ""),
                    "url": (
                        f"{_BASE_URL}{relative_url}"
                        if relative_url.startswith("/")
                        else relative_url
                    ),
                    "icon_url": _url(
                        item.get("community_icon") or item.get("icon_img")
                    ),
                    "subscribers": _nullable_integer(item.get("subscribers")),
                    "over18": _nullable_bool(
                        item.get("over18")
                        if "over18" in item
                        else item.get("over_18")
                    ),
                }
            suggestions.append(suggestion)
            if len(suggestions) >= limit:
                break
        return {
            **context,
            "total": len(suggestions),
            "suggestions": suggestions,
        }

    def _collect_listing(
        self,
        path: str,
        *,
        limit: int | None,
        after: str | None,
        extra: Mapping[str, Any],
        context: Mapping[str, Any],
        item_kind: str = "t3",
        items_key: str = "posts",
        cursor_kind: str = "t3",
        normalize: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._validate_limit(limit)
        cursor = self._cursor(after, cursor_kind)
        if limit == 0:
            return {
                **dict(context),
                "total": 0,
                "after": cursor,
                "has_more": False,
                items_key: [],
            }
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        has_more = True
        normalizer = normalize or self._normalize_post
        while has_more and (limit is None or len(items) < limit):
            cursor_key = cursor or "first"
            if cursor_key in seen_cursors:
                raise RedditResponseError(f"listing pagination repeated cursor {cursor_key}")
            seen_cursors.add(cursor_key)
            page_size = 100 if limit is None else min(max(limit - len(items), 1), 100)
            params = {**dict(extra), "limit": page_size}
            if cursor:
                params["after"] = cursor
            payload = self._json_get(path, params=params)
            data = _mapping(_mapping(payload).get("data"))
            children = _list(data.get("children"))
            for child in children:
                wrapper = _mapping(child)
                if wrapper.get("kind") != item_kind:
                    continue
                item = normalizer(_mapping(wrapper.get("data")))
                item_id = str(item.get("id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                items.append(item)
                if limit is not None and len(items) >= limit:
                    break
            raw_next_cursor = data.get("after")
            if raw_next_cursor is None:
                next_cursor = None
            elif not isinstance(raw_next_cursor, str):
                raise RedditResponseError(
                    "listing after cursor must be a string or null"
                )
            else:
                try:
                    next_cursor = self._cursor(raw_next_cursor, cursor_kind)
                except RedditInputError as exc:
                    raise RedditResponseError(
                        f"listing after cursor must be a {cursor_kind}_ fullname cursor"
                    ) from exc
            has_more = bool(next_cursor)
            if not has_more:
                cursor = None
                break
            if next_cursor == cursor:
                raise RedditResponseError("listing response did not advance its cursor")
            if next_cursor in seen_cursors:
                raise RedditResponseError(
                    f"listing pagination repeated cursor {next_cursor}"
                )
            cursor = next_cursor
        return {
            **dict(context),
            "total": len(items),
            "after": cursor,
            "has_more": has_more,
            items_key: items,
        }

    def _json_get(self, path: str, *, params: Mapping[str, Any]) -> Any:
        self.initialize_session()
        url = f"{_BASE_URL}{path}"
        request_params = {**dict(params), "raw_json": "1"}
        request_kind = self._json_request_kind(path)
        json_headers = {
            "Referer": _JSON_REFERER,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": self.user_agent,
        }
        response = self._request(
            url,
            params=request_params,
            request_kind=request_kind,
            headers=json_headers,
            accepted_statuses={403},
        )
        if int(getattr(response, "status_code", 0) or 0) == 403:
            refreshed = self.initialize_session(force=True)
            if not refreshed:
                raise RedditResponseError(f"Reddit returned HTTP 403 for {path}")
            response = self._request(
                url,
                params=request_params,
                request_kind=request_kind,
                headers=json_headers,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RedditResponseError(f"Reddit returned invalid JSON for {path}") from exc
        if isinstance(payload, Mapping) and payload.get("error"):
            raise RedditResponseError(
                _redact_proxy(
                    f"Reddit API error {payload.get('error')}: "
                    f"{payload.get('message') or 'unknown error'}",
                    self.proxy,
                )
            )
        return payload

    @staticmethod
    def _json_request_kind(path: str) -> str:
        if path == "/search/.json":
            return "global_search"
        if path.endswith("/search/.json"):
            return "subreddit_search"
        if path.startswith("/comments/"):
            return "post_comments"
        return "json"

    def _request(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        request_kind: str = "request",
        headers: Mapping[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
        retry_statuses: set[int] | None = None,
    ) -> requests.Response:
        accepted = accepted_statuses or set()
        retryable_statuses = retry_statuses or set()
        path = urlsplit(url).path
        cooldown_remaining = self._rate_limited_until - time.monotonic()
        if cooldown_remaining > 0:
            raise RedditRateLimited(
                path,
                retry_after_seconds=cooldown_remaining,
            )
        self._rate_limited_until = 0.0
        for attempt in range(self.retries + 1):
            try:
                request_options: dict[str, Any] = {
                    "params": dict(params),
                    "headers": dict(headers) if headers else None,
                    "timeout": self.timeout,
                    "allow_redirects": True,
                }
                if self.proxy:
                    request_options["proxy"] = self.proxy
                response = self.session.get(url, **request_options)
            except Exception as exc:
                error = _request_error_brief(exc, proxy=self.proxy)
                self._emit_fetch(
                    {
                        "request_kind": request_kind,
                        "request_url": url,
                        "request_params": dict(params),
                        "attempt": attempt + 1,
                        "status_code": None,
                        "response_text": "",
                        "retry_after_seconds": None,
                        "error": error,
                    }
                )
                if attempt >= self.retries:
                    raise RedditResponseError(
                        f"Reddit request failed for {path}: {error}"
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = _integer(getattr(response, "status_code", 0))
            try:
                response_text = str(getattr(response, "text", "") or "")
            except Exception:
                response_text = ""
            retry_after = (
                _response_retry_after_seconds(response) if status == 429 else None
            )
            self._emit_fetch(
                {
                    "request_kind": request_kind,
                    "request_url": url,
                    "request_params": dict(params),
                    "attempt": attempt + 1,
                    "status_code": status,
                    "response_text": response_text,
                    "retry_after_seconds": retry_after,
                    "error": "",
                }
            )
            if 200 <= status < 300 or status in accepted:
                return response
            if status == 429:
                if retry_after is not None:
                    self._rate_limited_until = time.monotonic() + retry_after
                raise RedditRateLimited(path, retry_after_seconds=retry_after)
            if (status >= 500 or status in retryable_statuses) and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            raise RedditResponseError(f"Reddit returned HTTP {status} for {path}")
        raise RedditResponseError(f"Reddit request exhausted retries for {path}")

    def _emit_fetch(self, record: dict[str, Any]) -> None:
        """保留每次 HTTP 尝试，并将记录交给调用方的持久化回调。"""
        retained = dict(record)
        self.fetch_records.append(retained)
        if not self.on_fetch:
            return
        try:
            self.on_fetch(dict(retained))
        except Exception:
            # 原始记录回调故障不能改变 Reddit 请求本身的状态语义，也不把
            # 回调异常文本写入日志，避免第三方异常携带代理凭证。
            logger.warning("Reddit 原始响应回调失败，request_kind=%s", record.get("request_kind"))

    @classmethod
    def _normalize_post(cls, data: Mapping[str, Any]) -> dict[str, Any]:
        post_id = str(data.get("id") or "")
        permalink = _url(data.get("permalink"))
        preview = _mapping(data.get("preview"))
        images: list[dict[str, Any]] = []
        for image_value in _list(preview.get("images")):
            image = _mapping(image_value)
            source = cls._normalize_image(_mapping(image.get("source")))
            resolutions = [
                cls._normalize_image(_mapping(item))
                for item in _list(image.get("resolutions"))
                if isinstance(item, Mapping)
            ]
            if source["url"] or resolutions:
                images.append({"source": source, "resolutions": resolutions})

        video_data = _mapping(
            _mapping(data.get("secure_media")).get("reddit_video")
            or _mapping(data.get("media")).get("reddit_video")
            or preview.get("reddit_video_preview")
        )
        video = cls._normalize_video(video_data) if video_data else None
        gallery = cls._normalize_gallery(data)
        return {
            "id": post_id,
            "fullname": str(data.get("name") or (f"t3_{post_id}" if post_id else "")),
            "url": f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink,
            "permalink": permalink,
            "title": str(data.get("title") or ""),
            "text": str(data.get("selftext") or ""),
            "outbound_url": _url(data.get("url_overridden_by_dest") or data.get("url")),
            "domain": str(data.get("domain") or ""),
            "author": str(data.get("author") or ""),
            "author_fullname": str(data.get("author_fullname") or ""),
            "subreddit": str(data.get("subreddit") or ""),
            "subreddit_id": str(data.get("subreddit_id") or ""),
            "created_utc": _number(data.get("created_utc")),
            "edited": data.get("edited") if data.get("edited") not in (False, None) else None,
            "stats": {
                "score": _integer(data.get("score")),
                "upvote_ratio": _number(data.get("upvote_ratio")),
                "comments": _integer(data.get("num_comments")),
                "awards": _integer(data.get("total_awards_received")),
            },
            "is_self": bool(data.get("is_self")),
            "is_video": bool(data.get("is_video")),
            "is_gallery": bool(data.get("is_gallery")),
            "over_18": bool(data.get("over_18")),
            "spoiler": bool(data.get("spoiler")),
            "locked": bool(data.get("locked")),
            "stickied": bool(data.get("stickied")),
            "archived": bool(data.get("archived")),
            "thumbnail": _url(data.get("thumbnail")),
            "images": images,
            "video": video,
            "gallery": gallery,
            "flair": {
                "text": str(data.get("link_flair_text") or ""),
                "background_color": str(data.get("link_flair_background_color") or ""),
                "text_color": str(data.get("link_flair_text_color") or ""),
            },
            "crosspost_parent": str(data.get("crosspost_parent") or ""),
        }

    @classmethod
    def _normalize_comment(cls, data: Mapping[str, Any]) -> dict[str, Any]:
        replies_value = data.get("replies")
        reply_children = (
            cls._listing_children(replies_value)
            if isinstance(replies_value, Mapping)
            else []
        )
        replies: list[dict[str, Any]] = []
        more_ids: list[str] = []
        for child in reply_children:
            wrapper = _mapping(child)
            child_data = _mapping(wrapper.get("data"))
            if wrapper.get("kind") == "t1":
                replies.append(cls._normalize_comment(child_data))
            elif wrapper.get("kind") == "more":
                more_ids.extend(str(item) for item in _list(child_data.get("children")) if item)
        return {
            "id": str(data.get("id") or ""),
            "fullname": str(data.get("name") or ""),
            "parent_id": str(data.get("parent_id") or ""),
            "link_id": str(data.get("link_id") or ""),
            "author": str(data.get("author") or ""),
            "author_fullname": str(data.get("author_fullname") or ""),
            "text": str(data.get("body") or ""),
            "created_utc": _number(data.get("created_utc")),
            "score": _integer(data.get("score")),
            "edited": data.get("edited") if data.get("edited") not in (False, None) else None,
            "is_submitter": bool(data.get("is_submitter")),
            "stickied": bool(data.get("stickied")),
            "locked": bool(data.get("locked")),
            "controversiality": _integer(data.get("controversiality")),
            "depth": _integer(data.get("depth")),
            "replies": replies,
            "more_reply_ids": more_ids,
        }

    @classmethod
    def _normalize_user_comment(cls, data: Mapping[str, Any]) -> dict[str, Any]:
        comment = cls._normalize_comment(data)
        permalink = _url(data.get("permalink"))
        comment.update(
            {
                "name": comment["fullname"],
                "body": comment["text"],
                "url": (
                    f"{_BASE_URL}{permalink}"
                    if permalink.startswith("/")
                    else permalink
                ),
                "permalink": permalink,
                "subreddit": str(data.get("subreddit") or ""),
                "subreddit_id": str(data.get("subreddit_id") or ""),
                "link_title": str(data.get("link_title") or ""),
                "link_author": str(data.get("link_author") or ""),
                "link_url": _url(data.get("link_url")),
            }
        )
        return comment

    @staticmethod
    def _normalize_image(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "url": _url(value.get("url") or value.get("u")),
            "width": _integer(value.get("width") or value.get("x")),
            "height": _integer(value.get("height") or value.get("y")),
        }

    @staticmethod
    def _normalize_video(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "fallback_url": _url(value.get("fallback_url")),
            "hls_url": _url(value.get("hls_url")),
            "dash_url": _url(value.get("dash_url")),
            "scrubber_media_url": _url(value.get("scrubber_media_url")),
            "width": _integer(value.get("width")),
            "height": _integer(value.get("height")),
            "duration_seconds": _integer(value.get("duration")),
            "bitrate_kbps": _integer(value.get("bitrate_kbps")),
            "has_audio": bool(value.get("has_audio")),
            "is_gif": bool(value.get("is_gif")),
        }

    @classmethod
    def _normalize_gallery(cls, data: Mapping[str, Any]) -> list[dict[str, Any]]:
        metadata = _mapping(data.get("media_metadata"))
        output: list[dict[str, Any]] = []
        for item_value in _list(_mapping(data.get("gallery_data")).get("items")):
            item = _mapping(item_value)
            media_id = str(item.get("media_id") or "")
            media = _mapping(metadata.get(media_id))
            source = cls._normalize_image(_mapping(media.get("s")))
            previews = [
                cls._normalize_image(_mapping(value))
                for value in _list(media.get("p"))
                if isinstance(value, Mapping)
            ]
            output.append(
                {
                    "id": media_id,
                    "caption": str(item.get("caption") or ""),
                    "outbound_url": _url(item.get("outbound_url")),
                    "status": str(media.get("status") or ""),
                    "mime_type": str(media.get("m") or ""),
                    "source": source,
                    "previews": previews,
                }
            )
        return output

    @staticmethod
    def _listing_children(value: Any) -> list[Any]:
        return _list(_mapping(_mapping(value).get("data")).get("children"))

    @staticmethod
    def _morechildren_things(payload: Any) -> list[Any]:
        if not isinstance(payload, Mapping):
            raise RedditResponseError("morechildren JSON root is not an object")
        envelope = payload.get("json")
        if not isinstance(envelope, Mapping):
            raise RedditResponseError("morechildren JSON envelope is not an object")
        errors = envelope.get("errors")
        if not isinstance(errors, Sequence) or isinstance(
            errors, (str, bytes, bytearray)
        ):
            raise RedditResponseError("morechildren JSON errors is not an array")
        if errors:
            raise RedditResponseError(f"Reddit morechildren API errors: {list(errors)!r}")
        data = envelope.get("data")
        if not isinstance(data, Mapping):
            raise RedditResponseError("morechildren JSON data is not an object")
        things = data.get("things")
        if not isinstance(things, Sequence) or isinstance(
            things, (str, bytes, bytearray)
        ):
            raise RedditResponseError("morechildren JSON things is not an array")
        return list(things)

    @staticmethod
    def _validate_comment_parent_cycles(
        comments: Mapping[str, Mapping[str, Any]]
    ) -> None:
        states: dict[str, int] = {}

        def visit(comment_id: str) -> None:
            state = states.get(comment_id, 0)
            if state == 1:
                raise RedditResponseError(
                    f"morechildren parent cycle detected at {comment_id}"
                )
            if state == 2:
                return
            states[comment_id] = 1
            parent_id = str(comments[comment_id].get("parent_id") or "")
            if parent_id.startswith("t1_"):
                parent_comment_id = parent_id[3:]
                if parent_comment_id in comments:
                    visit(parent_comment_id)
            states[comment_id] = 2

        for comment_id in comments:
            visit(comment_id)

    @staticmethod
    def resolve_subreddit(value: str) -> str:
        text = str(value or "").strip()
        if text.lower().startswith("r/"):
            text = text[2:]
        if "://" in text or "/" in text:
            parsed = urlsplit(text if "://" in text else f"https://{text}")
            if (parsed.hostname or "").lower().rstrip(".") not in _REDDIT_HOSTS:
                raise RedditInputError("subreddit URL must use a reddit.com host")
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) < 2 or parts[0].lower() != "r":
                raise RedditInputError("URL does not identify a subreddit")
            text = parts[1]
        if not _SUBREDDIT_RE.fullmatch(text):
            raise RedditInputError("subreddit name is malformed")
        return text

    @staticmethod
    def resolve_username(value: str) -> str:
        text = str(value or "").strip()
        if text.lower().startswith("u/"):
            text = text[2:]
        if "://" in text or "/" in text:
            parsed = urlsplit(text if "://" in text else f"https://{text}")
            if (parsed.hostname or "").lower().rstrip(".") not in _REDDIT_HOSTS:
                raise RedditInputError("user URL must use a reddit.com host")
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) < 2 or parts[0].lower() not in {"u", "user"}:
                raise RedditInputError("URL does not identify a Reddit user")
            text = parts[1]
        if not _USERNAME_RE.fullmatch(text):
            raise RedditInputError("Reddit username is malformed")
        return text

    @staticmethod
    def resolve_subreddit_fullname(value: str) -> str:
        fullname = str(value or "").strip().lower()
        if _SUBREDDIT_FULLNAME_RE.fullmatch(fullname) is None:
            raise RedditInputError(
                "subreddit settings requires a t5_ base36 fullname"
            )
        return fullname

    @staticmethod
    def resolve_post_id(value: str) -> str:
        text = str(value or "").strip()
        if _POST_ID_RE.fullmatch(text):
            return text.lower()
        parsed = urlsplit(text if "://" in text else f"https://{text}")
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in _REDDIT_HOSTS:
            raise RedditInputError("post URL must use a reddit.com or redd.it host")
        parts = [part for part in parsed.path.split("/") if part]
        candidate = ""
        if host in {"redd.it", "www.redd.it"} and parts:
            candidate = parts[0]
        elif "comments" in [part.lower() for part in parts]:
            index = [part.lower() for part in parts].index("comments")
            if index + 1 < len(parts):
                candidate = parts[index + 1]
        if not _POST_ID_RE.fullmatch(candidate):
            raise RedditInputError("post URL does not contain a valid Reddit post ID")
        return candidate.lower()

    @staticmethod
    def _response_comment_id(value: Any) -> str:
        if not isinstance(value, str):
            raise RedditResponseError("morechildren comment ID must be a string")
        match = _COMMENT_ID_RE.fullmatch(value.strip())
        if match is None:
            raise RedditResponseError(
                "morechildren returned a malformed comment ID"
            )
        return match.group(1).lower()

    @staticmethod
    def _more_comment_ids(values: Sequence[str] | str) -> list[str]:
        if isinstance(values, str):
            raw_values: Sequence[str] = [values]
        elif isinstance(values, Sequence) and not isinstance(
            values, (bytes, bytearray)
        ):
            raw_values = values
        else:
            raise RedditInputError("comment IDs must be a string or sequence")

        comment_ids: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            if not isinstance(raw_value, str):
                raise RedditInputError("comment ID must be a string")
            for value in raw_value.split(","):
                text = value.strip()
                match = _COMMENT_ID_RE.fullmatch(text)
                if match is None:
                    raise RedditInputError(
                        "comment IDs must be bare base36 IDs or t1_ fullnames"
                    )
                comment_id = match.group(1).lower()
                if comment_id in seen:
                    continue
                seen.add(comment_id)
                comment_ids.append(comment_id)
                if len(comment_ids) > 100:
                    raise RedditInputError(
                        "more-comments accepts at most 100 initial comment IDs"
                    )
        if not comment_ids:
            raise RedditInputError(
                "more-comments requires at least one comment ID"
            )
        return comment_ids

    @staticmethod
    def _batch_fullnames(values: Sequence[str] | str) -> list[str]:
        if isinstance(values, str):
            raw_values: Sequence[str] = [values]
        elif isinstance(values, Sequence) and not isinstance(
            values, (bytes, bytearray)
        ):
            raw_values = values
        else:
            raise RedditInputError("batch fullnames must be a string or sequence")

        requested: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            if not isinstance(raw_value, str):
                raise RedditInputError("batch fullname must be a string")
            for raw_fullname in raw_value.split(","):
                fullname = raw_fullname.strip().lower()
                if not fullname or _INFO_FULLNAME_RE.fullmatch(fullname) is None:
                    raise RedditInputError(
                        "batch fullname must use a t1_ or t3_ base36 fullname"
                    )
                if fullname in seen:
                    continue
                seen.add(fullname)
                requested.append(fullname)
                if len(requested) > 30:
                    raise RedditInputError("batch info accepts at most 30 fullnames")
        if not requested:
            raise RedditInputError("batch info requires at least one fullname")
        return requested

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        ):
            raise RedditInputError("limit must be a non-negative integer or None")

    @staticmethod
    def _page_size(value: int, name: str, *, maximum: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RedditInputError(f"{name} must be a non-negative integer")
        return min(value, maximum)

    @staticmethod
    def _cursor(value: str | None, kind: str = "t3") -> str | None:
        if value is None:
            return None
        if kind not in {"t1", "t3"}:
            raise RedditInputError("cursor kind must be t1 or t3")
        text = str(value).strip()
        if not text:
            return None
        if not re.fullmatch(rf"{kind}_[a-z0-9]+", text, re.IGNORECASE):
            raise RedditInputError(f"after must be a {kind}_ fullname cursor")
        return text

    @staticmethod
    def _choice(value: str, choices: set[str], name: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in choices:
            expected = ", ".join(sorted(choices))
            raise RedditInputError(f"{name} must be one of: {expected}")
        return normalized
