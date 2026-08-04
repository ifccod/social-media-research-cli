from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import http.cookiejar
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import uuid4

from .errors import (
    FacebookAdsInputError,
    FacebookAdsResponseError,
    FacebookAdsTransportError,
)


HOME_URL = "https://www.facebook.com/"
AD_LIBRARY_URL = "https://www.facebook.com/ads/library/"
GRAPHQL_URL = "https://www.facebook.com/api/graphql/"
SEARCH_DOC_ID = "24922295957467452"
TYPEAHEAD_DOC_ID = "9755915494515334"
DETAILS_DOC_ID = "25068828942793558"
SEARCH_FRIENDLY_NAME = "AdLibrarySearchPaginationQuery"
TYPEAHEAD_FRIENDLY_NAME = "useAdLibraryTypeaheadSuggestionDataSourceQuery"
DETAILS_FRIENDLY_NAME = "AdLibraryV3AdDetailsQuery"
LAST_PROTOCOL_VERIFIED = "2026-08-01"
FALLBACK_REVISION = "1033837939"
FALLBACK_VERSION = "fbece7"
DEFAULT_USER_AGENT = (
    "facebookexternalhit/1.1 "
    "(+http://www.facebook.com/externalhit_uatext.php)"
)

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_PAGE_ID_RE = re.compile(r"^[1-9][0-9]{0,29}$")
_VALID_AD_TYPES = {
    "ALL",
    "POLITICAL_AND_ISSUE_ADS",
    "HOUSING_ADS",
    "EMPLOYMENT_ADS",
    "CREDIT_ADS",
    "FINANCIAL_PRODUCTS_AND_SERVICES_ADS",
}
_VALID_STATUSES = {"ACTIVE", "INACTIVE", "ALL"}
_VALID_MEDIA_TYPES = {"ALL", "IMAGE", "VIDEO", "MEME", "IMAGE_AND_MEME", "NONE"}
_VALID_SEARCH_TYPES = {"KEYWORD_EXACT_PHRASE", "KEYWORD_UNORDERED", "PAGE"}
_VALID_PUBLISHER_PLATFORMS = {
    "FACEBOOK",
    "INSTAGRAM",
    "MESSENGER",
    "AUDIENCE_NETWORK",
    "WHATSAPP",
    "THREADS",
}
_VALID_SORT_MODES = {
    "total_impressions",
    "relevancy_monthly_grouped",
}
_MEDIA_HOST_SUFFIXES = (".fbcdn.net", ".fbsbx.com", ".cdninstagram.com")
_MISSING = object()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _first(raw: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw and raw[name] is not None:
            return raw[name]
    return None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError, OverflowError):
        return None


def _json_string(value: str) -> str:
    try:
        return str(json.loads(f'"{value}"'))
    except (json.JSONDecodeError, TypeError, ValueError):
        return html.unescape(value)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).strip().isdecimal():
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _iso_datetime(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else (_text(value) or None)


def _external_landing_url(value: Any) -> tuple[str, str]:
    source = html.unescape(_text(value))
    if not source:
        return "", ""
    try:
        parsed = urlsplit(source)
    except ValueError:
        return source, source
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host in {"l.facebook.com", "lm.facebook.com"}:
        target = _text(parse_qs(parsed.query).get("u", [""])[0])
        try:
            target_url = urlsplit(target)
        except ValueError:
            target_url = None
        if target_url and target_url.scheme in {"http", "https"} and target_url.hostname:
            return target, source
    return source, source


def _landing_domain(value: str) -> str:
    try:
        return (urlsplit(value).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def _deep_find(value: Any, names: set[str]) -> Any:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, child in current.items():
                if key in names:
                    return child
                if isinstance(child, (Mapping, list)):
                    stack.append(child)
        elif isinstance(current, list):
            stack.extend(reversed(current))
    return _MISSING


def _deep_mappings(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _deep_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _deep_mappings(child)


def _normalize_reach_breakdown(value: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """归一化 Meta 按国家、年龄和性别公开的触达分布。"""
    breakdown: list[dict[str, Any]] = []
    country_totals: dict[str, int] = {}
    for country_value in _items(value):
        country_raw = _mapping(country_value)
        country = _text(country_raw.get("country")).upper()
        age_groups: list[dict[str, Any]] = []
        country_total = 0
        for group_value in _items(country_raw.get("age_gender_breakdowns")):
            group_raw = _mapping(group_value)
            group: dict[str, Any] = {
                "age_range": _text(group_raw.get("age_range")) or None,
                "male": _optional_int(group_raw.get("male")),
                "female": _optional_int(group_raw.get("female")),
                "unknown": _optional_int(group_raw.get("unknown")),
            }
            country_total += sum(
                count or 0
                for count in (group["male"], group["female"], group["unknown"])
            )
            age_groups.append(group)
        breakdown.append(
            {
                "country": country or None,
                "age_gender_breakdowns": age_groups,
                "breakdown_reach_sum": country_total,
            }
        )
        if country:
            country_totals[country] = country_total
    return breakdown, country_totals


def _normalize_location_transparency(value: Any, *, region: str) -> dict[str, Any] | None:
    raw = _mapping(value)
    if not raw:
        return None
    breakdown, country_totals = _normalize_reach_breakdown(
        raw.get("age_country_gender_reach_breakdown")
    )
    total = _optional_int(
        raw.get("eu_total_reach") if region == "eu" else raw.get("total_reach")
    )
    age = _mapping(raw.get("age_audience"))
    return {
        "reported_total_reach": total,
        "targets_eu": raw.get("targets_eu") if region == "eu" else None,
        "targeting": {
            "locations": [
                {
                    "name": _text(_mapping(item).get("name")) or None,
                    "type": _text(_mapping(item).get("type")) or None,
                    "excluded": _mapping(item).get("excluded"),
                    "num_obfuscated": _optional_int(
                        _mapping(item).get("num_obfuscated")
                    ),
                }
                for item in _items(raw.get("location_audience"))
                if isinstance(item, Mapping)
            ],
            "gender": _text(raw.get("gender_audience")) or None,
            "age": {
                "min": _optional_int(age.get("min")),
                "max": _optional_int(age.get("max")),
            },
        },
        "reach_by_country": country_totals,
        "age_country_gender_reach_breakdown": breakdown,
    }


class _MetaHTMLParser(HTMLParser):
    """提取 Meta SSR 中的 JSON 脚本和静态 JavaScript URL。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_sources: list[str] = []
        self.script_urls: list[str] = []
        self._capture = False
        self._buffer: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() != "script":
            return
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        source_url = values.get("src", "")
        if source_url and "/rsrc.php" in source_url:
            self.script_urls.append(urljoin(HOME_URL, source_url))
        if values.get("type", "").casefold() == "application/json" and "data-sjs" in values:
            self._capture = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._capture:
            self.json_sources.append("".join(self._buffer))
            self._capture = False
            self._buffer = []


def _ssr_payloads(source: str) -> tuple[list[Mapping[str, Any]], list[str]]:
    if not isinstance(source, str) or not source.strip():
        raise FacebookAdsResponseError("Meta Ads Library SSR 返回了空页面")
    parser = _MetaHTMLParser()
    try:
        parser.feed(source.replace("\x00", ""))
        parser.close()
    except (TypeError, ValueError) as exc:
        raise FacebookAdsResponseError("Meta Ads Library SSR HTML 解析失败") from exc
    payloads: list[Mapping[str, Any]] = []
    for raw in parser.json_sources:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(value, Mapping):
            payloads.append(value)
    if not payloads:
        raise FacebookAdsResponseError(
            "Meta Ads Library SSR 中没有可解析的预加载数据",
            code="ssr_response_drift",
        )
    return payloads, list(dict.fromkeys(parser.script_urls))


def _preloader_context(
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    for payload in payloads:
        for item in _deep_mappings(payload):
            if item.get("queryName") != "AdLibraryFoundationRootQuery":
                continue
            variables = item.get("variables")
            if isinstance(variables, Mapping):
                return dict(variables), _text(item.get("queryID"))
    raise FacebookAdsResponseError(
        "Meta Ads Library SSR 缺少搜索预加载变量",
        code="ssr_response_drift",
    )


def _json_payloads(source: str) -> list[Mapping[str, Any]]:
    if not isinstance(source, str) or not source.strip():
        raise FacebookAdsResponseError("Meta GraphQL 返回了空响应")
    cleaned = re.sub(r"(?m)^\s*for \(;;\);", "", source).strip()
    if cleaned.startswith(")]}'"):
        cleaned = cleaned.partition("\n")[2].lstrip()
    decoder = json.JSONDecoder()
    index = 0
    payloads: list[Mapping[str, Any]] = []
    while index < len(cleaned):
        while index < len(cleaned) and cleaned[index].isspace():
            index += 1
        if index >= len(cleaned):
            break
        try:
            value, index = decoder.raw_decode(cleaned, index)
        except json.JSONDecodeError as exc:
            raise FacebookAdsResponseError(
                "Meta GraphQL 返回格式已变化",
                code="invalid_response",
            ) from exc
        if isinstance(value, Mapping):
            payloads.append(value)
    if not payloads:
        raise FacebookAdsResponseError("Meta GraphQL 返回中没有 JSON 对象")
    return payloads


def _graphql_errors(payloads: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    for payload in payloads:
        errors = payload.get("errors")
        output.extend(item for item in _items(errors) if isinstance(item, Mapping))
    return output


def _raise_graphql_error(payloads: Sequence[Mapping[str, Any]]) -> None:
    errors = _graphql_errors(payloads)
    if not errors:
        raise FacebookAdsResponseError(
            "Meta GraphQL 文档或响应路径已漂移",
            code="graphql_document_drift",
        )
    message = "; ".join(_text(item.get("message")) for item in errors if item)
    codes = {_optional_int(item.get("code")) for item in errors}
    lowered = message.casefold()
    if 1675004 in codes or "rate limit" in lowered:
        raise FacebookAdsResponseError(message or "Meta GraphQL 请求频率受限", code="rate_limited")
    if any(marker in lowered for marker in ("doc_id", "document", "persisted", "query")):
        raise FacebookAdsResponseError(
            message or "Meta GraphQL 文档已漂移",
            code="graphql_document_drift",
        )
    if codes & {1357001, 1357004} or "session" in lowered:
        raise FacebookAdsResponseError(
            message or "Meta 匿名会话已失效",
            code="anonymous_session_expired",
        )
    raise FacebookAdsResponseError(message or "Meta GraphQL 返回错误", code="graphql_error")


class FacebookAdsClient:
    """使用 Python HTTP 直连 Meta Ads Library 匿名网页协议。"""

    def __init__(
        self,
        *,
        timeout: float = 30,
        retries: int = 2,
        request_interval: float = 2,
        proxy: str = "",
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Any = None,
        sleep: Any = time.sleep,
        monotonic: Any = time.monotonic,
    ) -> None:
        if timeout <= 0:
            raise FacebookAdsInputError("timeout 必须大于 0")
        if retries < 0 or retries > 10:
            raise FacebookAdsInputError("retries 必须在 0 到 10 之间")
        if request_interval < 0 or request_interval > 60:
            raise FacebookAdsInputError("request_interval 必须在 0 到 60 秒之间")
        self.timeout = float(timeout)
        self.retries = retries
        self.request_interval = float(request_interval)
        self.user_agent = user_agent
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_graphql_at: float | None = None
        self._request_counter = 0
        self._tokens: dict[str, str] = {}
        self._initialized = False
        self._script_urls: list[str] = []
        self._search_doc_id = SEARCH_DOC_ID
        self._typeahead_doc_id = TYPEAHEAD_DOC_ID
        self._details_doc_id = DETAILS_DOC_ID
        self._root_query_id = ""
        self._bootstrap_url = ""
        self.cookie_jar = http.cookiejar.CookieJar()
        if opener is not None:
            self._opener = opener
        else:
            handlers: list[Any] = []
            if proxy:
                self._validate_proxy(proxy)
                handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
            handlers.append(HTTPCookieProcessor(self.cookie_jar))
            self._opener = build_opener(*handlers)

    @staticmethod
    def _validate_proxy(value: str) -> None:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise FacebookAdsInputError("proxy URL 格式错误") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or port is None:
            raise FacebookAdsInputError("proxy 必须是含端口的 http 或 https URL")

    def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return self.session_status()
        self._load_ssr(AD_LIBRARY_URL)
        return self.session_status()

    def _load_ssr(
        self, url: str
    ) -> tuple[str, list[Mapping[str, Any]]]:
        source, final_url = self._request(
            "GET",
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": self.user_agent,
            },
            purpose="ssr",
        )
        self._validate_facebook_url(final_url)
        self._bootstrap_url = final_url
        self._tokens = self.extract_session_tokens(source)
        if not self._tokens.get("lsd"):
            raise FacebookAdsResponseError(
                "Meta Ads Library SSR 未返回真实 lsd，会话 bootstrap 结构可能已变化",
                code="session_bootstrap_failed",
            )
        payloads, script_urls = _ssr_payloads(source)
        self._script_urls = script_urls
        revision = self._tokens.get("__rev", FALLBACK_REVISION)
        self._tokens.setdefault("__rev", revision)
        self._tokens.setdefault("__spin_r", revision)
        self._tokens.setdefault("__spin_b", "trunk")
        self._tokens.setdefault("__spin_t", str(int(time.time())))
        self._tokens.setdefault("__hsi", str(int(time.time() * 1000)))
        self._tokens.setdefault("__comet_req", "94")
        self._tokens.setdefault("__hs", "20476.HYP:comet_plat_default_pkg.2.1...0")
        self._tokens.setdefault("v", FALLBACK_VERSION)
        self._tokens.setdefault("x-asbd-id", "359341")
        self._tokens["jazoest"] = str(2 + sum(ord(char) for char in self._tokens["lsd"]))
        self._initialized = True
        return source, payloads

    def session_status(self) -> dict[str, Any]:
        return {
            "ready": self._initialized,
            "access": "anonymous",
            "transport": "python_http_ssr",
            "user_agent_profile": "meta_public_crawler",
            "protocol_verified_at": LAST_PROTOCOL_VERIFIED,
            "session_fields": sorted(self._tokens),
            "bootstrap_url": self._bootstrap_url,
        }

    def download_media(
        self,
        url: str,
        destination: str | Path,
        *,
        max_bytes: int = 512 * 1024 * 1024,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """匿名下载搜索结果中的临时 Meta CDN 素材并生成内容哈希。"""
        source_url = self._validate_media_url(url)
        if isinstance(destination, Path):
            target = destination.expanduser()
        elif isinstance(destination, str) and destination.strip():
            target = Path(destination).expanduser()
        else:
            raise FacebookAdsInputError("destination 必须是本机文件路径")
        if max_bytes < 1 or max_bytes > 2 * 1024 * 1024 * 1024:
            raise FacebookAdsInputError("max_bytes 必须在 1 到 2147483648 之间")
        if target.exists() and not overwrite:
            raise FacebookAdsInputError("destination 已存在；需要覆盖时传入 overwrite")
        if target.exists() and not target.is_file():
            raise FacebookAdsInputError("destination 必须是文件路径")

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
        last_error: BaseException | None = None
        try:
            for attempt in range(self.retries + 1):
                digest = sha256()
                written = 0
                try:
                    request = Request(
                        source_url,
                        headers={
                            "Accept": "image/*,video/*,application/octet-stream;q=0.8,*/*;q=0.5",
                            "User-Agent": self.user_agent,
                        },
                        method="GET",
                    )
                    response = self._opener.open(request, timeout=self.timeout)
                    try:
                        status = int(getattr(response, "status", response.getcode()))
                        if status not in {200, 206}:
                            raise FacebookAdsTransportError(
                                f"Meta CDN 返回 HTTP {status}",
                                code="media_download_failed",
                            )
                        final_url = self._validate_media_url(
                            str(response.geturl() or source_url)
                        )
                        content_type = (
                            response.headers.get_content_type()
                            if response.headers
                            else "application/octet-stream"
                        )
                        content_length = self._content_length(response.headers)
                        if content_length is not None and content_length > max_bytes:
                            raise FacebookAdsResponseError(
                                "Meta 素材超过 max_bytes",
                                code="media_too_large",
                            )
                        with temporary.open("wb") as output:
                            while True:
                                chunk = response.read(
                                    min(1024 * 1024, max_bytes - written + 1)
                                )
                                if not chunk:
                                    break
                                written += len(chunk)
                                if written > max_bytes:
                                    raise FacebookAdsResponseError(
                                        "Meta 素材超过 max_bytes",
                                        code="media_too_large",
                                    )
                                output.write(chunk)
                                digest.update(chunk)
                    finally:
                        response.close()
                    if target.exists() and not overwrite:
                        raise FacebookAdsInputError(
                            "destination 在下载期间被创建；需要覆盖时传入 overwrite"
                        )
                    temporary.replace(target)
                    return {
                        "kind": "facebook_media_download",
                        "access": "anonymous",
                        "source_url": source_url,
                        "final_url": final_url,
                        "destination": str(target.resolve()),
                        "bytes": written,
                        "sha256": digest.hexdigest(),
                        "content_type": content_type,
                        "url_stability": "local_snapshot",
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    }
                except FacebookAdsInputError:
                    raise
                except FacebookAdsResponseError:
                    raise
                except HTTPError as exc:
                    last_error = exc
                    if exc.code in _RETRYABLE_STATUS and attempt < self.retries:
                        temporary.unlink(missing_ok=True)
                        self._sleep(0.4 * (2**attempt))
                        continue
                    code = "rate_limited" if exc.code == 429 else "media_download_failed"
                    raise FacebookAdsTransportError(
                        f"Meta CDN 返回 HTTP {exc.code}", code=code
                    ) from exc
                except (OSError, URLError) as exc:
                    last_error = exc
                    if attempt < self.retries:
                        temporary.unlink(missing_ok=True)
                        self._sleep(0.4 * (2**attempt))
                        continue
                    raise FacebookAdsTransportError(
                        f"Meta 素材下载失败: {exc}", code="media_download_failed"
                    ) from exc
            raise FacebookAdsTransportError(
                "Meta 素材下载重试耗尽", code="media_download_failed"
            ) from last_error
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def extract_session_tokens(source: str) -> dict[str, str]:
        if not isinstance(source, str):
            return {}
        patterns: dict[str, tuple[str, ...]] = {
            "lsd": (
                r'"LSD",\[\],\{"token":"([^"\\]+(?:\\.[^"\\]*)*)"\}',
                r'"lsd"\s*:\s*"([^"\\]+(?:\\.[^"\\]*)*)"',
                r'name=["\']lsd["\']\s+value=["\']([^"\']+)',
            ),
            "__rev": (
                r'"__spin_r"\s*:\s*(\d+)',
                r'"server_revision"\s*:\s*(\d+)',
                r'"revision"\s*:\s*(\d+)',
            ),
            "__spin_t": (r'"__spin_t"\s*:\s*(\d+)',),
            "__spin_b": (r'"__spin_b"\s*:\s*"([^"]+)"',),
            "__hsi": (r'"__hsi"\s*:\s*"?(\d+)"?', r'"hsi"\s*:\s*"?(\d+)"?'),
            "fb_dtsg": (r'"DTSGInitialData",\[\],\{"token":"([^"]+)"',),
            "__dyn": (r'"__dyn"\s*:\s*"([^"]+)"',),
            "__csr": (r'"__csr"\s*:\s*"([^"]+)"',),
            "__hs": (
                r'"__hs"\s*:\s*"([^"]+)"',
                r'"haste_session"\s*:\s*"([^"]+)"',
            ),
            "__hsdp": (r'"__hsdp"\s*:\s*"([^"]+)"',),
            "__hblp": (r'"__hblp"\s*:\s*"([^"]+)"',),
            "__comet_req": (r'"__comet_req"\s*:\s*(\d+)',),
            "v": (r'"v"\s*:\s*"([a-f0-9]{4,10})"',),
            "x-asbd-id": (
                r'"asbd_id"\s*:\s*"?(\d+)"?',
                r'x-asbd-id["\s:]+(\d+)',
            ),
        }
        tokens: dict[str, str] = {}
        for name, alternatives in patterns.items():
            for pattern in alternatives:
                match = re.search(pattern, source)
                if match:
                    tokens[name] = _json_string(match.group(1))
                    break
        if "__rev" in tokens:
            tokens["__spin_r"] = tokens["__rev"]
        return tokens

    def search_pages(self, query: str, *, country: str = "US", limit: int = 10) -> dict[str, Any]:
        query = self._query(query, required=True)
        countries = self._countries([country])
        requested_limit = self._bounded_int(limit, "limit", 1, 50)
        source_url = self._source_url(
            query=query,
            countries=countries,
            page_ids=[],
            active_status="ALL",
            ad_type="ALL",
            media_type="ALL",
            search_type="KEYWORD_UNORDERED",
            publisher_platforms=[],
            content_languages=[],
            start_date="",
            end_date="",
            sort="relevancy_monthly_grouped",
            sort_direction="DESCENDING",
        )
        _, ssr_payloads = self._load_ssr(source_url)
        try:
            context, self._root_query_id = _preloader_context(ssr_payloads)
        except FacebookAdsResponseError:
            context = {}
        if _text(context.get("v")):
            self._tokens["v"] = _text(context["v"])
        variables = {
            "queryString": query,
            "country": countries[0],
            "adType": "ALL",
            "isMobile": False,
        }
        source = self._graphql(
            self._typeahead_doc_id,
            TYPEAHEAD_FRIENDLY_NAME,
            variables,
            source_url,
        )
        payloads = _json_payloads(source)
        try:
            suggestions = self._parse_suggestions(payloads)
        except FacebookAdsResponseError as exc:
            if exc.code != "graphql_document_drift":
                raise
            discovered = self._discover_document_id(TYPEAHEAD_FRIENDLY_NAME)
            if not discovered or discovered == self._typeahead_doc_id:
                raise
            self._typeahead_doc_id = discovered
            source = self._graphql(
                self._typeahead_doc_id,
                TYPEAHEAD_FRIENDLY_NAME,
                variables,
                source_url,
            )
            suggestions = self._parse_suggestions(_json_payloads(source))
        items = [self._normalize_page(item) for item in suggestions]
        items = [item for item in items if item["page_id"]][:requested_limit]
        return {
            "kind": "facebook_page_suggest",
            "source": "meta_ads_library_anonymous_ssr_graphql",
            "source_url": source_url,
            "access": "anonymous",
            "query": {"text": query, "country": countries[0]},
            "count": len(items),
            "items": items,
            "protocol": {
                "document": TYPEAHEAD_FRIENDLY_NAME,
                "document_id": self._typeahead_doc_id,
                "verified_at": LAST_PROTOCOL_VERIFIED,
            },
        }

    def search_ads(
        self,
        query: str = "",
        *,
        countries: str | Sequence[str] | None = None,
        ad_type: str = "ALL",
        active_status: str = "ACTIVE",
        media_type: str = "ALL",
        search_type: str = "KEYWORD_UNORDERED",
        page_ids: str | Sequence[str] | None = None,
        publisher_platforms: str | Sequence[str] | None = None,
        content_languages: str | Sequence[str] | None = None,
        start_date: str = "",
        end_date: str = "",
        sort: str = "total_impressions",
        sort_direction: str = "DESCENDING",
        cursor: str = "",
        page_size: int = 10,
        limit: int = 60,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        query = self._query(query, required=False)
        normalized_pages = self._page_ids(page_ids)
        if not query and not normalized_pages:
            raise FacebookAdsInputError("search-ads 至少需要 query 或 page_ids")
        normalized_countries = self._countries(countries)
        ad_type = self._enum(ad_type, "ad_type", _VALID_AD_TYPES)
        active_status = self._enum(active_status, "active_status", _VALID_STATUSES)
        media_type = self._enum(media_type, "media_type", _VALID_MEDIA_TYPES)
        search_type = self._enum(search_type, "search_type", _VALID_SEARCH_TYPES)
        platforms = self._platforms(publisher_platforms)
        languages = self._languages(content_languages)
        start_date, end_date = self._dates(start_date, end_date)
        sort = {
            "impressions": "total_impressions",
            "relevancy": "relevancy_monthly_grouped",
        }.get(sort, sort)
        if sort not in _VALID_SORT_MODES:
            raise FacebookAdsInputError("sort 不支持该排序模式")
        sort_direction = self._enum(
            sort_direction, "sort_direction", {"ASCENDING", "DESCENDING"}
        )
        requested_limit = self._bounded_int(limit, "limit", 1, 500)
        requested_page_size = self._bounded_int(page_size, "page_size", 1, 10)
        next_cursor = self._cursor(cursor)
        input_cursor = next_cursor or None
        source_url = self._source_url(
            query=query,
            countries=normalized_countries,
            page_ids=normalized_pages,
            active_status=active_status,
            ad_type=ad_type,
            media_type=media_type,
            search_type=search_type,
            publisher_platforms=platforms,
            content_languages=languages,
            start_date=start_date,
            end_date=end_date,
            sort=sort,
            sort_direction=sort_direction,
        )
        _, ssr_payloads = self._load_ssr(source_url)
        context, self._root_query_id = _preloader_context(ssr_payloads)
        if _text(context.get("v")):
            self._tokens["v"] = _text(context["v"])
        ssr_ads, ssr_page_info, source_count = self._parse_search_page(ssr_payloads)

        raw_ads: list[Mapping[str, Any]] = []
        seen_ads: set[str] = set()
        seen_cursors: set[str] = {next_cursor} if next_cursor else set()
        pages_fetched = 0 if input_cursor else 1
        graphql_pages_fetched = 0
        has_next_page = bool(
            _first(ssr_page_info, "has_next_page", "hasNextPage")
        )
        stop_reason = "source_exhausted"
        warnings: list[dict[str, str]] = []

        if not input_cursor:
            processed_ssr = 0
            for raw in ssr_ads:
                processed_ssr += 1
                identity = self._ad_identity(raw)
                if identity in seen_ads:
                    continue
                seen_ads.add(identity)
                raw_ads.append(raw)
                if len(raw_ads) >= requested_limit:
                    break
            next_cursor = _text(_first(ssr_page_info, "end_cursor", "endCursor"))
            if processed_ssr < len(ssr_ads):
                next_cursor = ""
                stop_reason = "limit_within_ssr"
                warnings.append(
                    {
                        "code": "continuation_not_representable",
                        "message": "limit 落在匿名 SSR 首屏内部，Meta 只提供首屏末尾 cursor",
                    }
                )
            elif len(raw_ads) >= requested_limit:
                stop_reason = "limit_reached"
            elif not has_next_page or not next_cursor:
                stop_reason = "source_exhausted"

        allowed_variables = {
            "activeStatus",
            "adType",
            "bylines",
            "collationToken",
            "contentLanguages",
            "countries",
            "excludedIDs",
            "isTargetedCountry",
            "location",
            "mediaType",
            "multiCountryFilterMode",
            "pageIDs",
            "potentialReachInput",
            "publisherPlatforms",
            "queryString",
            "regions",
            "searchType",
            "sessionID",
            "sortData",
            "source",
            "startDate",
            "v",
            "viewAllPageID",
        }
        base_variables = {
            key: value for key, value in context.items() if key in allowed_variables
        }
        base_variables.update(
            {
                "activeStatus": active_status.casefold(),
                "adType": self._graphql_ad_type(ad_type),
                "bylines": [],
                "collationToken": context.get("collationToken"),
                "contentLanguages": languages,
                "countries": normalized_countries,
                "excludedIDs": [],
                "isTargetedCountry": False,
                "location": context.get("location"),
                "mediaType": media_type.casefold(),
                "multiCountryFilterMode": context.get("multiCountryFilterMode"),
                "pageIDs": normalized_pages,
                "potentialReachInput": context.get("potentialReachInput"),
                "publisherPlatforms": [item.casefold() for item in platforms],
                "queryString": query,
                "regions": context.get("regions"),
                "searchType": search_type.casefold(),
                "sessionID": _text(context.get("sessionID")) or str(uuid4()),
                "sortData": {
                    "direction": sort_direction,
                    "mode": self._graphql_sort_mode(sort),
                },
                "source": context.get("source"),
                "startDate": (
                    {"min": start_date or None, "max": end_date or None}
                    if start_date or end_date
                    else None
                ),
                "v": self._tokens.get("v", FALLBACK_VERSION),
                "viewAllPageID": (
                    normalized_pages[0]
                    if search_type == "PAGE" and len(normalized_pages) == 1
                    else "0"
                ),
            }
        )

        while len(raw_ads) < requested_limit and next_cursor:
            variables = dict(base_variables)
            variables["first"] = min(
                requested_page_size,
                requested_limit - len(raw_ads),
            )
            variables["cursor"] = next_cursor

            source = self._graphql(
                self._search_doc_id,
                SEARCH_FRIENDLY_NAME,
                variables,
                source_url,
            )
            try:
                page_ads, page_info, page_count = self._parse_search_page(
                    _json_payloads(source)
                )
            except FacebookAdsResponseError as exc:
                if exc.code != "graphql_document_drift":
                    raise
                discovered = self._discover_document_id(SEARCH_FRIENDLY_NAME)
                if not discovered or discovered == self._search_doc_id:
                    raise
                self._search_doc_id = discovered
                source = self._graphql(
                    self._search_doc_id,
                    SEARCH_FRIENDLY_NAME,
                    variables,
                    source_url,
                )
                page_ads, page_info, page_count = self._parse_search_page(
                    _json_payloads(source)
                )
            if source_count is None:
                source_count = page_count
            pages_fetched += 1
            graphql_pages_fetched += 1
            added = 0
            for raw in page_ads:
                identity = self._ad_identity(raw)
                if identity in seen_ads:
                    continue
                seen_ads.add(identity)
                raw_ads.append(raw)
                added += 1
                if len(raw_ads) == requested_limit:
                    break

            has_next_page = bool(_first(page_info, "has_next_page", "hasNextPage"))
            candidate_cursor = _text(_first(page_info, "end_cursor", "endCursor"))
            if len(raw_ads) >= requested_limit:
                next_cursor = candidate_cursor
                stop_reason = "limit_reached"
                break
            if not has_next_page or not candidate_cursor:
                next_cursor = candidate_cursor
                stop_reason = "source_exhausted"
                break
            if candidate_cursor in seen_cursors:
                next_cursor = candidate_cursor
                stop_reason = "pagination_abnormal"
                warnings.append(
                    {
                        "code": "pagination_abnormal",
                        "message": "Meta GraphQL 重复返回同一 cursor，已停止续页",
                    }
                )
                break
            if not added:
                next_cursor = candidate_cursor
                stop_reason = "pagination_abnormal"
                warnings.append(
                    {
                        "code": "pagination_abnormal",
                        "message": "Meta GraphQL 声明存在续页但本页没有新增广告",
                    }
                )
                break
            seen_cursors.add(candidate_cursor)
            next_cursor = candidate_cursor

        if input_cursor and not graphql_pages_fetched:
            stop_reason = "cursor_unavailable"

        collected_at = datetime.now(timezone.utc)
        normalized = [
            self._normalize_ad(raw, rank=index, collected_at=collected_at, include_raw=include_raw)
            for index, raw in enumerate(raw_ads, start=1)
        ]
        self._add_sample_signals(normalized)
        return {
            "kind": "facebook_ad_search",
            "source": "meta_ads_library_anonymous_ssr_graphql",
            "source_url": source_url,
            "access": "anonymous",
            "collected_at": collected_at.isoformat(),
            "query": {
                "text": query,
                "countries": normalized_countries,
                "page_ids": normalized_pages,
                "active_status": active_status,
                "ad_type": ad_type,
                "media_type": media_type,
                "search_type": search_type,
                "publisher_platforms": platforms,
                "content_languages": languages,
                "start_date": start_date or None,
                "end_date": end_date or None,
                "sort": sort,
                "sort_direction": sort_direction,
            },
            "source_count": source_count,
            "count": len(normalized),
            "items": normalized,
            "pagination": {
                "input_cursor": input_cursor,
                "next_cursor": next_cursor or None,
                "has_next_page": has_next_page,
                "pages_fetched": pages_fetched,
                "ssr_pages_fetched": 1,
                "graphql_pages_fetched": graphql_pages_fetched,
                "stop_reason": stop_reason,
            },
            "warnings": warnings,
            "metric_scope": {
                "ad_likes": "not_published",
                "video_views": "not_published",
                "engagement": "not_published",
                "server_impression_sort": sort == "total_impressions",
                "actual_impressions": "only_when_returned_by_upstream",
                "ranking_rule": "result_rank 仅记录 Meta 返回顺序，不推导点赞或播放量",
            },
            "protocol": {
                "document": SEARCH_FRIENDLY_NAME,
                "document_id": self._search_doc_id,
                "root_document_id": self._root_query_id or None,
                "verified_at": LAST_PROTOCOL_VERIFIED,
            },
        }

    def page_ads(self, page_ids: str | Sequence[str], **kwargs: Any) -> dict[str, Any]:
        normalized_pages = self._page_ids(page_ids)
        if not normalized_pages:
            raise FacebookAdsInputError("page-ads 至少需要一个 Page id")
        return self.search_ads(
            "",
            page_ids=normalized_pages,
            search_type="PAGE",
            **kwargs,
        )

    def ad_details(
        self,
        ad_id: str,
        *,
        page_id: str = "",
        country: str = "US",
        political: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """匿名读取单条广告的地区触达、定向与付费主体详情。"""
        normalized_ad_id = _text(ad_id)
        if not _PAGE_ID_RE.fullmatch(normalized_ad_id):
            raise FacebookAdsInputError("ad_id 必须是 1 到 30 位十进制数字")
        normalized_country = self._countries([country])[0]
        requested_pages = self._page_ids([page_id]) if page_id else []
        source_url = f"{AD_LIBRARY_URL}?id={quote(normalized_ad_id)}"
        _, payloads = self._load_ssr(source_url)
        context, root_query_id = _preloader_context(payloads)
        self._root_query_id = root_query_id
        context_ad_id = _text(
            _first(context, "deeplinkAdID", "deeplink_ad_id", "adArchiveID")
        )
        if context_ad_id and context_ad_id != normalized_ad_id:
            raise FacebookAdsResponseError(
                "Meta Ads Library SSR 返回了不同的广告 id",
                code="ssr_response_drift",
            )
        resolved_page_id = (
            requested_pages[0]
            if requested_pages
            else _text(_first(context, "viewAllPageID", "view_all_page_id"))
        )
        if not _PAGE_ID_RE.fullmatch(resolved_page_id):
            raise FacebookAdsInputError(
                "Meta SSR 未提供 Page id；请从 search-ads 结果传入 page_id"
            )

        is_not_aaa_eligible = False
        for item in _deep_mappings(payloads):
            if _text(_first(item, "ad_archive_id", "adArchiveID")) != normalized_ad_id:
                continue
            if "is_aaa_eligible" in item:
                is_not_aaa_eligible = not bool(item.get("is_aaa_eligible"))
                break
        variables = {
            "adArchiveID": normalized_ad_id,
            "country": normalized_country,
            "pageID": resolved_page_id,
            "sessionID": _text(
                _first(context, "sessionID", "session_id")
            )
            or None,
            "source": context.get("source"),
            "isAdNonPolitical": not bool(political),
            "isAdNotAAAEligible": is_not_aaa_eligible,
        }
        source = self._graphql(
            self._details_doc_id,
            DETAILS_FRIENDLY_NAME,
            variables,
            source_url,
        )
        try:
            raw_details = self._parse_ad_details(_json_payloads(source))
        except FacebookAdsResponseError as exc:
            if exc.code != "graphql_document_drift":
                raise
            discovered = self._discover_document_id(DETAILS_FRIENDLY_NAME)
            if not discovered or discovered == self._details_doc_id:
                raise
            self._details_doc_id = discovered
            source = self._graphql(
                self._details_doc_id,
                DETAILS_FRIENDLY_NAME,
                variables,
                source_url,
            )
            raw_details = self._parse_ad_details(_json_payloads(source))

        collected_at = datetime.now(timezone.utc)
        result = self._normalize_ad_details(
            raw_details,
            ad_id=normalized_ad_id,
            page_id=resolved_page_id,
            country=normalized_country,
            source_url=source_url,
            collected_at=collected_at,
        )
        if include_raw:
            result["raw"] = dict(raw_details)
        result["protocol"] = {
            "document": DETAILS_FRIENDLY_NAME,
            "document_id": self._details_doc_id,
            "root_document_id": self._root_query_id or None,
            "verified_at": LAST_PROTOCOL_VERIFIED,
        }
        return result

    def _graphql(
        self,
        doc_id: str,
        friendly_name: str,
        variables: Mapping[str, Any],
        referer: str,
    ) -> str:
        self._wait_for_graphql_slot()
        payload = self._graphql_payload(doc_id, variables, friendly_name)
        source, final_url = self._request(
            "POST",
            GRAPHQL_URL,
            data=payload,
            headers={
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.facebook.com",
                "Referer": referer,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "User-Agent": self.user_agent,
                "X-ASBD-ID": self._tokens.get("x-asbd-id", "359341"),
                "X-FB-Friendly-Name": friendly_name,
                "X-FB-LSD": self._tokens["lsd"],
            },
            purpose="graphql",
        )
        self._last_graphql_at = self._monotonic()
        self._validate_facebook_url(final_url)
        return source

    def _discover_document_id(self, friendly_name: str) -> str:
        pattern = re.compile(
            rf'{re.escape(friendly_name)}_facebookRelayOperation"'
            rf'.{{0,180}}?exports="([0-9]{{10,20}})"',
            re.DOTALL,
        )
        for url in self._script_urls[:16]:
            self._validate_meta_asset_url(url)
            try:
                source, final_url = self._request(
                    "GET",
                    url,
                    headers={
                        "Accept": "*/*",
                        "Referer": self._bootstrap_url or AD_LIBRARY_URL,
                        "User-Agent": self.user_agent,
                    },
                    purpose="asset",
                )
            except FacebookAdsTransportError:
                continue
            self._validate_meta_asset_url(final_url)
            match = pattern.search(source)
            if match:
                return match.group(1)
        return ""

    def _graphql_payload(
        self,
        doc_id: str,
        variables: Mapping[str, Any],
        friendly_name: str,
    ) -> dict[str, str]:
        self._request_counter += 1
        payload = {
            "av": "0",
            "__aaid": "0",
            "__user": "0",
            "__a": "1",
            "__req": self._base36(self._request_counter),
            "__hs": self._tokens["__hs"],
            "dpr": "1",
            "__ccg": "GOOD",
            "__rev": self._tokens["__rev"],
            "__s": ":".join(uuid4().hex[:6] for _ in range(3)),
            "__hsi": self._tokens["__hsi"],
            "__comet_req": self._tokens["__comet_req"],
            "lsd": self._tokens["lsd"],
            "jazoest": self._tokens["jazoest"],
            "__spin_r": self._tokens["__spin_r"],
            "__spin_b": self._tokens["__spin_b"],
            "__spin_t": self._tokens["__spin_t"],
            "__jssesw": "1",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": friendly_name,
            "server_timestamps": "true",
            "variables": json.dumps(variables, ensure_ascii=False, separators=(",", ":")),
            "doc_id": doc_id,
        }
        for token in ("__dyn", "__csr", "fb_dtsg", "__hsdp", "__hblp"):
            if token in self._tokens:
                payload[token] = self._tokens[token]
        return payload

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        purpose: str,
    ) -> tuple[str, str]:
        encoded = urlencode(data).encode("utf-8") if data is not None else None
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            request = Request(url, data=encoded, headers=dict(headers or {}), method=method)
            try:
                response = self._opener.open(request, timeout=self.timeout)
                try:
                    status = int(getattr(response, "status", response.getcode()))
                    body = response.read()
                    final_url = str(response.geturl() or url)
                    content_type = response.headers.get_content_charset() if response.headers else None
                finally:
                    response.close()
            except HTTPError as exc:
                status = int(exc.code)
                body = exc.read()
                final_url = str(exc.geturl() or url)
                content_type = exc.headers.get_content_charset() if exc.headers else None
                last_error = exc
            except (OSError, URLError) as exc:
                last_error = exc
                if attempt < self.retries:
                    self._sleep(0.4 * (2**attempt))
                    continue
                raise FacebookAdsTransportError(f"Meta HTTP 请求失败: {exc}") from exc

            source = body.decode(content_type or "utf-8", errors="replace")
            if status == 200:
                return source, final_url
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                self._sleep(0.4 * (2**attempt))
                continue
            if status == 429:
                raise FacebookAdsTransportError("Meta HTTP 请求频率受限", code="rate_limited")
            if status in {400, 401, 403} and purpose == "ssr":
                raise FacebookAdsTransportError(
                    f"Meta Ads Library SSR 返回 HTTP {status}，当前出口被网络信誉策略拦截",
                    code="network_reputation_blocked",
                )
            if status in {401, 403}:
                raise FacebookAdsTransportError(
                    f"Meta GraphQL 返回 HTTP {status}",
                    code="anonymous_session_expired",
                )
            raise FacebookAdsTransportError(
                f"Meta HTTP 返回 {status}",
                code="upstream_http_error",
            ) from last_error
        raise FacebookAdsTransportError("Meta HTTP 请求重试耗尽")

    def _wait_for_graphql_slot(self) -> None:
        if self._last_graphql_at is None or self.request_interval <= 0:
            return
        remaining = self.request_interval - (self._monotonic() - self._last_graphql_at)
        if remaining > 0:
            self._sleep(remaining)

    @staticmethod
    def _validate_facebook_url(value: str) -> None:
        try:
            parsed = urlsplit(value)
            host = (parsed.hostname or "").casefold().rstrip(".")
        except ValueError as exc:
            raise FacebookAdsTransportError("Meta 重定向 URL 格式错误") from exc
        if parsed.scheme != "https" or not (host == "facebook.com" or host.endswith(".facebook.com")):
            raise FacebookAdsTransportError("Meta 请求重定向离开 facebook.com")

    @staticmethod
    def _validate_media_url(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise FacebookAdsInputError("media URL 不能为空")
        candidate = value.strip()
        try:
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").casefold()
            port = parsed.port
        except ValueError as exc:
            raise FacebookAdsInputError("media URL 格式错误") from exc
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or not any(host.endswith(suffix) for suffix in _MEDIA_HOST_SUFFIXES)
        ):
            raise FacebookAdsInputError("media URL 必须是可信 Meta CDN 的 HTTPS 地址")
        return candidate

    @staticmethod
    def _content_length(headers: Any) -> int | None:
        if not headers:
            return None
        value = headers.get("Content-Length")
        if value is None:
            return None
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result >= 0 else None

    @staticmethod
    def _validate_meta_asset_url(value: str) -> None:
        try:
            parsed = urlsplit(value)
            host = (parsed.hostname or "").casefold().rstrip(".")
            port = parsed.port
        except ValueError as exc:
            raise FacebookAdsTransportError("Meta 静态资源 URL 格式错误") from exc
        owned = (
            host == "facebook.com"
            or host.endswith(".facebook.com")
            or host == "fbcdn.net"
            or host.endswith(".fbcdn.net")
        )
        if (
            parsed.scheme != "https"
            or not owned
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
        ):
            raise FacebookAdsTransportError("Meta 静态资源 URL 离开可信域名")

    @staticmethod
    def _parse_ad_details(
        payloads: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        for payload in payloads:
            details = _deep_find(payload, {"ad_details", "adDetails"})
            if isinstance(details, Mapping):
                return details
        _raise_graphql_error(payloads)
        raise AssertionError("GraphQL 错误处理未抛出")

    @classmethod
    def _normalize_ad_details(
        cls,
        raw: Mapping[str, Any],
        *,
        ad_id: str,
        page_id: str,
        country: str,
        source_url: str,
        collected_at: datetime,
    ) -> dict[str, Any]:
        advertiser = _mapping(raw.get("advertiser"))
        page_raw = _mapping(advertiser.get("page"))
        library_page = _mapping(advertiser.get("ad_library_page_info"))
        page_info = _mapping(library_page.get("page_info"))
        page = cls._normalize_page({**page_raw, **page_info, "page_id": page_id})
        page.update(
            {
                "about": _text(_mapping(page_raw.get("about")).get("text")),
                "cover_photo_url": _text(page_info.get("page_cover_photo")) or None,
                "is_restricted": page_info.get("page_is_restricted"),
                "is_profile_page": page_info.get("is_profile_page"),
            }
        )
        aaa = _mapping(raw.get("aaa_info"))
        payer_beneficiary = [
            {
                "payer": _text(_mapping(item).get("payer")) or None,
                "beneficiary": _text(_mapping(item).get("beneficiary")) or None,
            }
            for item in _items(aaa.get("payer_beneficiary_data"))
            if isinstance(item, Mapping)
        ]
        transparency = _mapping(raw.get("transparency_by_location"))
        reach = {
            "eu": _normalize_location_transparency(
                transparency.get("eu_transparency"), region="eu"
            ),
            "uk": _normalize_location_transparency(
                transparency.get("uk_transparency"), region="uk"
            ),
            "br": _normalize_location_transparency(
                transparency.get("br_transparency"), region="br"
            ),
        }
        reach = {key: value for key, value in reach.items() if value is not None}
        page_spend = _mapping(library_page.get("page_spend"))
        verified_voice = _mapping(raw.get("verified_voice_context"))
        return {
            "kind": "facebook_ad_details",
            "source": "meta_ads_library_anonymous_graphql",
            "source_url": source_url,
            "access": "anonymous",
            "collected_at": collected_at.isoformat(),
            "ad_id": ad_id,
            "page_id": page_id,
            "query_country": country,
            "advertiser": {
                "page": page,
                "page_spend": {
                    "current_week": page_spend.get("current_week"),
                    "lifetime_by_disclaimer": _items(
                        page_spend.get("lifetime_by_disclaimer")
                    ),
                    "weekly_by_disclaimer": _items(
                        page_spend.get("weekly_by_disclaimer")
                    ),
                    "is_political_page": page_spend.get("is_political_page"),
                },
            },
            "payer_beneficiary": payer_beneficiary,
            "transparency": {
                "targets_eu": aaa.get("targets_eu"),
                "is_ad_taken_down": aaa.get("is_ad_taken_down"),
                "has_violating_payer_beneficiary": aaa.get(
                    "has_violating_payer_beneficiary"
                ),
                "reach": reach,
            },
            "violations": _items(raw.get("violation_types")),
            "verified_voice_types": _items(verified_voice.get("types")),
            "ai_disclosure": {
                "eligible": raw.get(
                    "is_siep_advertiser_eligible_for_ai_disclosure"
                ),
                "violating_eu_siep": raw.get("is_violating_eu_siep"),
            },
            "metric_scope": {
                "reported_total_reach": "published_estimated_unique_accounts",
                "country_age_gender_reach": "published_estimated_breakdown",
                "ad_impressions": "not_published_for_general_commercial_ads",
                "ad_likes": "not_published",
                "video_views": "not_published",
                "ctr": "not_published",
                "advertiser_page_likes": "advertiser_scale_only",
                "ranking_rule": "reach 只比较公开了相同地区口径的广告",
            },
        }

    @staticmethod
    def _parse_search_page(
        payloads: Sequence[Mapping[str, Any]],
    ) -> tuple[list[Mapping[str, Any]], Mapping[str, Any], int | None]:
        connections: list[Mapping[str, Any]] = []
        for payload in payloads:
            value = _deep_find(payload, {"search_results_connection", "searchResultsConnection"})
            if isinstance(value, Mapping):
                connections.append(value)
        if not connections:
            _raise_graphql_error(payloads)
        ads: list[Mapping[str, Any]] = []
        page_info: Mapping[str, Any] = {}
        total: int | None = None
        for connection in connections:
            current_total = _optional_int(connection.get("count"))
            if current_total is not None:
                total = current_total
            current_info = _first(connection, "page_info", "pageInfo")
            if isinstance(current_info, Mapping):
                page_info = current_info
            edges = connection.get("edges")
            if not isinstance(edges, list):
                raise FacebookAdsResponseError("Meta 广告连接的 edges 不是数组")
            for edge in edges:
                node = _mapping(_mapping(edge).get("node")) or _mapping(edge)
                collated = _first(node, "collated_results", "collatedResults")
                if isinstance(collated, list):
                    candidates = collated
                elif _first(node, "ad_archive_id", "adArchiveID", "id") is not None:
                    candidates = [node]
                else:
                    candidates = []
                for candidate in candidates:
                    if not isinstance(candidate, Mapping):
                        continue
                    flattened = dict(candidate)
                    snapshot = candidate.get("snapshot")
                    if isinstance(snapshot, Mapping):
                        for key, value in snapshot.items():
                            flattened.setdefault(key, value)
                    ads.append(flattened)
        return ads, page_info, total

    @staticmethod
    def _parse_suggestions(payloads: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        suggestions: list[Mapping[str, Any]] = []
        found = False
        for payload in payloads:
            raw = _deep_find(payload, {"typeahead_suggestions", "typeaheadSuggestions"})
            if raw is not _MISSING:
                found = True
                if isinstance(raw, Mapping):
                    raw = _first(raw, "page_results", "pageResults") or []
                suggestions.extend(item for item in _items(raw) if isinstance(item, Mapping))
            connection = _deep_find(
                payload,
                {"typeahead_suggestions_connection", "typeaheadSuggestionsConnection"},
            )
            if isinstance(connection, Mapping):
                found = True
                for edge in _items(connection.get("edges")):
                    node = _mapping(_mapping(edge).get("node")) or _mapping(edge)
                    if node:
                        suggestions.append(node)
        if not found:
            _raise_graphql_error(payloads)
        return suggestions

    @staticmethod
    def _normalize_page(raw: Mapping[str, Any]) -> dict[str, Any]:
        nested = _mapping(_first(raw, "page", "page_data", "pageData"))
        source = {**nested, **raw}
        page_id = _text(_first(source, "page_id", "pageID", "id"))
        alias = _text(_first(source, "page_alias", "pageAlias", "alias"))
        page_url = _text(
            _first(source, "page_profile_uri", "pageProfileURI", "url", "uri")
        )
        if not page_url and (alias or page_id):
            page_url = f"https://www.facebook.com/{quote(alias or page_id, safe='')}"
        raw_verification = _first(
            source,
            "verification",
            "is_verified",
            "isVerified",
            "page_verified",
            "page_verification",
        )
        if isinstance(raw_verification, bool):
            verified: bool | None = raw_verification
            verification_status = "VERIFIED" if verified else "NOT_VERIFIED"
        else:
            verification_status = _text(raw_verification).upper()
            if verification_status == "NOT_VERIFIED":
                verified = False
            elif verification_status.endswith("VERIFIED"):
                verified = True
            else:
                verified = None
        return {
            "page_id": page_id,
            "name": _text(_first(source, "page_name", "pageName", "name")),
            "url": page_url,
            "alias": alias,
            "profile_picture_url": _text(
                _first(
                    source,
                    "page_profile_picture_url",
                    "pageProfilePictureURL",
                    "page_logo_url",
                    "pageLogoURL",
                    "image_uri",
                    "imageURI",
                    "profile_photo",
                )
            ),
            "verified": verified,
            "verification_status": verification_status or None,
            "like_count": _optional_int(
                _first(source, "page_like_count", "pageLikeCount", "like_count", "likes")
            ),
            "category": _text(_first(source, "category", "page_category", "pageCategory")),
            "country": _text(source.get("country")) or None,
            "entity_type": _text(_first(source, "entity_type", "entityType")) or None,
            "page_is_deleted": _first(source, "page_is_deleted", "pageIsDeleted"),
            "instagram": {
                "username": _text(_first(source, "ig_username", "igUsername")) or None,
                "follower_count": _optional_int(
                    _first(source, "ig_followers", "igFollowers")
                ),
                "verification_status": (
                    _text(_first(source, "ig_verification", "igVerification")).upper()
                    or None
                ),
            },
            "ads_library_url": (
                f"{AD_LIBRARY_URL}?active_status=all&ad_type=all&country=ALL"
                f"&search_type=page&view_all_page_id={quote(page_id)}"
                if page_id
                else ""
            ),
        }

    @classmethod
    def _normalize_ad(
        cls,
        raw: Mapping[str, Any],
        *,
        rank: int,
        collected_at: datetime,
        include_raw: bool,
    ) -> dict[str, Any]:
        ad_id = _text(_first(raw, "ad_archive_id", "adArchiveID", "id"))
        page = cls._normalize_page(raw)
        cards = [item for item in _items(raw.get("cards")) if isinstance(item, Mapping)]
        creatives: list[dict[str, Any]] = []
        if cards:
            for index, card in enumerate(cards, start=1):
                creatives.append(cls._creative(card, fallback=raw, index=index))
        else:
            creatives.append(cls._creative(raw, fallback={}, index=1))
        start = _first(raw, "ad_delivery_start_time", "start_date", "startDate")
        stop = _first(raw, "ad_delivery_stop_time", "end_date", "endDate")
        start_dt = _parse_datetime(start)
        stop_dt = _parse_datetime(stop)
        active_until = min(stop_dt, collected_at) if stop_dt else collected_at
        active_days = None
        if start_dt:
            active_days = max(0, (active_until.date() - start_dt.date()).days + 1)
        is_active = _first(raw, "is_active", "isActive")
        ad_status = _text(_first(raw, "ad_status", "adStatus"))
        if is_active is None and ad_status:
            is_active = ad_status == "ACTIVE"
        platforms = [
            _text(item).upper()
            for item in _items(
                _first(raw, "publisher_platforms", "publisherPlatforms", "publisher_platform")
            )
            if _text(item)
        ]
        landing_urls = [
            _text(creative.get("landing_url")) for creative in creatives if creative.get("landing_url")
        ]
        result: dict[str, Any] = {
            "ad_id": ad_id,
            "source_url": f"{AD_LIBRARY_URL}?id={quote(ad_id)}" if ad_id else "",
            "page": page,
            "status": {
                "is_active": is_active,
                "ad_status": ad_status or None,
                "delivery_start_time": _iso_datetime(start),
                "delivery_stop_time": _iso_datetime(stop),
            },
            "display_format": _text(_first(raw, "display_format", "displayFormat")),
            "creatives": creatives,
            "landing_domains": sorted({_landing_domain(value) for value in landing_urls if value}),
            "publisher_platforms": list(dict.fromkeys(platforms)),
            "targeted_or_reached_countries": [
                _text(item)
                for item in _items(
                    _first(
                        raw,
                        "targeted_or_reached_countries",
                        "targetedOrReachedCountries",
                    )
                )
                if _text(item)
            ],
            "categories": [
                _text(item)
                for item in _items(_first(raw, "page_categories", "categories"))
                if _text(item)
            ],
            "collation": {
                "id": _text(_first(raw, "collation_id", "collationID")) or None,
                "count": _optional_int(_first(raw, "collation_count", "collationCount")),
            },
            "transparency": {
                "impressions": _first(raw, "impressions", "impressionsWithIndex", "impressions_with_index"),
                "spend": _first(raw, "spend", "spendWithIndex"),
                "reach": _first(raw, "reach", "reach_estimate"),
                "total_active_time": _first(raw, "total_active_time", "totalActiveTime"),
                "currency": _text(raw.get("currency")) or None,
                "bylines": _items(raw.get("bylines")),
                "beneficiary_payers": _items(
                    _first(raw, "beneficiary_payers", "beneficiaryPayers")
                ),
            },
            "disclosures": {
                "contains_digitally_created_media": _first(
                    raw,
                    "contains_digital_created_media",
                    "containsDigitallyCreatedMedia",
                ),
                "contains_sensitive_content": _first(
                    raw,
                    "contains_sensitive_content",
                    "containsSensitiveContent",
                ),
                "gated_type": _text(_first(raw, "gated_type", "gatedType")) or None,
            },
            "proxy_signals": {
                "result_rank": rank,
                "active_days": active_days,
                "creative_variant_count": (
                    _optional_int(_first(raw, "collation_count", "collationCount"))
                    or len(creatives)
                ),
                "publisher_platform_count": len(set(platforms)),
            },
        }
        if include_raw:
            result["raw"] = dict(raw)
        return result

    @classmethod
    def _creative(
        cls,
        raw: Mapping[str, Any],
        *,
        fallback: Mapping[str, Any],
        index: int,
    ) -> dict[str, Any]:
        def value(*names: str) -> Any:
            return _first(raw, *names) if _first(raw, *names) is not None else _first(fallback, *names)

        body_value = value("body", "ad_creative_body")
        body = _text(body_value.get("text")) if isinstance(body_value, Mapping) else _text(body_value)
        landing_url, tracking_url = _external_landing_url(value("link_url", "linkUrl"))
        media: list[dict[str, Any]] = []
        videos = [item for item in _items(raw.get("videos")) if isinstance(item, Mapping)]
        images = [item for item in _items(raw.get("images")) if isinstance(item, Mapping)]
        if not videos and not images and raw is not fallback:
            videos = [item for item in _items(fallback.get("videos")) if isinstance(item, Mapping)]
            images = [item for item in _items(fallback.get("images")) if isinstance(item, Mapping)]
        if any(name in raw for name in ("video_hd_url", "video_sd_url", "video_preview_image_url")):
            videos.insert(0, raw)
        if any(name in raw for name in ("original_image_url", "resized_image_url")):
            images.insert(0, raw)
        for video in videos:
            hd = _text(_first(video, "video_hd_url", "videoHdUrl"))
            sd = _text(_first(video, "video_sd_url", "videoSdUrl"))
            watermarked_hd = _text(
                _first(video, "watermarked_video_hd_url", "watermarkedVideoHdUrl")
            )
            watermarked_sd = _text(
                _first(video, "watermarked_video_sd_url", "watermarkedVideoSdUrl")
            )
            url = hd or sd
            if url:
                media.append(
                    {
                        "type": "video",
                        "url": url,
                        "variants": {
                            key: val
                            for key, val in {
                                "hd": hd,
                                "sd": sd,
                                "watermarked_hd": watermarked_hd,
                                "watermarked_sd": watermarked_sd,
                            }.items()
                            if val
                        },
                        "thumbnail_url": _text(
                            _first(video, "video_preview_image_url", "videoPreviewImageUrl")
                        ),
                        "url_stability": "ephemeral_cdn",
                    }
                )
        for image in images:
            original = _text(_first(image, "original_image_url", "originalImageUrl"))
            resized = _text(_first(image, "resized_image_url", "resizedImageUrl"))
            watermarked = _text(
                _first(
                    image,
                    "watermarked_resized_image_url",
                    "watermarkedResizedImageUrl",
                )
            )
            url = original or resized
            if url:
                media.append(
                    {
                        "type": "image",
                        "url": url,
                        "variants": {
                            key: val
                            for key, val in {
                                "original": original,
                                "resized": resized,
                                "watermarked": watermarked,
                            }.items()
                            if val
                        },
                        "url_stability": "ephemeral_cdn",
                    }
                )
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in media:
            key = (_text(item.get("type")), _text(item.get("url")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return {
            "index": index,
            "body": body,
            "title": _text(value("title", "link_title", "linkTitle")),
            "description": _text(value("link_description", "linkDescription")),
            "caption": _text(value("caption")),
            "cta_text": _text(value("cta_text", "ctaText")),
            "cta_type": _text(value("cta_type", "ctaType")),
            "landing_url": landing_url,
            "tracking_url": tracking_url if tracking_url != landing_url else "",
            "media": deduped,
        }

    @staticmethod
    def _add_sample_signals(items: list[dict[str, Any]]) -> None:
        page_counts = Counter(_text(item.get("page", {}).get("page_id")) for item in items)
        domain_counts = Counter(
            domain for item in items for domain in _items(item.get("landing_domains")) if domain
        )
        copy_keys: list[str] = []
        for item in items:
            first_creative = _mapping(_items(item.get("creatives"))[0] if item.get("creatives") else {})
            source = "\n".join(
                (
                    _text(first_creative.get("body")).casefold(),
                    _text(first_creative.get("title")).casefold(),
                    ",".join(_items(item.get("landing_domains"))),
                )
            )
            copy_keys.append(sha256(source.encode("utf-8")).hexdigest() if source.strip() else "")
        copy_counts = Counter(key for key in copy_keys if key)
        for item, copy_key in zip(items, copy_keys, strict=True):
            page_id = _text(item.get("page", {}).get("page_id"))
            domains = _items(item.get("landing_domains"))
            item["proxy_signals"].update(
                {
                    "same_page_ads_in_sample": page_counts.get(page_id, 0) if page_id else 0,
                    "same_landing_domain_ads_in_sample": max(
                        (domain_counts.get(domain, 0) for domain in domains), default=0
                    ),
                    "same_copy_ads_in_sample": copy_counts.get(copy_key, 0) if copy_key else 0,
                }
            )

    @staticmethod
    def _source_url(
        *,
        query: str,
        countries: Sequence[str],
        page_ids: Sequence[str],
        active_status: str,
        ad_type: str,
        media_type: str,
        search_type: str,
        publisher_platforms: Sequence[str],
        content_languages: Sequence[str],
        start_date: str,
        end_date: str,
        sort: str,
        sort_direction: str,
    ) -> str:
        ad_type_url = {
            "CREDIT_ADS": "financial_products_and_services_ads",
            "FINANCIAL_PRODUCTS_AND_SERVICES_ADS": "financial_products_and_services_ads",
        }.get(ad_type, ad_type.casefold())
        params: list[tuple[str, str]] = [
            ("active_status", active_status.casefold()),
            ("ad_type", ad_type_url),
            ("country", countries[0]),
            ("media_type", media_type.casefold()),
            ("search_type", search_type.casefold()),
            ("sort_data[mode]", sort),
            ("sort_data[direction]", FacebookAdsClient._sort_direction_value(sort_direction)),
        ]
        if query:
            params.append(("q", query))
        if search_type == "PAGE" and len(page_ids) == 1:
            params.append(("view_all_page_id", page_ids[0]))
        params.extend(("page_ids[]", item) for item in page_ids)
        params.extend(
            ("publisher_platforms[]", item.casefold())
            for item in publisher_platforms
        )
        params.extend(("content_languages[]", item) for item in content_languages)
        if start_date:
            params.append(("start_date[min]", start_date))
        if end_date:
            params.append(("start_date[max]", end_date))
        return f"{AD_LIBRARY_URL}?{urlencode(params)}"

    @staticmethod
    def _graphql_ad_type(value: str) -> str:
        if value == "CREDIT_ADS":
            return "FINANCIAL_PRODUCTS_AND_SERVICES_ADS"
        return value

    @staticmethod
    def _sort_direction_value(value: str) -> str:
        return "asc" if value == "ASCENDING" else "desc"

    @staticmethod
    def _graphql_sort_mode(value: str) -> str:
        return {
            "total_impressions": "SORT_BY_TOTAL_IMPRESSIONS",
            "relevancy_monthly_grouped": "SORT_BY_RELEVANCY_MONTHLY_GROUPED",
        }[value]

    @staticmethod
    def _ad_identity(raw: Mapping[str, Any]) -> str:
        identifier = _text(_first(raw, "ad_archive_id", "adArchiveID", "id"))
        if identifier:
            return identifier
        return sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _base36(value: int) -> str:
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        output = ""
        while value:
            value, remainder = divmod(value, 36)
            output = digits[remainder] + output
        return output or "0"

    @staticmethod
    def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            raise FacebookAdsInputError(f"{name} 必须是整数")
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise FacebookAdsInputError(f"{name} 必须是整数") from exc
        if result < minimum or result > maximum:
            raise FacebookAdsInputError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
        return result

    @staticmethod
    def _enum(value: Any, name: str, allowed: set[str]) -> str:
        normalized = _text(value).upper()
        if normalized not in allowed:
            raise FacebookAdsInputError(f"{name} 不支持 {value!r}")
        return normalized

    @staticmethod
    def _query(value: Any, *, required: bool) -> str:
        if not isinstance(value, str):
            raise FacebookAdsInputError("query 必须是字符串")
        result = re.sub(r"\s+", " ", value).strip()
        if required and not result:
            raise FacebookAdsInputError("query 不能为空")
        if len(result) > 500 or any(char in result for char in "\r\n\0"):
            raise FacebookAdsInputError("query 长度或字符不符合要求")
        return result

    @staticmethod
    def _split_values(value: str | Sequence[str] | None, name: str) -> list[str]:
        if value is None:
            return []
        raw = [value] if isinstance(value, str) else list(value)
        output: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                raise FacebookAdsInputError(f"{name} 必须是字符串")
            output.extend(part.strip() for part in item.split(",") if part.strip())
        return list(dict.fromkeys(output))

    @classmethod
    def _countries(cls, value: str | Sequence[str] | None) -> list[str]:
        output = [item.upper() for item in cls._split_values(value, "countries")] or ["US"]
        if any(item != "ALL" and not _COUNTRY_RE.fullmatch(item) for item in output):
            raise FacebookAdsInputError("country 必须是两字母代码或 ALL")
        if len(output) > 1:
            raise FacebookAdsInputError("匿名 Ads Library 每次只接受一个 country")
        return output

    @classmethod
    def _page_ids(cls, value: str | Sequence[str] | None) -> list[str]:
        output = cls._split_values(value, "page_ids")
        if any(not _PAGE_ID_RE.fullmatch(item) for item in output):
            raise FacebookAdsInputError("Page id 必须是 1 到 30 位十进制数字")
        if len(output) > 50:
            raise FacebookAdsInputError("Meta 页面过滤一次最多接受 50 个 Page id")
        return output

    @classmethod
    def _platforms(cls, value: str | Sequence[str] | None) -> list[str]:
        output = [item.upper() for item in cls._split_values(value, "publisher_platforms")]
        if any(item not in _VALID_PUBLISHER_PLATFORMS for item in output):
            raise FacebookAdsInputError("publisher platform 包含不支持的值")
        return output

    @classmethod
    def _languages(cls, value: str | Sequence[str] | None) -> list[str]:
        output = [item.casefold() for item in cls._split_values(value, "content_languages")]
        if any(not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", item) for item in output):
            raise FacebookAdsInputError("content language 必须是 BCP 47 语言代码")
        return output

    @staticmethod
    def _dates(start_value: Any, end_value: Any) -> tuple[str, str]:
        values = [_text(start_value), _text(end_value)]
        parsed: list[date | None] = []
        for label, value in zip(("start_date", "end_date"), values, strict=True):
            if not value:
                parsed.append(None)
                continue
            try:
                parsed.append(date.fromisoformat(value))
            except ValueError as exc:
                raise FacebookAdsInputError(f"{label} 必须使用 YYYY-MM-DD") from exc
        if parsed[0] and parsed[1] and parsed[1] <= parsed[0]:
            raise FacebookAdsInputError("end_date 必须晚于 start_date")
        return values[0], values[1]

    @staticmethod
    def _cursor(value: Any) -> str:
        result = _text(value)
        if len(result) > 4096 or any(char in result for char in "\r\n\0"):
            raise FacebookAdsInputError("cursor 长度或字符不符合要求")
        return result
