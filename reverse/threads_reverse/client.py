from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from curl_cffi import requests

from .errors import ThreadsInputError, ThreadsResponseError

DEFAULT_USER_AGENT = (
    "facebookexternalhit/1.1 "
    "(+http://www.facebook.com/externalhit_uatext.php)"
)

_BASE_URL = "https://www.threads.com"
_SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_SHORTCODE_INDEX = {character: index for index, character in enumerate(_SHORTCODE_ALPHABET)}
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?$")
_SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_MEDIA_ID_RE = re.compile(r"^[1-9][0-9]{0,24}$")
_URL_IN_TEXT_RE = re.compile(
    r"(?<![A-Za-z0-9.-])(?:https?://)?(?:[A-Za-z0-9-]+\.)*"
    r"threads\.(?:com|net)(?![A-Za-z0-9.-])(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)
_PROFILE_TITLE_RE = re.compile(
    r"^(?P<name>.*?)\s*\(@(?P<username>[A-Za-z0-9_.]+)\)\s*[\u2022\u00b7]\s*Threads(?:,.*)?$",
    re.IGNORECASE,
)
_POST_TITLE_RE = re.compile(
    r"^(?P<name>.*?)\s*\(@(?P<username>[A-Za-z0-9_.]+)\)\s+on\s+Threads$",
    re.IGNORECASE,
)
_PROFILE_DESCRIPTION_RE = re.compile(
    r"^\s*(?P<followers>[0-9][0-9.,]*\s*[KMB]?)\s+Followers\s*"
    r"[\u2022\u00b7]\s*(?P<threads>[0-9][0-9.,]*\s*[KMB]?)\s+Threads"
    r"(?:\s*[\u2022\u00b7]\s*(?P<bio>.*))?$",
    re.IGNORECASE | re.DOTALL,
)
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>\uff0c\u3002\uff1b\uff1a\uff01\uff1f\uff09\u3011\u300b\u3001"


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _compact_number(value: Any) -> int:
    text = str(value or "").strip().upper().replace(",", "").replace(" ", "")
    if not text:
        return 0
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    suffix = text[-1]
    multiplier = multipliers.get(suffix, 1)
    if multiplier != 1:
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except (TypeError, ValueError, OverflowError):
        return 0


def _clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.split("\n")]
    output: list[str] = []
    for line in lines:
        if line:
            output.append(line)
        elif output and output[-1]:
            output.append("")
    while output and not output[-1]:
        output.pop()
    return "\n".join(output)


def _classes(attrs: Mapping[str, str]) -> set[str]:
    return {item for item in attrs.get("class", "").split() if item}


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _walk_mappings(child)


def _absolute_threads_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = f"https:{raw}"
    elif raw.startswith("/"):
        raw = f"{_BASE_URL}{raw}"
    return raw


def _external_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    host = (parsed.hostname or "").lower()
    if host in {"l.facebook.com", "l.instagram.com"}:
        target = (parse_qs(parsed.query).get("u") or [""])[0]
        if target.startswith(("https://", "http://")):
            return target
    return raw


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


def _new_embed_block(depth: int) -> dict[str, Any]:
    return {
        "_depth": depth,
        "_avatar_depth": None,
        "_body_depth": None,
        "_body_parts": [],
        "_timestamp_depth": None,
        "_timestamp_parts": [],
        "_media_depths": [],
        "_topic_depth": None,
        "_link_depth": None,
        "_link": None,
        "_topic_link_depth": None,
        "_topic_link": None,
        "_count_depth": None,
        "_count_parts": [],
        "_action_icon_depth": None,
        "_action_icon_value": None,
        "username": "",
        "profile_url": "",
        "avatar": "",
        "verified": False,
        "images": [],
        "videos": [],
        "links": [],
        "topics": [],
        "counts": [],
    }


class _EmbedCollector(HTMLParser):
    _MEDIA_CLASSES = {
        "MediaScrollImageContainer",
        "MediaScrollVideoContainer",
        "SingleInnerMediaContainer",
        "SingleInnerMediaContainerVideo",
    }
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.blocks: list[dict[str, Any]] = []
        self._active: list[dict[str, Any]] = []
        self.post_url = ""
        self._link_container_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        values = {str(name).lower(): str(value or "") for name, value in attrs}
        classes = _classes(values)
        lower_tag = tag.lower()

        if "LinkContainer" in classes:
            self._link_container_depth = self.depth
        elif lower_tag == "a" and self._link_container_depth is not None and not self.post_url:
            self.post_url = _absolute_threads_url(values.get("href"))

        if "OuterContainer" in classes:
            block = _new_embed_block(self.depth)
            block["_index"] = len(self.blocks)
            self.blocks.append({})
            self._active.append(block)
        if not self._active:
            if lower_tag in self._VOID_TAGS:
                self.handle_endtag(lower_tag)
            return
        block = self._active[-1]

        if lower_tag == "br" and block["_body_depth"] is not None:
            block["_body_parts"].append("\n")

        if "AvatarContainer" in classes:
            block["_avatar_depth"] = self.depth
        if "BodyTextContainer" in classes:
            block["_body_depth"] = self.depth
        if "Timestamp" in classes:
            block["_timestamp_depth"] = self.depth
            block["_timestamp_parts"] = []
        if classes & self._MEDIA_CLASSES:
            block["_media_depths"].append(self.depth)
        if "TopicTagWrapper" in classes:
            block["_topic_depth"] = self.depth
        if "VerifiedBadge" in classes:
            block["verified"] = True
        if "ActionBarIcon" in classes:
            block["_action_icon_depth"] = self.depth
            block["_action_icon_value"] = None
        if "ActionBarCount" in classes:
            block["_count_depth"] = self.depth
            block["_count_parts"] = []

        if lower_tag == "a" and block["_body_depth"] is not None:
            block["_link_depth"] = self.depth
            block["_link"] = {"href": values.get("href", ""), "parts": []}
        elif lower_tag == "a" and block["_topic_depth"] is not None:
            block["_topic_link_depth"] = self.depth
            block["_topic_link"] = {"href": values.get("href", ""), "parts": []}
        elif lower_tag == "a" and "HeaderLink" in classes and not block["username"]:
            href = _absolute_threads_url(values.get("href"))
            username = _profile_username_from_url(href)
            if username:
                block["username"] = username
                block["profile_url"] = f"{_BASE_URL}/@{username}"

        if lower_tag == "img":
            src = str(values.get("src") or "").strip()
            if src and block["_avatar_depth"] is not None:
                block["avatar"] = src
            elif src and block["_media_depths"]:
                item = {
                    "url": src,
                    "width": _integer(values.get("width")) or None,
                    "height": _integer(values.get("height")) or None,
                    "alt": str(values.get("alt") or "") or None,
                }
                if not any(existing["url"] == src for existing in block["images"]):
                    block["images"].append(item)
        elif lower_tag == "video" and block["_media_depths"]:
            src = str(values.get("src") or "").strip()
            poster = str(values.get("poster") or "").strip() or None
            if src:
                block["videos"].append({"url": src, "poster_url": poster})
        elif lower_tag == "source" and block["_media_depths"]:
            src = str(values.get("src") or "").strip()
            if src and not any(existing["url"] == src for existing in block["videos"]):
                block["videos"].append({"url": src, "poster_url": None})

        if lower_tag in self._VOID_TAGS:
            self.handle_endtag(lower_tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if not self._active:
            return
        block = self._active[-1]
        if block["_body_depth"] is not None:
            block["_body_parts"].append(data)
        if block["_timestamp_depth"] is not None:
            block["_timestamp_parts"].append(data)
        if block["_count_depth"] is not None:
            block["_count_parts"].append(data)
        if block["_link"] is not None:
            block["_link"]["parts"].append(data)
        if block["_topic_link"] is not None:
            block["_topic_link"]["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._active:
            block = self._active[-1]
            if block["_count_depth"] == self.depth:
                display = _clean_text("".join(block["_count_parts"]))
                block["_action_icon_value"] = {
                    "display": display,
                    "value": _compact_number(display),
                }
                block["_count_depth"] = None
                block["_count_parts"] = []
            if block["_action_icon_depth"] == self.depth:
                block["counts"].append(
                    block["_action_icon_value"] or {"display": "0", "value": 0}
                )
                block["_action_icon_depth"] = None
                block["_action_icon_value"] = None
            if block["_link_depth"] == self.depth and block["_link"] is not None:
                href = _external_url(block["_link"]["href"])
                text = _clean_text("".join(block["_link"]["parts"]))
                if href:
                    block["links"].append({"url": href, "text": text or None})
                block["_link_depth"] = None
                block["_link"] = None
            if block["_topic_link_depth"] == self.depth and block["_topic_link"] is not None:
                href = _absolute_threads_url(block["_topic_link"]["href"])
                text = _clean_text("".join(block["_topic_link"]["parts"]))
                if text or href:
                    block["topics"].append({"name": text or None, "url": href or None})
                block["_topic_link_depth"] = None
                block["_topic_link"] = None
            if block["_timestamp_depth"] == self.depth:
                block["timestamp"] = _clean_text("".join(block["_timestamp_parts"]))
                block["_timestamp_depth"] = None
            if block["_body_depth"] == self.depth:
                block["body"] = _clean_text("".join(block["_body_parts"]))
                block["_body_depth"] = None
            if block["_avatar_depth"] == self.depth:
                block["_avatar_depth"] = None
            if self.depth in block["_media_depths"]:
                block["_media_depths"].remove(self.depth)
            if block["_topic_depth"] == self.depth:
                block["_topic_depth"] = None
            if block["_depth"] == self.depth:
                self.blocks[_integer(block.get("_index"))] = self._finish_block(block)
                self._active.pop()

        if self._link_container_depth == self.depth:
            self._link_container_depth = None
        self.depth = max(0, self.depth - 1)

    @staticmethod
    def _finish_block(block: Mapping[str, Any]) -> dict[str, Any]:
        counts = list(block.get("counts") or [])
        while len(counts) < 4:
            counts.append({"display": "0", "value": 0})
        count_names = ("likes", "replies", "reposts", "shares")
        return {
            "text": str(block.get("body") or ""),
            "author": {
                "username": str(block.get("username") or "") or None,
                "profile_url": str(block.get("profile_url") or "") or None,
                "avatar": str(block.get("avatar") or "") or None,
                "verified": bool(block.get("verified")),
            },
            "images": list(block.get("images") or []),
            "videos": list(block.get("videos") or []),
            "links": list(block.get("links") or []),
            "topics": list(block.get("topics") or []),
            "published_at_text": str(block.get("timestamp") or "") or None,
            "stats": {name: counts[index]["value"] for index, name in enumerate(count_names)},
            "stats_display": {
                name: counts[index]["display"] for index, name in enumerate(count_names)
            },
        }


def _parse_page(source: str) -> _PageCollector:
    if not isinstance(source, str) or not source.strip():
        raise ThreadsResponseError("Threads HTML is empty")
    collector = _PageCollector()
    try:
        collector.feed(source.replace("\x00", ""))
    except (TypeError, ValueError) as exc:
        raise ThreadsResponseError("Threads HTML could not be parsed") from exc
    return collector


def _hydration_mappings(page: _PageCollector) -> Iterable[Mapping[str, Any]]:
    for attrs, payload in page.scripts:
        if "data-sjs" not in attrs and attrs.get("type", "").lower() != "application/json":
            continue
        try:
            value = json.loads(payload.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        yield from _walk_mappings(value)


def _profile_username_from_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if not ThreadsClient._is_threads_host(parsed.hostname):
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 1 or not parts[0].startswith("@"):
        return None
    username = parts[0][1:]
    if not _USERNAME_RE.fullmatch(username) or ".." in username:
        return None
    return username.lower()


class ThreadsClient:
    """通过普通 HTTP 读取 Threads 公开 SSR 页面和嵌入页。"""

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
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    def get_profile(self, reference: str) -> dict[str, Any]:
        username = self.resolve_username(reference)
        url = f"{_BASE_URL}/@{username}"
        response = self._request(url)
        return self.parse_profile_html(
            response.text,
            expected_username=username,
            page_url=str(getattr(response, "url", "") or url),
        )

    def get_user_profile(self, reference: str) -> dict[str, Any]:
        return self.get_profile(reference)

    def get_post(self, reference: str) -> dict[str, Any]:
        resolved = self.resolve_post_reference(reference)
        shortcode = str(resolved["shortcode"])
        input_username = str(resolved.get("username") or "threads")
        embed_url = f"{_BASE_URL}/@{input_username}/post/{shortcode}/embed"
        embed_response = self._request(embed_url)
        post = self.parse_embed_html(
            embed_response.text,
            expected_shortcode=shortcode,
            page_url=str(getattr(embed_response, "url", "") or embed_url),
        )
        embed_author = post.get("author") if isinstance(post.get("author"), Mapping) else {}
        username = str(embed_author.get("username") or resolved.get("username") or "threads")
        canonical_url = f"{_BASE_URL}/@{username}/post/{shortcode}"
        page_response = self._request(canonical_url)
        page = self.parse_post_page_html(
            page_response.text,
            expected_shortcode=shortcode,
            page_url=str(getattr(page_response, "url", "") or canonical_url),
        )
        author = dict(post.get("author") or {})
        if page.get("author_name"):
            author["name"] = page["author_name"]
        if page.get("username"):
            author["username"] = page["username"]
            author["profile_url"] = f"{_BASE_URL}/@{page['username']}"
        post.update(
            {
                "id": page["id"],
                "shortcode": shortcode,
                "url": page["url"],
                "owner_id": page.get("owner_id"),
                "is_reply": page.get("is_reply"),
                "author": author,
                "cover_url": page.get("cover_url") or post.get("image_url"),
                "open_graph": page["open_graph"],
                "source_url": resolved["url"],
                "page_url": str(getattr(page_response, "url", "") or canonical_url),
                "embed_url": str(getattr(embed_response, "url", "") or embed_url),
            }
        )
        return post

    @classmethod
    def resolve_username(cls, reference: str) -> str:
        if not isinstance(reference, str):
            raise ThreadsInputError("Threads profile reference must be a string")
        text = reference.strip()
        if not text:
            raise ThreadsInputError("Threads profile reference is empty")
        if text.startswith("@") and "/" not in text:
            text = text[1:]
        elif _USERNAME_RE.fullmatch(text):
            pass
        else:
            url = cls._extract_threads_url(text)
            parsed = cls._validated_url(url)
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            if len(parts) != 1 or not parts[0].startswith("@"):
                raise ThreadsInputError("URL is not a Threads profile URL")
            text = parts[0][1:]
        if (
            not _USERNAME_RE.fullmatch(text)
            or text.startswith(".")
            or text.endswith(".")
            or ".." in text
        ):
            raise ThreadsInputError("Threads username is malformed")
        return text.lower()

    @classmethod
    def resolve_post_reference(cls, reference: str) -> dict[str, Any]:
        if not isinstance(reference, str):
            raise ThreadsInputError("Threads post reference must be a string")
        text = reference.strip()
        if not text:
            raise ThreadsInputError("Threads post reference is empty")

        if _MEDIA_ID_RE.fullmatch(text):
            shortcode = cls.media_id_to_shortcode(text)
            return {
                "id": text,
                "shortcode": shortcode,
                "username": None,
                "url": f"{_BASE_URL}/@threads/post/{shortcode}",
            }
        if _SHORTCODE_RE.fullmatch(text):
            return {
                "id": cls.shortcode_to_media_id(text),
                "shortcode": text,
                "username": None,
                "url": f"{_BASE_URL}/@threads/post/{text}",
            }

        url = cls._extract_threads_url(text)
        parsed = cls._validated_url(url)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        username: str | None = None
        shortcode = ""
        if len(parts) >= 3 and parts[0].startswith("@") and parts[1].lower() == "post":
            username = cls.resolve_username(parts[0])
            shortcode = parts[2]
            if len(parts) > 3 and parts[3].lower() != "embed":
                raise ThreadsInputError("URL is not a Threads post URL")
            if len(parts) > 4:
                raise ThreadsInputError("URL is not a Threads post URL")
        elif len(parts) == 2 and parts[0].lower() in {"t", "post"}:
            shortcode = parts[1]
        else:
            raise ThreadsInputError("URL is not a Threads post URL")
        if not _SHORTCODE_RE.fullmatch(shortcode):
            raise ThreadsInputError("Threads shortcode is malformed")
        canonical_username = username or "threads"
        return {
            "id": cls.shortcode_to_media_id(shortcode),
            "shortcode": shortcode,
            "username": username,
            "url": f"{_BASE_URL}/@{canonical_username}/post/{shortcode}",
        }

    @staticmethod
    def shortcode_to_media_id(shortcode_or_url: str) -> str:
        if not isinstance(shortcode_or_url, str):
            raise ThreadsInputError("Threads shortcode must be a string")
        text = shortcode_or_url.strip()
        if not _SHORTCODE_RE.fullmatch(text):
            try:
                text = str(ThreadsClient.resolve_post_reference(text)["shortcode"])
            except ThreadsInputError as exc:
                raise ThreadsInputError("Threads shortcode is malformed") from exc
        media_id = 0
        for character in text:
            media_id = media_id * 64 + _SHORTCODE_INDEX[character]
        if media_id <= 0:
            raise ThreadsInputError("Threads shortcode does not encode a positive media id")
        return str(media_id)

    @staticmethod
    def media_id_to_shortcode(media_id: str | int) -> str:
        text = str(media_id).strip()
        if not _MEDIA_ID_RE.fullmatch(text):
            raise ThreadsInputError("Threads media id is malformed")
        number = int(text)
        encoded: list[str] = []
        while number:
            number, remainder = divmod(number, 64)
            encoded.append(_SHORTCODE_ALPHABET[remainder])
        return "".join(reversed(encoded))

    @classmethod
    def parse_profile_html(
        cls,
        source: str,
        *,
        expected_username: str | None = None,
        page_url: str = _BASE_URL,
    ) -> dict[str, Any]:
        if expected_username is not None:
            expected_username = cls.resolve_username(expected_username)
        page = _parse_page(source)
        title = page.meta.get("og:title") or page.meta.get("twitter:title") or ""
        description = (
            page.meta.get("og:description")
            or page.meta.get("description")
            or page.meta.get("twitter:description")
            or ""
        )
        canonical = _absolute_threads_url(page.canonical or page.meta.get("og:url") or page_url)
        title_match = _PROFILE_TITLE_RE.match(title.strip())
        username = _profile_username_from_url(canonical)
        if title_match:
            username = title_match.group("username").lower()
        if not username:
            username = expected_username
        if not username:
            raise ThreadsResponseError("Threads profile page does not contain a public username")
        if expected_username and username != expected_username:
            raise ThreadsResponseError(
                f"Threads profile page returned @{username}, expected @{expected_username}"
            )

        user_id: str | None = None
        for item in _hydration_mappings(page):
            candidate = str(item.get("user_id") or "")
            if candidate.isdigit() and (
                "should_show_related_profiles" in item
                or "author_related_post_igids" in item
            ):
                user_id = candidate
                break
        if user_id is None:
            match = re.search(r'"user_id"\s*:\s*"([1-9][0-9]+)"', source)
            user_id = match.group(1) if match else None

        followers = 0
        thread_count = 0
        biography = description.strip()
        display_followers: str | None = None
        display_threads: str | None = None
        description_match = _PROFILE_DESCRIPTION_RE.match(description.strip())
        if description_match:
            display_followers = description_match.group("followers").replace(" ", "")
            display_threads = description_match.group("threads").replace(" ", "")
            followers = _compact_number(display_followers)
            thread_count = _compact_number(display_threads)
            biography = str(description_match.group("bio") or "").strip()
            suffix = re.compile(
                rf"\s*See the latest conversations with\s+@{re.escape(username)}\.?\s*$",
                re.IGNORECASE,
            )
            biography = suffix.sub("", biography).strip()

        return {
            "id": user_id,
            "username": username,
            "name": title_match.group("name").strip() if title_match else "",
            "url": f"{_BASE_URL}/@{username}",
            "biography": biography,
            "avatar": page.meta.get("og:image") or page.meta.get("twitter:image") or None,
            "stats": {
                "followers": followers,
                "threads": thread_count,
            },
            "stats_display": {
                "followers": display_followers,
                "threads": display_threads,
            },
            "open_graph": {
                "title": title,
                "description": description,
                "url": page.meta.get("og:url") or canonical or None,
                "image_url": page.meta.get("og:image") or None,
                "type": page.meta.get("og:type") or None,
            },
        }

    @classmethod
    def parse_post_page_html(
        cls,
        source: str,
        *,
        expected_shortcode: str | None = None,
        page_url: str = _BASE_URL,
    ) -> dict[str, Any]:
        if expected_shortcode is not None and not _SHORTCODE_RE.fullmatch(expected_shortcode):
            raise ThreadsInputError("Threads shortcode is malformed")
        page = _parse_page(source)
        canonical = _absolute_threads_url(page.canonical or page.meta.get("og:url") or page_url)
        reference: dict[str, Any] | None = None
        try:
            reference = cls.resolve_post_reference(canonical)
        except ThreadsInputError:
            if expected_shortcode:
                reference = cls.resolve_post_reference(expected_shortcode)
        if not reference:
            raise ThreadsResponseError("Threads post page does not contain a public post URL")
        shortcode = str(reference["shortcode"])
        if expected_shortcode and shortcode != expected_shortcode:
            raise ThreadsResponseError(
                f"Threads post page returned {shortcode}, expected {expected_shortcode}"
            )

        route: Mapping[str, Any] = {}
        expected_id = cls.shortcode_to_media_id(shortcode)
        for item in _hydration_mappings(page):
            post_id = str(item.get("post_id") or "")
            if post_id == expected_id:
                route = item
                break
        if not route:
            match = re.search(
                r'"post_id"\s*:\s*"(?P<post_id>[1-9][0-9]+)"'
                r'.{0,600}?"owner_id_for_crawlers"\s*:\s*"(?P<owner_id>[1-9][0-9]+)"'
                r'.{0,1200}?"is_reply"\s*:\s*(?P<is_reply>true|false)',
                source,
                re.DOTALL,
            )
            if match and match.group("post_id") == expected_id:
                route = {
                    "post_id": match.group("post_id"),
                    "owner_id_for_crawlers": match.group("owner_id"),
                    "is_reply": match.group("is_reply") == "true",
                }

        title = page.meta.get("og:title") or page.meta.get("twitter:title") or ""
        title_match = _POST_TITLE_RE.match(title.strip())
        username = str(reference.get("username") or "") or None
        if title_match:
            username = title_match.group("username").lower()
        return {
            "id": str(route.get("post_id") or expected_id),
            "shortcode": shortcode,
            "username": username,
            "author_name": title_match.group("name").strip() if title_match else None,
            "owner_id": str(route.get("owner_id_for_crawlers") or "") or None,
            "is_reply": route.get("is_reply") if "is_reply" in route else None,
            "url": f"{_BASE_URL}/@{username or 'threads'}/post/{shortcode}",
            "cover_url": page.meta.get("og:image") or page.meta.get("twitter:image") or None,
            "open_graph": {
                "title": title,
                "description": page.meta.get("description")
                or page.meta.get("og:description")
                or page.meta.get("twitter:description")
                or "",
                "url": page.meta.get("og:url") or canonical or None,
                "image_url": page.meta.get("og:image") or None,
                "image_width": _integer(page.meta.get("og:image:width")) or None,
                "image_height": _integer(page.meta.get("og:image:height")) or None,
            },
        }

    @classmethod
    def parse_embed_html(
        cls,
        source: str,
        *,
        expected_shortcode: str | None = None,
        page_url: str = _BASE_URL,
    ) -> dict[str, Any]:
        if not isinstance(source, str) or not source.strip():
            raise ThreadsResponseError("Threads embed HTML is empty")
        collector = _EmbedCollector()
        try:
            collector.feed(source.replace("\x00", ""))
        except (TypeError, ValueError) as exc:
            raise ThreadsResponseError("Threads embed HTML could not be parsed") from exc
        blocks = [block for block in collector.blocks if block]
        if not blocks:
            raise ThreadsResponseError("Threads embed HTML does not contain a public post")

        reference: dict[str, Any] | None = None
        for value in (collector.post_url, page_url):
            try:
                reference = cls.resolve_post_reference(value)
            except ThreadsInputError:
                continue
            break
        shortcode = str((reference or {}).get("shortcode") or expected_shortcode or "")
        if not shortcode:
            raise ThreadsResponseError("Threads embed HTML does not contain a public shortcode")
        if expected_shortcode and shortcode != expected_shortcode:
            raise ThreadsResponseError(
                f"Threads embed returned {shortcode}, expected {expected_shortcode}"
            )

        post = dict(blocks[0])
        username = str(post.get("author", {}).get("username") or (reference or {}).get("username") or "")
        images = list(post.get("images") or [])
        videos = list(post.get("videos") or [])
        if videos and len(videos) + len(images) > 1:
            media_type = "carousel"
        elif videos:
            media_type = "video"
        elif len(images) > 1:
            media_type = "carousel"
        elif images:
            media_type = "image"
        else:
            media_type = "text"
        post.update(
            {
                "id": cls.shortcode_to_media_id(shortcode),
                "shortcode": shortcode,
                "url": f"{_BASE_URL}/@{username or 'threads'}/post/{shortcode}",
                "media_type": media_type,
                "image_url": images[0]["url"] if images else None,
                "video_url": videos[0]["url"] if videos else None,
                "quoted_posts": blocks[1:],
            }
        )
        return post

    def _request(self, url: str) -> requests.Response:
        path = urlsplit(url).path or "/"
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestsError as exc:
                if attempt >= self.retries:
                    raise ThreadsResponseError(f"Threads request failed for {path}: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = _integer(getattr(response, "status_code", 0))
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            if status < 200 or status >= 300:
                raise ThreadsResponseError(f"Threads returned HTTP {status} for {path}")
            return response
        raise ThreadsResponseError(f"Threads request exhausted retries for {path}")

    @staticmethod
    def _extract_threads_url(value: str) -> str:
        candidate = value.strip()
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", candidate):
            candidate = candidate.rstrip(_TRAILING_URL_PUNCTUATION)
        else:
            match = _URL_IN_TEXT_RE.search(candidate)
            if not match:
                raise ThreadsInputError("reference does not contain a supported Threads URL")
            candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        return candidate

    @classmethod
    def _validated_url(cls, value: str):
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ThreadsInputError("Threads URL is malformed") from exc
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ThreadsInputError("Threads URL must use HTTP or HTTPS")
        if not cls._is_threads_host(parsed.hostname):
            raise ThreadsInputError("Threads URL must use a threads.com or threads.net host")
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        if parsed.username or parsed.password or port not in (None, default_port):
            raise ThreadsInputError("Threads URL must not contain credentials or a custom port")
        return parsed

    @staticmethod
    def _is_threads_host(hostname: str | None) -> bool:
        host = (hostname or "").lower().rstrip(".")
        return host in {"threads.com", "threads.net"} or host.endswith(
            (".threads.com", ".threads.net")
        )
