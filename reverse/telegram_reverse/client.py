from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from curl_cffi import requests

from .errors import TelegramInputError, TelegramResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_BASE_URL = "https://t.me"
_MAX_CHANNEL_BATCH = 20
_MAX_SEARCH_LIMIT = 100
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_POST_ID_RE = re.compile(r"^[1-9]\d*$")
_COUNT_RE = re.compile(r"([0-9][0-9.,\s]*\s*[KMBT]?)", re.IGNORECASE)
_COUNT_SUFFIX_RE = re.compile(r"([0-9][0-9.,\s]*\s*[KMBT]?)\s*$", re.IGNORECASE)
_BACKGROUND_URL_RE = re.compile(
    r"background-image\s*:\s*url\(\s*(['\"]?)(.*?)\1\s*\)",
    re.IGNORECASE,
)
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


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self._stack = [self.root]

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        node = _Node(tag.lower(), {key: value or "" for key, value in attrs})
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == target:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _walk(node: _Node):
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _walk(child)


def _find_class(node: _Node, class_name: str) -> _Node | None:
    return next((item for item in _walk(node) if class_name in item.classes), None)


def _find_all_class(node: _Node, class_name: str) -> list[_Node]:
    return [item for item in _walk(node) if class_name in item.classes]


def _find_tag(node: _Node, tag: str) -> _Node | None:
    return next((item for item in _walk(node) if item.tag == tag), None)


def _render_text(node: _Node) -> str:
    parts: list[str] = []

    def visit(item: _Node | str) -> None:
        if isinstance(item, str):
            parts.append(item)
            return
        if item.tag in {"script", "style", "svg"}:
            return
        if item.tag == "br":
            parts.append("\n")
            return
        if item.tag == "img" and item.attrs.get("alt"):
            parts.append(item.attrs["alt"])
        for child in item.children:
            visit(child)

    visit(node)
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in "".join(parts).split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    output: list[str] = []
    for line in lines:
        if line or not output or output[-1]:
            output.append(line)
    return "\n".join(output)


def _absolute_url(value: str) -> str:
    return urljoin(f"{_BASE_URL}/", value.strip()) if value else ""


def _style_url(node: _Node | None) -> str:
    if node is None:
        return ""
    match = _BACKGROUND_URL_RE.search(node.attrs.get("style", ""))
    return _absolute_url(match.group(2)) if match else ""


def _number(value: str) -> int:
    raw = value.strip().replace("\xa0", "").replace(" ", "")
    match = _COUNT_RE.search(raw)
    if not match:
        return 0
    token = match.group(1).replace(" ", "")
    suffix = token[-1:].upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}.get(
        suffix,
        1,
    )
    if multiplier != 1:
        token = token[:-1]
    if "," in token and "." not in token:
        pieces = token.split(",")
        token = ".".join(pieces) if multiplier != 1 and len(pieces[-1]) <= 2 else "".join(pieces)
    else:
        token = token.replace(",", "")
    try:
        return int(Decimal(token) * multiplier)
    except (InvalidOperation, ValueError):
        return 0


def _duration_seconds(value: str) -> int:
    try:
        fields = [int(item) for item in value.strip().split(":")]
    except ValueError:
        return 0
    total = 0
    for field_value in fields:
        total = total * 60 + field_value
    return total


def _timestamp(value: str) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _parse_document(source: str) -> _Node:
    parser = _TreeParser()
    parser.feed(source)
    parser.close()
    return parser.root


def _meta_content(root: _Node, *names: str) -> str:
    expected = set(names)
    for node in _walk(root):
        if node.tag != "meta":
            continue
        identity = node.attrs.get("property") or node.attrs.get("name")
        if identity in expected:
            return node.attrs.get("content", "").strip()
    return ""


def _post_sort_key(post: dict[str, Any]) -> int:
    try:
        return int(post["id"])
    except (KeyError, TypeError, ValueError):
        return 0


class TelegramClient:
    """无需浏览器即可匿名读取 Telegram 公开频道预览。"""

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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    def get_channel(self, channel_url_or_username: str) -> dict[str, Any]:
        username = self._channel(channel_url_or_username)
        page = self._get_page(username)
        return page["channel"]

    def get_channels(self, channel_references: Sequence[str]) -> dict[str, Any]:
        if isinstance(channel_references, (str, bytes)):
            raise TelegramInputError("channels must be a sequence of channel references")
        try:
            references = list(channel_references)
        except TypeError as exc:
            raise TelegramInputError("channels must be a sequence of channel references") from exc
        if not references:
            raise TelegramInputError("channels must contain at least one channel reference")
        if len(references) > _MAX_CHANNEL_BATCH:
            raise TelegramInputError(
                f"channels must contain at most {_MAX_CHANNEL_BATCH} channel references"
            )

        results: list[dict[str, Any]] = []
        success_count = 0
        for reference in references:
            try:
                channel = self.get_channel(reference)
            except TelegramInputError as exc:
                results.append(
                    {
                        "input": reference,
                        "ok": False,
                        "channel": None,
                        "error": {"code": "input_error", "message": str(exc)},
                    }
                )
            except TelegramResponseError as exc:
                results.append(
                    {
                        "input": reference,
                        "ok": False,
                        "channel": None,
                        "error": {"code": "response_error", "message": str(exc)},
                    }
                )
            else:
                success_count += 1
                results.append(
                    {
                        "input": reference,
                        "ok": True,
                        "channel": channel,
                        "error": None,
                    }
                )
        return {
            "requested": len(references),
            "success_count": success_count,
            "error_count": len(references) - success_count,
            "results": results,
        }

    def get_posts(
        self,
        channel_url_or_username: str,
        *,
        before: str | int | None = None,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        username = self._channel(channel_url_or_username)
        cursor = self._before(before)
        if limit is not None and (isinstance(limit, bool) or limit < 0):
            raise TelegramInputError("limit must be non-negative")
        if limit == 0:
            return {
                "channel": {"username": username, "url": f"{_BASE_URL}/{username}"},
                "before": cursor,
                "next_before": cursor,
                "has_more": False,
                "total": 0,
                "posts": [],
            }

        return self._collect_posts(username, before=cursor, limit=limit)

    def search(
        self,
        channel_url_or_username: str,
        query: str,
        *,
        before: str | int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        username = self._channel(channel_url_or_username)
        normalized_query = self._query(query)
        cursor = self._before(before)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_SEARCH_LIMIT
        ):
            raise TelegramInputError(
                f"limit must be between 1 and {_MAX_SEARCH_LIMIT} for search"
            )
        result = self._collect_posts(
            username,
            before=cursor,
            limit=limit,
            query=normalized_query,
        )
        return {
            "channel": result["channel"],
            "query": normalized_query,
            "scope": "recent",
            "bounded": True,
            "before": result["before"],
            "next_before": result["next_before"],
            "has_more": result["has_more"],
            "total": result["total"],
            "posts": result["posts"],
        }

    def _collect_posts(
        self,
        username: str,
        *,
        before: str | None,
        limit: int | None,
        query: str | None = None,
    ) -> dict[str, Any]:
        cursor = before
        initial_cursor = cursor
        seen_cursors: set[str] = set()
        seen_posts: set[str] = set()
        collected: list[dict[str, Any]] = []
        channel: dict[str, Any] | None = None
        has_more = True

        while has_more and (limit is None or len(collected) < limit):
            cursor_key = cursor or "latest"
            if cursor_key in seen_cursors:
                raise TelegramResponseError(f"Telegram pagination repeated cursor {cursor_key}")
            seen_cursors.add(cursor_key)
            page = self._get_page(username, query=query, before=cursor)
            channel = channel or page["channel"]
            posts = sorted(page["posts"], key=_post_sort_key, reverse=True)
            available = [
                post
                for post in posts
                if str(post.get("id") or "")
                and str(post.get("id")) not in seen_posts
            ]
            remaining = None if limit is None else limit - len(collected)
            selected = available if remaining is None else available[:remaining]
            for post in selected:
                identity = str(post.get("id") or "")
                seen_posts.add(identity)
                collected.append(post)
            page_truncated = len(selected) < len(available)
            next_cursor = page["next_before"]
            has_more = page_truncated or bool(next_cursor)
            cursor = next_cursor
            if not posts:
                break

        if channel is None:
            channel = {"username": username, "url": f"{_BASE_URL}/{username}"}
        next_before = str(collected[-1]["id"]) if has_more and collected else None
        return {
            "channel": channel,
            "before": initial_cursor,
            "next_before": next_before,
            "has_more": bool(next_before),
            "total": len(collected),
            "posts": collected,
        }

    def get_post(
        self,
        post_url_or_channel: str,
        post_id: str | int | None = None,
    ) -> dict[str, Any]:
        username, identifier = self._post(post_url_or_channel, post_id)
        page = self._get_page(username, before=str(int(identifier) + 1))
        for post in page["posts"]:
            if post["id"] == identifier and post["channel"].lower() == username.lower():
                return post
        raise TelegramResponseError(f"Telegram post {username}/{identifier} was not found")

    @staticmethod
    def parse_channel_html(source: str, *, fallback_username: str = "") -> dict[str, Any]:
        root = _parse_document(source)
        return TelegramClient._parse_channel(root, fallback_username)

    @staticmethod
    def parse_posts_html(source: str) -> list[dict[str, Any]]:
        root = _parse_document(source)
        return TelegramClient._parse_posts(root)

    @staticmethod
    def parse_post_html(source: str, *, post_id: str | int | None = None) -> dict[str, Any]:
        posts = TelegramClient.parse_posts_html(source)
        if post_id is None:
            if len(posts) != 1:
                raise TelegramResponseError("Telegram HTML does not contain exactly one post")
            return posts[0]
        identifier = TelegramClient._positive_id(post_id, "post_id")
        for post in posts:
            if post["id"] == identifier:
                return post
        raise TelegramResponseError(f"Telegram HTML does not contain post {identifier}")

    def _get_page(
        self,
        username: str,
        *,
        query: str | None = None,
        before: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {}
        if query is not None:
            params["q"] = query
        if before:
            params["before"] = before
        response = self._request(f"{_BASE_URL}/s/{username}", params=params)
        root = _parse_document(response.text)
        history = _find_class(root, "tgme_channel_history")
        if history is None:
            raise TelegramResponseError("Telegram HTML does not contain a public channel history")
        return {
            "channel": self._parse_channel(root, username),
            "posts": self._parse_posts(history),
            "next_before": self._next_before(root),
        }

    def _request(self, url: str, *, params: dict[str, str]) -> requests.Response:
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise TelegramResponseError(f"Telegram request failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code == 200:
                return response
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.retries:
                    time.sleep(0.4 * (2**attempt))
                    continue
            raise TelegramResponseError(f"Telegram returned HTTP {response.status_code}")
        raise TelegramResponseError("Telegram request exhausted all retries")

    @staticmethod
    def _parse_channel(root: _Node, fallback_username: str) -> dict[str, Any]:
        main = next((node for node in _walk(root) if node.tag == "main"), None)
        canonical = (main.attrs.get("data-url", "") if main else "").strip("/")
        username = canonical or fallback_username
        info = _find_class(root, "tgme_channel_info")
        header = _find_class(root, "tgme_header_info")
        channel_scope = info or header or root
        title_node = _find_class(channel_scope, "tgme_channel_info_header_title") or _find_class(
            channel_scope, "tgme_header_title"
        )
        title = _render_text(title_node) if title_node else _meta_content(root, "og:title", "twitter:title")
        if title.endswith(" - Telegram") or title.endswith(" \u2013 Telegram"):
            title = title[:-11].rstrip()
        description_node = _find_class(root, "tgme_channel_info_description")
        description = (
            _render_text(description_node)
            if description_node
            else _meta_content(root, "og:description", "twitter:description")
        )
        image_node = _find_class(channel_scope, "tgme_page_photo_image")
        image = _find_tag(image_node, "img") if image_node else None
        avatar = image.attrs.get("src", "") if image else _meta_content(root, "og:image", "twitter:image")

        counters: dict[str, int] = {}
        counter_text: dict[str, str] = {}
        for counter in _find_all_class(root, "tgme_channel_info_counter"):
            value_node = _find_class(counter, "counter_value")
            type_node = _find_class(counter, "counter_type")
            label = _render_text(type_node).lower().replace(" ", "_") if type_node else ""
            raw_value = _render_text(value_node) if value_node else ""
            if label:
                counters[label] = _number(raw_value)
                counter_text[label] = raw_value
        if not counters:
            header_counter = _find_class(root, "tgme_header_counter")
            raw_counter = _render_text(header_counter) if header_counter else ""
            match = re.match(r"\s*([0-9][0-9.,]*\s*[KMBT]?)\s+(.+?)\s*$", raw_counter, re.IGNORECASE)
            if match:
                label = match.group(2).lower().replace(" ", "_")
                counters[label] = _number(match.group(1))
                counter_text[label] = match.group(1)
        if not username:
            username = _meta_content(root, "twitter:site").lstrip("@")
        return {
            "username": username,
            "url": f"{_BASE_URL}/{username}" if username else "",
            "title": title,
            "description": description,
            "avatar": _absolute_url(avatar),
            "verified": _find_class(channel_scope, "verified-icon") is not None,
            "subscribers": counters.get("subscribers", 0),
            "members": counters.get("members", 0),
            "counters": counters,
            "counter_text": counter_text,
        }

    @staticmethod
    def _parse_posts(root: _Node) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        for node in _find_all_class(root, "tgme_widget_message"):
            reference = node.attrs.get("data-post", "")
            if "/" not in reference:
                continue
            channel, identifier = reference.rsplit("/", 1)
            if not channel or not _POST_ID_RE.fullmatch(identifier):
                continue
            posts.append(TelegramClient._parse_post_node(node, channel, identifier))
        return posts

    @staticmethod
    def _parse_post_node(node: _Node, channel: str, identifier: str) -> dict[str, Any]:
        text_node = _find_class(node, "tgme_widget_message_text")
        text = _render_text(text_node) if text_node else ""
        author_node = _find_class(node, "tgme_widget_message_owner_name")
        author_link = author_node.attrs.get("href", "") if author_node else ""
        links: list[dict[str, str]] = []
        if text_node:
            for link in (item for item in _walk(text_node) if item.tag == "a"):
                href = _absolute_url(link.attrs.get("href", ""))
                if href:
                    links.append({"url": href, "text": _render_text(link)})

        views_node = _find_class(node, "tgme_widget_message_views")
        views_text = _render_text(views_node) if views_node else ""
        forwards_node = _find_class(node, "tgme_widget_message_forwards") or _find_class(
            node, "tgme_widget_message_shares"
        )
        forwards_text = _render_text(forwards_node) if forwards_node else ""
        time_node = next((item for item in _walk(node) if item.tag == "time" and item.attrs.get("datetime")), None)
        published_at = time_node.attrs.get("datetime", "") if time_node else ""
        meta_node = _find_class(node, "tgme_widget_message_meta")

        forwarded_from = None
        forwarded_node = _find_class(node, "tgme_widget_message_forwarded_from")
        if forwarded_node:
            source_link = _find_tag(forwarded_node, "a")
            source_url = _absolute_url(source_link.attrs.get("href", "")) if source_link else ""
            source_name_node = _find_class(forwarded_node, "tgme_widget_message_forwarded_from_name")
            forwarded_from = {
                "name": _render_text(source_name_node or source_link or forwarded_node),
                "url": source_url,
            }

        reactions = TelegramClient._parse_reactions(node)
        return {
            "id": identifier,
            "channel": channel,
            "url": f"{_BASE_URL}/{channel}/{identifier}",
            "author": {
                "name": _render_text(author_node) if author_node else "",
                "url": _absolute_url(author_link),
            },
            "text": text,
            "links": links,
            "media": TelegramClient._parse_media(node),
            "views": _number(views_text),
            "views_text": views_text,
            "forwards": _number(forwards_text),
            "forwards_text": forwards_text,
            "forwarded_from": forwarded_from,
            "reaction_count": sum(item["count"] for item in reactions),
            "reactions": reactions,
            "published_at": published_at,
            "published_timestamp": _timestamp(published_at),
            "edited": "edited" in (_render_text(meta_node).lower() if meta_node else ""),
        }

    @staticmethod
    def _parse_reactions(node: _Node) -> list[dict[str, Any]]:
        container = _find_class(node, "tgme_widget_message_reactions")
        if container is None:
            return []
        output: list[dict[str, Any]] = []
        for reaction in _find_all_class(container, "tgme_reaction"):
            value = _render_text(reaction)
            count_match = _COUNT_SUFFIX_RE.search(value)
            count_text = count_match.group(1).strip() if count_match else ""
            emoji_node = _find_class(reaction, "emoji")
            custom_emoji = next((item for item in _walk(reaction) if item.tag == "tg-emoji"), None)
            paid = "tgme_reaction_paid" in reaction.classes
            output.append(
                {
                    "emoji": "\u2b50" if paid else (_render_text(emoji_node) if emoji_node else ""),
                    "emoji_id": custom_emoji.attrs.get("emoji-id", "") if custom_emoji else "",
                    "paid": paid,
                    "count": _number(count_text),
                    "count_text": count_text,
                }
            )
        return output

    @staticmethod
    def _parse_media(node: _Node) -> list[dict[str, Any]]:
        media: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def append(item: dict[str, Any]) -> None:
            identity = (str(item.get("type") or ""), str(item.get("url") or item.get("thumbnail_url") or ""))
            if identity[1] and identity not in seen:
                seen.add(identity)
                media.append(item)

        for photo in _find_all_class(node, "tgme_widget_message_photo_wrap"):
            append({"type": "photo", "url": _style_url(photo)})

        for player in _find_all_class(node, "tgme_widget_message_video_player"):
            video = next((item for item in _walk(player) if item.tag == "video" and item.attrs.get("src")), None)
            thumb = _find_class(player, "tgme_widget_message_video_thumb")
            duration_node = _find_class(player, "message_video_duration")
            duration_text = _render_text(duration_node) if duration_node else ""
            append(
                {
                    "type": "video",
                    "url": _absolute_url(video.attrs.get("src", "")) if video else "",
                    "thumbnail_url": _style_url(thumb),
                    "duration": _duration_seconds(duration_text),
                    "duration_text": duration_text,
                }
            )

        for audio in (item for item in _walk(node) if item.tag == "audio"):
            source = audio.attrs.get("src", "")
            if not source:
                source_node = next(
                    (
                        item
                        for item in _walk(audio)
                        if item.tag == "source" and item.attrs.get("src")
                    ),
                    None,
                )
                source = source_node.attrs.get("src", "") if source_node else ""
            append({"type": "audio", "url": _absolute_url(source)})

        for document in _find_all_class(node, "tgme_widget_message_document_wrap"):
            link = document if document.tag == "a" else _find_tag(document, "a")
            append(
                {
                    "type": "document",
                    "url": _absolute_url(link.attrs.get("href", "")) if link else "",
                    "name": _render_text(_find_class(document, "tgme_widget_message_document_title") or document),
                }
            )

        for sticker in _find_all_class(node, "tgme_widget_message_sticker"):
            append({"type": "sticker", "url": _style_url(sticker)})

        for preview in _find_all_class(node, "tgme_widget_message_link_preview"):
            title_node = _find_class(preview, "link_preview_title")
            description_node = _find_class(preview, "link_preview_description")
            image_node = _find_class(preview, "link_preview_image")
            append(
                {
                    "type": "link_preview",
                    "url": _absolute_url(preview.attrs.get("href", "")),
                    "title": _render_text(title_node) if title_node else "",
                    "description": _render_text(description_node) if description_node else "",
                    "thumbnail_url": _style_url(image_node),
                }
            )
        return media

    @staticmethod
    def _next_before(root: _Node) -> str | None:
        more = _find_class(root, "js-messages_more")
        value = more.attrs.get("data-before", "") if more else ""
        if _POST_ID_RE.fullmatch(value):
            return value
        for node in _walk(root):
            if node.tag != "link" or node.attrs.get("rel") != "prev":
                continue
            query = urlsplit(_absolute_url(node.attrs.get("href", ""))).query
            match = re.search(r"(?:^|&)before=([1-9]\d*)(?:&|$)", query)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _channel(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TelegramInputError("channel must be a public username or t.me URL")
        candidate = value.strip()
        if candidate.startswith("@"):
            candidate = candidate[1:]
        elif "://" in candidate or candidate.lower().startswith(("t.me/", "telegram.me/")):
            url = candidate if "://" in candidate else f"https://{candidate}"
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
                raise TelegramInputError("channel URL must use the t.me host")
            parts = [part for part in parsed.path.split("/") if part]
            if parts and parts[0].lower() == "s":
                parts.pop(0)
            if len(parts) != 1:
                raise TelegramInputError("channel URL must identify one public channel")
            candidate = parts[0] if parts else ""
        if not _USERNAME_RE.fullmatch(candidate) or candidate.lower() in {"joinchat", "addstickers", "share", "proxy"}:
            raise TelegramInputError("channel username is malformed")
        return candidate

    @staticmethod
    def _post(value: str, post_id: str | int | None) -> tuple[str, str]:
        if post_id is not None:
            return TelegramClient._channel(value), TelegramClient._positive_id(post_id, "post_id")
        if not isinstance(value, str) or not value.strip():
            raise TelegramInputError("post must be channel/post_id or a t.me post URL")
        candidate = value.strip()
        if "://" in candidate or candidate.lower().startswith(("t.me/", "telegram.me/")):
            url = candidate if "://" in candidate else f"https://{candidate}"
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
                raise TelegramInputError("post URL must use the t.me host")
            parts = [part for part in parsed.path.split("/") if part]
        else:
            parts = [part for part in candidate.split("/") if part]
        if parts and parts[0].lower() == "s":
            parts.pop(0)
        if len(parts) != 2:
            raise TelegramInputError("post must identify a public channel and post ID")
        return TelegramClient._channel(parts[0]), TelegramClient._positive_id(parts[1], "post_id")

    @staticmethod
    def _positive_id(value: str | int, name: str) -> str:
        if isinstance(value, bool):
            raise TelegramInputError(f"{name} must be a positive integer")
        candidate = str(value).strip()
        if not _POST_ID_RE.fullmatch(candidate):
            raise TelegramInputError(f"{name} must be a positive integer")
        return candidate

    @staticmethod
    def _before(value: str | int | None) -> str | None:
        return None if value is None else TelegramClient._positive_id(value, "before")

    @staticmethod
    def _query(value: str) -> str:
        if not isinstance(value, str):
            raise TelegramInputError("query must be a string")
        query = value.strip()
        if not 1 <= len(query) <= 100:
            raise TelegramInputError("query must contain between 1 and 100 characters")
        if any(unicodedata.category(character) == "Cc" for character in query):
            raise TelegramInputError("query must not contain control characters")
        return query
