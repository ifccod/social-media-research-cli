from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from curl_cffi import requests

from .errors import InstagramInputError, InstagramResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
WEB_APP_ID = "936619743392459"

_BASE_URL = "https://www.instagram.com"
_PROFILE_INFO_URL = f"{_BASE_URL}/api/v1/users/web_profile_info/"
_SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_SHORTCODE_INDEX = {character: index for index, character in enumerate(_SHORTCODE_ALPHABET)}
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?$")
_SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_HANDLE_CALL_RE = re.compile(r"\.handle\(")
_POST_ROUTES = {"p", "reel", "tv"}
_RESERVED_PROFILE_ROUTES = {
    "about",
    "accounts",
    "api",
    "developer",
    "developers",
    "direct",
    "directory",
    "emails",
    "explore",
    "legal",
    "p",
    "press",
    "privacy",
    "reel",
    "reels",
    "stories",
    "tv",
    "web",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _integer(value)
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _edge_count(raw: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        edge = raw.get(key)
        if isinstance(edge, Mapping) and "count" in edge:
            return _integer(edge.get("count"))
    return 0


def _caption(raw: Mapping[str, Any]) -> str:
    direct = raw.get("caption")
    if isinstance(direct, Mapping):
        return str(direct.get("text") or "")
    if isinstance(direct, str):
        return direct
    edges = _list(_mapping(raw.get("edge_media_to_caption")).get("edges"))
    for edge in edges:
        text = _mapping(_mapping(edge).get("node")).get("text")
        if text is not None:
            return str(text)
    return ""


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self._inside_script = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._inside_script = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._inside_script:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._inside_script:
            self.scripts.append("".join(self._buffer))
            self._inside_script = False
            self._buffer = []


class InstagramClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        app_id: str = WEB_APP_ID,
        timeout: float = 20,
        retries: int = 2,
    ) -> None:
        self.session = session or requests.Session(impersonate="chrome")
        self.timeout = timeout
        self.retries = max(0, retries)
        self._identity_ready = False
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": user_agent,
                "X-ASBD-ID": "129477",
                "X-IG-App-ID": app_id,
            }
        )

    def initialize_session(self) -> None:
        """通过常规 HTTP GET 初始化 Instagram 匿名 Cookie。"""
        if self._identity_ready:
            return
        self._request(
            f"{_BASE_URL}/",
            params={},
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        csrf_token = self._cookie_value("csrftoken")
        if csrf_token:
            self.session.headers["X-CSRFToken"] = csrf_token
        self._identity_ready = True

    def get_user_profile(self, username_or_url: str) -> dict[str, Any]:
        username = self.resolve_username(username_or_url)
        user = self._get_profile_user(username)
        return self._normalize_profile(user)

    def get_profile(self, username_or_url: str) -> dict[str, Any]:
        return self.get_user_profile(username_or_url)

    def get_profile_page(
        self,
        username_or_url: str,
        *,
        limit: int | None = 12,
    ) -> dict[str, Any]:
        username = self.resolve_username(username_or_url)
        self._validate_limit(limit)
        user = self._get_profile_user(username)
        timeline = _mapping(user.get("edge_owner_to_timeline_media"))
        posts = self._normalize_post_edges(timeline, limit=limit)
        page_info = _mapping(timeline.get("page_info"))
        return {
            "profile": self._normalize_profile(user),
            "available": _integer(timeline.get("count")),
            "total": len(posts),
            "has_more": bool(page_info.get("has_next_page")),
            "next_cursor": str(page_info.get("end_cursor") or "") or None,
            "posts": posts,
        }

    def get_user_posts(
        self,
        username_or_url: str,
        *,
        limit: int | None = 12,
    ) -> dict[str, Any]:
        username = self.resolve_username(username_or_url)
        self._validate_limit(limit)
        if limit == 0:
            return {
                "username": username,
                "user_id": None,
                "available": 0,
                "total": 0,
                "has_more": False,
                "next_cursor": None,
                "posts": [],
            }
        user = self._get_profile_user(username)
        timeline = _mapping(user.get("edge_owner_to_timeline_media"))
        posts = self._normalize_post_edges(timeline, limit=limit)
        page_info = _mapping(timeline.get("page_info"))
        return {
            "username": str(user.get("username") or username),
            "user_id": str(user.get("id") or "") or None,
            "available": _integer(timeline.get("count")),
            "total": len(posts),
            "has_more": bool(page_info.get("has_next_page")),
            "next_cursor": str(page_info.get("end_cursor") or "") or None,
            "posts": posts,
        }

    def get_post(self, shortcode_or_url: str) -> dict[str, Any]:
        shortcode = self.resolve_shortcode(shortcode_or_url)
        response = self._request(
            f"{_BASE_URL}/p/{shortcode}/embed/captioned/",
            params={},
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Referer": f"{_BASE_URL}/p/{shortcode}/",
            },
        )
        return self.parse_embed_html(response.text, expected_shortcode=shortcode)

    @classmethod
    def parse_embed_html(
        cls,
        source: str,
        *,
        expected_shortcode: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(source, str) or not source.strip():
            raise InstagramResponseError("Instagram embed response is empty")
        collector = _ScriptCollector()
        collector.feed(source)
        candidates: list[Mapping[str, Any]] = []
        for script in collector.scripts:
            for match in _HANDLE_CALL_RE.finditer(script):
                try:
                    encoded = cls._extract_json_object(script, match.end())
                    payload = json.loads(encoded)
                except (InstagramResponseError, TypeError, ValueError):
                    continue
                candidates.extend(cls._find_shortcode_media(payload))
        for media in candidates:
            shortcode = str(media.get("shortcode") or media.get("code") or "")
            if expected_shortcode is None or shortcode == expected_shortcode:
                return cls._normalize_media(media, fallback_shortcode=expected_shortcode)
        detail = f" for {expected_shortcode}" if expected_shortcode else ""
        raise InstagramResponseError(
            f"Instagram embed HTML does not contain public post metadata{detail}"
        )

    @staticmethod
    def resolve_username(username_or_url: str) -> str:
        text = str(username_or_url or "").strip()
        if text.startswith("@"):
            text = text[1:]
        if "://" in text or "/" in text:
            parsed = urlsplit(text if "://" in text else f"https://{text}")
            if not InstagramClient._is_instagram_host(parsed.hostname):
                raise InstagramInputError("profile URL must use an instagram.com host")
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) != 1 or parts[0].lower() in _RESERVED_PROFILE_ROUTES:
                raise InstagramInputError("URL is not an Instagram profile URL")
            text = parts[0]
        if (
            not _USERNAME_RE.fullmatch(text)
            or text.startswith(".")
            or text.endswith(".")
            or ".." in text
        ):
            raise InstagramInputError("Instagram username is malformed")
        if text.lower() in _RESERVED_PROFILE_ROUTES:
            raise InstagramInputError("Instagram username resolves to a reserved route")
        return text.lower()

    @staticmethod
    def resolve_shortcode(shortcode_or_url: str) -> str:
        text = str(shortcode_or_url or "").strip()
        if "://" in text or "/" in text:
            parsed = urlsplit(text if "://" in text else f"https://{text}")
            if not InstagramClient._is_instagram_host(parsed.hostname):
                raise InstagramInputError("post URL must use an instagram.com host")
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) < 2 or parts[0].lower() not in _POST_ROUTES:
                raise InstagramInputError("URL is not an Instagram post URL")
            text = parts[1]
        if not _SHORTCODE_RE.fullmatch(text):
            raise InstagramInputError("Instagram shortcode is malformed")
        return text

    @staticmethod
    def shortcode_to_media_id(shortcode_or_url: str) -> str:
        shortcode = InstagramClient.resolve_shortcode(shortcode_or_url)
        media_id = 0
        for character in shortcode:
            media_id = media_id * 64 + _SHORTCODE_INDEX[character]
        if media_id <= 0:
            raise InstagramInputError("Instagram shortcode does not encode a positive media id")
        return str(media_id)

    @staticmethod
    def media_id_to_shortcode(media_id: str | int) -> str:
        text = str(media_id or "").strip()
        if not text.isdigit() or int(text) <= 0:
            raise InstagramInputError("Instagram media id must be a positive integer")
        value = int(text)
        characters: list[str] = []
        while value:
            characters.append(_SHORTCODE_ALPHABET[value % 64])
            value //= 64
        return "".join(reversed(characters))

    def _get_profile_user(self, username: str) -> Mapping[str, Any]:
        payload = self._json_get(
            _PROFILE_INFO_URL,
            params={"username": username},
            headers={"Referer": f"{_BASE_URL}/{username}/"},
        )
        status = str(payload.get("status") or "ok").lower()
        if status != "ok":
            message = payload.get("message") or "unknown API error"
            raise InstagramResponseError(f"Instagram profile API returned {status}: {message}")
        user = _mapping(_mapping(payload.get("data")).get("user"))
        if not user.get("id") or not user.get("username"):
            raise InstagramResponseError(
                f"Instagram profile response does not contain public user data for {username}"
            )
        return user

    def _json_get(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        response = self._request(url, params=params, headers=headers)
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise InstagramResponseError(
                f"Instagram returned invalid JSON for {urlsplit(url).path}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise InstagramResponseError(
                f"Instagram returned a non-object payload for {urlsplit(url).path}"
            )
        return payload

    def _request(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response:
        path = urlsplit(url).path
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=dict(params),
                    headers=dict(headers) if headers else None,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestsError as exc:
                if attempt >= self.retries:
                    raise InstagramResponseError(f"Instagram request failed for {path}: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = _integer(getattr(response, "status_code", 0))
            if status == 429 or status >= 500:
                if attempt < self.retries:
                    time.sleep(0.4 * (2**attempt))
                    continue
            if status < 200 or status >= 300:
                raise InstagramResponseError(f"Instagram returned HTTP {status} for {path}")
            return response
        raise InstagramResponseError(f"Instagram request exhausted retries for {path}")

    @classmethod
    def _normalize_media(
        cls,
        raw: Mapping[str, Any],
        *,
        fallback_shortcode: str | None = None,
    ) -> dict[str, Any]:
        shortcode = str(raw.get("shortcode") or raw.get("code") or fallback_shortcode or "")
        typename = str(raw.get("__typename") or "")
        child_edges = _list(_mapping(raw.get("edge_sidecar_to_children")).get("edges"))
        child_nodes = [
            _mapping(_mapping(edge).get("node"))
            for edge in child_edges
            if _mapping(_mapping(edge).get("node"))
        ]
        if not child_nodes:
            child_nodes = [
                _mapping(item)
                for item in _list(raw.get("carousel_media"))
                if isinstance(item, Mapping)
            ]
        if typename == "GraphSidecar" or child_nodes:
            media_type = "carousel"
        elif typename == "GraphVideo" or bool(raw.get("is_video")):
            media_type = "video"
        else:
            media_type = "image"

        resources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for key in ("display_resources", "thumbnail_resources"):
            for item in _list(raw.get(key)):
                resource = _mapping(item)
                url = str(resource.get("src") or resource.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                resources.append(
                    {
                        "url": url,
                        "width": _integer(resource.get("config_width") or resource.get("width")),
                        "height": _integer(resource.get("config_height") or resource.get("height")),
                    }
                )
        dimensions = _mapping(raw.get("dimensions"))
        owner = _mapping(raw.get("owner") or raw.get("user"))
        location = _mapping(raw.get("location"))
        timestamp = raw.get("taken_at_timestamp") or raw.get("taken_at")
        children = [
            cls._normalize_media(child, fallback_shortcode=shortcode)
            for child in child_nodes
        ]
        return {
            "id": str(raw.get("id") or raw.get("pk") or "") or None,
            "shortcode": shortcode or None,
            "url": f"{_BASE_URL}/p/{shortcode}/" if shortcode else None,
            "media_type": media_type,
            "typename": typename or None,
            "is_video": media_type == "video",
            "caption": _caption(raw),
            "display_url": str(raw.get("display_url") or "") or None,
            "thumbnail_url": str(raw.get("thumbnail_src") or raw.get("display_url") or "") or None,
            "video_url": str(raw.get("video_url") or "") or None,
            "video_duration": _optional_float(raw.get("video_duration")),
            "view_count": _integer(raw.get("video_view_count") or raw.get("video_play_count")),
            "like_count": _edge_count(raw, "edge_media_preview_like", "edge_liked_by"),
            "comment_count": _edge_count(raw, "edge_media_to_comment"),
            "published_timestamp": _integer(timestamp) or None,
            "published_at": _timestamp_iso(timestamp),
            "width": _integer(dimensions.get("width")),
            "height": _integer(dimensions.get("height")),
            "accessibility_caption": str(raw.get("accessibility_caption") or "") or None,
            "product_type": str(raw.get("product_type") or "") or None,
            "owner": {
                "id": str(owner.get("id") or owner.get("pk") or "") or None,
                "username": str(owner.get("username") or "") or None,
                "full_name": str(owner.get("full_name") or "") or None,
                "is_verified": bool(owner.get("is_verified")),
                "profile_pic_url": str(owner.get("profile_pic_url") or "") or None,
                "follower_count": _edge_count(owner, "edge_followed_by"),
            },
            "location": {
                "id": str(location.get("id") or location.get("pk") or "") or None,
                "name": str(location.get("name") or "") or None,
            }
            if location
            else None,
            "music": dict(_mapping(raw.get("clips_music_attribution_info"))) or None,
            "resources": resources,
            "children": children,
        }

    @classmethod
    def _normalize_profile(cls, user: Mapping[str, Any]) -> dict[str, Any]:
        timeline = _mapping(user.get("edge_owner_to_timeline_media"))
        links: list[dict[str, str | None]] = []
        for item in _list(user.get("bio_links")):
            link = _mapping(item)
            url = str(link.get("url") or link.get("lynx_url") or "")
            if not url:
                continue
            links.append(
                {
                    "title": str(link.get("title") or "") or None,
                    "url": url,
                    "lynx_url": str(link.get("lynx_url") or "") or None,
                }
            )
        username = str(user.get("username") or "")
        return {
            "id": str(user.get("id") or "") or None,
            "username": username,
            "profile_url": f"{_BASE_URL}/{username}/" if username else None,
            "full_name": str(user.get("full_name") or ""),
            "biography": str(user.get("biography") or ""),
            "external_url": str(user.get("external_url") or "") or None,
            "bio_links": links,
            "avatar": str(user.get("profile_pic_url") or "") or None,
            "avatar_hd": str(user.get("profile_pic_url_hd") or "") or None,
            "is_private": bool(user.get("is_private")),
            "is_verified": bool(user.get("is_verified")),
            "is_business": bool(user.get("is_business_account")),
            "is_professional": bool(user.get("is_professional_account")),
            "category": str(
                user.get("category_name")
                or user.get("overall_category_name")
                or user.get("business_category_name")
                or ""
            )
            or None,
            "followers": _edge_count(user, "edge_followed_by"),
            "following": _edge_count(user, "edge_follow"),
            "post_count": _integer(timeline.get("count")),
            "highlight_count": _integer(user.get("highlight_reel_count")),
            "pronouns": [str(item) for item in _list(user.get("pronouns"))],
        }

    @classmethod
    def _normalize_post_edges(
        cls,
        timeline: Mapping[str, Any],
        *,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        edges = _list(timeline.get("edges"))
        if limit is not None:
            edges = edges[: min(limit, 12)]
        posts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for edge in edges:
            node = _mapping(_mapping(edge).get("node"))
            shortcode = str(node.get("shortcode") or "")
            identifier = str(node.get("id") or shortcode)
            if not node or not identifier or identifier in seen:
                continue
            seen.add(identifier)
            posts.append(cls._normalize_media(node))
        return posts

    @classmethod
    def _find_shortcode_media(cls, value: Any) -> list[Mapping[str, Any]]:
        found: list[Mapping[str, Any]] = []
        if isinstance(value, Mapping):
            media = value.get("shortcode_media")
            if isinstance(media, Mapping):
                found.append(media)
            context = value.get("contextJSON")
            if isinstance(context, str):
                try:
                    found.extend(cls._find_shortcode_media(json.loads(context)))
                except (TypeError, ValueError):
                    pass
            for key, child in value.items():
                if key not in {"shortcode_media", "contextJSON"}:
                    found.extend(cls._find_shortcode_media(child))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for child in value:
                found.extend(cls._find_shortcode_media(child))
        return found

    @staticmethod
    def _extract_json_object(source: str, start: int) -> str:
        begin = source.find("{", start)
        if begin < 0:
            raise InstagramResponseError("ServerJS handle call has no JSON object")
        depth = 0
        in_string = False
        escaped = False
        for index in range(begin, len(source)):
            character = source[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return source[begin : index + 1]
        raise InstagramResponseError("ServerJS handle call contains unterminated JSON")

    @staticmethod
    def _is_instagram_host(hostname: str | None) -> bool:
        host = (hostname or "").lower().rstrip(".")
        return host == "instagram.com" or host.endswith(".instagram.com")

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 0
            or limit > 12
        ):
            raise InstagramInputError("limit must be an integer from 0 through 12, or None")

    def _cookie_value(self, name: str) -> str | None:
        cookie_jar = getattr(self.session, "cookies", None)
        raw_jar = getattr(cookie_jar, "jar", None)
        if raw_jar is not None:
            for cookie in raw_jar:
                if getattr(cookie, "name", None) == name:
                    return str(getattr(cookie, "value", "")) or None
        if cookie_jar is not None and hasattr(cookie_jar, "get"):
            try:
                value = cookie_jar.get(name)
            except (KeyError, ValueError):
                value = None
            return str(value) if value else None
        return None
