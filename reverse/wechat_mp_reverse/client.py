from __future__ import annotations

import base64
import html
import math
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import WeChatMPInputError, WeChatMPResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

_BASE_URL = "https://mp.weixin.qq.com"
_ARTICLE_HOST = "mp.weixin.qq.com"
_EXTENSION_PATH = "/mp/getappmsgext"
_SHORT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_BIZ_RE = re.compile(r"^[A-Za-z0-9+/]{8,128}={0,2}$")
_DECIMAL_RE = re.compile(r"^[1-9][0-9]{0,31}$")
_URL_IN_TEXT_RE = re.compile(
    r"https?://mp\.weixin\.qq\.com(?::[0-9]+)?/s"
    r"(?:/[A-Za-z0-9_-]{1,160}|\?[^\s<>\"']+)?"
    r"(?:#[^\s<>\"']*)?",
    re.IGNORECASE,
)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>，。；：！？）】》、"
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_VOID_TAGS = frozenset(
    {
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
)
_BLOCK_TAGS = frozenset(
    {
        "article",
        "blockquote",
        "br",
        "div",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_TEXT_TARGETS = frozenset(
    {"activity-name", "js_name", "publish_time", "js_ip_wording"}
)


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


def _clean_text(value: str) -> str:
    value = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\xa0", " ")
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


def _absolute_url(value: Any, *, base: str = _BASE_URL) -> str:
    raw = html.unescape(str(value or "")).strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        return f"https:{raw}"
    return urljoin(f"{base.rstrip('/')}/", raw)


def _deduplicate(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _decode_js_string(value: str) -> str:
    output: list[str] = []
    index = 0
    escapes = {
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "0": "\0",
    }
    while index < len(value):
        character = value[index]
        if character != "\\" or index + 1 >= len(value):
            output.append(character)
            index += 1
            continue
        escaped = value[index + 1]
        if escaped == "x" and index + 3 < len(value):
            token = value[index + 2 : index + 4]
            if re.fullmatch(r"[0-9A-Fa-f]{2}", token):
                output.append(chr(int(token, 16)))
                index += 4
                continue
        if escaped == "u" and index + 5 < len(value):
            token = value[index + 2 : index + 6]
            if re.fullmatch(r"[0-9A-Fa-f]{4}", token):
                output.append(chr(int(token, 16)))
                index += 6
                continue
        if escaped in {"\n", "\r"}:
            index += 2
            if escaped == "\r" and index < len(value) and value[index] == "\n":
                index += 1
            continue
        output.append(escapes.get(escaped, escaped))
        index += 2
    return html.unescape("".join(output))


def _extract_js_string(source: str, name: str) -> str:
    assignment = re.compile(
        rf"(?:\bvar\s+|window\.){re.escape(name)}\s*=\s*"
        rf"(?:htmlDecode\(\s*)?"
        rf"(?:\"(?P<double>(?:\\.|[^\"\\])*)\"|"
        rf"'(?P<single>(?:\\.|[^'\\])*)')",
        re.DOTALL,
    )
    match = assignment.search(source)
    if not match:
        return ""
    return _decode_js_string(match.group("double") or match.group("single") or "")


def _extract_js_number(source: str, name: str) -> int:
    string_value = _extract_js_string(source, name)
    if string_value:
        return _integer(string_value)
    match = re.search(
        rf"(?:\bvar\s+|window\.){re.escape(name)}\s*=\s*(-?[0-9]+)", source
    )
    return _integer(match.group(1)) if match else 0


def _published_at(timestamp: int) -> str | None:
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _decode_biz_uin(value: str) -> str:
    if not value:
        return ""
    try:
        decoded = base64.b64decode(value, validate=True).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return ""
    return decoded if decoded.isdecimal() else ""


def _serialize_start_tag(
    tag: str, attrs: list[tuple[str, str | None]], *, closed: bool = False
) -> str:
    parts = [f"<{tag}"]
    for name, value in attrs:
        if value is None:
            parts.append(f" {name}")
        else:
            parts.append(f' {name}="{html.escape(value, quote=True)}"')
    parts.append("/>" if closed else ">")
    return "".join(parts)


class _ArticleCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.content_html: list[str] = []
        self.content_text: list[str] = []
        self.images: list[str] = []
        self.videos: list[str] = []
        self.links: list[str] = []
        self.target_text: dict[str, list[str]] = {name: [] for name in _TEXT_TARGETS}
        self._target_depths: dict[str, int] = {}
        self._content_depth: int | None = None
        self._content_tag = ""
        self._skip_depth: int | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lower = tag.lower()
        values = {str(name).lower(): str(value or "") for name, value in attrs}
        if lower == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = values.get("content", "")
        elif lower == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "") or self.canonical

        identity = values.get("id", "")
        if identity in _TEXT_TARGETS:
            self._target_depths[identity] = self.depth

        entering_content = identity == "js_content" and self._content_depth is None
        if entering_content:
            self._content_depth = self.depth
            self._content_tag = lower
        elif self._content_depth is not None:
            if self._skip_depth is None and lower in {"script", "style"}:
                self._skip_depth = self.depth
            elif self._skip_depth is None:
                self.content_html.append(
                    _serialize_start_tag(lower, attrs, closed=lower in _VOID_TAGS)
                )
                if lower in _BLOCK_TAGS:
                    self.content_text.append("\n")
                if lower == "img":
                    self.images.append(
                        _absolute_url(values.get("data-src") or values.get("src"))
                    )
                    if values.get("alt"):
                        self.content_text.append(values["alt"])
                elif lower in {"video", "source"}:
                    self.videos.append(_absolute_url(values.get("src")))
                elif lower == "a":
                    self.links.append(_absolute_url(values.get("href")))

        if lower not in _VOID_TAGS:
            self.depth += 1

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in _VOID_TAGS:
            return
        self.depth = max(0, self.depth - 1)
        for identity, target_depth in tuple(self._target_depths.items()):
            if self.depth == target_depth:
                del self._target_depths[identity]
        if self._content_depth is None:
            return
        if self._skip_depth is not None:
            if self.depth == self._skip_depth:
                self._skip_depth = None
            return
        if self.depth == self._content_depth and lower == self._content_tag:
            self._content_depth = None
            self._content_tag = ""
            return
        self.content_html.append(f"</{lower}>")
        if lower in _BLOCK_TAGS:
            self.content_text.append("\n")

    def handle_data(self, data: str) -> None:
        for identity in self._target_depths:
            self.target_text[identity].append(data)
        if self._content_depth is not None and self._skip_depth is None:
            self.content_html.append(html.escape(data, quote=False))
            self.content_text.append(data)

    def handle_entityref(self, name: str) -> None:
        self._handle_reference(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._handle_reference(f"&#{name};")

    def _handle_reference(self, value: str) -> None:
        decoded = html.unescape(value)
        for identity in self._target_depths:
            self.target_text[identity].append(decoded)
        if self._content_depth is not None and self._skip_depth is None:
            self.content_html.append(value)
            self.content_text.append(decoded)


def _parse_album_list(source: str) -> list[dict[str, Any]]:
    match = re.search(
        r"var\s+album_info_list\s*=\s*\[(.*?)\n\s*\];", source, re.DOTALL
    )
    if not match:
        return []
    block = match.group(1)
    pattern = re.compile(
        r"\{\s*title:\s*(?:\"(?P<td>(?:\\.|[^\"\\])*)\"|"
        r"'(?P<ts>(?:\\.|[^'\\])*)').*?"
        r"size:\s*(?:\"(?P<sd>[0-9]+)\"|'(?P<ss>[0-9]+)').*?"
        r"link:\s*(?:\"(?P<ld>(?:\\.|[^\"\\])*)\"|"
        r"'(?P<ls>(?:\\.|[^'\\])*)').*?"
        r"albumIdStr:\s*(?:\"(?P<id_d>[0-9]+)\"|'(?P<id_s>[0-9]+)')",
        re.DOTALL,
    )
    albums: list[dict[str, Any]] = []
    for item in pattern.finditer(block):
        album_id = item.group("id_d") or item.group("id_s") or ""
        albums.append(
            {
                "id": album_id,
                "title": _decode_js_string(item.group("td") or item.group("ts") or ""),
                "size": _integer(item.group("sd") or item.group("ss")),
                "url": _absolute_url(
                    _decode_js_string(item.group("ld") or item.group("ls") or "")
                ),
            }
        )
    return albums


def _parse_page_related(source: str) -> list[dict[str, str]]:
    match = re.search(
        r"var\s+album_keep_read_info\s*=\s*\{(?P<body>.*?)\n\s*\}",
        source,
        re.DOTALL,
    )
    if not match:
        return []
    body = match.group("body")
    items: list[dict[str, str]] = []
    for relation, prefix in (("previous", "pre"), ("next", "next")):
        link = _extract_object_string(body, f"{prefix}_article_link")
        title = _extract_object_string(body, f"{prefix}_article_title")
        if link or title:
            items.append(
                {
                    "relation": relation,
                    "title": title,
                    "url": _absolute_url(link),
                }
            )
    return items


def _extract_object_string(source: str, name: str) -> str:
    match = re.search(
        rf"\b{re.escape(name)}\s*:\s*"
        rf"(?:\"(?P<double>(?:\\.|[^\"\\])*)\"|"
        rf"'(?P<single>(?:\\.|[^'\\])*)')",
        source,
        re.DOTALL,
    )
    if not match:
        return ""
    return _decode_js_string(match.group("double") or match.group("single") or "")


class WeChatMPClient:
    """无需浏览器运行时即可读取微信公众号公开文章页。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30,
        retries: int = 2,
    ) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise WeChatMPInputError("timeout must be a positive finite number")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise WeChatMPInputError("retries must be a non-negative integer")
        if (
            not isinstance(user_agent, str)
            or not user_agent.strip()
            or "\r" in user_agent
            or "\n" in user_agent
        ):
            raise WeChatMPInputError("user_agent must be a non-empty single-line string")
        self.session = (
            session if session is not None else requests.Session(impersonate="chrome")
        )
        self.timeout = float(timeout)
        self.retries = retries
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def resolve_article_url(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise WeChatMPInputError("article reference must be a non-empty string")
        source = html.unescape(value.strip())
        match = _URL_IN_TEXT_RE.search(source)
        if not match:
            raise WeChatMPInputError("reference does not contain a WeChat MP article URL")
        candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise WeChatMPInputError("article URL is malformed") from exc
        if parsed.username or parsed.password:
            raise WeChatMPInputError("article URL must not contain credentials")
        if (parsed.hostname or "").lower() != _ARTICLE_HOST:
            raise WeChatMPInputError("article URL host must be mp.weixin.qq.com")
        if port is not None and port not in {80, 443}:
            raise WeChatMPInputError("article URL uses a non-standard port")
        if "%" in parsed.path or "\\" in parsed.path:
            raise WeChatMPInputError("article URL path must not be encoded")
        pieces = [part for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query, keep_blank_values=True)
        if len(pieces) == 2 and pieces[0] == "s":
            if not _SHORT_TOKEN_RE.fullmatch(pieces[1]):
                raise WeChatMPInputError("article short token is malformed")
        elif pieces == ["s"]:
            biz = (query.get("__biz") or [""])[0]
            mid = (query.get("mid") or [""])[0]
            idx = (query.get("idx") or [""])[0]
            sn = (query.get("sn") or [""])[0]
            if not (
                _BIZ_RE.fullmatch(biz)
                and _DECIMAL_RE.fullmatch(mid)
                and _DECIMAL_RE.fullmatch(idx)
                and re.fullmatch(r"[0-9a-fA-F]{16,64}", sn)
            ):
                raise WeChatMPInputError(
                    "long article URL must include valid __biz, mid, idx, and sn values"
                )
        else:
            raise WeChatMPInputError("article URL must use the public /s route")
        return urlunsplit(("https", _ARTICLE_HOST, parsed.path, parsed.query, parsed.fragment))

    @classmethod
    def parse_article_html(
        cls,
        source: str,
        *,
        page_url: str = "",
        expected_url: str = "",
    ) -> dict[str, Any]:
        if not isinstance(source, str) or not source.strip():
            raise WeChatMPResponseError("WeChat article page is empty", url=page_url or None)
        collector = _ArticleCollector()
        try:
            collector.feed(source)
            collector.close()
        except (ValueError, TypeError) as exc:
            raise WeChatMPResponseError(
                "WeChat article HTML is malformed", url=page_url or None
            ) from exc

        title = (
            _extract_js_string(source, "msg_title")
            or _clean_text("".join(collector.target_text["activity-name"]))
            or collector.meta.get("og:title", "").strip()
        )
        content_text = _clean_text("".join(collector.content_text))
        content_html = "".join(collector.content_html).strip()
        if not title or (not content_text and not content_html):
            lowered = source.lower()
            context = "verification or access page" if any(
                token in lowered
                for token in ("wappoc_appmsgcaptcha", "<title>verify", "<title>\u9a8c\u8bc1")
            ) else "public article metadata"
            raise WeChatMPResponseError(
                f"WeChat page does not contain {context}", url=page_url or None
            )

        canonical_raw = (
            _extract_js_string(source, "msg_link")
            or collector.meta.get("og:url", "")
            or collector.canonical
            or page_url
        )
        try:
            canonical_url = cls.resolve_article_url(canonical_raw)
        except WeChatMPInputError as exc:
            raise WeChatMPResponseError(
                "WeChat page returned an invalid canonical article URL",
                url=page_url or None,
            ) from exc

        biz = _extract_js_string(source, "biz") or _extract_js_string(source, "appuin")
        mid = _extract_js_string(source, "mid") or _extract_js_string(source, "appmsgid")
        idx = _extract_js_string(source, "idx") or _extract_js_string(source, "msg_daily_idx")
        sn = _extract_js_string(source, "sn")
        if expected_url:
            cls._validate_article_identity(
                expected_url,
                canonical_url,
                page_ids={"biz": biz, "mid": mid, "idx": idx, "sn": sn},
            )

        timestamp = _extract_js_number(source, "create_time") or _extract_js_number(
            source, "ct"
        )
        account_name = _extract_js_string(source, "nickname") or _clean_text(
            "".join(collector.target_text["js_name"])
        )
        username = _extract_js_string(source, "user_name")
        account = {
            "name": account_name,
            "username": username,
            "alias": _extract_js_string(source, "alias"),
            "signature": _extract_js_string(source, "profile_signature"),
            "avatar": _absolute_url(_extract_js_string(source, "round_head_img")),
            "hd_avatar": _absolute_url(_extract_js_string(source, "hd_head_img")),
            "verify_status": _extract_js_number(source, "verify_status"),
            "biz": biz,
            "biz_uin": _decode_biz_uin(biz),
        }
        description = (
            _extract_js_string(source, "msg_desc")
            or collector.meta.get("og:description", "")
            or collector.meta.get("description", "")
        ).strip()
        author = (
            _extract_js_string(source, "author")
            or collector.meta.get("article:author", "")
            or collector.meta.get("og:article:author", "")
        ).strip()
        cover_url = _absolute_url(
            _extract_js_string(source, "msg_cdn_url")
            or collector.meta.get("og:image", "")
        )
        comment_id = _extract_js_string(source, "comment_id")
        article_id = _extract_js_string(source, "appmsgid") or mid
        page_publish_text = _clean_text("".join(collector.target_text["publish_time"]))
        return {
            "source": "public_article_page",
            "url": canonical_url,
            "resolved_url": page_url or canonical_url,
            "title": html.unescape(title).strip(),
            "description": html.unescape(description),
            "author": html.unescape(author),
            "published_timestamp": timestamp,
            "published_at": _published_at(timestamp),
            "published_at_text": page_publish_text,
            "cover_url": cover_url,
            "account": account,
            "ids": {
                "biz": biz,
                "biz_uin": account["biz_uin"],
                "mid": str(mid or article_id),
                "appmsgid": str(article_id),
                "idx": str(idx),
                "sn": sn,
                "comment_id": str(comment_id),
            },
            "content_html": content_html,
            "content_text": content_text,
            "media": {
                "images": _deduplicate([cover_url, *collector.images]),
                "videos": _deduplicate(collector.videos),
            },
            "links": _deduplicate(collector.links),
            "albums": _parse_album_list(source),
            "related_articles": _parse_page_related(source),
            "comment": {
                "id": str(comment_id),
                "enabled": bool(_extract_js_number(source, "comment_enabled")),
            },
            "open_graph": dict(collector.meta),
        }

    def get_article(self, article_url: str) -> dict[str, Any]:
        expected = self.resolve_article_url(article_url)
        response = self._send("GET", expected)
        resolved = str(response.url or expected)
        self._validate_response_url(resolved, expected_path="/s")
        return self.parse_article_html(
            response.text,
            page_url=resolved,
            expected_url=expected,
        )

    def get_account_from_article(self, article_url: str) -> dict[str, Any]:
        article = self.get_article(article_url)
        return {
            "source_article_url": article["url"],
            **article["account"],
        }

    def get_article_extensions(self, article_url: str) -> dict[str, Any]:
        article = self.get_article(article_url)
        return self._get_extensions(article)

    def get_related_articles(self, article_url: str) -> dict[str, Any]:
        article = self.get_article(article_url)
        extension = self._get_extensions(article)
        combined = [*article["related_articles"], *extension["related_articles"]]
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in combined:
            identity = str(item.get("url") or item.get("title") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            items.append(item)
        return {
            "article": {"url": article["url"], "title": article["title"]},
            "count": len(items),
            "items": items,
            "tags": extension["tags"],
        }

    def _get_extensions(self, article: Mapping[str, Any]) -> dict[str, Any]:
        ids = _mapping(article.get("ids"))
        biz = str(ids.get("biz") or "")
        if not biz or not str(ids.get("mid") or ""):
            raise WeChatMPResponseError(
                "article page did not expose identifiers for extension data",
                url=str(article.get("url") or "") or None,
            )
        data = self._extension_form(article)
        response = self._send(
            "POST",
            f"{_BASE_URL}{_EXTENSION_PATH}",
            params={"f": "json", "__biz": biz},
            data=data,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": _BASE_URL,
                "Referer": str(article.get("resolved_url") or article.get("url") or ""),
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        self._validate_response_url(str(response.url or ""), expected_path=_EXTENSION_PATH)
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise WeChatMPResponseError(
                "WeChat article extension response is not JSON",
                status_code=response.status_code,
                url=str(response.url or "") or None,
            ) from exc
        root = _mapping(payload)
        base_response = _mapping(root.get("base_resp"))
        error_code = base_response.get("ret")
        if not root or _integer(error_code) != 0:
            message = str(
                base_response.get("err_msg")
                or base_response.get("errmsg")
                or root.get("errmsg")
                or "WeChat article extension API returned an error"
            )
            raise WeChatMPResponseError(
                message,
                status_code=response.status_code,
                error_code=error_code,
                url=str(response.url or "") or None,
                payload=payload,
            )
        return self._normalize_extensions(root, article)

    @staticmethod
    def _extension_form(article: Mapping[str, Any]) -> dict[str, Any]:
        ids = _mapping(article.get("ids"))
        albums = _list(article.get("albums"))
        current_album = str(_mapping(albums[0]).get("id") or "") if albums else ""
        return {
            "r": f"{time.time() % 1:.16f}",
            "__biz": str(ids.get("biz") or ""),
            "appmsg_type": "9",
            "mid": str(ids.get("mid") or ""),
            "sn": str(ids.get("sn") or ""),
            "idx": str(ids.get("idx") or ""),
            "scene": "75",
            "subscene": "0",
            "ascene": "0",
            "title": quote(str(article.get("title") or ""), safe=""),
            "ct": str(article.get("published_timestamp") or ""),
            "abtest_cookie": "",
            "devicetype": "",
            "version": "",
            "is_need_ticket": "0",
            "is_need_ad": "0",
            "comment_id": str(ids.get("comment_id") or ""),
            "is_need_reward": "0",
            "both_ad": "0",
            "reward_uin_count": "0",
            "send_time": "",
            "msg_daily_idx": str(ids.get("idx") or ""),
            "is_original": "1",
            "is_only_read": "1",
            "req_id": "",
            "pass_ticket": "",
            "is_temp_url": "0",
            "item_show_type": "0",
            "tmp_version": "1",
            "more_read_type": "0",
            "appmsg_like_type": "1",
            "related_video_sn": "",
            "related_video_num": "5",
            "vid": "",
            "is_pay_subscribe": "0",
            "pay_subscribe_uin_count": "0",
            "has_red_packet_cover": "0",
            "album_video_num": "5",
            "cur_album_id": current_album,
            "is_public_related_video": "0",
            "encode_info_by_base64": "",
            "exptype": "",
            "export_key": "",
            "export_key_extinfo": "",
            "segment_comment_id": "0",
            "business_type": "0",
        }

    @staticmethod
    def _normalize_extensions(
        payload: Mapping[str, Any], article: Mapping[str, Any]
    ) -> dict[str, Any]:
        tags: list[dict[str, Any]] = []
        for value in _list(_mapping(payload.get("public_tag_info")).get("tags")):
            item = _mapping(value)
            album = _mapping(item.get("album_info"))
            album_id = str(
                album.get("album_id_str") or item.get("album_id") or album.get("album_id") or ""
            )
            tags.append(
                {
                    "id": album_id,
                    "name": str(item.get("tag_name") or album.get("title") or ""),
                    "content_count": _integer(
                        item.get("tag_content_num") or album.get("content_size")
                    ),
                    "url": _absolute_url(item.get("tag_link") or album.get("link")),
                    "updating": bool(_integer(album.get("isupdating"))),
                }
            )

        related: list[dict[str, Any]] = []
        album_extension = _mapping(payload.get("appmsg_album_extinfo"))
        for relation, prefix in (("previous", "pre"), ("next", "next")):
            item_url = _absolute_url(album_extension.get(f"{prefix}_article_link"))
            item_title = str(album_extension.get(f"{prefix}_article_title") or "")
            if item_url or item_title:
                related.append(
                    {"relation": relation, "title": item_title, "url": item_url}
                )
        for value in _list(payload.get("more_read_list")):
            item = _mapping(value)
            item_url = _absolute_url(
                item.get("url") or item.get("link") or item.get("content_url")
            )
            item_title = str(item.get("title") or item.get("msg_title") or "")
            if item_url or item_title:
                related.append(
                    {
                        "relation": "recommended",
                        "title": item_title,
                        "url": item_url,
                        "cover_url": _absolute_url(
                            item.get("cover") or item.get("cover_url") or item.get("cdn_url")
                        ),
                    }
                )

        stats_payload = _mapping(payload.get("appmsgstat"))
        statistics: dict[str, Any] | None = None
        if stats_payload:
            statistics = {
                "reads": _integer(stats_payload.get("read_num")),
                "real_reads": _integer(stats_payload.get("real_read_num")),
                "likes": _integer(stats_payload.get("like_num")),
                "liked": bool(stats_payload.get("liked")),
                "visible": bool(stats_payload.get("show")),
            }
        return {
            "article": {
                "url": str(article.get("url") or ""),
                "title": str(article.get("title") or ""),
            },
            "base_response": dict(_mapping(payload.get("base_resp"))),
            "statistics": statistics,
            "tags": tags,
            "related_articles": related,
            "more_read": _list(payload.get("more_read_list")),
            "advertisements": _list(payload.get("advertisement_info")),
            "raw": dict(payload),
        }

    def _send(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", True)
        for attempt in range(self.retries + 1):
            try:
                if method == "GET":
                    response = self.session.get(url, **kwargs)
                elif method == "POST":
                    response = self.session.post(url, **kwargs)
                else:
                    raise AssertionError(f"unsupported method {method}")
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise WeChatMPResponseError(
                        f"WeChat request failed: {exc}", url=url, retryable=True
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = int(response.status_code or 0)
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            if status >= 400 or status <= 0:
                raise WeChatMPResponseError(
                    f"WeChat HTTP {status}",
                    status_code=status,
                    url=str(response.url or url),
                    retryable=status in _RETRYABLE_STATUS,
                )
            return response
        raise AssertionError("request retry loop exhausted")

    @staticmethod
    def _validate_response_url(url: str, *, expected_path: str) -> None:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise WeChatMPResponseError("WeChat response URL is malformed", url=url) from exc
        if (
            parsed.username
            or parsed.password
            or (parsed.hostname or "").lower() != _ARTICLE_HOST
            or (port is not None and port not in {80, 443})
        ):
            raise WeChatMPResponseError(
                "WeChat response redirected outside mp.weixin.qq.com", url=url
            )
        if expected_path == "/s":
            if parsed.path != "/s" and not parsed.path.startswith("/s/"):
                raise WeChatMPResponseError(
                    "WeChat response left the public article route", url=url
                )
        elif parsed.path != expected_path:
            raise WeChatMPResponseError(
                f"WeChat response path is not {expected_path}", url=url
            )

    @classmethod
    def _validate_article_identity(
        cls,
        expected_url: str,
        canonical_url: str,
        *,
        page_ids: Mapping[str, str],
    ) -> None:
        expected = urlsplit(cls.resolve_article_url(expected_url))
        canonical = urlsplit(cls.resolve_article_url(canonical_url))
        expected_parts = [part for part in expected.path.split("/") if part]
        canonical_parts = [part for part in canonical.path.split("/") if part]
        if len(expected_parts) == 2 and len(canonical_parts) == 2:
            if expected_parts[1] != canonical_parts[1]:
                raise WeChatMPResponseError(
                    "WeChat article canonical token does not match the request",
                    url=canonical_url,
                )
            return
        expected_query = parse_qs(expected.query)
        for query_name, page_name in (
            ("__biz", "biz"),
            ("mid", "mid"),
            ("idx", "idx"),
            ("sn", "sn"),
        ):
            expected_value = (expected_query.get(query_name) or [""])[0]
            page_value = str(page_ids.get(page_name) or "")
            if expected_value and page_value and expected_value != page_value:
                raise WeChatMPResponseError(
                    f"WeChat article {query_name} does not match the request",
                    url=canonical_url,
                )
