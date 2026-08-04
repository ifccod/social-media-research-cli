from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import Lemon8InputError, Lemon8ResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_BASE_URL = "https://www.lemon8-app.com"
_PAGE_HOSTS = {
    "lemon8-app.com",
    "www.lemon8-app.com",
    "m.lemon8-app.com",
}
_SHORT_HOSTS = {"v.lemon8-app.com", "s.lemon8-app.com"}
_POST_ID_RE = re.compile(r"^[0-9]{10,24}$")
_USER_ID_RE = re.compile(r"^[0-9]{10,24}$")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_REGION_RE = re.compile(r"^[A-Za-z]{2}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2}[-_](?P<region>[A-Za-z]{2})$")
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_STATE_ASSIGNMENT_RE = re.compile(
    r"(?:window\s*\.\s*)?(?:__INITIAL_STATE__|__APOLLO_STATE__|"
    r"__NUXT__|SIGI_STATE)\s*=\s*"
)
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_RESERVED_ROUTES = {
    "about",
    "article",
    "community-guideline",
    "discover",
    "experience",
    "feed",
    "follow",
    "legal",
    "poi",
    "search",
    "topic",
    "user",
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


def _number(value: Any) -> int | float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _first(raw: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return None


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _integer(value)
    if timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _walk(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _walk(child)


class _PageCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.scripts: list[tuple[dict[str, str], str]] = []
        self._script_attrs: dict[str, str] | None = None
        self._script_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(name).lower(): str(value or "") for name, value in attrs}
        lower_tag = tag.lower()
        if lower_tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = values.get("content", "")
        elif lower_tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "") or self.canonical
        elif lower_tag == "script":
            self._script_attrs = values
            self._script_buffer = []

    def handle_data(self, data: str) -> None:
        if self._script_attrs is not None:
            self._script_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._script_attrs is not None:
            self.scripts.append((self._script_attrs, "".join(self._script_buffer)))
            self._script_attrs = None
            self._script_buffer = []


class _ContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.tags: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(name).lower(): str(value or "") for name, value in attrs}
        if tag.lower() in {"br", "p", "div", "li"}:
            self.parts.append("\n")
        if tag.lower() == "a" and values.get("data-type", "").lower() in {
            "forum",
            "hashtag",
            "topic",
        }:
            name = values.get("data-name", "").strip().lstrip("#").strip()
            if name:
                self.tags.append(
                    {
                        "id": values.get("data-id", "") or None,
                        "name": name,
                        "region": values.get("data-region", "").lower() or None,
                    }
                )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in "".join(self.parts).split("\n")]
        return "\n".join(line for line in lines if line)


def _parse_document(source: str) -> _PageCollector:
    if not isinstance(source, str) or not source.strip():
        raise Lemon8ResponseError("Lemon8 HTML is empty")
    collector = _PageCollector()
    try:
        collector.feed(source.replace("\x00", ""))
    except (TypeError, ValueError) as exc:
        raise Lemon8ResponseError("Lemon8 HTML could not be parsed") from exc
    return collector


def _decode_json_script(payload: str) -> Any | None:
    value = payload.strip()
    if not value:
        return None
    candidates = [value]
    if value[:3].lower() in {"%7b", "%5b"} or "%22" in value[:80].lower():
        candidates.insert(0, unquote(value))
    for candidate in candidates:
        try:
            result = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if isinstance(result, (Mapping, list)):
            return result
    return None


def _normalize_region(value: Any, *, default: str = "us") -> str:
    region = str(value or default).strip().lower()
    if not _REGION_RE.fullmatch(region):
        raise Lemon8InputError("region must be a two-letter country code")
    return region


def _normalize_handle(value: Any) -> str:
    handle = unquote(str(value or "").strip()).lstrip("@").strip()
    if not _HANDLE_RE.fullmatch(handle) or handle in {".", "..", "_"}:
        raise Lemon8InputError(f"invalid Lemon8 author handle: {value}")
    return handle


def _normalize_id(value: Any, label: str = "post id") -> str:
    identifier = str(value or "").strip()
    if not _POST_ID_RE.fullmatch(identifier):
        raise Lemon8InputError(f"invalid Lemon8 {label}: {value}")
    return identifier


def _extract_url(value: str) -> str:
    candidate = html.unescape(value.strip())
    match = _URL_IN_TEXT_RE.search(candidate)
    if match:
        candidate = match.group(0).rstrip(".,;!)]}\u3002\uff0c\uff1b\uff01\uff09\u3011\u300b")
    elif candidate.startswith("//"):
        candidate = f"https:{candidate}"
    elif candidate.lower().startswith(("lemon8-app.com/", "www.lemon8-app.com/", "v.lemon8-app.com/", "s.lemon8-app.com/")):
        candidate = f"https://{candidate}"
    return candidate


def _region_from_path(parts: list[str]) -> tuple[list[str], str | None]:
    if not parts:
        return parts, None
    match = _LOCALE_RE.fullmatch(parts[0])
    if not match:
        return parts, None
    return parts[1:], match.group("region").lower()


def _page_url(path: str, region: str) -> str:
    return f"{_BASE_URL}{path}?{urlencode({'region': region})}"


def _absolute_url(value: Any, *, base: str = _BASE_URL) -> str:
    raw = html.unescape(str(value or "").strip())
    if not raw:
        return ""
    return urljoin(f"{base}/", raw)


class Lemon8Client:
    """不执行页面 JavaScript，读取 Lemon8 匿名公开页面。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
        region: str = "us",
    ) -> None:
        self.region = _normalize_region(region)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session(impersonate="chrome")
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": user_agent,
            }
        )

    @classmethod
    def parse_post_reference(
        cls,
        reference: str,
        *,
        region: str = "us",
    ) -> dict[str, Any]:
        if not isinstance(reference, str):
            raise Lemon8InputError("post reference must be a string")
        value = reference.strip()
        default_region = _normalize_region(region)
        if _POST_ID_RE.fullmatch(value):
            return {
                "id": value,
                "author": None,
                "region": default_region,
                "url": _page_url(f"/@_/{value}", default_region),
                "is_short_url": False,
            }
        if not value:
            raise Lemon8InputError("post reference is empty")

        candidate = _extract_url(value)
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() not in {"http", "https"}:
            raise Lemon8InputError("Lemon8 URL must use HTTP or HTTPS")
        try:
            port = parsed.port
        except ValueError as exc:
            raise Lemon8InputError("Lemon8 URL contains an invalid port") from exc
        if parsed.username or parsed.password or port not in (None, 443):
            raise Lemon8InputError("Lemon8 URL must not contain credentials or a custom port")
        if host in _SHORT_HOSTS:
            if not parsed.path.strip("/"):
                raise Lemon8InputError("Lemon8 short URL does not contain a token")
            return {
                "id": None,
                "author": None,
                "region": default_region,
                "url": urlunsplit(("https", host, parsed.path, parsed.query, "")),
                "is_short_url": True,
            }

        host_region = host.split(".", 1)[0] if re.fullmatch(r"[a-z]{2}\.lemon8-app\.com", host) else None
        if host not in _PAGE_HOSTS and host_region is None:
            raise Lemon8InputError(f"invalid Lemon8 host: {host or '(missing)'}")
        parts, path_region = _region_from_path([unquote(part) for part in parsed.path.split("/") if part])
        query_region = (parse_qs(parsed.query).get("region") or [None])[0]
        resolved_region = _normalize_region(query_region or path_region or host_region, default=default_region)

        author: str | None = None
        identifier = ""
        if len(parts) == 2 and _POST_ID_RE.fullmatch(parts[-1]):
            identifier = parts[-1]
            candidate_author = parts[-2]
            if candidate_author.lower() not in {"article", "share"}:
                author = _normalize_handle(candidate_author)
        elif len(parts) == 2 and parts[0].lower() == "article" and _POST_ID_RE.fullmatch(parts[1]):
            identifier = parts[1]
        if not identifier:
            raise Lemon8InputError(f"invalid Lemon8 post reference: {reference}")
        path = f"/@{quote(author, safe='._-')}/{identifier}" if author else f"/@_/{identifier}"
        return {
            "id": identifier,
            "author": author,
            "region": resolved_region,
            "url": _page_url(path, resolved_region),
            "is_short_url": False,
        }

    @classmethod
    def parse_user_reference(
        cls,
        reference: str,
        *,
        region: str = "us",
    ) -> dict[str, Any]:
        if not isinstance(reference, str):
            raise Lemon8InputError("user reference must be a string")
        value = reference.strip()
        default_region = _normalize_region(region)
        if _USER_ID_RE.fullmatch(value):
            return {
                "id": value,
                "author": None,
                "region": default_region,
                "url": _page_url(f"/user/{value}/share", default_region),
                "is_short_url": False,
            }
        if value.startswith("@") and "://" not in value:
            author = _normalize_handle(value)
            return {
                "id": None,
                "author": author,
                "region": default_region,
                "url": _page_url(f"/@{quote(author, safe='._-')}", default_region),
                "is_short_url": False,
            }
        if _HANDLE_RE.fullmatch(value) and value.lower() not in _RESERVED_ROUTES:
            author = _normalize_handle(value)
            return {
                "id": None,
                "author": author,
                "region": default_region,
                "url": _page_url(f"/@{quote(author, safe='._-')}", default_region),
                "is_short_url": False,
            }
        if not value:
            raise Lemon8InputError("user reference is empty")

        candidate = _extract_url(value)
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() not in {"http", "https"}:
            raise Lemon8InputError("Lemon8 URL must use HTTP or HTTPS")
        try:
            port = parsed.port
        except ValueError as exc:
            raise Lemon8InputError("Lemon8 URL contains an invalid port") from exc
        if parsed.username or parsed.password or port not in (None, 443):
            raise Lemon8InputError("Lemon8 URL must not contain credentials or a custom port")
        if host in _SHORT_HOSTS:
            if not parsed.path.strip("/"):
                raise Lemon8InputError("Lemon8 short URL does not contain a token")
            return {
                "id": None,
                "author": None,
                "region": default_region,
                "url": urlunsplit(("https", host, parsed.path, parsed.query, "")),
                "is_short_url": True,
            }
        host_region = host.split(".", 1)[0] if re.fullmatch(r"[a-z]{2}\.lemon8-app\.com", host) else None
        if host not in _PAGE_HOSTS and host_region is None:
            raise Lemon8InputError(f"invalid Lemon8 host: {host or '(missing)'}")
        parts, path_region = _region_from_path([unquote(part) for part in parsed.path.split("/") if part])
        query_region = (parse_qs(parsed.query).get("region") or [None])[0]
        resolved_region = _normalize_region(query_region or path_region or host_region, default=default_region)

        if len(parts) >= 3 and parts[0].lower() == "user" and parts[2].lower() == "share":
            user_id = _normalize_id(parts[1], "user id")
            return {
                "id": user_id,
                "author": None,
                "region": resolved_region,
                "url": _page_url(f"/user/{user_id}/share", resolved_region),
                "is_short_url": False,
            }
        if not parts:
            raise Lemon8InputError(f"invalid Lemon8 user reference: {reference}")
        if len(parts) == 1:
            author_part = parts[0]
        elif len(parts) == 2 and _POST_ID_RE.fullmatch(parts[1]):
            author_part = parts[0]
        elif len(parts) == 2 and parts[1].lower() in {"follow", "topic"}:
            author_part = parts[0]
        else:
            raise Lemon8InputError(f"invalid Lemon8 user reference: {reference}")
        if author_part.lower() in _RESERVED_ROUTES:
            raise Lemon8InputError(f"invalid Lemon8 user reference: {reference}")
        author = _normalize_handle(author_part)
        return {
            "id": None,
            "author": author,
            "region": resolved_region,
            "url": _page_url(f"/@{quote(author, safe='._-')}", resolved_region),
            "is_short_url": False,
        }

    @classmethod
    def resolve_post_id(cls, reference: str) -> str:
        result = cls.parse_post_reference(reference)
        if not result["id"]:
            raise Lemon8InputError("short URLs require one HTTP request before the post id is known")
        return str(result["id"])

    @classmethod
    def resolve_author(cls, reference: str) -> str:
        try:
            result = cls.parse_post_reference(reference)
        except Lemon8InputError:
            result = cls.parse_user_reference(reference)
        if not result["author"]:
            raise Lemon8InputError("the Lemon8 reference does not contain an author handle")
        return str(result["author"])

    @staticmethod
    def extract_open_graph(source: str, *, page_url: str = _BASE_URL) -> dict[str, Any]:
        page = _parse_document(source)
        canonical = _absolute_url(page.canonical or page.meta.get("og:url"), base=page_url)
        return {
            "title": page.meta.get("og:title") or page.meta.get("twitter:title") or "",
            "description": page.meta.get("og:description") or page.meta.get("description") or "",
            "type": page.meta.get("og:type") or "",
            "url": _absolute_url(page.meta.get("og:url"), base=page_url),
            "canonical_url": canonical,
            "image_url": _absolute_url(page.meta.get("og:image") or page.meta.get("twitter:image"), base=page_url),
            "image_width": _integer(page.meta.get("og:image:width")),
            "image_height": _integer(page.meta.get("og:image:height")),
            "video_url": _absolute_url(page.meta.get("og:video") or page.meta.get("twitter:player:stream"), base=page_url),
            "keywords": page.meta.get("keywords") or "",
        }

    @staticmethod
    def extract_hydration_json(source: str) -> list[Any]:
        page = _parse_document(source)
        output: list[Any] = []
        for attrs, payload in page.scripts:
            script_type = attrs.get("type", "").lower()
            identifier = attrs.get("id", "")
            is_json = script_type in {"application/json", "application/ld+json"}
            is_hydration = (
                attrs.get("data-ttark") == "__remixContext"
                or identifier in {"__NEXT_DATA__", "__NUXT_DATA__", "SIGI_STATE"}
            )
            if is_json or is_hydration:
                value = _decode_json_script(payload)
                if value is not None:
                    output.append(value)
        decoder = json.JSONDecoder()
        for match in _STATE_ASSIGNMENT_RE.finditer(source):
            try:
                value, _ = decoder.raw_decode(source, match.end())
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(value, (Mapping, list)):
                output.append(value)
        return output

    @classmethod
    def parse_post_html(
        cls,
        source: str,
        *,
        expected_id: str | None = None,
        page_url: str = _BASE_URL,
    ) -> dict[str, Any]:
        if expected_id is not None:
            expected_id = _normalize_id(expected_id)
        open_graph = cls.extract_open_graph(source, page_url=page_url)
        hydration = cls.extract_hydration_json(source)
        raw = cls._find_post(hydration, expected_id=expected_id)
        if not raw and expected_id:
            raw = cls._find_post(hydration, expected_id=None)

        fallback_reference: dict[str, Any] | None = None
        for value in (open_graph["canonical_url"], open_graph["url"], page_url):
            try:
                fallback_reference = cls.parse_post_reference(str(value))
            except Lemon8InputError:
                continue
            if fallback_reference.get("id"):
                break
        identifier = str(_first(raw, "groupId", "group_id", "itemId", "item_id", "articleId", "id") or "")
        identifier = identifier if _POST_ID_RE.fullmatch(identifier) else str((fallback_reference or {}).get("id") or "")
        if expected_id and identifier and identifier != expected_id:
            raise Lemon8ResponseError(
                f"Lemon8 page returned post {identifier}, expected {expected_id}"
            )
        identifier = expected_id or identifier
        if not identifier:
            raise Lemon8ResponseError("Lemon8 page does not contain a public post id")

        author_raw = _mapping(_first(raw, "author", "user", "owner"))
        author_handle = str(_first(author_raw, "linkName", "link_name", "uniqueId", "username") or "")
        if not author_handle:
            author_handle = str((fallback_reference or {}).get("author") or "")
        region = str(_first(raw, "articleRegion", "article_region", "region") or (fallback_reference or {}).get("region") or "us").lower()
        try:
            region = _normalize_region(region)
        except Lemon8InputError:
            region = "us"

        content_html = str(_first(raw, "content", "contentHtml", "content_html", "descHtml") or "")
        content_parser = _ContentParser()
        if content_html:
            content_parser.feed(content_html)
        body = content_parser.text() or str(_first(raw, "shortContent", "short_content", "description", "desc") or "").strip()
        body = body or str(open_graph["description"] or "").strip()
        tags = cls._normalize_tags(content_parser.tags, raw, body, region)
        images = cls._normalize_images(raw, open_graph)
        video = cls._normalize_video(raw, open_graph)
        article_class = str(_first(raw, "articleClass", "article_class", "mediaType", "type") or "").lower()
        if video.get("url"):
            media_type = "video"
        elif len(images) > 1 or article_class in {"gallery", "carousel"}:
            media_type = "gallery"
        elif images:
            media_type = "image"
        else:
            media_type = article_class or "article"

        publish_time = _integer(_first(raw, "publishTime", "publish_time", "createTime", "create_time", "timestamp"))
        modify_time = _integer(_first(raw, "modifyTime", "modify_time", "updateTime", "update_time"))
        title = str(_first(raw, "title", "articleTitle", "article_title") or open_graph["title"] or "").strip()
        source_name = "hydration" if raw else "open_graph"
        if not raw and not (title or body or images or video.get("url")):
            raise Lemon8ResponseError(f"Lemon8 page does not contain public post data for {identifier}")

        canonical_author = author_handle or str((fallback_reference or {}).get("author") or "_")
        canonical_path = f"/@{quote(canonical_author, safe='._-')}/{identifier}"
        location_raw = _mapping(_first(raw, "locationInfo", "location_info", "location"))
        return {
            "id": identifier,
            "url": _page_url(canonical_path, region),
            "source": source_name,
            "media_type": media_type,
            "region": region,
            "title": title,
            "body": body,
            "body_html": content_html,
            "author": cls._normalize_author(author_raw, author_handle, region),
            "stats": {
                "views": _integer(_first(raw, "readCount", "read_count", "viewCount", "view_count", "playCount")),
                "likes": _integer(_first(raw, "diggCount", "digg_count", "likeCount", "like_count", "articleLikes")),
                "saves": _integer(_first(raw, "favoriteCount", "favorite_count", "collectCount", "collect_count")),
                "comments": _integer(_first(raw, "commentCount", "comment_count")),
            },
            "tags": tags,
            "images": images,
            "video": video,
            "published_timestamp": publish_time or None,
            "published_at": _timestamp_iso(publish_time),
            "modified_timestamp": modify_time or None,
            "modified_at": _timestamp_iso(modify_time),
            "location": {
                "id": str(_first(location_raw, "poiId", "poi_id", "id") or "") or None,
                "name": str(_first(location_raw, "poiName", "poi_name", "name") or "") or None,
            },
            "ocr_text": [str(item) for item in _list(_first(raw, "ocrText", "ocr_text")) if str(item).strip()],
            "open_graph": open_graph,
        }

    @classmethod
    def parse_profile_html(
        cls,
        source: str,
        *,
        expected_author: str | None = None,
        expected_user_id: str | None = None,
        page_url: str = _BASE_URL,
    ) -> dict[str, Any]:
        if expected_author:
            expected_author = _normalize_handle(expected_author)
        if expected_user_id:
            expected_user_id = _normalize_id(expected_user_id, "user id")
        open_graph = cls.extract_open_graph(source, page_url=page_url)
        hydration = cls.extract_hydration_json(source)
        raw = cls._find_user(
            hydration,
            expected_author=expected_author,
            expected_user_id=expected_user_id,
        )
        if not raw and (expected_author or expected_user_id):
            raw = cls._find_user(
                hydration,
                expected_author=None,
                expected_user_id=None,
            )
        if not raw:
            raise Lemon8ResponseError("Lemon8 page does not contain public user data")

        user_id = str(_first(raw, "userId", "user_id", "id", "uid") or "")
        author = str(_first(raw, "linkName", "link_name", "uniqueId", "username") or expected_author or "")
        if expected_user_id and user_id and user_id != expected_user_id:
            raise Lemon8ResponseError(
                f"Lemon8 page returned user {user_id}, expected {expected_user_id}"
            )
        if expected_author and author and author.casefold() != expected_author.casefold():
            raise Lemon8ResponseError(
                f"Lemon8 page returned author {author}, expected {expected_author}"
            )
        if not user_id or not author:
            raise Lemon8ResponseError("Lemon8 user data is missing its id or author handle")

        region = "us"
        try:
            region = cls.parse_user_reference(open_graph["canonical_url"] or page_url)["region"]
        except Lemon8InputError:
            pass
        auth_info = _mapping(_first(raw, "authInfo", "auth_info", "verification"))
        links = []
        for item in _list(_first(raw, "thirdLinks", "third_links", "links")):
            link = _mapping(item)
            url = _absolute_url(_first(link, "url", "link"))
            if url:
                links.append(
                    {
                        "platform": str(_first(link, "platform", "type") or ""),
                        "name": str(_first(link, "name", "title") or ""),
                        "url": url,
                    }
                )
        return {
            "id": user_id,
            "username": author,
            "name": str(_first(raw, "nickName", "nick_name", "nickname", "name") or ""),
            "url": _page_url(f"/@{quote(author, safe='._-')}", region),
            "avatar_url": _absolute_url(_first(raw, "avatar", "avatarUrl", "avatar_url")),
            "bio": str(_first(raw, "description", "bio", "signature") or ""),
            "location": str(_first(raw, "location", "regionName", "region_name") or ""),
            "gender": _integer(raw.get("gender")) or None,
            "verified": bool(_first(auth_info, "showAuthSymbol", "show_auth_symbol", "verified")),
            "user_type": _integer(_first(raw, "userType", "user_type")),
            "privacy_status": _integer(_first(raw, "privacyStatus", "privacy_status")),
            "is_banned": bool(_first(raw, "isBannedAccount", "is_banned_account", "isBanned")),
            "stats": {
                "followers": _integer(_first(raw, "followerCount", "follower_count", "followers")),
                "following": _integer(_first(raw, "followingCount", "following_count", "following")),
                "posts": _integer(_first(raw, "postCount", "post_count", "publishCount")),
                "likes_received": _integer(_first(raw, "dugCount", "dug_count")),
                "saves_received": _integer(_first(raw, "favoredCount", "favored_count")),
                "likes_given": _integer(_first(raw, "diggCount", "digg_count")),
                "saved": _integer(_first(raw, "favoriteCount", "favorite_count")),
            },
            "links": links,
            "open_graph": open_graph,
        }

    def get_post(self, reference: str) -> dict[str, Any]:
        parsed = self.parse_post_reference(reference, region=self.region)
        response = self._request(parsed["url"])
        final_url = str(getattr(response, "url", "") or parsed["url"])
        self._validate_final_url(final_url)
        final_id = parsed["id"]
        if not final_id:
            try:
                final_id = self.parse_post_reference(final_url, region=parsed["region"])["id"]
            except Lemon8InputError:
                final_id = None
        return self.parse_post_html(
            response.text,
            expected_id=final_id,
            page_url=final_url,
        )

    def get_user_profile(self, reference: str) -> dict[str, Any]:
        parsed = self.parse_user_reference(reference, region=self.region)
        response = self._request(parsed["url"])
        final_url = str(getattr(response, "url", "") or parsed["url"])
        self._validate_final_url(final_url)
        final_author = parsed["author"]
        final_user_id = parsed["id"]
        if not final_author:
            try:
                final_author = self.parse_user_reference(final_url, region=parsed["region"])["author"]
            except Lemon8InputError:
                final_author = None
        return self.parse_profile_html(
            response.text,
            expected_author=final_author,
            expected_user_id=final_user_id,
            page_url=final_url,
        )

    def _request(self, url: str) -> requests.Response:
        path = urlsplit(url).path
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    headers={"Referer": f"{_BASE_URL}/"},
                )
            except requests.RequestsError as exc:
                if attempt >= self.retries:
                    raise Lemon8ResponseError(f"Lemon8 request failed for {path}: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = _integer(getattr(response, "status_code", 0))
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            if status < 200 or status >= 300:
                raise Lemon8ResponseError(f"Lemon8 returned HTTP {status} for {path}")
            return response
        raise Lemon8ResponseError(f"Lemon8 request exhausted retries for {path}")

    @staticmethod
    def _validate_final_url(url: str) -> None:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        is_region_host = bool(re.fullmatch(r"[a-z]{2}\.lemon8-app\.com", host))
        try:
            port = parsed.port
        except ValueError:
            port = -1
        if parsed.username or parsed.password or port not in (None, 443):
            raise Lemon8ResponseError("Lemon8 redirect contains invalid URL authority")
        if parsed.scheme.lower() not in {"http", "https"} or (
            host not in _PAGE_HOSTS and host not in _SHORT_HOSTS and not is_region_host
        ):
            raise Lemon8ResponseError(
                f"Lemon8 redirect left the owned hosts: {host or '(missing)'}"
            )

    @staticmethod
    def _find_post(hydration: Sequence[Any], *, expected_id: str | None) -> Mapping[str, Any]:
        best: Mapping[str, Any] = {}
        best_score = 0
        for root in hydration:
            for item in _walk(root):
                identifier = str(_first(item, "groupId", "group_id", "itemId", "item_id", "articleId", "id") or "")
                if not _POST_ID_RE.fullmatch(identifier):
                    continue
                if expected_id and identifier != expected_id:
                    continue
                score = 10
                if expected_id and identifier == expected_id:
                    score += 100
                if _first(item, "articleClass", "article_class", "mediaType"):
                    score += 15
                if _first(item, "content", "contentHtml", "content_html"):
                    score += 20
                if _first(item, "publishTime", "publish_time", "createTime"):
                    score += 15
                if isinstance(_first(item, "author", "user", "owner"), Mapping):
                    score += 10
                if _first(item, "imageList", "image_list", "video", "largeImage"):
                    score += 10
                if score > best_score:
                    best = item
                    best_score = score
        return best

    @staticmethod
    def _find_user(
        hydration: Sequence[Any],
        *,
        expected_author: str | None,
        expected_user_id: str | None,
    ) -> Mapping[str, Any]:
        best: Mapping[str, Any] = {}
        best_score = 0
        for root in hydration:
            for item in _walk(root):
                user_id = str(_first(item, "userId", "user_id", "uid") or "")
                author = str(_first(item, "linkName", "link_name", "uniqueId", "username") or "")
                if not user_id or not author:
                    continue
                if expected_user_id and user_id != expected_user_id:
                    continue
                if expected_author and author.casefold() != expected_author.casefold():
                    continue
                score = 10
                if expected_user_id and user_id == expected_user_id:
                    score += 100
                if expected_author and author.casefold() == expected_author.casefold():
                    score += 100
                for key in ("postCount", "followingCount", "thirdLinks", "privacyStatus", "dugCount"):
                    if key in item:
                        score += 10
                if "followerCount" in item:
                    score += 5
                if score > best_score:
                    best = item
                    best_score = score
        return best

    @staticmethod
    def _normalize_author(raw: Mapping[str, Any], fallback_handle: str, region: str) -> dict[str, Any]:
        handle = str(_first(raw, "linkName", "link_name", "uniqueId", "username") or fallback_handle or "")
        auth_info = _mapping(_first(raw, "authInfo", "auth_info", "verification"))
        return {
            "id": str(_first(raw, "userId", "user_id", "uid", "id") or "") or None,
            "username": handle or None,
            "name": str(_first(raw, "nickName", "nick_name", "nickname", "name") or ""),
            "url": _page_url(f"/@{quote(handle, safe='._-')}", region) if handle else None,
            "avatar_url": _absolute_url(_first(raw, "avatar", "avatarUrl", "avatar_url")) or None,
            "follower_count": _integer(_first(raw, "followerCount", "follower_count", "followers")),
            "verified": bool(_first(auth_info, "showAuthSymbol", "show_auth_symbol", "verified")),
        }

    @staticmethod
    def _normalize_images(raw: Mapping[str, Any], open_graph: Mapping[str, Any]) -> list[dict[str, Any]]:
        values = _list(_first(raw, "imageList", "image_list", "images", "gallery"))
        role = "content"
        if not values:
            cover = _first(raw, "largeImage", "large_image", "cover", "coverImage")
            if cover:
                values = [cover]
                role = "cover"
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in values:
            image = _mapping(item)
            url_value = _first(image, "url", "imageUrl", "image_url", "displayUrl")
            if isinstance(url_value, Mapping):
                url_value = _first(_mapping(url_value), "url", "uri")
            if not url_value:
                url_list = _list(_first(image, "urlList", "url_list"))
                url_value = url_list[0] if url_list else ""
            url = _absolute_url(url_value)
            if not url or url in seen:
                continue
            seen.add(url)
            output.append(
                {
                    "url": url,
                    "width": _integer(_first(image, "width", "imageWidth", "image_width")),
                    "height": _integer(_first(image, "height", "imageHeight", "image_height")),
                    "share_url": _absolute_url(_first(image, "shareCardCoverImage", "share_card_cover_image")) or None,
                    "role": role,
                }
            )
        og_image = _absolute_url(open_graph.get("image_url"))
        if og_image and not output:
            output.append(
                {
                    "url": og_image,
                    "width": _integer(open_graph.get("image_width")),
                    "height": _integer(open_graph.get("image_height")),
                    "share_url": None,
                    "role": "open_graph",
                }
            )
        return output

    @staticmethod
    def _normalize_video(raw: Mapping[str, Any], open_graph: Mapping[str, Any]) -> dict[str, Any]:
        video = _mapping(_first(raw, "video", "videoInfo", "video_info"))
        url_value = _first(video, "url", "playUrl", "play_url", "downloadUrl")
        if isinstance(url_value, Mapping):
            url_value = _first(_mapping(url_value), "url", "uri")
        if not url_value:
            urls = _list(_first(video, "urlList", "url_list", "playAddr"))
            url_value = urls[0] if urls else open_graph.get("video_url")
        return {
            "url": _absolute_url(url_value) or None,
            "width": _integer(_first(video, "width", "videoWidth", "video_width")),
            "height": _integer(_first(video, "height", "videoHeight", "video_height")),
            "duration_seconds": _number(_first(video, "duration", "durationSeconds", "duration_seconds")),
            "muted": bool(_integer(_first(video, "muteStatus", "mute_status", "muted"))),
        }

    @staticmethod
    def _normalize_tags(
        content_tags: Sequence[Mapping[str, Any]],
        raw: Mapping[str, Any],
        body: str,
        region: str,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = [dict(item) for item in content_tags]
        for item in _list(_first(raw, "hashtags", "hashTags", "forumList", "topicList", "tags")):
            tag = _mapping(item)
            name = str(_first(tag, "name", "hashtagName", "hashtag_name", "title") or "").lstrip("#").strip()
            if name:
                candidates.append(
                    {
                        "id": str(_first(tag, "id", "forumId", "forum_id", "hashtagId") or "") or None,
                        "name": name,
                        "region": str(_first(tag, "region", "articleRegion") or region).lower(),
                    }
                )
        if not candidates:
            for match in re.finditer(r"(?<![\w#])#([^#\s]+)", body):
                name = match.group(1).strip(".,;:!?()[]{}")
                if name:
                    candidates.append({"id": None, "name": name, "region": region})

        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in candidates:
            name = str(item.get("name") or "").strip().lstrip("#").strip()
            identifier = str(item.get("id") or "")
            key = (identifier, name.casefold())
            if not name or key in seen:
                continue
            seen.add(key)
            tag_region = str(item.get("region") or region).lower()
            output.append(
                {
                    "id": identifier or None,
                    "name": name,
                    "region": tag_region,
                    "url": _page_url(f"/topic/{identifier}", tag_region) if identifier else None,
                }
            )
        return output
