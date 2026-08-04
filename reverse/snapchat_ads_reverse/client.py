from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from .errors import (
    SnapchatAdsInputError,
    SnapchatAdsResponseError,
    SnapchatAdsTransportError,
)


BASE_URL = "https://adsapi.snapchat.com"
ADS_SEARCH_PATH = "/v1/ads_library/ads/search"
AD_DETAIL_PATH = "/v1/ads_library/ads/{ad_id}"
SPONSORED_CONTENT_PATH = "/v1/ads_library/sponsored_content"
SPONSORED_SEARCH_PATH = "/v1/ads_library/sponsored_content/search"
LAST_PROTOCOL_VERIFIED = "2026-08-01"
DEFAULT_USER_AGENT = "reverse-snapchat-ads/1.0"

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_AD_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_REQUEST_COUNTRIES = {
    "at",
    "be",
    "bg",
    "cy",
    "cz",
    "de",
    "dk",
    "ee",
    "el",
    "es",
    "fi",
    "fr",
    "hr",
    "hu",
    "ie",
    "it",
    "lt",
    "lu",
    "lv",
    "mt",
    "nl",
    "pl",
    "pt",
    "ro",
    "se",
    "si",
    "sk",
}
_MEDIA_HOST_SUFFIXES = (".sc-cdn.net", ".snapchat.com", ".snap.com")
_MEDIA_HOSTS = {
    "storage.googleapis.com",
    "community-lens.storage.googleapis.com",
    "lens-preview-storage.storage.googleapis.com",
}
_MAX_JSON_BYTES = 64 * 1024 * 1024
_MAX_CURSOR_LENGTH = 16_384
_MAX_PAGES = 100


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError, OverflowError):
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_datetime(value: Any, *, field: str) -> str | None:
    source = _text(value)
    if not source:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", source):
            parsed = datetime.combine(date.fromisoformat(source), datetime.min.time())
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(source.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
            parsed = parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise SnapchatAdsInputError(
            f"{field} 必须是 YYYY-MM-DD 或带时区的 ISO 8601 时间"
        ) from exc
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_countries(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        source = value.split(",")
    else:
        source = []
        for item in _items(value):
            source.extend(str(item).split(","))
    countries: list[str] = []
    for item in source:
        country = item.strip().casefold()
        if country == "gr":
            country = "el"
        if country not in _REQUEST_COUNTRIES:
            raise SnapchatAdsInputError(
                f"country {item!r} 不在 Snapchat Ads Gallery 官方请求国家列表中"
            )
        if country not in countries:
            countries.append(country)
    return countries


def _validate_cursor(value: Any) -> str:
    cursor = _text(value)
    if not cursor:
        return ""
    if len(cursor) > _MAX_CURSOR_LENGTH or any(ord(char) < 32 for char in cursor):
        raise SnapchatAdsInputError("cursor 格式无效")
    return cursor


def _validate_limit(value: Any, *, maximum: int = 500) -> int:
    if isinstance(value, bool):
        raise SnapchatAdsInputError("limit 必须是整数")
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise SnapchatAdsInputError("limit 必须是整数") from exc
    if limit < 1 or limit > maximum:
        raise SnapchatAdsInputError(f"limit 必须在 1 到 {maximum} 之间")
    return limit


def _validate_product_limit(value: Any) -> int:
    if isinstance(value, bool):
        raise SnapchatAdsInputError("product_limit 必须是整数")
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise SnapchatAdsInputError("product_limit 必须是整数") from exc
    if limit < 0 or limit > 100:
        raise SnapchatAdsInputError("product_limit 必须在 0 到 100 之间")
    return limit


def _valid_media_url(value: Any) -> str:
    source = _text(value)
    if not source:
        return ""
    try:
        parsed = urlsplit(source)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme != "https" or not host:
        return ""
    if host in _MEDIA_HOSTS or any(host.endswith(suffix) for suffix in _MEDIA_HOST_SUFFIXES):
        return source
    return ""


def _require_media_url(value: Any) -> str:
    source = _valid_media_url(value)
    if not source:
        raise SnapchatAdsInputError(
            "媒体 URL 必须使用 Snapchat 官方响应中的 HTTPS CDN 地址"
        )
    return source


def _image_links(value: Any) -> list[str]:
    image = _mapping(value)
    output: list[str] = []
    for candidate in _items(image.get("image_links")):
        url = _valid_media_url(candidate)
        if url and url not in output:
            output.append(url)
    return output


def _media_entry(url: Any, *, role: str, media_type: Any = "") -> dict[str, Any] | None:
    normalized = _valid_media_url(url)
    if not normalized:
        return None
    return {
        "role": role,
        "type": _text(media_type).casefold() or None,
        "url": normalized,
    }


def _normalize_dpa_product(raw: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "title",
        "description",
        "brand",
        "product_type",
        "age_group",
        "availability",
        "color",
        "condition",
        "gender",
        "size",
        "link",
        "custom_label_0",
        "custom_label_1",
        "custom_label_2",
        "custom_label_3",
        "custom_label_4",
    )
    product: dict[str, Any] = {
        field: raw.get(field)
        for field in fields
        if raw.get(field) not in (None, "", [], {})
    }
    product["main_image_urls"] = _image_links(raw.get("main_image"))
    additional: list[dict[str, Any]] = []
    for media in _items(raw.get("additional_media"))[:20]:
        item = _mapping(media)
        urls = _image_links(item)
        if not urls:
            continue
        additional.append(
            {
                "urls": urls,
                "tags": [
                    _text(tag)
                    for tag in _items(item.get("tags"))
                    if _text(tag)
                ],
            }
        )
    product["additional_media"] = additional
    return product


def _normalize_dpa(value: Any, *, product_limit: int) -> dict[str, Any] | None:
    raw = _mapping(value)
    products = [
        _mapping(item)
        for item in _items(raw.get("items"))
        if isinstance(item, Mapping)
    ]
    if not raw and not products:
        return None
    normalized = [_normalize_dpa_product(item) for item in products[:product_limit]]
    return {
        "product_count": len(products),
        "returned_product_count": len(normalized),
        "products_truncated": len(products) > len(normalized),
        "products": normalized,
    }


def _normalize_ad(
    raw: Mapping[str, Any],
    *,
    product_limit: int,
    include_raw: bool,
) -> dict[str, Any]:
    ad_id = _text(raw.get("id"))
    media: list[dict[str, Any]] = []
    candidates = [
        _media_entry(
            raw.get("top_snap_media_download_link"),
            role="top_snap",
            media_type=raw.get("top_snap_media_type"),
        )
    ]
    lens = _mapping(raw.get("lens_preview"))
    candidates.extend(
        (
            _media_entry(lens.get("preview_video_url"), role="lens_preview", media_type="video"),
            _media_entry(lens.get("preview_image_url"), role="lens_preview", media_type="image"),
            _media_entry(lens.get("icon_url"), role="lens_icon", media_type="image"),
        )
    )
    deep_link = _mapping(raw.get("deep_link_properties"))
    candidates.append(
        _media_entry(
            deep_link.get("icon_media_url"),
            role="deep_link_icon",
            media_type="image",
        )
    )
    seen_media: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate["url"] in seen_media:
            continue
        seen_media.add(candidate["url"])
        media.append(candidate)

    impressions_map: dict[str, int] = {}
    for country, value in _mapping(raw.get("impressions_map")).items():
        count = _optional_int(value)
        if count is not None:
            impressions_map[_text(country).casefold()] = count

    web_view = _mapping(raw.get("web_view_properties"))
    dpa = _normalize_dpa(raw.get("dpa_preview"), product_limit=product_limit)
    result: dict[str, Any] = {
        "id": ad_id or None,
        "source_url": (
            f"{BASE_URL}{AD_DETAIL_PATH.format(ad_id=ad_id)}" if ad_id else None
        ),
        "name": _text(raw.get("name")) or None,
        "status": _text(raw.get("status")) or None,
        "start_date": _text(raw.get("start_date")) or None,
        "advertiser": {
            "paying_name": _text(raw.get("paying_advertiser_name")) or None,
            "account_name": _text(raw.get("ad_account_name")) or None,
            "profile_name": _text(raw.get("profile_name")) or None,
            "brand_name": _text(raw.get("brand_name")) or None,
            "profile_logo_url": _valid_media_url(raw.get("profile_logo_url")) or None,
        },
        "creative": {
            "creative_type": _text(raw.get("creative_type")) or None,
            "ad_type": _text(raw.get("ad_type")) or None,
            "render_type": _text(raw.get("ad_render_type")) or None,
            "top_snap_media_type": _text(raw.get("top_snap_media_type")) or None,
            "top_snap_crop_position": _text(raw.get("top_snap_crop_position")) or None,
            "headline": _text(raw.get("headline")) or None,
            "call_to_action": _text(raw.get("call_to_action")) or None,
            "languages": [
                _text(item)
                for item in _items(raw.get("languages"))
                if _text(item)
            ],
            "media": media,
            "landing_url": _text(web_view.get("url")) or None,
            "deep_link_uri": _text(deep_link.get("deep_link_uri")) or None,
        },
        "impressions_total": _optional_int(raw.get("impressions_total")),
        "impressions_by_country": impressions_map,
        "targeting": raw.get("targeting_v2")
        if isinstance(raw.get("targeting_v2"), Mapping)
        else None,
        "review_status": _text(raw.get("review_status")) or None,
        "rejection_reasons": _items(raw.get("rejection_reasons")),
        "dpa": dpa,
    }
    if include_raw:
        result["raw"] = dict(raw)
    return result


def _normalize_sponsored_content(
    raw: Mapping[str, Any],
    *,
    include_raw: bool,
) -> dict[str, Any]:
    content_url = _text(raw.get("content_url"))
    thumbnail_url = _valid_media_url(raw.get("thumbnail_url"))
    result: dict[str, Any] = {
        "source_url": content_url or None,
        "sponsor_name": _text(raw.get("sponsor_name")) or None,
        "sponsor_url": _text(raw.get("sponsor_url")) or None,
        "creator_name": _text(raw.get("creator_name")) or None,
        "creator_url": _text(raw.get("creator_url")) or None,
        "content_type": _text(raw.get("content_type")) or None,
        "content_url": content_url or None,
        "thumbnail_url": thumbnail_url or None,
        "media": (
            [{"role": "thumbnail", "type": "image", "url": thumbnail_url}]
            if thumbnail_url
            else []
        ),
    }
    if include_raw:
        result["raw"] = dict(raw)
    return result


class SnapchatAdsClient:
    """使用 Python HTTP 直连 Snapchat 官方 Ads Gallery API。"""

    def __init__(
        self,
        *,
        timeout: float = 30,
        retries: int = 2,
        request_interval: float = 0.5,
        proxy: str = "",
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout <= 0:
            raise SnapchatAdsInputError("timeout 必须大于 0")
        if retries < 0 or retries > 10:
            raise SnapchatAdsInputError("retries 必须在 0 到 10 之间")
        if request_interval < 0 or request_interval > 60:
            raise SnapchatAdsInputError("request_interval 必须在 0 到 60 秒之间")
        handlers = []
        if proxy:
            parsed = urlsplit(proxy)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise SnapchatAdsInputError("proxy 必须是有效的 http 或 https URL")
            handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.request_interval = float(request_interval)
        self.user_agent = user_agent
        self._opener = opener or build_opener(*handlers)
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def _wait_for_slot(self) -> None:
        if self._last_request_at is not None:
            remaining = self.request_interval - (
                self._monotonic() - self._last_request_at
            )
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _open(self, request: Request):
        for attempt in range(self.retries + 1):
            self._wait_for_slot()
            try:
                return self._opener.open(request, timeout=self.timeout)
            except HTTPError as exc:
                code = int(exc.code)
                if code in _RETRYABLE_STATUS and attempt < self.retries:
                    self._sleep(min(5.0, 0.5 * (2**attempt)))
                    continue
                error_code = {
                    400: "upstream_rejected_input",
                    401: "anonymous_access_denied",
                    403: "anonymous_access_denied",
                    404: "not_found",
                    429: "rate_limited",
                }.get(code, "upstream_unavailable" if code >= 500 else "upstream_http_error")
                raise SnapchatAdsTransportError(
                    f"Snapchat Ads Gallery HTTP {code}",
                    code=error_code,
                ) from exc
            except (OSError, TimeoutError, URLError) as exc:
                if attempt < self.retries:
                    self._sleep(min(5.0, 0.5 * (2**attempt)))
                    continue
                raise SnapchatAdsTransportError(
                    f"Snapchat Ads Gallery 请求失败: {exc}",
                    code="network_error",
                ) from exc
        raise AssertionError("重试循环未返回")

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if path not in {
            ADS_SEARCH_PATH,
            SPONSORED_CONTENT_PATH,
            SPONSORED_SEARCH_PATH,
        } and not path.startswith("/v1/ads_library/ads/"):
            raise SnapchatAdsInputError("请求路径不在 Snapchat Ads Gallery 白名单中")
        encoded_query = urlencode(
            [(key, value) for key, value in (query or {}).items() if value not in (None, "")]
        )
        url = f"{BASE_URL}{path}"
        if encoded_query:
            url = f"{url}?{encoded_query}"
        data = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if body is not None
            else None
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        response = self._open(Request(url, data=data, headers=headers, method=method))
        try:
            content_length = _optional_int(response.headers.get("Content-Length"))
            if content_length is not None and content_length > _MAX_JSON_BYTES:
                raise SnapchatAdsResponseError(
                    "Snapchat Ads Gallery JSON 响应超过大小上限",
                    code="response_too_large",
                )
            source = response.read(_MAX_JSON_BYTES + 1)
            if len(source) > _MAX_JSON_BYTES:
                raise SnapchatAdsResponseError(
                    "Snapchat Ads Gallery JSON 响应超过大小上限",
                    code="response_too_large",
                )
        finally:
            response.close()
        try:
            payload = json.loads(source.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapchatAdsResponseError(
                "Snapchat Ads Gallery 返回了无效 JSON",
                code="invalid_json",
            ) from exc
        if not isinstance(payload, Mapping):
            raise SnapchatAdsResponseError("Snapchat Ads Gallery JSON 根节点不是对象")
        status = _text(payload.get("request_status")).upper()
        if status != "SUCCESS":
            message = _text(payload.get("message")) or _text(payload.get("request_status"))
            raise SnapchatAdsResponseError(
                message or "Snapchat Ads Gallery 请求未成功",
                code="upstream_request_failed",
            )
        return payload

    @staticmethod
    def _next_cursor(payload: Mapping[str, Any], *, expected_path: str) -> str:
        next_link = _text(_mapping(payload.get("paging")).get("next_link"))
        if not next_link:
            return ""
        try:
            parsed = urlsplit(next_link)
        except ValueError as exc:
            raise SnapchatAdsResponseError(
                "Snapchat Ads Gallery next_link 格式已变化",
                code="pagination_drift",
            ) from exc
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != "adsapi.snapchat.com"
            or parsed.path != expected_path
        ):
            raise SnapchatAdsResponseError(
                "Snapchat Ads Gallery next_link 越出官方分页端点",
                code="pagination_drift",
            )
        cursors = parse_qs(parsed.query, keep_blank_values=True).get("cursor", [])
        if len(cursors) != 1:
            raise SnapchatAdsResponseError(
                "Snapchat Ads Gallery next_link 缺少唯一 cursor",
                code="pagination_drift",
            )
        return _validate_cursor(cursors[0])

    def _paginate(
        self,
        *,
        path: str,
        method: str,
        body: Mapping[str, Any] | None,
        cursor: str,
        limit: int,
        query_limit: int | None,
        wrapper_fields: tuple[str, ...],
        normalizer: Callable[[Mapping[str, Any]], dict[str, Any]],
        identity: Callable[[Mapping[str, Any]], str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, str]], list[str]]:
        input_cursor = _validate_cursor(cursor)
        current_cursor = input_cursor
        seen_cursors = {current_cursor} if current_cursor else set()
        seen_items: set[str] = set()
        items: list[dict[str, Any]] = []
        request_ids: list[str] = []
        pages_fetched = 0
        stop_reason = "source_exhausted"
        next_cursor = ""
        has_next_page = False
        warnings: list[dict[str, str]] = []

        while pages_fetched < _MAX_PAGES:
            query: dict[str, Any] = {"cursor": current_cursor}
            if query_limit is not None:
                query["limit"] = min(query_limit, max(1, limit - len(items)))
            payload = self._request_json(path, method=method, query=query, body=body)
            pages_fetched += 1
            request_id = _text(payload.get("request_id"))
            if request_id:
                request_ids.append(request_id)
            raw_wrappers = _items(payload.get("ad_previews"))
            if not raw_wrappers:
                raw_wrappers = _items(payload.get("organic_content"))

            page_items: list[dict[str, Any]] = []
            for wrapper_value in raw_wrappers:
                wrapper = _mapping(wrapper_value)
                if _text(wrapper.get("sub_request_status")).upper() not in {"", "SUCCESS"}:
                    warnings.append(
                        {
                            "code": "sub_request_failed",
                            "message": _text(wrapper.get("sub_request_status"))
                            or "单条子请求失败",
                        }
                    )
                    continue
                raw: Mapping[str, Any] = {}
                for field in wrapper_fields:
                    candidate = wrapper.get(field)
                    if isinstance(candidate, Mapping):
                        raw = candidate
                        break
                if not raw:
                    continue
                key = identity(raw)
                if key and key in seen_items:
                    continue
                if key:
                    seen_items.add(key)
                page_items.append(normalizer(raw))

            upstream_next = self._next_cursor(payload, expected_path=path)
            has_next_page = bool(upstream_next)
            remaining = limit - len(items)
            if len(page_items) > remaining:
                items.extend(page_items[:remaining])
                stop_reason = "limit_within_page"
                next_cursor = ""
                warnings.append(
                    {
                        "code": "continuation_not_representable",
                        "message": "limit 落在上游页面内部，cursor 只能指向整页之后",
                    }
                )
                break
            items.extend(page_items)
            next_cursor = upstream_next
            if len(items) >= limit:
                stop_reason = "limit_reached"
                break
            if not upstream_next:
                stop_reason = "source_exhausted"
                break
            if upstream_next in seen_cursors:
                stop_reason = "pagination_abnormal"
                next_cursor = ""
                warnings.append(
                    {
                        "code": "pagination_abnormal",
                        "message": "Snapchat Ads Gallery 返回了重复 cursor",
                    }
                )
                break
            seen_cursors.add(upstream_next)
            current_cursor = upstream_next
        else:
            stop_reason = "page_cap_reached"
            warnings.append(
                {
                    "code": "page_cap_reached",
                    "message": f"达到单次 {_MAX_PAGES} 页保护上限",
                }
            )

        pagination = {
            "input_cursor": input_cursor or None,
            "next_cursor": next_cursor or None,
            "has_next_page": has_next_page,
            "pages_fetched": pages_fetched,
            "stop_reason": stop_reason,
        }
        return items, pagination, warnings, request_ids

    def search_ads(
        self,
        *,
        paying_advertiser_name: str = "",
        countries: Any = None,
        start_date: Any = "",
        end_date: Any = "",
        status: str = "ACTIVE",
        cursor: str = "",
        limit: int = 50,
        product_limit: int = 20,
        sort_by: str = "impressions",
        include_raw: bool = False,
    ) -> dict[str, Any]:
        advertiser = _text(paying_advertiser_name)
        normalized_countries = _normalize_countries(countries)
        normalized_start = _normalize_datetime(start_date, field="start_date")
        normalized_end = _normalize_datetime(end_date, field="end_date")
        if normalized_start and normalized_end and normalized_start > normalized_end:
            raise SnapchatAdsInputError("start_date 不能晚于 end_date")
        normalized_status = _text(status).upper()
        if normalized_status not in {"ACTIVE", "PAUSED"}:
            raise SnapchatAdsInputError("status 必须是 ACTIVE 或 PAUSED")
        normalized_limit = _validate_limit(limit)
        normalized_product_limit = _validate_product_limit(product_limit)
        if sort_by not in {"impressions", "start_date", "upstream"}:
            raise SnapchatAdsInputError(
                "sort_by 必须是 impressions、start_date 或 upstream"
            )
        body: dict[str, Any] = {"status": normalized_status}
        if advertiser:
            body["paying_advertiser_name"] = advertiser
        if normalized_countries:
            body["countries"] = normalized_countries
        if normalized_start:
            body["start_date"] = normalized_start
        if normalized_end:
            body["end_date"] = normalized_end

        items, pagination, warnings, request_ids = self._paginate(
            path=ADS_SEARCH_PATH,
            method="POST",
            body=body,
            cursor=cursor,
            limit=normalized_limit,
            query_limit=None,
            wrapper_fields=("ad_preview",),
            normalizer=lambda raw: _normalize_ad(
                raw,
                product_limit=normalized_product_limit,
                include_raw=include_raw,
            ),
            identity=lambda raw: _text(raw.get("id")),
        )
        for rank, item in enumerate(items, 1):
            item["upstream_rank"] = rank
        if sort_by == "impressions":
            items.sort(
                key=lambda item: (
                    item.get("impressions_total")
                    if item.get("impressions_total") is not None
                    else -1
                ),
                reverse=True,
            )
        elif sort_by == "start_date":
            items.sort(key=lambda item: _text(item.get("start_date")), reverse=True)
        for rank, item in enumerate(items, 1):
            item["result_rank"] = rank

        return {
            "kind": "snapchat_ads_search",
            "access": "anonymous_official_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "query": {
                "paying_advertiser_name": advertiser or None,
                "countries": normalized_countries,
                "start_date": normalized_start,
                "end_date": normalized_end,
                "status": normalized_status,
                "sort_by": sort_by,
            },
            "count": len(items),
            "items": items,
            "pagination": pagination,
            "request_ids": request_ids,
            "metric_scope": {
                "impressions_total": "published_actual_count",
                "impressions_by_country": "published_actual_count",
                "ctr": "not_published",
                "ad_likes": "not_published",
                "video_views": "not_published",
                "ranking_rule": (
                    "impressions 与 start_date 只在本次已采集样本内排序"
                    if sort_by != "upstream"
                    else "保留 Snapchat 上游返回顺序"
                ),
            },
            "warnings": warnings,
        }

    def get_ad(
        self,
        ad_id: str,
        *,
        product_limit: int = 20,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_id = _text(ad_id).lower()
        if not _AD_ID_RE.fullmatch(normalized_id):
            raise SnapchatAdsInputError("ad_id 必须是 Snapchat Ads Gallery UUID")
        normalized_product_limit = _validate_product_limit(product_limit)
        path = AD_DETAIL_PATH.format(ad_id=normalized_id)
        payload = self._request_json(path, method="GET")
        raw = payload.get("ad_preview")
        if not isinstance(raw, Mapping):
            raise SnapchatAdsResponseError(
                "Snapchat Ads Gallery 详情缺少 ad_preview",
                code="response_drift",
            )
        return {
            "kind": "snapchat_ad",
            "access": "anonymous_official_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "request_id": _text(payload.get("request_id")) or None,
            "item": _normalize_ad(
                raw,
                product_limit=normalized_product_limit,
                include_raw=include_raw,
            ),
            "metric_scope": {
                "impressions_total": "published_actual_count",
                "impressions_by_country": "published_actual_count",
                "ctr": "not_published",
                "ad_likes": "not_published",
                "video_views": "not_published",
            },
        }

    def sponsored_content(
        self,
        *,
        cursor: str = "",
        limit: int = 50,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_limit = _validate_limit(limit)
        items, pagination, warnings, request_ids = self._paginate(
            path=SPONSORED_CONTENT_PATH,
            method="GET",
            body=None,
            cursor=cursor,
            limit=normalized_limit,
            query_limit=100,
            wrapper_fields=("sponsored_content_preview", "organic_content"),
            normalizer=lambda raw: _normalize_sponsored_content(
                raw, include_raw=include_raw
            ),
            identity=lambda raw: _text(raw.get("content_url")),
        )
        return self._sponsored_result(
            kind="snapchat_sponsored_content",
            query={},
            items=items,
            pagination=pagination,
            warnings=warnings,
            request_ids=request_ids,
        )

    def search_sponsored_content(
        self,
        creator_name: str,
        *,
        cursor: str = "",
        page_size: int = 50,
        limit: int = 50,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        creator = _text(creator_name)
        if not creator or len(creator) > 200:
            raise SnapchatAdsInputError("creator_name 长度必须在 1 到 200 之间")
        normalized_limit = _validate_limit(limit)
        normalized_page_size = _validate_limit(page_size, maximum=100)
        items, pagination, warnings, request_ids = self._paginate(
            path=SPONSORED_SEARCH_PATH,
            method="POST",
            body={"creator_name": creator},
            cursor=cursor,
            limit=normalized_limit,
            query_limit=normalized_page_size,
            wrapper_fields=("sponsored_content_preview", "organic_content"),
            normalizer=lambda raw: _normalize_sponsored_content(
                raw, include_raw=include_raw
            ),
            identity=lambda raw: _text(raw.get("content_url")),
        )
        return self._sponsored_result(
            kind="snapchat_sponsored_content_search",
            query={"creator_name": creator},
            items=items,
            pagination=pagination,
            warnings=warnings,
            request_ids=request_ids,
        )

    @staticmethod
    def _sponsored_result(
        *,
        kind: str,
        query: Mapping[str, Any],
        items: list[dict[str, Any]],
        pagination: Mapping[str, Any],
        warnings: list[dict[str, str]],
        request_ids: list[str],
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "access": "anonymous_official_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "query": dict(query),
            "count": len(items),
            "items": items,
            "pagination": dict(pagination),
            "request_ids": request_ids,
            "metric_scope": {
                "views": "not_published",
                "likes": "not_published",
                "shares": "not_published",
                "ranking_rule": "保留 Snapchat 上游返回顺序",
            },
            "warnings": warnings,
        }

    def download_media(
        self,
        url: str,
        destination: str | Path,
        *,
        max_bytes: int = 512 * 1024 * 1024,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        media_url = _require_media_url(url)
        if isinstance(max_bytes, bool):
            raise SnapchatAdsInputError("max_bytes 必须是整数")
        try:
            normalized_max = int(max_bytes)
        except (TypeError, ValueError) as exc:
            raise SnapchatAdsInputError("max_bytes 必须是整数") from exc
        if normalized_max < 1 or normalized_max > 2 * 1024 * 1024 * 1024:
            raise SnapchatAdsInputError(
                "max_bytes 必须在 1 到 2147483648 之间"
            )
        path = Path(destination).expanduser()
        if path.exists() and not overwrite:
            raise SnapchatAdsInputError("媒体 destination 已存在；使用 overwrite 覆盖")
        if path.exists() and path.is_dir():
            raise SnapchatAdsInputError("媒体 destination 不能是目录")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        digest = sha256()
        byte_count = 0
        request = Request(
            media_url,
            headers={"Accept": "*/*", "User-Agent": self.user_agent},
            method="GET",
        )
        response = self._open(request)
        try:
            final_url = _require_media_url(
                response.geturl() if hasattr(response, "geturl") else media_url
            )
            content_length = _optional_int(response.headers.get("Content-Length"))
            if content_length is not None and content_length > normalized_max:
                raise SnapchatAdsResponseError(
                    "Snapchat 媒体超过 max_bytes",
                    code="media_too_large",
                )
            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(min(1024 * 1024, normalized_max + 1))
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    if byte_count > normalized_max:
                        raise SnapchatAdsResponseError(
                            "Snapchat 媒体超过 max_bytes",
                            code="media_too_large",
                        )
                    handle.write(chunk)
                    digest.update(chunk)
            if path.exists() and not overwrite:
                raise SnapchatAdsInputError(
                    "媒体 destination 在下载期间被创建；使用 overwrite 覆盖"
                )
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            response.close()
        return {
            "kind": "snapchat_media_download",
            "source_url": media_url,
            "final_url": final_url,
            "destination": str(path.resolve()),
            "bytes": byte_count,
            "sha256": digest.hexdigest(),
            "content_type": _text(response.headers.get("Content-Type")).partition(";")[0]
            or None,
        }
