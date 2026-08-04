from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from .errors import (
    MicrosoftAdsInputError,
    MicrosoftAdsResponseError,
    MicrosoftAdsTransportError,
)


BASE_URL = "https://adlibrary.api.bingads.microsoft.com/api/v1"
ADVERTISERS_PATH = "/Advertisers"
ADS_PATH = "/Ads"
LIBRARY_URL = "https://adlibrary.ads.microsoft.com/"
LAST_PROTOCOL_VERIFIED = "2026-08-01"
DEFAULT_USER_AGENT = "reverse-microsoft-ads/1.0"

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_JSON_BYTES = 32 * 1024 * 1024
_MAX_PAGE_SIZE = 24
_MAX_LIMIT = 500
_MAX_PAGES = 100
_ID_RE = re.compile(r"^[1-9]\d{0,19}$")
_COUNTRY_CODE_RE = re.compile(r"^[1-9]\d{0,5}$")


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
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_id(value: Any, *, field: str) -> str:
    normalized = _text(value)
    if not _ID_RE.fullmatch(normalized):
        raise MicrosoftAdsInputError(f"{field} 必须是十进制正整数")
    return normalized


def _validate_text(value: Any, *, field: str, required: bool = False) -> str:
    normalized = _text(value)
    if required and not normalized:
        raise MicrosoftAdsInputError(f"{field} 不能为空")
    if len(normalized) > 300:
        raise MicrosoftAdsInputError(f"{field} 长度最多 300 个字符")
    return normalized


def _validate_date(value: Any, *, field: str) -> str:
    normalized = _text(value)
    if not normalized:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        raise MicrosoftAdsInputError(f"{field} 必须使用 YYYY-MM-DD")
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise MicrosoftAdsInputError(f"{field} 必须使用 YYYY-MM-DD") from exc
    return normalized


def _validate_nonnegative(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise MicrosoftAdsInputError(f"{field} 必须是非负整数")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise MicrosoftAdsInputError(f"{field} 必须是非负整数") from exc
    if normalized < 0:
        raise MicrosoftAdsInputError(f"{field} 必须是非负整数")
    return normalized


def _validate_limit(value: Any, *, maximum: int = _MAX_LIMIT) -> int:
    normalized = _validate_nonnegative(value, field="limit")
    if normalized < 1 or normalized > maximum:
        raise MicrosoftAdsInputError(f"limit 必须在 1 到 {maximum} 之间")
    return normalized


def _validate_page_size(value: Any) -> int:
    normalized = _validate_limit(value, maximum=_MAX_PAGE_SIZE)
    return normalized


def _normalize_country_codes(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    source: list[str] = []
    if isinstance(value, str):
        source.extend(value.split(","))
    else:
        for item in _items(value):
            source.extend(str(item).split(","))
    result: list[str] = []
    for item in source:
        code = item.strip()
        if not _COUNTRY_CODE_RE.fullmatch(code):
            raise MicrosoftAdsInputError(
                "country_code 必须使用 Microsoft Ad Library 的数字国家代码"
            )
        if code not in result:
            result.append(code)
    return result


def _json_string(value: Any) -> Any:
    source = _text(value)
    if not source:
        return None
    try:
        return json.loads(source)
    except json.JSONDecodeError:
        return source


def _normalize_advertiser(raw: Mapping[str, Any]) -> dict[str, Any]:
    advertiser_id = _text(raw.get("AdvertiserId"))
    return {
        "advertiser_id": advertiser_id or None,
        "name": _text(raw.get("AdvertiserName")) or None,
        "country": _text(raw.get("AdvertiserCountry")) or None,
        "is_verified": raw.get("IsVerified"),
        "source_url": (
            f"{BASE_URL}{ADVERTISERS_PATH}/{advertiser_id}"
            if advertiser_id
            else None
        ),
    }


def _normalize_ad(
    raw: Mapping[str, Any],
    *,
    include_raw: bool = False,
) -> dict[str, Any]:
    ad_id = _text(raw.get("AdId"))
    advertiser_id = _text(raw.get("AdvertiserId"))
    result: dict[str, Any] = {
        "ad_id": ad_id or None,
        "advertiser": {
            "advertiser_id": advertiser_id or None,
            "name": _text(raw.get("AdvertiserName")) or None,
            "source_url": (
                f"{BASE_URL}{ADVERTISERS_PATH}/{advertiser_id}"
                if advertiser_id
                else None
            ),
        },
        "copy": {
            "title": _text(raw.get("Title")) or None,
            "description": _text(raw.get("Description")) or None,
        },
        "display_url": _text(raw.get("DisplayUrl")) or None,
        "destination_url": _text(raw.get("DestinationUrl")) or None,
        "asset_resource_url": _text(raw.get("AssetJson")) or None,
        "source_url": f"{BASE_URL}{ADS_PATH}/{ad_id}" if ad_id else None,
        "library_url": LIBRARY_URL,
    }
    details = raw.get("AdDetails")
    if isinstance(details, Mapping):
        result["details"] = _normalize_ad_details(details)
    if include_raw:
        result["raw"] = dict(raw)
    return result


def _normalize_ad_details(raw: Mapping[str, Any]) -> dict[str, Any]:
    country_shares = []
    for value in _items(raw.get("ImpressionsByCountry")):
        item = _mapping(value)
        country = _text(item.get("Country"))
        share = _text(item.get("ImpressionShare"))
        if country or share:
            country_shares.append(
                {
                    "country": country or None,
                    "impression_share": share or None,
                }
            )
    targets = []
    for value in _items(raw.get("Targets")):
        item = _mapping(value)
        target_type = _text(item.get("TargetType"))
        if not target_type and "UsedForExclusion" not in item:
            continue
        targets.append(
            {
                "type": target_type or None,
                "used_for_exclusion": item.get("UsedForExclusion"),
            }
        )
    restriction = raw.get("RestrictionReason")
    if restriction in (None, "", [], {}):
        restriction = raw.get("RejectionJson")
    return {
        "paid_for_by": _text(raw.get("PaidForByName")) or None,
        "start_date": _text(raw.get("StartDate")) or None,
        "end_date": _text(raw.get("EndDate")) or None,
        "total_impressions_range": _text(raw.get("TotalImpressionsRange")) or None,
        "impressions_by_country": country_shares,
        "targets": targets,
        "restriction": _json_string(restriction),
    }


class MicrosoftAdsClient:
    """Microsoft Advertising 官方公开 Ad Library API 客户端。"""

    def __init__(
        self,
        *,
        timeout: float = 30,
        retries: int = 2,
        request_interval: float = 1,
        proxy: str = "",
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Any = None,
    ) -> None:
        if timeout <= 0:
            raise MicrosoftAdsInputError("timeout 必须大于 0")
        if retries < 0:
            raise MicrosoftAdsInputError("retries 必须是非负整数")
        if request_interval < 0:
            raise MicrosoftAdsInputError("request_interval 必须是非负数")
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.request_interval = float(request_interval)
        self.user_agent = user_agent
        self._last_request_at = 0.0
        self._opener = opener or build_opener(
            ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
        )

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        delay = self.request_interval - elapsed
        if delay > 0:
            time.sleep(delay)

    def _open(self, request: Request) -> Any:
        for attempt in range(self.retries + 1):
            self._wait()
            try:
                response = self._opener.open(request, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                return response
            except HTTPError as exc:
                self._last_request_at = time.monotonic()
                body = exc.read(_MAX_JSON_BYTES + 1)
                message = ""
                try:
                    payload = json.loads(body.decode("utf-8"))
                    error = _mapping(_mapping(payload).get("error"))
                    message = _text(error.get("message"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
                if exc.code in _RETRYABLE_STATUS and attempt < self.retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                code = "rate_limited" if exc.code == 429 else "http_error"
                raise MicrosoftAdsTransportError(
                    message or f"Microsoft Ad Library 返回 HTTP {exc.code}",
                    code=code,
                ) from exc
            except (TimeoutError, URLError, OSError) as exc:
                self._last_request_at = time.monotonic()
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                raise MicrosoftAdsTransportError(
                    f"Microsoft Ad Library 请求失败：{exc}"
                ) from exc
        raise AssertionError("重试循环未返回")

    def _request_json(
        self,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        encoded = urlencode(
            {
                key: value
                for key, value in (query or {}).items()
                if value not in (None, "")
            }
        )
        url = f"{BASE_URL}{path}"
        if encoded:
            url = f"{url}?{encoded}"
        response = self._open(
            Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.user_agent,
                },
                method="GET",
            )
        )
        try:
            content_length = _optional_int(response.headers.get("Content-Length"))
            if content_length is not None and content_length > _MAX_JSON_BYTES:
                raise MicrosoftAdsResponseError(
                    "Microsoft Ad Library JSON 响应超过大小上限",
                    code="response_too_large",
                )
            source = response.read(_MAX_JSON_BYTES + 1)
            if len(source) > _MAX_JSON_BYTES:
                raise MicrosoftAdsResponseError(
                    "Microsoft Ad Library JSON 响应超过大小上限",
                    code="response_too_large",
                )
        finally:
            response.close()
        try:
            payload = json.loads(source.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MicrosoftAdsResponseError(
                "Microsoft Ad Library 返回了无效 JSON",
                code="invalid_json",
            ) from exc
        if not isinstance(payload, Mapping):
            raise MicrosoftAdsResponseError("Microsoft Ad Library JSON 根节点不是对象")
        error = payload.get("error")
        if isinstance(error, Mapping):
            raise MicrosoftAdsResponseError(
                _text(error.get("message")) or "Microsoft Ad Library 请求未成功",
                code="upstream_request_failed",
            )
        return payload

    def _search(
        self,
        path: str,
        *,
        query: Mapping[str, Any],
        offset: int,
        limit: int,
        page_size: int,
        normalizer: Any,
        identity_field: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int | None]:
        current_offset = offset
        pages_fetched = 0
        source_count: int | None = None
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        stop_reason = "source_exhausted"

        while pages_fetched < _MAX_PAGES and len(items) < limit:
            size = min(page_size, limit - len(items))
            payload = self._request_json(
                path,
                query={**query, "$top": size, "$skip": current_offset},
            )
            pages_fetched += 1
            count = _optional_int(payload.get("@odata.count"))
            if count is not None:
                source_count = count
            raw_items = [
                _mapping(value)
                for value in _items(payload.get("value"))
                if isinstance(value, Mapping)
            ]
            for raw in raw_items:
                identity = _text(raw.get(identity_field))
                if identity and identity in seen:
                    continue
                if identity:
                    seen.add(identity)
                items.append(normalizer(raw))
                if len(items) >= limit:
                    break
            current_offset += len(raw_items)
            if len(items) >= limit:
                stop_reason = "limit_reached"
                break
            if not raw_items or len(raw_items) < size:
                stop_reason = "source_exhausted"
                break
            if source_count is not None and current_offset >= source_count:
                stop_reason = "source_exhausted"
                break
        else:
            if pages_fetched >= _MAX_PAGES:
                stop_reason = "page_cap_reached"

        has_next_page = bool(
            stop_reason == "limit_reached"
            and (source_count is None or current_offset < source_count)
        )
        return (
            items,
            {
                "input_offset": offset,
                "next_offset": current_offset if has_next_page else None,
                "has_next_page": has_next_page,
                "pages_fetched": pages_fetched,
                "stop_reason": stop_reason,
            },
            source_count,
        )

    def search_advertisers(
        self,
        query: str,
        *,
        offset: int = 0,
        limit: int = 24,
        page_size: int = 24,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_query = _validate_text(query, field="query", required=True)
        normalized_offset = _validate_nonnegative(offset, field="offset")
        normalized_limit = _validate_limit(limit)
        normalized_page_size = _validate_page_size(page_size)
        items, pagination, source_count = self._search(
            ADVERTISERS_PATH,
            query={"searchText": normalized_query},
            offset=normalized_offset,
            limit=normalized_limit,
            page_size=normalized_page_size,
            normalizer=lambda raw: {
                **_normalize_advertiser(raw),
                **({"raw": dict(raw)} if include_raw else {}),
            },
            identity_field="AdvertiserId",
        )
        return {
            "kind": "microsoft_advertiser_search",
            "access": "anonymous_official_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "source_url": f"{BASE_URL}{ADVERTISERS_PATH}",
            "query": {"text": normalized_query},
            "source_count": source_count,
            "count": len(items),
            "items": items,
            "pagination": pagination,
        }

    def get_advertiser(
        self,
        advertiser_id: Any,
        *,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_id = _validate_id(advertiser_id, field="advertiser_id")
        payload = self._request_json(f"{ADVERTISERS_PATH}/{normalized_id}")
        item = _normalize_advertiser(payload)
        if include_raw:
            item["raw"] = dict(payload)
        return {
            "kind": "microsoft_advertiser",
            "access": "anonymous_official_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "item": item,
        }

    def search_ads(
        self,
        query: str = "",
        *,
        advertiser_id: Any = "",
        start_date: Any = "",
        end_date: Any = "",
        country_codes: Any = None,
        offset: int = 0,
        limit: int = 48,
        page_size: int = 24,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_query = _validate_text(query, field="query")
        normalized_advertiser = (
            _validate_id(advertiser_id, field="advertiser_id")
            if _text(advertiser_id)
            else ""
        )
        if not normalized_query and not normalized_advertiser:
            raise MicrosoftAdsInputError("query 与 advertiser_id 至少提供一个")
        normalized_start = _validate_date(start_date, field="start_date")
        normalized_end = _validate_date(end_date, field="end_date")
        if normalized_start and normalized_end and normalized_start > normalized_end:
            raise MicrosoftAdsInputError("start_date 必须早于或等于 end_date")
        countries = _normalize_country_codes(country_codes)
        normalized_offset = _validate_nonnegative(offset, field="offset")
        normalized_limit = _validate_limit(limit)
        normalized_page_size = _validate_page_size(page_size)
        query_params: dict[str, Any] = {
            "searchText": normalized_query,
            "advertiserId": normalized_advertiser,
            "startDate": normalized_start,
            "endDate": normalized_end,
            "countryCodes": ",".join(countries),
        }
        items, pagination, source_count = self._search(
            ADS_PATH,
            query=query_params,
            offset=normalized_offset,
            limit=normalized_limit,
            page_size=normalized_page_size,
            normalizer=lambda raw: _normalize_ad(raw, include_raw=include_raw),
            identity_field="AdId",
        )
        for rank, item in enumerate(items, start=1):
            item["result_rank"] = rank
        return {
            "kind": "microsoft_ads_search",
            "access": "anonymous_official_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "source_url": f"{BASE_URL}{ADS_PATH}",
            "coverage": "ads_with_eligible_impressions_in_eu_or_eea",
            "query": {
                "text": normalized_query or None,
                "advertiser_id": normalized_advertiser or None,
                "start_date": normalized_start or None,
                "end_date": normalized_end or None,
                "country_codes": countries,
            },
            "source_count": source_count,
            "count": len(items),
            "items": items,
            "pagination": pagination,
            "metric_scope": {
                "search_result_impressions": "not_included; call get-ad",
                "clicks": "not_published",
                "ctr": "not_published",
                "spend": "not_published",
                "ranking_rule": "保留 Microsoft 上游顺序，不推导广告效果",
            },
        }

    def get_ad(
        self,
        ad_id: Any,
        *,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_id = _validate_id(ad_id, field="ad_id")
        payload = self._request_json(
            f"{ADS_PATH}/{normalized_id}",
            query={"expand": "AdDetails(expand=ImpressionsByCountry,Targets)"},
        )
        item = _normalize_ad(payload, include_raw=include_raw)
        return {
            "kind": "microsoft_ad",
            "access": "anonymous_official_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "coverage": "ads_with_eligible_impressions_in_eu_or_eea",
            "item": item,
            "metric_scope": {
                "total_impressions_range": "published_official_eea_bucket",
                "impressions_by_country": "published_percentage_share_not_count",
                "targets": "aggregate_over_eligible_ad_run",
                "clicks": "not_published",
                "ctr": "not_published",
                "spend": "not_published",
            },
        }
