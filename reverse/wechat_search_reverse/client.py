from __future__ import annotations

import html
import math
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import WeChatSearchInputError, WeChatSearchResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

_BASE_URL = "https://weixin.sogou.com"
_SEARCH_URL = f"{_BASE_URL}/weixin"
_SEARCH_HOST = "weixin.sogou.com"
_ARTICLE_HOST = "mp.weixin.qq.com"
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_ARTICLE_BOX_RE = re.compile(r"^sogou_vr_11002601_box_[0-9]+$")
_ACCOUNT_BOX_RE = re.compile(r"^sogou_vr_11002301_box_[0-9]+$")
_TITLE_ID_RE = re.compile(r"^sogou_vr_[0-9]+_title_[0-9]+$")
_SUMMARY_ID_RE = re.compile(r"^sogou_vr_[0-9]+_summary_[0-9]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ANTI_MARKERS = (
    "id=\"seccodeForm\"",
    "id='seccodeForm'",
    "antispider.min.js",
    "这些请求是您的正常行为而不是自动程序发出的",
    "访问过于频繁",
)


def _clean_text(value: Any) -> str:
    source = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", source).strip()


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError, OverflowError):
        return 0


def _published_at(timestamp: int) -> str | None:
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _absolute_url(value: Any, *, base: str = _BASE_URL) -> str:
    source = html.unescape(str(value or "")).strip()
    if not source:
        return ""
    if source.startswith("//"):
        return f"https:{source}"
    return urljoin(f"{base.rstrip('/')}/", source)


def _cover_urls(value: Any) -> tuple[str, str]:
    thumbnail = _absolute_url(value)
    if not thumbnail:
        return "", ""
    parsed = urlsplit(thumbnail)
    original = str(parse_qs(parsed.query).get("url", [""])[0]).strip()
    if original.startswith("//"):
        original = f"https:{original}"
    if urlsplit(original).scheme not in {"http", "https"}:
        original = thumbnail
    return original, thumbnail


def _decode_js_string(value: str) -> str:
    output: list[str] = []
    index = 0
    escapes = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "0": "\0"}
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
        output.append(escapes.get(escaped, escaped))
        index += 2
    return "".join(output)


class _SogouSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.items: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.item_depth = -1
        self.capture = ""
        self.capture_depth = -1
        self.capture_parts: list[str] = []
        self.dl_term = ""
        self.total: int | None = None
        self.next_href = ""
        self.no_results = False
        self.result_context = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._handle_start(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.depth += 1

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._handle_start(tag, attrs)

    def _handle_start(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lower = tag.lower()
        values = {str(name).lower(): str(value or "") for name, value in attrs}
        identity = values.get("id", "")
        classes = set(values.get("class", "").split())

        if "wx-topbox" in classes:
            self.result_context = True
        if identity == "noresult_part1_container":
            self.no_results = True
            self.result_context = True
        if lower == "a" and identity == "sogou_next":
            self.next_href = values.get("href", "")

        kind = ""
        if lower == "li" and _ARTICLE_BOX_RE.fullmatch(identity):
            kind = "article"
        elif lower == "li" and _ACCOUNT_BOX_RE.fullmatch(identity):
            kind = "account"
        if kind:
            self.result_context = True
            self.current = {
                "kind": kind,
                "id": values.get("d", ""),
                "title": "",
                "summary": "",
                "url": "",
                "image": "",
                "account_name": "",
                "published_timestamp": 0,
                "username": "",
                "description": "",
                "verification": "",
            }
            self.item_depth = self.depth
            self.dl_term = ""

        if self.current is None:
            return
        if lower == "img" and not self.current["image"]:
            self.current["image"] = values.get("data-src") or values.get("src", "")
        if lower == "a" and _TITLE_ID_RE.fullmatch(identity):
            self.current["url"] = values.get("href", "")
            self._start_capture("title")
        elif lower == "p" and _SUMMARY_ID_RE.fullmatch(identity):
            self._start_capture("summary")
        elif lower == "span" and "all-time-y2" in classes:
            self._start_capture("account_name")
        elif lower == "label" and values.get("name") == "em_weixinhao":
            self._start_capture("username")
        elif lower == "p" and "info" in classes:
            self._start_capture("account_info")
        elif lower == "script":
            self._start_capture("script")
        elif lower == "dt":
            self._start_capture("dl_term")
        elif lower == "dd":
            self._start_capture("dl_value")

    def _start_capture(self, name: str) -> None:
        if self.capture:
            return
        self.capture = name
        self.capture_depth = self.depth
        self.capture_parts = []

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.capture_parts.append(data)

    def handle_comment(self, data: str) -> None:
        match = re.search(r"resultbarnum:\s*([0-9,]+)", data)
        if match:
            self.total = _integer(match.group(1))

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower not in _VOID_TAGS:
            self.depth = max(0, self.depth - 1)
        if self.capture and self.depth == self.capture_depth:
            self._finish_capture()
        if lower == "li" and self.current is not None and self.depth == self.item_depth:
            self.items.append(self.current)
            self.current = None
            self.item_depth = -1
            self.dl_term = ""

    def _finish_capture(self) -> None:
        if self.current is None:
            self.capture = ""
            self.capture_parts = []
            return
        raw = "".join(self.capture_parts)
        value = _clean_text(raw)
        if self.capture in {"title", "summary", "account_name", "username"}:
            self.current[self.capture] = value
        elif self.capture == "script":
            match = re.search(r"timeConvert\(\s*['\"]([0-9]+)['\"]\s*\)", raw)
            if match:
                self.current["published_timestamp"] = _integer(match.group(1))
        elif self.capture == "account_info":
            match = re.search(r"(?:微信号|帐号|账号)\s*[:：]\s*([^\s|]+)", value)
            if match and not self.current["username"]:
                self.current["username"] = match.group(1)
        elif self.capture == "dl_term":
            self.dl_term = value
        elif self.capture == "dl_value":
            if "功能介绍" in self.dl_term or "帐号简介" in self.dl_term or "账号简介" in self.dl_term:
                self.current["description"] = value
            elif "微信认证" in self.dl_term or "认证" == self.dl_term.rstrip("：:"):
                self.current["verification"] = value
        self.capture = ""
        self.capture_depth = -1
        self.capture_parts = []


class WeChatSearchClient:
    """使用匿名 HTTP 会话搜索搜狗公开微信索引。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30,
        retries: int = 2,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise WeChatSearchInputError("timeout must be a positive finite number")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise WeChatSearchInputError("retries must be a non-negative integer")
        if not isinstance(user_agent, str) or not user_agent.strip() or _CONTROL_RE.search(user_agent):
            raise WeChatSearchInputError("user_agent must be a non-empty HTTP header value")
        self.session = session or requests.Session(impersonate="chrome")
        self.timeout = float(timeout)
        self.retries = retries
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": user_agent,
            }
        )

    def search(
        self,
        keyword: str,
        *,
        business_type: str = "article",
        page: int = 1,
        limit: int | None = 10,
    ) -> dict[str, Any]:
        vertical = str(business_type or "").strip().lower()
        if vertical == "article":
            return self.search_articles(keyword, page=page, limit=limit)
        if vertical == "account":
            return self.search_accounts(keyword, page=page, limit=limit)
        raise WeChatSearchInputError(
            "business_type must be 'article' or 'account' for the public Sogou index"
        )

    def search_articles(
        self, keyword: str, *, page: int = 1, limit: int | None = 10
    ) -> dict[str, Any]:
        return self._search(keyword, kind="article", page=page, limit=limit)

    def search_accounts(
        self, keyword: str, *, page: int = 1, limit: int | None = 10
    ) -> dict[str, Any]:
        return self._search(keyword, kind="account", page=page, limit=limit)

    def _search(
        self,
        keyword: str,
        *,
        kind: str,
        page: int,
        limit: int | None,
    ) -> dict[str, Any]:
        query = self._validate_keyword(keyword)
        page_number = self._validate_page(page)
        item_limit = self._validate_limit(limit)
        response = self._request(
            _SEARCH_URL,
            params={
                "type": "2" if kind == "article" else "1",
                "query": query,
                "ie": "utf8",
                "s_from": "input",
                "_sug_": "n",
                "_sug_type_": "",
                "page": page_number,
            },
        )
        return self.parse_search_html(
            response.text,
            keyword=query,
            kind=kind,
            page=page_number,
            limit=item_limit,
            page_url=str(response.url or _SEARCH_URL),
        )

    def resolve_article_url(self, sogou_url: str) -> str:
        redirect_url = self._validate_sogou_link(sogou_url)
        self._seed_identity_from_link(redirect_url)
        response = self._request(
            redirect_url,
            headers={"Referer": f"{_BASE_URL}/"},
        )
        return self.parse_article_redirect_html(response.text)

    @classmethod
    def parse_search_html(
        cls,
        source: str,
        *,
        keyword: str = "",
        kind: str = "article",
        page: int = 1,
        limit: int | None = 10,
        page_url: str = "",
    ) -> dict[str, Any]:
        text = str(source or "")
        cls._raise_for_access_page(text, page_url=page_url)
        if kind not in {"article", "account"}:
            raise WeChatSearchInputError("kind must be 'article' or 'account'")
        parser = _SogouSearchParser()
        try:
            parser.feed(text.replace("\x00", ""))
            parser.close()
        except (TypeError, ValueError) as exc:
            raise WeChatSearchResponseError("Sogou WeChat search HTML is malformed") from exc
        if not parser.result_context:
            raise WeChatSearchResponseError(
                "Sogou WeChat response did not contain a search result state",
                error_code="missing_result_state",
                url=page_url or None,
            )

        normalized = [
            cls._normalize_article(item)
            if item.get("kind") == "article"
            else cls._normalize_account(item)
            for item in parser.items
            if item.get("kind") == kind
        ]
        available = len(normalized)
        if limit is not None:
            normalized = normalized[:limit]
        next_page = cls._next_page(parser.next_href)
        total = parser.total
        if parser.no_results and total is None:
            total = 0
        return {
            "provider": "sogou_weixin",
            "keyword": keyword,
            "business_type": kind,
            "page": page,
            "page_url": page_url,
            "total": total,
            "available_on_page": available,
            "count": len(normalized),
            "has_more": bool(parser.next_href),
            "next_page": next_page,
            "items": normalized,
        }

    @classmethod
    def parse_article_redirect_html(cls, source: str) -> str:
        text = str(source or "")
        cls._raise_for_access_page(text)
        pieces: list[str] = []
        assignment = re.compile(
            r"\burl\s*(?P<operator>\+?=)\s*(?P<quote>['\"])(?P<value>(?:\\.|(?!\2).)*)\2\s*;",
            re.DOTALL,
        )
        for match in assignment.finditer(text):
            value = _decode_js_string(match.group("value"))
            if match.group("operator") == "=":
                pieces = [value]
            else:
                pieces.append(value)
        target = "".join(pieces).strip()
        if re.search(r"\burl\.replace\(\s*['\"]@['\"]\s*,\s*['\"]['\"]\s*\)", text):
            target = target.replace("@", "")
        if not target:
            raise WeChatSearchResponseError(
                "Sogou article redirect did not contain a target URL",
                error_code="missing_redirect_target",
            )
        cls._validate_article_target(target)
        return target

    @staticmethod
    def _normalize_article(raw: dict[str, Any]) -> dict[str, Any]:
        cover, thumbnail = _cover_urls(raw.get("image"))
        timestamp = _integer(raw.get("published_timestamp"))
        return {
            "id": str(raw.get("id") or ""),
            "title": _clean_text(raw.get("title")),
            "summary": _clean_text(raw.get("summary")),
            "url": WeChatSearchClient._result_link(raw.get("url")),
            "url_kind": "temporary_sogou_redirect",
            "article_url": "",
            "account": {"name": _clean_text(raw.get("account_name"))},
            "cover_url": cover,
            "thumbnail_url": thumbnail,
            "published_timestamp": timestamp,
            "published_at": _published_at(timestamp),
        }

    @staticmethod
    def _normalize_account(raw: dict[str, Any]) -> dict[str, Any]:
        avatar, thumbnail = _cover_urls(raw.get("image"))
        return {
            "id": str(raw.get("id") or ""),
            "name": _clean_text(raw.get("title")),
            "username": _clean_text(raw.get("username")),
            "description": _clean_text(raw.get("description")),
            "verification": _clean_text(raw.get("verification")),
            "url": WeChatSearchClient._result_link(raw.get("url")),
            "url_kind": "temporary_sogou_redirect",
            "avatar_url": avatar,
            "thumbnail_url": thumbnail,
        }

    @staticmethod
    def _result_link(value: Any) -> str:
        target = _absolute_url(value)
        parsed = urlsplit(target)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname == _SEARCH_HOST
            and parsed.username is None
            and parsed.password is None
            and parsed.path == "/link"
        ):
            return urlunsplit(("https", _SEARCH_HOST, parsed.path, parsed.query, ""))
        return ""

    @staticmethod
    def _next_page(value: str) -> int | None:
        if not value:
            return None
        parsed = urlsplit(html.unescape(value))
        page = _integer(parse_qs(parsed.query).get("page", [0])[0])
        return page if page > 0 else None

    @staticmethod
    def _validate_keyword(value: Any) -> str:
        if not isinstance(value, str):
            raise WeChatSearchInputError("keyword must be a string")
        keyword = value.strip()
        if not keyword or len(keyword) > 80:
            raise WeChatSearchInputError("keyword must contain between 1 and 80 characters")
        if _CONTROL_RE.search(keyword):
            raise WeChatSearchInputError("keyword must not contain control characters")
        return keyword

    @staticmethod
    def _validate_page(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
            raise WeChatSearchInputError("page must be an integer between 1 and 100")
        return value

    @staticmethod
    def _validate_limit(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
            raise WeChatSearchInputError("limit must be an integer between 1 and 10 or None")
        return value

    @staticmethod
    def _validate_sogou_link(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise WeChatSearchInputError("expected a Sogou WeChat article redirect URL")
        target = html.unescape(value.strip())
        parsed = urlsplit(target)
        try:
            port = parsed.port
        except ValueError as exc:
            raise WeChatSearchInputError(
                "expected an exact Sogou WeChat type=2 /link URL"
            ) from exc
        query = parse_qs(parsed.query)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _SEARCH_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.path != "/link"
            or query.get("type") != ["2"]
            or not query.get("url", [""])[0]
            or not query.get("token", [""])[0]
        ):
            raise WeChatSearchInputError("expected an exact Sogou WeChat type=2 /link URL")
        return urlunsplit(("https", _SEARCH_HOST, "/link", parsed.query, ""))

    def _seed_identity_from_link(self, value: str) -> None:
        token = str(parse_qs(urlsplit(value).query).get("token", [""])[0])
        if re.fullmatch(r"[0-9A-Fa-f]{48}", token):
            self.session.cookies.set(
                "SNUID", token[8:40].upper(), domain=".sogou.com", path="/"
            )

    @staticmethod
    def _validate_article_target(value: str) -> None:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise WeChatSearchResponseError(
                "Sogou article redirect target is outside the public WeChat article route",
                error_code="invalid_redirect_target",
                url=value,
            ) from exc
        decoded_path = unquote(parsed.path)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _ARTICLE_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or not (decoded_path == "/s" or re.fullmatch(r"/s/[A-Za-z0-9_-]{8,160}", decoded_path))
            or decoded_path != parsed.path
        ):
            raise WeChatSearchResponseError(
                "Sogou article redirect target is outside the public WeChat article route",
                error_code="invalid_redirect_target",
                url=value,
            )

    @classmethod
    def _raise_for_access_page(cls, source: str, *, page_url: str = "") -> None:
        if any(marker in source for marker in _ANTI_MARKERS) or "/antispider/" in page_url:
            raise WeChatSearchResponseError(
                "Sogou WeChat requested interactive verification",
                error_code="verification_required",
                url=page_url or None,
            )

    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        self._validate_request_url(url)
        path = urlsplit(url).path
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=dict(params or {}),
                    headers=dict(headers) if headers else None,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.RequestsError as exc:
                if attempt >= self.retries:
                    raise WeChatSearchResponseError(
                        f"Sogou WeChat request failed for {path}: {exc}",
                        error_code="transport_error",
                        url=url,
                        retryable=True,
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue

            status = int(response.status_code or 0)
            response_url = str(response.url or url)
            self._validate_response_url(response_url)
            if status == 200:
                self._raise_for_access_page(response.text, page_url=response_url)
                return response
            if 300 <= status < 400:
                location = _absolute_url(response.headers.get("location"), base=response_url)
                if "/antispider/" in location:
                    raise WeChatSearchResponseError(
                        "Sogou WeChat requested interactive verification",
                        status_code=status,
                        error_code="verification_required",
                        url=location,
                    )
                raise WeChatSearchResponseError(
                    f"Sogou WeChat returned an unexpected HTTP {status} redirect for {path}",
                    status_code=status,
                    error_code="unexpected_redirect",
                    url=location or response_url,
                )
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            raise WeChatSearchResponseError(
                f"Sogou WeChat returned HTTP {status} for {path}",
                status_code=status,
                error_code="http_error",
                url=response_url,
                retryable=status in _RETRYABLE_STATUS,
            )
        raise WeChatSearchResponseError(
            f"Sogou WeChat request exhausted retries for {path}", retryable=True
        )

    @staticmethod
    def _validate_request_url(value: str) -> None:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise WeChatSearchInputError(
                "request URL is outside the Sogou WeChat routes"
            ) from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != _SEARCH_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.path not in {"/weixin", "/link"}
        ):
            raise WeChatSearchInputError("request URL is outside the Sogou WeChat routes")

    @staticmethod
    def _validate_response_url(value: str) -> None:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise WeChatSearchResponseError(
                "Sogou WeChat response URL is outside the expected routes",
                error_code="unexpected_response_url",
                url=value,
            ) from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != _SEARCH_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.path not in {"/weixin", "/link", "/antispider/"}
        ):
            raise WeChatSearchResponseError(
                "Sogou WeChat response URL is outside the expected routes",
                error_code="unexpected_response_url",
                url=value,
            )
