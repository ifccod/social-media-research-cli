from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, unquote_plus, urlsplit

from curl_cffi import requests

from .errors import TwitterInputError, TwitterResponseError
from .signer import TwitterSyndicationSigner, normalize_tweet_id


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"
TWITTER_API_ORIGIN = "https://api.x.com"
TWITTER_WEB_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
GUEST_ACTIVATE_URL = f"{TWITTER_API_ORIGIN}/1.1/guest/activate.json"
TREND_LOCATIONS_URL = f"{TWITTER_API_ORIGIN}/1.1/trends/available.json"
TRENDS_PLACE_URL = f"{TWITTER_API_ORIGIN}/1.1/trends/place.json"
TWITTER_HOME_FEED_PATH = "/bridge/v1/twitter/home-feed"
TWITTER_SEARCH_POSTS_PATH = "/bridge/v1/twitter/search-posts"
TWITTER_USER_PATH = "/bridge/v1/twitter/user"
TWITTER_USER_TWEETS_PATH = "/bridge/v1/twitter/user-tweets"
TWITTER_FOLLOWERS_PATH = "/bridge/v1/twitter/followers"
TWITTER_FOLLOWING_PATH = "/bridge/v1/twitter/following"
TWITTER_HOME_REFERER = "https://x.com/home"

SYNDICATION_FEATURES = ";".join(
    (
        "tfw_timeline_list:",
        "tfw_follower_count_sunset:true",
        "tfw_tweet_edit_backend:on",
        "tfw_refsrc_session:on",
        "tfw_fosnr_soft_interventions_enabled:on",
        "tfw_show_birdwatch_pivots_enabled:on",
        "tfw_show_business_verified_badge:on",
        "tfw_duplicate_scribes_to_settings:on",
        "tfw_use_profile_image_shape_enabled:on",
        "tfw_show_blue_verified_badge:on",
        "tfw_legacy_timeline_sunset:true",
        "tfw_show_gov_verified_badge:on",
        "tfw_show_business_affiliate_badge:on",
        "tfw_tweet_edit_frontend:on",
    )
)

_TWITTER_HOSTS = {
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    "m.twitter.com",
    "x.com",
    "www.x.com",
    "mobile.x.com",
    "m.x.com",
}
_STATUS_PATH_RE = re.compile(r"/(?:status|statuses)/([1-9]\d*)(?:/|$)")
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_GUEST_TOKEN_RE = re.compile(r"^[1-9]\d{5,39}$")
_LOCATION_KEY_RE = re.compile(r"[^a-z0-9]+")
_SCREEN_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_USER_ID_RE = re.compile(r"^[1-9]\d{0,19}$")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _optional_bool(value: object) -> bool | None:
    if value is True:
        return True
    if value is False:
        return False
    return None


def _timestamp(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (OverflowError, ValueError):
        try:
            return int(
                datetime.strptime(
                    value,
                    "%a %b %d %H:%M:%S %z %Y",
                ).timestamp()
            )
        except (OverflowError, ValueError):
            return None


def _utf16_slice(value: str, start: int, end: int) -> str:
    if start < 0 or end < start:
        return value
    encoded = value.encode("utf-16-le")
    if end * 2 > len(encoded):
        return value
    try:
        return encoded[start * 2 : end * 2].decode("utf-16-le")
    except UnicodeDecodeError:
        return value


def parse_tweet_id(tweet_url_or_id: str | int) -> str:
    """从十进制 ID 或帖子直达 URL 中提取 X snowflake。"""

    if isinstance(tweet_url_or_id, bool):
        raise TwitterInputError("tweet reference must be an ID or X status URL")
    if isinstance(tweet_url_or_id, int):
        return normalize_tweet_id(tweet_url_or_id)
    if not isinstance(tweet_url_or_id, str) or not tweet_url_or_id.strip():
        raise TwitterInputError("tweet reference must be an ID or X status URL")

    candidate = tweet_url_or_id.strip()
    if candidate.isdecimal():
        return normalize_tweet_id(candidate)
    if "://" not in candidate and any(
        candidate.lower().startswith(f"{host}/") for host in _TWITTER_HOSTS
    ):
        candidate = f"https://{candidate}"

    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise TwitterInputError("tweet URL is malformed") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    scheme = parsed.scheme.lower()
    expected_port = 80 if scheme == "http" else 443
    if (
        scheme not in {"http", "https"}
        or host not in _TWITTER_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port != expected_port)
    ):
        raise TwitterInputError("tweet URL must use a supported twitter.com or x.com host")
    match = _STATUS_PATH_RE.search(parsed.path)
    if not match:
        raise TwitterInputError("tweet URL does not contain a status ID")
    return normalize_tweet_id(match.group(1))


class TwitterClient:
    """通过匿名网页接口读取 X 公开帖子和趋势。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        signer: TwitterSyndicationSigner | None = None,
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
    ) -> None:
        self.session = session or requests.Session(impersonate="chrome")
        self.signer = signer or TwitterSyndicationSigner()
        self.timeout = timeout
        self.retries = max(0, retries)
        self.browser_fetch = browser_fetch
        self.session.headers.update(
            {
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    def get_trending(
        self,
        location: str | int = "UnitedStates",
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        """返回国家、城市、国家代码或数字 WOEID 对应的趋势。"""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise TwitterInputError("trend limit must be in 1..50")
        location = self._validate_trend_location(location)
        guest_token = self._activate_guest()
        woeid, resolved = self._resolve_trend_location(location, guest_token)
        payload = self._twitter_api_json(
            TRENDS_PLACE_URL,
            guest_token=guest_token,
            params={"id": str(woeid)},
        )
        if not isinstance(payload, list) or len(payload) != 1:
            raise TwitterResponseError("trends/place JSON root must contain one result")
        root = _mapping(payload[0])
        raw_items = root.get("trends")
        if not isinstance(raw_items, list):
            raise TwitterResponseError("trends/place response does not contain trends")
        upstream_locations = _list(root.get("locations"))
        upstream_location = (
            cls_location
            if (cls_location := self._normalize_upstream_location(upstream_locations))
            else resolved
        )
        items = [
            self._normalize_trend(item, rank=index + 1)
            for index, item in enumerate(raw_items[:limit])
        ]
        return {
            "kind": "trend_list",
            "source": "twitter_web_trends",
            "transport": "web_api",
            "endpoint": "/1.1/trends/place.json",
            "location": upstream_location,
            "as_of": _text(root.get("as_of")),
            "created_at": _text(root.get("created_at")),
            "count": len(items),
            "raw_count": len(raw_items),
            "items": items,
        }

    def get_trend_locations(
        self,
        *,
        country: str = "",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """列出 X 趋势地区，可按国家或代码筛选。"""

        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000
        ):
            raise TwitterInputError("trend location limit must be in 1..1000")
        guest_token = self._activate_guest()
        locations = self._fetch_trend_locations(guest_token)
        country_key = self._location_key(country) if country else ""
        if country_key:
            locations = [
                item
                for item in locations
                if country_key
                in {
                    self._location_key(_text(item.get("country"))),
                    self._location_key(_text(item.get("country_code"))),
                    self._location_key(_text(item.get("name"))),
                }
            ]
        total = len(locations)
        if limit is not None:
            locations = locations[:limit]
        return {
            "kind": "trend_locations",
            "source": "twitter_web_trends",
            "transport": "web_api",
            "endpoint": "/1.1/trends/available.json",
            "country": country or None,
            "count": len(locations),
            "total": total,
            "items": locations,
        }

    def get_home_feed(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态读取 X For You 推荐流。"""

        limit = self._timeline_limit(limit)
        cursor = self._timeline_cursor(cursor)
        entries = [("count", str(limit))]
        if cursor:
            entries.append(("cursor", cursor))
        payload = self._browser_request(
            TWITTER_HOME_FEED_PATH,
            entries,
            TWITTER_HOME_REFERER,
        )
        return self._normalize_timeline(
            payload,
            mode="home",
            query=None,
            product=None,
            limit=limit,
        )

    def search_posts(
        self,
        query: str,
        *,
        product: str = "top",
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态主动搜索 X 帖子。"""

        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 512
            or any(character in query for character in "\r\n\0")
        ):
            raise TwitterInputError("search query must be 1..512 characters")
        query = query.strip()
        products = {"top": "Top", "latest": "Latest"}
        if product not in products:
            raise TwitterInputError("search product must be top or latest")
        limit = self._timeline_limit(limit)
        cursor = self._timeline_cursor(cursor)
        entries = [
            ("query", query),
            ("count", str(limit)),
            ("product", products[product]),
        ]
        if cursor:
            entries.append(("cursor", cursor))
        referer = "https://x.com/search?" + urlencode(
            {
                "q": query,
                "src": "typed_query",
                "f": "live" if product == "latest" else "top",
            }
        )
        payload = self._browser_request(
            TWITTER_SEARCH_POSTS_PATH,
            entries,
            referer,
        )
        return self._normalize_timeline(
            payload,
            mode="search",
            query=query,
            product=product,
            limit=limit,
        )

    def get_user(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态读取用户资料。"""

        kind, value = self._identity(screen_name, user_id)
        payload = self._browser_request(
            TWITTER_USER_PATH,
            [(kind, value)],
            TWITTER_HOME_REFERER,
        )
        return self._normalize_user_payload(
            payload,
            self_user=kind == "screen_name" and value == "me",
        )

    def get_user_tweets(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
        *,
        limit: int = 10,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态读取用户推文时间线。"""

        limit = self._timeline_limit(limit)
        cursor = self._timeline_cursor(cursor)
        entries = self._list_identity_entries(screen_name, user_id)
        entries.append(("count", str(limit)))
        if cursor:
            entries.append(("cursor", cursor))
        payload = self._browser_request(
            TWITTER_USER_TWEETS_PATH,
            entries,
            TWITTER_HOME_REFERER,
        )
        return self._normalize_timeline(
            payload,
            mode="user",
            query=None,
            product=None,
            limit=limit,
        )

    def get_followers(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态读取粉丝列表。"""

        return self._get_user_list(
            TWITTER_FOLLOWERS_PATH,
            "followers",
            screen_name,
            user_id,
            limit=limit,
            cursor=cursor,
        )

    def get_following(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态读取关注列表。"""

        return self._get_user_list(
            TWITTER_FOLLOWING_PATH,
            "following",
            screen_name,
            user_id,
            limit=limit,
            cursor=cursor,
        )

    def _get_user_list(
        self,
        path: str,
        kind: str,
        screen_name: str | None,
        user_id: str | None,
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        limit = self._timeline_limit(limit)
        cursor = self._timeline_cursor(cursor)
        entries = self._list_identity_entries(screen_name, user_id)
        self_user = entries[0] == ("screen_name", "me")
        entries.append(("count", str(limit)))
        if cursor:
            entries.append(("cursor", cursor))
        payload = self._browser_request(path, entries, TWITTER_HOME_REFERER)
        return self._normalize_user_list(
            payload,
            kind=kind,
            self_user=self_user,
            limit=limit,
        )

    def _list_identity_entries(
        self,
        screen_name: str | None,
        user_id: str | None,
    ) -> list[tuple[str, str]]:
        kind, value = self._identity(screen_name, user_id)
        if kind == "user_id" or value == "me":
            return [(kind, value)]
        profile = self.get_user(screen_name=value)
        rest_id = _text(_mapping(profile.get("user")).get("id"))
        if not rest_id or _mapping(profile.get("user")).get("unavailable") is True:
            raise TwitterResponseError(
                "X user is unavailable",
                code="invalid_response",
            )
        return [("user_id", rest_id)]

    @staticmethod
    def _identity(
        screen_name: str | None,
        user_id: str | None,
    ) -> tuple[str, str]:
        if user_id is not None and not isinstance(user_id, str):
            raise TwitterInputError("user_id must be a decimal snowflake")
        if screen_name is not None and not isinstance(screen_name, str):
            raise TwitterInputError("screen_name is invalid")
        handle = screen_name.strip() if screen_name else ""
        rest_id = user_id.strip() if user_id else ""
        if handle and rest_id:
            raise TwitterInputError(
                "screen_name and user_id are mutually exclusive"
            )
        if rest_id:
            if not _USER_ID_RE.fullmatch(rest_id):
                raise TwitterInputError("user_id must be a decimal snowflake")
            return "user_id", rest_id
        if not handle or handle == "me":
            return "screen_name", "me"
        if not _SCREEN_NAME_RE.fullmatch(handle):
            raise TwitterInputError("screen_name is invalid")
        return "screen_name", handle

    def _browser_request(
        self,
        path: str,
        entries: Sequence[tuple[str, str]],
        referer: str,
    ) -> Mapping[str, Any]:
        if self.browser_fetch is None:
            raise TwitterResponseError(
                "Twitter browser session transport is not configured"
            )
        payload = self.browser_fetch(path, entries, referer)
        if not isinstance(payload, Mapping):
            raise TwitterResponseError(
                "Twitter browser session response must be an object"
            )
        return payload

    @staticmethod
    def _timeline_limit(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 100
        ):
            raise TwitterInputError("timeline limit must be in 1..100")
        return value

    @staticmethod
    def _timeline_cursor(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if (
            not isinstance(value, str)
            or len(value) > 2048
            or any(character in value for character in "\r\n\0")
        ):
            raise TwitterInputError("timeline cursor is invalid")
        return value

    @classmethod
    def _normalize_timeline(
        cls,
        payload: Mapping[str, Any],
        *,
        mode: str,
        query: str | None,
        product: str | None,
        limit: int,
    ) -> dict[str, Any]:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TwitterResponseError(
                "Twitter timeline response does not contain data",
                code="invalid_response",
            )
        entries = list(cls._timeline_entries(data))
        posts: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursors: dict[str, str] = {}
        for entry in entries:
            content = _mapping(entry.get("content"))
            for cursor_type, cursor_value in cls._timeline_cursors(content):
                cursors[cursor_type.lower()] = cursor_value
            promoted = cls._timeline_has_key(content, "promotedMetadata")
            for result in cls._timeline_tweet_results(content):
                post = cls._normalize_graphql_tweet(
                    result,
                    promoted=promoted,
                )
                if post is None or post["id"] in seen:
                    continue
                seen.add(post["id"])
                posts.append(post)
        posts = posts[:limit]
        return {
            "kind": "twitter_timeline",
            "source": _text(payload.get("source")) or "twitter_web_graphql",
            "transport": _text(payload.get("transport")) or "browser_web",
            "endpoint": _text(payload.get("endpoint")),
            "operation": _text(payload.get("operation")),
            "browser_session": True,
            "mode": mode,
            "query": query,
            "product": product,
            "count": len(posts),
            "posts": posts,
            "next_cursor": cursors.get("bottom"),
            "previous_cursor": cursors.get("top"),
            "has_more": bool(cursors.get("bottom")),
            "rate_limit": dict(_mapping(payload.get("rate_limit"))),
        }

    @classmethod
    def _timeline_entries(
        cls,
        value: object,
    ):
        if isinstance(value, Mapping):
            if isinstance(value.get("entryId"), str) and isinstance(
                value.get("content"),
                Mapping,
            ):
                yield value
                return
            for nested in value.values():
                yield from cls._timeline_entries(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from cls._timeline_entries(nested)

    @classmethod
    def _normalize_user_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        self_user: bool,
    ) -> dict[str, Any]:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TwitterResponseError(
                "Twitter user response does not contain data",
                code="invalid_response",
            )
        result = _mapping(_mapping(data.get("user")).get("result"))
        user = cls._normalize_graphql_user(result, allow_unavailable=True)
        if user is None:
            raise TwitterResponseError(
                "Twitter user response does not contain a user",
                code="invalid_response",
            )
        return {
            "kind": "twitter_user",
            "source": _text(payload.get("source")) or "twitter_web_graphql",
            "transport": _text(payload.get("transport")) or "browser_web",
            "endpoint": _text(payload.get("endpoint")),
            "operation": _text(payload.get("operation")),
            "browser_session": True,
            "self": self_user,
            "user": user,
            "rate_limit": dict(_mapping(payload.get("rate_limit"))),
        }

    @classmethod
    def _normalize_user_list(
        cls,
        payload: Mapping[str, Any],
        *,
        kind: str,
        self_user: bool,
        limit: int,
    ) -> dict[str, Any]:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TwitterResponseError(
                "Twitter user list response does not contain data",
                code="invalid_response",
            )
        result = _mapping(_mapping(data.get("user")).get("result"))
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursors: dict[str, str] = {}
        if _text(result.get("__typename")) != "UserUnavailable":
            for entry in cls._timeline_entries(data):
                content = _mapping(entry.get("content"))
                for cursor_type, cursor_value in cls._timeline_cursors(content):
                    cursors[cursor_type.lower()] = cursor_value
                for node in cls._timeline_user_results(content):
                    user = cls._normalize_graphql_user(node)
                    if user is None or user["id"] in seen:
                        continue
                    seen.add(user["id"])
                    items.append(user)
        items = items[:limit]
        return {
            "kind": f"twitter_{kind}",
            "source": _text(payload.get("source")) or "twitter_web_graphql",
            "transport": _text(payload.get("transport")) or "browser_web",
            "endpoint": _text(payload.get("endpoint")),
            "operation": _text(payload.get("operation")),
            "browser_session": True,
            "self": self_user,
            "count": len(items),
            "items": items,
            "next_cursor": cursors.get("bottom"),
            "previous_cursor": cursors.get("top"),
            "has_more": bool(cursors.get("bottom")),
            "rate_limit": dict(_mapping(payload.get("rate_limit"))),
        }

    @classmethod
    def _normalize_graphql_user(
        cls,
        value: Mapping[str, Any],
        *,
        allow_unavailable: bool = False,
    ) -> dict[str, Any] | None:
        if not value:
            return None
        unavailable = _text(value.get("__typename")) == "UserUnavailable"
        if unavailable and not allow_unavailable:
            return None
        core = _mapping(value.get("core"))
        legacy = _mapping(value.get("legacy"))
        avatar = _mapping(value.get("avatar"))
        verification = _mapping(value.get("verification"))
        relationships = _mapping(value.get("relationship_counts"))
        privacy = _mapping(value.get("privacy"))
        rest_id = _text(value.get("rest_id")) or _text(legacy.get("id_str"))
        if not unavailable and (not rest_id or not rest_id.isdecimal()):
            return None
        username = _text(core.get("screen_name")) or _text(
            legacy.get("screen_name")
        )
        homepage = f"https://x.com/{username}" if username else ""
        verified = (
            verification.get("verified") is True or legacy.get("verified") is True
        )
        blue_verified = value.get("is_blue_verified") is True
        description = _text(
            _mapping(value.get("profile_bio")).get("description")
        ) or _text(legacy.get("description"))
        perspectives = _mapping(value.get("relationship_perspectives"))
        followed_by_me = _optional_bool(perspectives.get("following"))
        if followed_by_me is None:
            followed_by_me = _optional_bool(legacy.get("following"))
        return {
            "id": rest_id,
            "name": _text(core.get("name")) or _text(legacy.get("name")),
            "username": username,
            "url": homepage,
            "homepage": homepage,
            "avatar_url": (
                _text(avatar.get("image_url"))
                or _text(legacy.get("profile_image_url_https"))
            ),
            "description": description,
            "verified": verified or blue_verified,
            "legacy_verified": verified,
            "blue_verified": blue_verified,
            "verified_type": _text(
                verification.get("verified_type") or legacy.get("verified_type")
            ),
            "profile_image_shape": _text(value.get("profile_image_shape")),
            "followers": _optional_int(
                relationships.get("followers", legacy.get("followers_count"))
            ),
            "following": _optional_int(
                relationships.get("following", legacy.get("friends_count"))
            ),
            "followed_by_me": followed_by_me,
            "protected": (
                privacy.get("protected") is True
                or legacy.get("protected") is True
            ),
            "unavailable": unavailable,
        }

    @classmethod
    def _timeline_user_results(
        cls,
        value: object,
    ):
        if isinstance(value, Mapping):
            user_results = value.get("user_results")
            if isinstance(user_results, Mapping):
                result = user_results.get("result")
                if isinstance(result, Mapping):
                    yield result
                return
            for nested in value.values():
                yield from cls._timeline_user_results(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from cls._timeline_user_results(nested)

    @classmethod
    def _timeline_tweet_results(
        cls,
        value: object,
    ):
        if isinstance(value, Mapping):
            tweet_results = value.get("tweet_results")
            if isinstance(tweet_results, Mapping):
                result = tweet_results.get("result")
                if isinstance(result, Mapping):
                    yield result
                return
            for nested in value.values():
                yield from cls._timeline_tweet_results(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from cls._timeline_tweet_results(nested)

    @classmethod
    def _timeline_cursors(
        cls,
        value: object,
    ):
        if isinstance(value, Mapping):
            cursor_type = _text(value.get("cursorType"))
            cursor_value = _text(value.get("value"))
            if cursor_type and cursor_value:
                yield cursor_type, cursor_value
                return
            for nested in value.values():
                yield from cls._timeline_cursors(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from cls._timeline_cursors(nested)

    @classmethod
    def _timeline_has_key(cls, value: object, name: str) -> bool:
        if isinstance(value, Mapping):
            if name in value:
                return True
            return any(
                cls._timeline_has_key(nested, name)
                for nested in value.values()
            )
        if isinstance(value, list):
            return any(cls._timeline_has_key(nested, name) for nested in value)
        return False

    @classmethod
    def _normalize_graphql_tweet(
        cls,
        value: Mapping[str, Any],
        *,
        promoted: bool,
    ) -> dict[str, Any] | None:
        result = value
        if _text(result.get("__typename")) == "TweetWithVisibilityResults":
            result = _mapping(result.get("tweet"))
        legacy = dict(_mapping(result.get("legacy")))
        identifier = _text(result.get("rest_id")) or _text(legacy.get("id_str"))
        if not identifier or not identifier.isdecimal():
            return None
        user_result = _mapping(
            _mapping(_mapping(result.get("core")).get("user_results")).get(
                "result"
            )
        )
        if _text(user_result.get("__typename")) == "UserUnavailable":
            return None
        user_core = _mapping(user_result.get("core"))
        user_legacy = dict(_mapping(user_result.get("legacy")))
        avatar = _mapping(user_result.get("avatar"))
        verification = _mapping(user_result.get("verification"))
        relationships = _mapping(user_result.get("relationship_counts"))
        user_legacy.update(
            {
                "id_str": (
                    _text(user_result.get("rest_id"))
                    or _text(user_legacy.get("id_str"))
                ),
                "name": (
                    _text(user_core.get("name"))
                    or _text(user_legacy.get("name"))
                ),
                "screen_name": (
                    _text(user_core.get("screen_name"))
                    or _text(user_legacy.get("screen_name"))
                ),
                "profile_image_url_https": (
                    _text(avatar.get("image_url"))
                    or _text(user_legacy.get("profile_image_url_https"))
                ),
                "verified": (
                    verification.get("verified") is True
                    or user_legacy.get("verified") is True
                ),
                "is_blue_verified": user_result.get("is_blue_verified") is True,
                "profile_image_shape": _text(
                    user_result.get("profile_image_shape")
                ),
                "description": (
                    _text(
                        _mapping(user_result.get("profile_bio")).get(
                            "description"
                        )
                    )
                    or _text(user_legacy.get("description"))
                ),
            }
        )
        extended_entities = _mapping(legacy.get("extended_entities"))
        payload = {
            **legacy,
            "id_str": identifier,
            "text": _text(legacy.get("full_text")),
            "user": user_legacy,
            "note_tweet": result.get("note_tweet"),
            "mediaDetails": _list(extended_entities.get("media")),
        }
        try:
            normalized = cls.normalize_tweet(payload)
        except TwitterResponseError:
            return None
        views = _mapping(result.get("views"))
        normalized["stats"].update(
            {
                "quotes": _optional_int(legacy.get("quote_count")),
                "bookmarks": _optional_int(legacy.get("bookmark_count")),
                "views": _optional_int(views.get("count")),
            }
        )
        normalized["author"].update(
            {
                "followers": _optional_int(
                    relationships.get(
                        "followers",
                        user_legacy.get("followers_count"),
                    )
                ),
                "following": _optional_int(
                    relationships.get(
                        "following",
                        user_legacy.get("friends_count"),
                    )
                ),
            }
        )
        normalized["promoted"] = promoted
        normalized["display_type"] = _text(result.get("__typename")) or "Tweet"
        return normalized

    def _activate_guest(self) -> str:
        payload = self._twitter_api_json(
            GUEST_ACTIVATE_URL,
            method="POST",
            guest_token="",
        )
        if not isinstance(payload, Mapping):
            raise TwitterResponseError("guest activation JSON root must be an object")
        token = _text(payload.get("guest_token"))
        if not _GUEST_TOKEN_RE.fullmatch(token):
            raise TwitterResponseError("guest activation response has no valid guest_token")
        return token

    def _fetch_trend_locations(self, guest_token: str) -> list[dict[str, Any]]:
        payload = self._twitter_api_json(
            TREND_LOCATIONS_URL,
            guest_token=guest_token,
        )
        if not isinstance(payload, list):
            raise TwitterResponseError("trends/available JSON root must be an array")
        locations = [
            self._normalize_location(item)
            for item in payload
            if isinstance(item, Mapping)
        ]
        if not locations:
            raise TwitterResponseError("trends/available returned no valid locations")
        return locations

    def _resolve_trend_location(
        self,
        reference: str | int,
        guest_token: str,
    ) -> tuple[int, dict[str, Any]]:
        reference = self._validate_trend_location(reference)
        if isinstance(reference, int):
            return reference, {"name": "", "woeid": reference}
        candidate = reference

        key = self._location_key(candidate)
        locations = self._fetch_trend_locations(guest_token)
        matches = [
            item
            for item in locations
            if key == self._location_key(_text(item.get("name")))
        ]
        if not matches:
            matches = [
                item
                for item in locations
                if _text(item.get("place_type")).lower() == "country"
                and key
                in {
                    self._location_key(_text(item.get("country"))),
                    self._location_key(_text(item.get("country_code"))),
                }
            ]
        if not matches:
            raise TwitterInputError(
                f"trend location {candidate!r} is not in X trends/available"
            )
        if len(matches) > 1:
            names = ", ".join(
                f"{_text(item.get('name'))} ({_text(item.get('country_code'))})"
                for item in matches[:5]
            )
            raise TwitterInputError(
                f"trend location {candidate!r} is ambiguous: {names}"
            )
        return int(matches[0]["woeid"]), matches[0]

    @staticmethod
    def _validate_trend_location(reference: str | int) -> str | int:
        if isinstance(reference, bool):
            raise TwitterInputError("trend location must be a name, code, or WOEID")
        if isinstance(reference, int):
            if reference < 1:
                raise TwitterInputError("trend WOEID must be positive")
            return reference
        if not isinstance(reference, str) or not reference.strip():
            raise TwitterInputError("trend location must be a name, code, or WOEID")
        candidate = reference.strip()
        if len(candidate) > 100:
            raise TwitterInputError("trend location is too long")
        if candidate.isdecimal():
            woeid = int(candidate)
            if woeid < 1:
                raise TwitterInputError("trend WOEID must be positive")
            return woeid
        return candidate

    def _twitter_api_json(
        self,
        url: str,
        *,
        guest_token: str,
        method: str = "GET",
        params: Mapping[str, str] | None = None,
    ) -> object:
        headers = {
            "Authorization": f"Bearer {TWITTER_WEB_BEARER_TOKEN}",
            "X-Twitter-Active-User": "yes",
            "X-Twitter-Client-Language": "en",
        }
        if guest_token:
            headers["X-Guest-Token"] = guest_token
        request = self.session.post if method == "POST" else self.session.get
        for attempt in range(self.retries + 1):
            try:
                response = request(
                    url,
                    params=dict(params or {}),
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise TwitterResponseError(f"Twitter Web request failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise TwitterResponseError(
                        "Twitter Web response is not valid JSON"
                    ) from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.retries:
                    time.sleep(0.4 * (2**attempt))
                    continue
            if response.status_code == 404:
                raise TwitterResponseError("trend location is not available")
            raise TwitterResponseError(
                f"Twitter Web returned HTTP {response.status_code}"
            )
        raise TwitterResponseError("Twitter Web request exhausted all retries")

    @classmethod
    def _normalize_location(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        place_type = _mapping(value.get("placeType"))
        woeid = _optional_int(value.get("woeid"))
        if not _text(value.get("name")) or woeid is None or woeid < 1:
            raise TwitterResponseError("trends/available contains an invalid location")
        return {
            "name": _text(value.get("name")),
            "woeid": woeid,
            "country": _text(value.get("country")),
            "country_code": _text(value.get("countryCode")) or None,
            "parent_id": _optional_int(value.get("parentid")),
            "place_type": _text(place_type.get("name")),
            "place_type_code": _optional_int(place_type.get("code")),
        }

    @classmethod
    def _normalize_upstream_location(
        cls,
        values: list[Any],
    ) -> dict[str, Any] | None:
        if len(values) != 1:
            return None
        value = _mapping(values[0])
        name = _text(value.get("name"))
        woeid = _optional_int(value.get("woeid"))
        if not name or woeid is None or woeid < 1:
            return None
        return {"name": name, "woeid": woeid}

    @classmethod
    def _normalize_trend(
        cls,
        value: object,
        *,
        rank: int,
    ) -> dict[str, Any]:
        trend = _mapping(value)
        name = _text(trend.get("name"))
        query = _text(trend.get("query"))
        if not name or not query:
            raise TwitterResponseError("trends/place contains an invalid trend item")
        query_text = unquote_plus(query)
        canonical_url = "https://x.com/search?" + urlencode(
            {"q": query_text, "src": "trend_click"}
        )
        return {
            "rank": rank,
            "name": name,
            "query": query_text,
            "url": canonical_url,
            "upstream_url": _text(trend.get("url")),
            "tweet_volume": _optional_int(trend.get("tweet_volume")),
            "promoted_content": trend.get("promoted_content"),
        }

    @staticmethod
    def _location_key(value: str) -> str:
        return _LOCATION_KEY_RE.sub("", value.strip().lower())

    def get_tweet(
        self,
        tweet_url_or_id: str | int,
        *,
        language: str = "en",
    ) -> dict[str, Any]:
        identifier = parse_tweet_id(tweet_url_or_id)
        payload = self._get_tweet_payload(identifier, language=language)
        return self.normalize_tweet(payload, requested_id=identifier)

    def get_tweet_raw(
        self,
        tweet_url_or_id: str | int,
        *,
        language: str = "en",
    ) -> dict[str, Any]:
        identifier = parse_tweet_id(tweet_url_or_id)
        return self._get_tweet_payload(identifier, language=language)

    def _get_tweet_payload(self, identifier: str, *, language: str) -> dict[str, Any]:
        language = self._language(language)
        signed = self.signer.sign(identifier)
        params = {
            "id": signed["id"],
            "lang": language,
            "features": SYNDICATION_FEATURES,
            "token": signed["token"],
        }

        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    SYNDICATION_URL,
                    params=params,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise TwitterResponseError(f"Syndication request failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue

            if response.status_code == 200:
                payload = self._json(response)
                if not payload:
                    raise TwitterResponseError(f"tweet {identifier} was not found")
                typename = _text(payload.get("__typename"))
                if typename == "TweetTombstone":
                    raise TwitterResponseError(f"tweet {identifier} returned a tombstone")
                if typename and typename != "Tweet":
                    raise TwitterResponseError(
                        f"tweet {identifier} returned unexpected type {typename!r}"
                    )
                if not _text(payload.get("id_str")):
                    raise TwitterResponseError(
                        f"tweet {identifier} response does not contain id_str"
                    )
                return payload

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.retries:
                    time.sleep(0.4 * (2**attempt))
                    continue
            if response.status_code == 404:
                raise TwitterResponseError(f"tweet {identifier} was not found")
            raise TwitterResponseError(
                f"Syndication returned HTTP {response.status_code} for tweet {identifier}"
            )
        raise TwitterResponseError("Syndication request exhausted all retries")

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise TwitterResponseError("Syndication response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise TwitterResponseError("Syndication JSON root must be an object")
        return payload

    @staticmethod
    def _language(value: str) -> str:
        if not isinstance(value, str) or not _LANGUAGE_RE.fullmatch(value):
            raise TwitterInputError("language must be a short BCP 47 language tag")
        return value

    @classmethod
    def normalize_tweet(
        cls,
        payload: Mapping[str, Any],
        *,
        requested_id: str | int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise TwitterResponseError("tweet payload must be an object")
        identifier = _text(payload.get("id_str"))
        try:
            identifier = normalize_tweet_id(identifier)
        except TwitterInputError as exc:
            raise TwitterResponseError("tweet payload contains an invalid id_str") from exc

        normalized_requested_id = (
            normalize_tweet_id(requested_id) if requested_id is not None else identifier
        )
        user = _mapping(payload.get("user"))
        username = _text(user.get("screen_name"))
        url = (
            f"https://x.com/{username}/status/{identifier}"
            if username
            else f"https://x.com/i/status/{identifier}"
        )
        syndication_text = _text(payload.get("text"))
        note_tweet = _mapping(payload.get("note_tweet"))
        note_result = cls._note_tweet_result(note_tweet)
        note_text = _text(note_result.get("text"))
        raw_text = note_text or syndication_text
        display_range = _list(
            note_result.get("display_text_range")
            if note_text
            else payload.get("display_text_range")
        )
        visible_text = raw_text
        if len(display_range) == 2:
            start = _optional_int(display_range[0])
            end = _optional_int(display_range[1])
            if start is not None and end is not None:
                visible_text = _utf16_slice(raw_text, start, end)

        entity_source = (
            note_result.get("entity_set", note_result.get("entities"))
            if note_text
            else payload.get("entities")
        )
        entities = cls._normalize_entities(entity_source)
        quoted_payload = payload.get("quoted_tweet")
        quoted_tweet = (
            cls.normalize_tweet(_mapping(quoted_payload))
            if isinstance(quoted_payload, Mapping)
            else None
        )
        parent_payload = payload.get("parent")
        parent = (
            cls.normalize_tweet(_mapping(parent_payload))
            if isinstance(parent_payload, Mapping)
            else None
        )
        edit_control = dict(_mapping(payload.get("edit_control")))
        edit_ids = {
            _text(item)
            for item in _list(edit_control.get("edit_tweet_ids"))
            if _text(item)
        }
        resolved_from_edit = (
            normalized_requested_id != identifier
            and normalized_requested_id in edit_ids
        )
        is_retweet = normalized_requested_id != identifier and not resolved_from_edit
        retweet = None
        if is_retweet:
            retweet = {
                "id": normalized_requested_id,
                "url": f"https://x.com/i/status/{normalized_requested_id}",
                "source_tweet_id": identifier,
                "source_tweet_url": url,
            }

        reply_to = None
        reply_id = _text(payload.get("in_reply_to_status_id_str"))
        if reply_id:
            reply_username = _text(payload.get("in_reply_to_screen_name"))
            reply_to = {
                "tweet_id": reply_id,
                "user_id": _text(payload.get("in_reply_to_user_id_str")),
                "username": reply_username,
                "url": (
                    f"https://x.com/{reply_username}/status/{reply_id}"
                    if reply_username
                    else f"https://x.com/i/status/{reply_id}"
                ),
            }

        created_at = _text(payload.get("created_at"))
        return {
            "id": identifier,
            "requested_id": normalized_requested_id,
            "url": url,
            "requested_url": f"https://x.com/i/status/{normalized_requested_id}",
            "author": cls._normalize_author(user),
            "text": visible_text,
            "raw_text": raw_text,
            "text_truncated": bool(note_tweet) and not bool(note_text),
            "note_tweet_id": _text(note_result.get("id")) or _text(note_tweet.get("id")),
            "language": _text(payload.get("lang")),
            "created_at": created_at,
            "created_timestamp": _timestamp(created_at),
            "stats": {
                "likes": _optional_int(payload.get("favorite_count")),
                "replies": _optional_int(
                    payload.get("conversation_count", payload.get("reply_count"))
                ),
                "reposts": _optional_int(payload.get("retweet_count")),
            },
            "media": cls._normalize_media(payload),
            "links": entities["urls"],
            "entities": entities,
            "possibly_sensitive": bool(payload.get("possibly_sensitive", False)),
            "edited": bool(payload.get("isEdited", False)),
            "edit_control": edit_control,
            "resolved_from_edit": resolved_from_edit,
            "reply_to": reply_to,
            "parent": parent,
            "quoted_tweet": quoted_tweet,
            "is_retweet": is_retweet,
            "retweet": retweet,
        }

    @staticmethod
    def _note_tweet_result(note_tweet: Mapping[str, Any]) -> Mapping[str, Any]:
        if not note_tweet:
            return {}
        nested = _mapping(_mapping(note_tweet.get("note_tweet_results")).get("result"))
        if nested:
            return nested
        direct_result = _mapping(note_tweet.get("result"))
        return direct_result or note_tweet

    @staticmethod
    def _normalize_author(user: Mapping[str, Any]) -> dict[str, Any]:
        username = _text(user.get("screen_name"))
        verified = bool(user.get("verified", False))
        blue_verified = bool(user.get("is_blue_verified", False))
        return {
            "id": _text(user.get("id_str")),
            "name": _text(user.get("name")),
            "username": username,
            "url": f"https://x.com/{username}" if username else "",
            "avatar_url": _text(user.get("profile_image_url_https")),
            "description": _text(user.get("description")),
            "verified": verified or blue_verified,
            "legacy_verified": verified,
            "blue_verified": blue_verified,
            "verified_type": _text(user.get("verified_type")),
            "profile_image_shape": _text(user.get("profile_image_shape")),
        }

    @staticmethod
    def _normalize_entities(value: object) -> dict[str, list[dict[str, Any]]]:
        entities = _mapping(value)

        def indices(item: Mapping[str, Any]) -> list[int]:
            raw = _list(item.get("indices"))
            output = [_optional_int(entry) for entry in raw[:2]]
            return [entry for entry in output if entry is not None]

        urls = [
            {
                "url": _text(item.get("url")),
                "display_url": _text(item.get("display_url")),
                "expanded_url": _text(item.get("expanded_url")),
                "indices": indices(item),
            }
            for item in map(_mapping, _list(entities.get("urls")))
        ]
        hashtags = [
            {"text": _text(item.get("text")), "indices": indices(item)}
            for item in map(_mapping, _list(entities.get("hashtags")))
        ]
        mentions = [
            {
                "id": _text(item.get("id_str")),
                "name": _text(item.get("name")),
                "username": _text(item.get("screen_name")),
                "indices": indices(item),
            }
            for item in map(_mapping, _list(entities.get("user_mentions")))
        ]
        symbols = [
            {"text": _text(item.get("text")), "indices": indices(item)}
            for item in map(_mapping, _list(entities.get("symbols")))
        ]
        return {
            "urls": urls,
            "hashtags": hashtags,
            "mentions": mentions,
            "symbols": symbols,
        }

    @classmethod
    def _normalize_media(cls, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        details = [_mapping(item) for item in _list(payload.get("mediaDetails"))]
        if details:
            return [cls._normalize_media_detail(item) for item in details]

        output: list[dict[str, Any]] = []
        for photo_value in _list(payload.get("photos")):
            photo = _mapping(photo_value)
            output.append(
                {
                    "type": "photo",
                    "url": _text(photo.get("url")),
                    "thumbnail_url": _text(photo.get("url")),
                    "expanded_url": _text(photo.get("expandedUrl")),
                    "width": _optional_int(photo.get("width")),
                    "height": _optional_int(photo.get("height")),
                    "alt_text": "",
                    "duration_ms": None,
                    "aspect_ratio": [],
                    "availability": "",
                    "variants": [],
                }
            )
        video = _mapping(payload.get("video"))
        if video:
            variants = [
                {
                    "url": _text(_mapping(item).get("src")),
                    "content_type": _text(_mapping(item).get("type")),
                    "bitrate": None,
                }
                for item in _list(video.get("variants"))
            ]
            output.append(
                {
                    "type": "video",
                    "url": cls._best_video_url(variants),
                    "thumbnail_url": _text(video.get("poster")),
                    "expanded_url": "",
                    "width": None,
                    "height": None,
                    "alt_text": "",
                    "duration_ms": _optional_int(video.get("durationMs")),
                    "aspect_ratio": _list(video.get("aspectRatio")),
                    "availability": _text(
                        _mapping(video.get("mediaAvailability")).get("status")
                    ),
                    "variants": variants,
                }
            )
        return output

    @classmethod
    def _normalize_media_detail(cls, media: Mapping[str, Any]) -> dict[str, Any]:
        media_type = _text(media.get("type"))
        original = _mapping(media.get("original_info"))
        video_info = _mapping(media.get("video_info"))
        variants = [
            {
                "url": _text(variant.get("url")),
                "content_type": _text(variant.get("content_type")),
                "bitrate": _optional_int(variant.get("bitrate")),
            }
            for variant in map(_mapping, _list(video_info.get("variants")))
        ]
        thumbnail_url = _text(media.get("media_url_https"))
        url = thumbnail_url if media_type == "photo" else cls._best_video_url(variants)
        return {
            "type": media_type,
            "url": url,
            "thumbnail_url": thumbnail_url,
            "expanded_url": _text(media.get("expanded_url")),
            "width": _optional_int(original.get("width")),
            "height": _optional_int(original.get("height")),
            "alt_text": _text(media.get("ext_alt_text")),
            "duration_ms": _optional_int(video_info.get("duration_millis")),
            "aspect_ratio": _list(video_info.get("aspect_ratio")),
            "availability": _text(
                _mapping(media.get("ext_media_availability")).get("status")
            ),
            "variants": variants,
        }

    @staticmethod
    def _best_video_url(variants: list[dict[str, Any]]) -> str:
        mp4 = [
            item
            for item in variants
            if item.get("content_type") == "video/mp4" and item.get("url")
        ]
        if mp4:
            return _text(max(mp4, key=lambda item: item.get("bitrate") or 0).get("url"))
        return _text(next((item.get("url") for item in variants if item.get("url")), ""))


__all__ = [
    "DEFAULT_USER_AGENT",
    "SYNDICATION_FEATURES",
    "SYNDICATION_URL",
    "TWITTER_FOLLOWERS_PATH",
    "TWITTER_FOLLOWING_PATH",
    "TWITTER_HOME_FEED_PATH",
    "TWITTER_HOME_REFERER",
    "TWITTER_SEARCH_POSTS_PATH",
    "TWITTER_USER_PATH",
    "TWITTER_USER_TWEETS_PATH",
    "TwitterClient",
    "parse_tweet_id",
]
