from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import mimetypes
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from .errors import (
    PinterestAdsInputError,
    PinterestAdsResponseError,
    PinterestAdsTransportError,
)


PINTEREST_BASE_URL = "https://www.pinterest.com"
PINTEREST_API_BASE_URL = "https://api.pinterest.com"
PINTEREST_ADS_BASE_URL = "https://ads.pinterest.com"
VISUAL_SEARCH_PATH = "/v3/visual_search/extension/image/"
ADS_RESOURCE_PATH = "/resource/ApiResource/get/"
SEARCH_RESOURCE_PATH = "/resource/BaseSearchResource/get/"
PIN_RESOURCE_PATH = "/resource/PinResource/get/"
ADS_LIBRARY_PATH = "/ads/v4/ads_repository/ad_library"
ADS_DETAIL_PATH = "/ads/v4/ads_repository/ad_library/{ad_id}"
LAST_PROTOCOL_VERIFIED = "2026-08-01"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
)

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_PIN_ID_RE = re.compile(r"^[0-9]{5,24}$")
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9_+/=|.-]{1,32768}$")
_FILTER_RE = re.compile(r"^[A-Za-z0-9_ +&'()./-]{1,100}$")
_ADS_COUNTRIES = {
    "AR",
    "AT",
    "AU",
    "BE",
    "BR",
    "CA",
    "CH",
    "CL",
    "CO",
    "DE",
    "DK",
    "ES",
    "FI",
    "FR",
    "GB",
    "IE",
    "IT",
    "JP",
    "LU",
    "MX",
    "NL",
    "NO",
    "NZ",
    "PT",
    "SE",
    "US",
}
_MEDIA_HOST_SUFFIXES = (".pinimg.com",)
_MEDIA_HOSTS = {
    "pinimg.com",
    "media.pinterest.com",
    "s3.amazonaws.com",
}
_MAX_JSON_BYTES = 64 * 1024 * 1024
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_PAGES = 20
_END_BOOKMARKS = {"", "-end-", "null"}


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


def _validate_limit(value: Any, *, maximum: int = 500, field: str = "limit") -> int:
    if isinstance(value, bool):
        raise PinterestAdsInputError(f"{field} 必须是整数")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise PinterestAdsInputError(f"{field} 必须是整数") from exc
    if normalized < 1 or normalized > maximum:
        raise PinterestAdsInputError(f"{field} 必须在 1 到 {maximum} 之间")
    return normalized


def _validate_opaque(value: Any, *, field: str) -> str:
    source = _text(value)
    if not source:
        return ""
    if not _OPAQUE_RE.fullmatch(source):
        raise PinterestAdsInputError(f"{field} 格式无效")
    return source


def _validate_id(value: Any, *, field: str) -> str:
    source = _text(value)
    if not _PIN_ID_RE.fullmatch(source):
        raise PinterestAdsInputError(f"{field} 必须是 Pinterest 数字 ID")
    return source


def _normalize_date(value: Any, *, field: str) -> str:
    source = _text(value)
    if not source:
        return ""
    try:
        return date.fromisoformat(source).isoformat()
    except ValueError as exc:
        raise PinterestAdsInputError(f"{field} 必须使用 YYYY-MM-DD") from exc


def _date_range(start_date: Any, end_date: Any) -> tuple[str, str]:
    end = _normalize_date(end_date, field="end_date")
    start = _normalize_date(start_date, field="start_date")
    if not end:
        end = datetime.now(timezone.utc).date().isoformat()
    if not start:
        start = (date.fromisoformat(end) - timedelta(days=29)).isoformat()
    start_value = date.fromisoformat(start)
    end_value = date.fromisoformat(end)
    if start_value > end_value:
        raise PinterestAdsInputError("start_date 不得晚于 end_date")
    if (end_value - start_value).days > 30:
        raise PinterestAdsInputError("Pinterest Ads Repository 日期跨度最多为 30 天")
    return start, end


def _normalize_filter(value: Any, *, field: str, maximum: int = 100) -> str:
    source = _text(value)
    if not source:
        return ""
    if len(source) > maximum or not _FILTER_RE.fullmatch(source):
        raise PinterestAdsInputError(f"{field} 格式无效")
    return source


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
    if host == "s3.amazonaws.com":
        return source if parsed.path.startswith("/media.pinterest.com/") else ""
    if host in _MEDIA_HOSTS or any(host.endswith(suffix) for suffix in _MEDIA_HOST_SUFFIXES):
        return source
    return ""


def _require_media_url(value: Any) -> str:
    source = _valid_media_url(value)
    if not source:
        raise PinterestAdsInputError(
            "媒体 URL 必须使用 Pinterest 公开响应中的 HTTPS CDN 地址"
        )
    return source


def _parse_created_at(value: Any) -> float:
    source = _text(value)
    if not source:
        return 0
    try:
        return parsedate_to_datetime(source).timestamp()
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(source.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return 0


def _number_token(value: str) -> int | None:
    source = value.strip().upper().replace(",", "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMB]?)", source)
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
        match.group(2)
    ]
    return int(float(match.group(1)) * multiplier)


def _range_bounds(value: Any) -> tuple[int | None, int | None]:
    source = _text(value)
    if not source:
        return None, None
    numbers = [_number_token(part) for part in re.split(r"\s*(?:-|–|—|to)\s*", source)]
    normalized = [item for item in numbers if item is not None]
    if len(normalized) >= 2:
        return normalized[0], normalized[1]
    if len(normalized) == 1:
        return normalized[0], normalized[0]
    return None, None


def _image_variants(value: Any) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, item_value in _mapping(value).items():
        item = _mapping(item_value)
        url = _valid_media_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        variants.append(
            {
                "variant": _text(name),
                "url": url,
                "width": _optional_int(item.get("width")),
                "height": _optional_int(item.get("height")),
            }
        )
    variants.sort(
        key=lambda item: (
            (item.get("width") or 0) * (item.get("height") or 0),
            item.get("variant") == "orig",
        ),
        reverse=True,
    )
    return variants


def _video_variants(value: Any) -> list[dict[str, Any]]:
    video = _mapping(value)
    source = _mapping(video.get("video_list")) or video
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, item_value in source.items():
        item = _mapping(item_value)
        url = _valid_media_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        variants.append(
            {
                "variant": _text(name),
                "transport": "hls" if urlsplit(url).path.endswith(".m3u8") else "file",
                "url": url,
                "width": _optional_int(item.get("width")),
                "height": _optional_int(item.get("height")),
                "duration_ms": _optional_int(item.get("duration")),
                "thumbnail_url": _valid_media_url(item.get("thumbnail")) or None,
            }
        )
    variants.sort(
        key=lambda item: (
            item.get("transport") == "file",
            (item.get("width") or 0) * (item.get("height") or 0),
        ),
        reverse=True,
    )
    return variants


def _normalize_person(value: Any) -> dict[str, Any] | None:
    raw = _mapping(value)
    if not raw:
        return None
    user_id = _text(raw.get("id"))
    username = _text(raw.get("username"))
    return {
        "id": user_id or None,
        "username": username or None,
        "name": _text(raw.get("full_name")) or _text(raw.get("first_name")) or None,
        "follower_count": _optional_int(raw.get("follower_count")),
        "is_verified_merchant": raw.get("is_verified_merchant"),
        "profile_url": f"{PINTEREST_BASE_URL}/{quote(username)}/" if username else None,
    }


def _normalize_pin(raw: Mapping[str, Any], *, include_raw: bool) -> dict[str, Any]:
    pin_id = _text(raw.get("id")) or _text(raw.get("cacheable_id"))
    images = _image_variants(raw.get("images"))
    if not images:
        seen_images: set[str] = set()
        for name in ("image_large_url", "image_medium_url", "image_square_url"):
            url = _valid_media_url(raw.get(name))
            if not url or url in seen_images:
                continue
            seen_images.add(url)
            images.append({"variant": name, "url": url, "width": None, "height": None})
    videos = _video_variants(raw.get("videos"))
    pinner = _normalize_person(raw.get("pinner") or raw.get("closeup_attribution"))
    board = _mapping(raw.get("board"))
    board_url = _text(board.get("url"))
    aggregated = _mapping(_mapping(raw.get("aggregated_pin_data")).get("aggregated_stats"))
    repins = _optional_int(raw.get("repin_count"))
    if repins is None:
        repins = _optional_int(aggregated.get("saves"))
    reactions: dict[str, int] = {}
    for key, value in _mapping(raw.get("reaction_counts")).items():
        count = _optional_int(value)
        if count is not None:
            reactions[_text(key)] = count
    pin_join = _mapping(raw.get("pin_join"))
    visual_annotations = [
        _text(item)
        for item in _items(pin_join.get("visual_annotation"))
        if _text(item)
    ]
    result: dict[str, Any] = {
        "id": pin_id or None,
        "source_url": f"{PINTEREST_BASE_URL}/pin/{pin_id}/" if pin_id else None,
        "title": (
            _text(raw.get("title"))
            or _text(raw.get("grid_title"))
            or _text(raw.get("closeup_unified_title"))
            or None
        ),
        "description": (
            _text(raw.get("description"))
            or _text(raw.get("closeup_unified_description"))
            or None
        ),
        "created_at": _text(raw.get("created_at")) or None,
        "landing_url": _text(raw.get("link")) or _text(raw.get("tracked_link")) or None,
        "domain": _text(raw.get("domain")) or None,
        "pinner": pinner,
        "board": (
            {
                "id": _text(board.get("id")) or None,
                "name": _text(board.get("name")) or None,
                "url": f"{PINTEREST_BASE_URL}{board_url}" if board_url.startswith("/") else None,
            }
            if board
            else None
        ),
        "metrics": {
            "saves": repins,
            "comments": _optional_int(raw.get("comment_count")),
            "shares": _optional_int(raw.get("share_count")),
            "reactions": reactions,
        },
        "media": {
            "is_video": bool(videos) or bool(raw.get("is_video")),
            "images": images,
            "videos": videos,
            "best_image_url": images[0]["url"] if images else None,
            "best_video_url": videos[0]["url"] if videos else None,
        },
        "visual_annotations": visual_annotations,
        "is_promoted": raw.get("is_promoted"),
    }
    if include_raw:
        result["raw"] = dict(raw)
    return result


def _normalize_visual_pin(
    raw: Mapping[str, Any], *, include_raw: bool
) -> dict[str, Any]:
    result = _normalize_pin(raw, include_raw=include_raw)
    result["price"] = {
        "value": raw.get("price_value"),
        "currency": _text(raw.get("price_currency")) or None,
    }
    result["visual_match"] = {
        "is_uploaded": raw.get("is_uploaded"),
        "is_repin": raw.get("is_repin"),
        "is_downstream_promotion": raw.get("is_downstream_promotion"),
    }
    return result


def _urls_from_value(value: Any, *, maximum: int = 100) -> list[str]:
    output: list[str] = []
    stack = [value]
    while stack and len(output) < maximum:
        current = stack.pop()
        if isinstance(current, Mapping):
            stack.extend(current.values())
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            stack.extend(current)
        else:
            url = _valid_media_url(current)
            if url and url not in output:
                output.append(url)
    return output


def _normalize_ad(
    ad_id: str,
    raw: Mapping[str, Any],
    *,
    include_raw: bool,
) -> dict[str, Any]:
    pin_data = _mapping(raw.get("pin_data"))
    advertiser_names = [
        _text(item) for item in _items(raw.get("advertiser_names")) if _text(item)
    ]
    if not advertiser_names:
        advertiser = _text(raw.get("advertiser_name"))
        if advertiser:
            advertiser_names.append(advertiser)
    media: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = (
        (raw.get("image_link"), "image", "ad_image"),
        (pin_data.get("image_link"), "image", "pin_image"),
        (pin_data.get("video_link"), "video", "pin_video"),
        (raw.get("image_url"), "image", "third_party_image"),
    )
    for value, media_type, role in candidates:
        url = _valid_media_url(value)
        if not url or url in seen:
            continue
        seen.add(url)
        media.append({"role": role, "type": media_type, "url": url})
    for url in _urls_from_value(raw.get("dynamic_images")):
        if url not in seen:
            seen.add(url)
            media.append({"role": "dynamic_image", "type": "image", "url": url})

    eu_range = _text(raw.get("user_count_eu"))
    eu_lower, eu_upper = _range_bounds(eu_range)
    country_ranges: dict[str, dict[str, Any]] = {}
    for country, value in _mapping(raw.get("user_count_by_country")).items():
        label = _text(value)
        lower, upper = _range_bounds(label)
        country_ranges[_text(country)] = {
            "range": label or None,
            "lower_bound": lower,
            "upper_bound": upper,
        }
    title = (
        _text(pin_data.get("title"))
        or _text(raw.get("ad_title"))
        or None
    )
    description = (
        _text(pin_data.get("details"))
        or _text(raw.get("ad_description"))
        or None
    )
    result: dict[str, Any] = {
        "id": ad_id,
        "source_url": f"{PINTEREST_ADS_BASE_URL}/ads-repository/{ad_id}/",
        "pin_source_url": (
            f"{PINTEREST_BASE_URL}/pin/{ad_id}/" if _PIN_ID_RE.fullmatch(ad_id) else None
        ),
        "advertiser_names": advertiser_names,
        "start_date": _text(raw.get("start_date")) or None,
        "end_date": _text(raw.get("end_date")) or None,
        "creative": {
            "title": title,
            "description": description,
            "content_creator_name": _text(pin_data.get("content_creator_name")) or None,
            "landing_url": _text(raw.get("external_atc_url")) or None,
            "media": media,
            "story_pin_page_blocks": _items(pin_data.get("story_pin_page_blocks")),
        },
        "audience_range": {
            "eu": {
                "range": eu_range or None,
                "lower_bound": eu_lower,
                "upper_bound": eu_upper,
            },
            "by_country": country_ranges,
        },
        "targeting": {
            "age_buckets": _items(raw.get("age_buckets")),
            "genders": _items(raw.get("genders")),
            "countries": _items(raw.get("countries")),
            "regions": _items(raw.get("regions")),
            "metros": _items(raw.get("metros")),
            "postal_codes": _items(raw.get("postal_codes")),
            "interests": _items(raw.get("interests")),
            "audience_types": _items(raw.get("pinner_list_types")),
            "devices": _items(raw.get("devices")),
            "internet_service_providers": _items(
                raw.get("internet_service_providers")
            ),
            "has_excluded_locations": raw.get("has_excluded_locations"),
            "keywords_used": raw.get("keywords_used"),
            "negative_keywords_used": raw.get("negative_keywords_used"),
        },
        "transparency": {
            "content_commercial": raw.get("content_commercial"),
            "is_local_inventory": raw.get("is_local_inventory"),
            "review_status": raw.get("review_status"),
            "statement_of_reasons": raw.get("statement_of_reasons"),
            "violation_source": raw.get("violation_source"),
            "violation_decision_means": raw.get("violation_decision_means"),
            "is_removed_creative": raw.get("is_removed_creative"),
        },
    }
    if include_raw:
        result["raw"] = dict(raw)
    return result


def _extract_ad_rows(data: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    rows: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for field, id_field in (
        ("pin_ids_with_metadata", "pin_id"),
        ("ad_ids_with_metadata", "ad_id"),
    ):
        for value in _items(data.get(field)):
            item = _mapping(value)
            ad_id = _text(item.get(id_field))
            details = _mapping(item.get("ad_details")) or item
            if ad_id and ad_id not in seen:
                seen.add(ad_id)
                rows.append((ad_id, details))
    for field in ("pin_ids", "ad_ids"):
        for value in _items(data.get(field)):
            ad_id = _text(value)
            if ad_id and ad_id not in seen:
                seen.add(ad_id)
                rows.append((ad_id, {}))
    return rows


def _normalize_guides(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in _items(data.get("rankedGuides")):
        item = _mapping(value)
        query = _text(item.get("term"))
        if not query or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        output.append(
            {
                "query": query,
                "label": _text(item.get("display")) or None,
                "score": item.get("score"),
                "source": "ranked_guide",
            }
        )
    for value in _items(data.get("oneBarModules")):
        item = _mapping(value)
        action = _mapping(item.get("action"))
        auxiliary = _mapping(item.get("aux_data"))
        query = _text(action.get("search_query")) or _text(auxiliary.get("query"))
        if not query or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        display = _mapping(item.get("display"))
        output.append(
            {
                "query": query,
                "label": _text(display.get("display_text")) or None,
                "score": None,
                "source": "one_bar_module",
            }
        )
    return output


def _collect_result_pins(results: Any) -> list[Mapping[str, Any]]:
    pins: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    stack = list(reversed(_items(results)))
    while stack:
        value = stack.pop()
        item = _mapping(value)
        if not item:
            continue
        pin_id = _text(item.get("id"))
        if _text(item.get("type")).casefold() == "pin" and pin_id:
            if pin_id not in seen:
                seen.add(pin_id)
                pins.append(item)
            continue
        for field in ("objects", "results", "items"):
            stack.extend(reversed(_items(item.get(field))))
    return pins


class PinterestAdsClient:
    """使用 Python HTTP 直连 Pinterest 匿名公开素材接口。"""

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
            raise PinterestAdsInputError("timeout 必须大于 0")
        if retries < 0 or retries > 10:
            raise PinterestAdsInputError("retries 必须在 0 到 10 之间")
        if request_interval < 0 or request_interval > 60:
            raise PinterestAdsInputError("request_interval 必须在 0 到 60 秒之间")
        handlers = []
        if proxy:
            parsed = urlsplit(proxy)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise PinterestAdsInputError("proxy 必须是有效的 http 或 https URL")
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
                status = int(exc.code)
                if status in _RETRYABLE_STATUS and attempt < self.retries:
                    self._sleep(min(5.0, 0.5 * (2**attempt)))
                    continue
                code = {
                    400: "upstream_rejected_input",
                    401: "anonymous_access_denied",
                    403: "anonymous_access_denied",
                    404: "not_found",
                    429: "rate_limited",
                }.get(
                    status,
                    "upstream_unavailable" if status >= 500 else "upstream_http_error",
                )
                raise PinterestAdsTransportError(
                    f"Pinterest HTTP {status}", code=code
                ) from exc
            except (OSError, TimeoutError, URLError) as exc:
                if attempt < self.retries:
                    self._sleep(min(5.0, 0.5 * (2**attempt)))
                    continue
                raise PinterestAdsTransportError(
                    f"Pinterest 请求失败: {exc}", code="network_error"
                ) from exc
        raise AssertionError("重试循环未返回")

    @staticmethod
    def _read_json(response: Any) -> Mapping[str, Any]:
        try:
            content_length = _optional_int(response.headers.get("Content-Length"))
            if content_length is not None and content_length > _MAX_JSON_BYTES:
                raise PinterestAdsResponseError(
                    "Pinterest JSON 响应超过大小上限", code="response_too_large"
                )
            source = response.read(_MAX_JSON_BYTES + 1)
            if len(source) > _MAX_JSON_BYTES:
                raise PinterestAdsResponseError(
                    "Pinterest JSON 响应超过大小上限", code="response_too_large"
                )
        finally:
            response.close()
        try:
            decoded = source.decode("utf-8").lstrip()
            if decoded.startswith(")]}'"):
                decoded = decoded.partition("\n")[2]
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PinterestAdsResponseError(
                "Pinterest 返回了无效 JSON", code="invalid_json"
            ) from exc
        if not isinstance(payload, Mapping):
            raise PinterestAdsResponseError("Pinterest JSON 根节点不是对象")
        return payload

    def _request_json(self, request: Request) -> Mapping[str, Any]:
        return self._read_json(self._open(request))

    def _resource(
        self,
        *,
        base_url: str,
        resource_path: str,
        source_url: str,
        options: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], str]:
        if (base_url, resource_path) not in {
            (PINTEREST_ADS_BASE_URL, ADS_RESOURCE_PATH),
            (PINTEREST_BASE_URL, SEARCH_RESOURCE_PATH),
            (PINTEREST_BASE_URL, PIN_RESOURCE_PATH),
        }:
            raise PinterestAdsInputError("Pinterest resource 路径不在白名单中")
        data = json.dumps(
            {"options": dict(options), "context": {}},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        query = urlencode(
            {"source_url": source_url, "data": data, "_": int(time.time() * 1000)}
        )
        url = f"{base_url}{resource_path}?{query}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Referer": f"{base_url}/",
                "User-Agent": self.user_agent,
                "X-Pinterest-PWS-Handler": "www/index.js",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="GET",
        )
        payload = self._request_json(request)
        response = payload.get("resource_response")
        if not isinstance(response, Mapping):
            raise PinterestAdsResponseError(
                "Pinterest resource 响应缺少 resource_response",
                code="response_drift",
            )
        status = _text(response.get("status")).casefold()
        code = _optional_int(response.get("code"))
        if status not in {"", "success"} or code not in {None, 0}:
            message = _text(response.get("message")) or "Pinterest resource 请求未成功"
            raise PinterestAdsResponseError(message, code="upstream_request_failed")
        data_value = response.get("data")
        if not isinstance(data_value, Mapping):
            raise PinterestAdsResponseError(
                "Pinterest resource 响应 data 结构已变化", code="response_drift"
            )
        return response, url

    @staticmethod
    def _multipart_body(
        image: bytes,
        filename: str,
        content_type: str,
        fields: Mapping[str, Any],
    ) -> tuple[bytes, str]:
        boundary = f"----reversePinterest{uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                (
                    f"--{boundary}\r\n".encode("ascii"),
                    (
                        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    ).encode("ascii"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                )
            )
        safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.extend(
            (
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="image"; filename="{safe_name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
                image,
                b"\r\n",
                f"--{boundary}--\r\n".encode("ascii"),
            )
        )
        return b"".join(chunks), boundary

    def _visual_page(
        self,
        *,
        image: bytes,
        filename: str,
        content_type: str,
        page_size: int,
        crop: tuple[float, float, float, float],
        bookmark: str,
        search_identifier: str,
    ) -> Mapping[str, Any]:
        x, y, width, height = crop
        fields: dict[str, Any] = {
            "page_size": page_size,
            "camera_type": 0,
            "search_type": 0,
            "source_type": 0,
            "crop_source": 5,
            "x": x,
            "y": y,
            "w": width,
            "h": height,
        }
        if bookmark:
            fields["bookmark"] = bookmark
        if search_identifier:
            fields["search_identifier"] = search_identifier
        body, boundary = self._multipart_body(image, filename, content_type, fields)
        request = Request(
            f"{PINTEREST_API_BASE_URL}{VISUAL_SEARCH_PATH}",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": self.user_agent,
            },
            method="PUT",
        )
        payload = self._request_json(request)
        status = _text(payload.get("status")).casefold()
        code = _optional_int(payload.get("code"))
        if status != "success" or code not in {None, 0}:
            message = _text(payload.get("message")) or "Pinterest Lens 请求未成功"
            raise PinterestAdsResponseError(message, code="upstream_request_failed")
        if not isinstance(payload.get("data"), list):
            raise PinterestAdsResponseError(
                "Pinterest Lens 响应 data 结构已变化", code="response_drift"
            )
        return payload

    def visual_search(
        self,
        image: str | Path,
        *,
        x: float = 0,
        y: float = 0,
        width: float = 1,
        height: float = 1,
        bookmark: str = "",
        search_identifier: str = "",
        page_size: int = 50,
        limit: int = 50,
        sort_by: str = "repins",
        max_image_bytes: int = _MAX_IMAGE_BYTES,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        path = Path(image).expanduser()
        if not path.is_file():
            raise PinterestAdsInputError("image 必须是存在的本机图片文件")
        normalized_max = _validate_limit(
            max_image_bytes, maximum=100 * 1024 * 1024, field="max_image_bytes"
        )
        size = path.stat().st_size
        if size < 1 or size > normalized_max:
            raise PinterestAdsInputError("image 为空或超过 max_image_bytes")
        try:
            crop = tuple(float(value) for value in (x, y, width, height))
        except (TypeError, ValueError) as exc:
            raise PinterestAdsInputError("裁剪坐标必须是 0 到 1 的数字") from exc
        crop_x, crop_y, crop_width, crop_height = crop
        if (
            crop_x < 0
            or crop_y < 0
            or crop_width <= 0
            or crop_height <= 0
            or crop_x + crop_width > 1
            or crop_y + crop_height > 1
        ):
            raise PinterestAdsInputError("裁剪区域必须完整位于 0 到 1 的图片坐标内")
        normalized_page_size = _validate_limit(page_size, maximum=100, field="page_size")
        normalized_limit = _validate_limit(limit)
        current_bookmark = _validate_opaque(bookmark, field="bookmark")
        current_identifier = _validate_opaque(
            search_identifier, field="search_identifier"
        )
        if current_bookmark and not current_identifier:
            raise PinterestAdsInputError("从 bookmark 续页时必须同时提供 search_identifier")
        if sort_by not in {"repins", "recent", "upstream"}:
            raise PinterestAdsInputError("sort_by 必须是 repins、recent 或 upstream")
        image_bytes = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        seen_ids: set[str] = set()
        seen_bookmarks = {current_bookmark} if current_bookmark else set()
        items: list[dict[str, Any]] = []
        pages = 0
        next_bookmark = current_bookmark
        source_image_url = ""
        annotations: list[Any] = []
        stop_reason = "source_exhausted"

        while pages < _MAX_PAGES:
            payload = self._visual_page(
                image=image_bytes,
                filename=path.name,
                content_type=content_type,
                page_size=min(normalized_page_size, max(1, normalized_limit - len(items))),
                crop=(crop_x, crop_y, crop_width, crop_height),
                bookmark=current_bookmark,
                search_identifier=current_identifier,
            )
            pages += 1
            current_identifier = _text(payload.get("search_identifier")) or current_identifier
            source_image_url = _valid_media_url(payload.get("url")) or source_image_url
            if not annotations:
                annotations = _items(payload.get("annotations"))
            for rank, raw_value in enumerate(_items(payload.get("data")), 1):
                raw = _mapping(raw_value)
                pin_id = _text(raw.get("id")) or _text(raw.get("cacheable_id"))
                if not pin_id or pin_id in seen_ids:
                    continue
                seen_ids.add(pin_id)
                item = _normalize_visual_pin(raw, include_raw=include_raw)
                item["upstream_rank"] = len(items) + 1
                item["page_rank"] = rank
                items.append(item)
                if len(items) >= normalized_limit:
                    break
            next_bookmark = _validate_opaque(payload.get("bookmark"), field="bookmark")
            if len(items) >= normalized_limit:
                stop_reason = "limit_reached"
                break
            if next_bookmark.casefold() in _END_BOOKMARKS:
                stop_reason = "source_exhausted"
                break
            if next_bookmark in seen_bookmarks:
                stop_reason = "pagination_abnormal"
                next_bookmark = ""
                break
            seen_bookmarks.add(next_bookmark)
            current_bookmark = next_bookmark
        else:
            stop_reason = "page_cap_reached"

        if sort_by == "repins":
            items.sort(
                key=lambda item: item["metrics"].get("saves") or 0,
                reverse=True,
            )
        elif sort_by == "recent":
            items.sort(key=lambda item: _parse_created_at(item.get("created_at")), reverse=True)
        for rank, item in enumerate(items, 1):
            item["result_rank"] = rank
        return {
            "kind": "pinterest_visual_search",
            "access": "anonymous_web_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "query": {
                "image": str(path.resolve()),
                "image_sha256": sha256(image_bytes).hexdigest(),
                "crop": {"x": crop_x, "y": crop_y, "width": crop_width, "height": crop_height},
                "sort_by": sort_by,
            },
            "count": len(items),
            "items": items,
            "annotations": annotations,
            "source_image_url": source_image_url or None,
            "pagination": {
                "input_bookmark": bookmark or None,
                "next_bookmark": next_bookmark or None,
                "search_identifier": current_identifier or None,
                "pages_fetched": pages,
                "stop_reason": stop_reason,
            },
            "metric_scope": {
                "saves": "公开 Pin repin_count；用于本次相似结果样本内排序",
                "ad_performance": "not_published",
            },
        }

    def search_ads(
        self,
        *,
        start_date: str = "",
        end_date: str = "",
        country: str = "FR",
        advertiser_name: str = "",
        vertical: str = "",
        gender: str = "",
        age_bucket: str = "",
        bookmark: str = "",
        page_size: int = 24,
        limit: int = 100,
        sort_by: str = "reach",
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_start, normalized_end = _date_range(start_date, end_date)
        normalized_country = _text(country).upper()
        if normalized_country not in _ADS_COUNTRIES:
            raise PinterestAdsInputError("country 不在 Pinterest Ads Repository 国家列表中")
        normalized_advertiser = _text(advertiser_name)
        if len(normalized_advertiser) > 200:
            raise PinterestAdsInputError("advertiser_name 最多 200 个字符")
        normalized_vertical = _normalize_filter(vertical, field="vertical")
        normalized_gender = _normalize_filter(gender, field="gender")
        normalized_age = _normalize_filter(age_bucket, field="age_bucket")
        input_bookmark = _validate_opaque(bookmark, field="bookmark")
        normalized_page_size = _validate_limit(page_size, maximum=100, field="page_size")
        normalized_limit = _validate_limit(limit)
        if sort_by not in {"reach", "start_date", "upstream"}:
            raise PinterestAdsInputError("sort_by 必须是 reach、start_date 或 upstream")
        base_params: dict[str, Any] = {
            "start_date": normalized_start,
            "end_date": normalized_end,
            "country": normalized_country,
        }
        for key, value in (
            ("advertiser_name", normalized_advertiser),
            ("vertical", normalized_vertical),
            ("gender", normalized_gender),
            ("age_bucket", normalized_age),
        ):
            if value:
                base_params[key] = value

        current_bookmark = input_bookmark
        seen_bookmarks = {current_bookmark} if current_bookmark else set()
        seen_ids: set[str] = set()
        items: list[dict[str, Any]] = []
        pages = 0
        next_bookmark = current_bookmark
        stop_reason = "source_exhausted"
        while pages < _MAX_PAGES:
            params = dict(base_params)
            params["page_size"] = min(
                normalized_page_size, max(1, normalized_limit - len(items))
            )
            if current_bookmark:
                params["bookmark"] = current_bookmark
            response, _ = self._resource(
                base_url=PINTEREST_ADS_BASE_URL,
                resource_path=ADS_RESOURCE_PATH,
                source_url="/ads-repository/",
                options={"url": ADS_LIBRARY_PATH, "data": params},
            )
            pages += 1
            data = _mapping(response.get("data"))
            for ad_id, raw in _extract_ad_rows(data):
                if ad_id in seen_ids:
                    continue
                seen_ids.add(ad_id)
                item = _normalize_ad(ad_id, raw, include_raw=include_raw)
                item["upstream_rank"] = len(items) + 1
                items.append(item)
                if len(items) >= normalized_limit:
                    break
            next_bookmark = _validate_opaque(response.get("bookmark"), field="bookmark")
            if len(items) >= normalized_limit:
                stop_reason = "limit_reached"
                break
            if next_bookmark.casefold() in _END_BOOKMARKS:
                stop_reason = "source_exhausted"
                break
            if next_bookmark in seen_bookmarks:
                stop_reason = "pagination_abnormal"
                next_bookmark = ""
                break
            seen_bookmarks.add(next_bookmark)
            current_bookmark = next_bookmark
        else:
            stop_reason = "page_cap_reached"

        if sort_by == "reach":
            items.sort(
                key=lambda item: item["audience_range"]["eu"].get("upper_bound") or -1,
                reverse=True,
            )
        elif sort_by == "start_date":
            items.sort(key=lambda item: _text(item.get("start_date")), reverse=True)
        for rank, item in enumerate(items, 1):
            item["result_rank"] = rank
        return {
            "kind": "pinterest_ads_search",
            "access": "anonymous_official_repository",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "query": {
                **base_params,
                "sort_by": sort_by,
            },
            "count": len(items),
            "items": items,
            "pagination": {
                "input_bookmark": input_bookmark or None,
                "next_bookmark": next_bookmark or None,
                "pages_fetched": pages,
                "stop_reason": stop_reason,
            },
            "metric_scope": {
                "user_count_eu": "Pinterest 公开受众触达区间，并非 impressions",
                "user_count_by_country": "Pinterest 公开分国家触达区间",
                "impressions": "not_published",
                "engagement": "not_published",
                "ranking_rule": (
                    "reach 与 start_date 只在本次已采集样本内排序"
                    if sort_by != "upstream"
                    else "保留 Pinterest 上游返回顺序"
                ),
            },
        }

    def get_ad(self, ad_id: str, *, include_raw: bool = False) -> dict[str, Any]:
        normalized_id = _validate_id(ad_id, field="ad_id")
        api_path = ADS_DETAIL_PATH.format(ad_id=normalized_id)
        response, _ = self._resource(
            base_url=PINTEREST_ADS_BASE_URL,
            resource_path=ADS_RESOURCE_PATH,
            source_url="/ads-repository/",
            options={"url": api_path, "data": {}},
        )
        data = _mapping(response.get("data"))
        details = data.get("ad_details")
        if not isinstance(details, Mapping):
            raise PinterestAdsResponseError(
                "Pinterest Ads Repository 详情缺少 ad_details",
                code="response_drift",
            )
        return {
            "kind": "pinterest_ad",
            "access": "anonymous_official_repository",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "item": _normalize_ad(normalized_id, details, include_raw=include_raw),
            "metric_scope": {
                "user_count_eu": "Pinterest 公开受众触达区间，并非 impressions",
                "user_count_by_country": "Pinterest 公开分国家触达区间",
                "impressions": "not_published",
                "engagement": "not_published",
            },
        }

    def search_pins(
        self,
        query: str,
        *,
        scope: str = "pins",
        bookmark: str = "",
        page_size: int = 50,
        limit: int = 100,
        sort_by: str = "upstream",
        include_raw: bool = False,
    ) -> dict[str, Any]:
        normalized_query = _text(query)
        if not normalized_query or len(normalized_query) > 500:
            raise PinterestAdsInputError("query 长度必须在 1 到 500 之间")
        normalized_scope = _text(scope).casefold()
        if normalized_scope not in {"pins", "videos"}:
            raise PinterestAdsInputError("scope 必须是 pins 或 videos")
        input_bookmark = _validate_opaque(bookmark, field="bookmark")
        normalized_page_size = _validate_limit(page_size, maximum=100, field="page_size")
        normalized_limit = _validate_limit(limit)
        if sort_by not in {"saves", "recent", "upstream"}:
            raise PinterestAdsInputError("sort_by 必须是 saves、recent 或 upstream")

        current_bookmark = input_bookmark
        seen_bookmarks = {current_bookmark} if current_bookmark else set()
        seen_ids: set[str] = set()
        items: list[dict[str, Any]] = []
        guides: list[dict[str, Any]] = []
        pages = 0
        next_bookmark = current_bookmark
        stop_reason = "source_exhausted"
        while pages < _MAX_PAGES:
            options: dict[str, Any] = {
                "query": normalized_query,
                "scope": normalized_scope,
                "rs": "typed",
                "page_size": min(
                    normalized_page_size, max(1, normalized_limit - len(items))
                ),
            }
            if current_bookmark:
                options["bookmarks"] = [current_bookmark]
            source_url = f"/search/{normalized_scope}/?q={quote(normalized_query)}&rs=typed"
            response, _ = self._resource(
                base_url=PINTEREST_BASE_URL,
                resource_path=SEARCH_RESOURCE_PATH,
                source_url=source_url,
                options=options,
            )
            pages += 1
            data = _mapping(response.get("data"))
            if not guides:
                guides = _normalize_guides(data)
            for raw in _collect_result_pins(data.get("results")):
                pin_id = _text(raw.get("id"))
                if not pin_id or pin_id in seen_ids:
                    continue
                seen_ids.add(pin_id)
                item = _normalize_pin(raw, include_raw=include_raw)
                item["upstream_rank"] = len(items) + 1
                items.append(item)
                if len(items) >= normalized_limit:
                    break
            next_bookmark = _validate_opaque(response.get("bookmark"), field="bookmark")
            if len(items) >= normalized_limit:
                stop_reason = "limit_reached"
                break
            if next_bookmark.casefold() in _END_BOOKMARKS:
                stop_reason = "source_exhausted"
                break
            if next_bookmark in seen_bookmarks:
                stop_reason = "pagination_abnormal"
                next_bookmark = ""
                break
            seen_bookmarks.add(next_bookmark)
            current_bookmark = next_bookmark
        else:
            stop_reason = "page_cap_reached"

        if sort_by == "saves":
            items.sort(key=lambda item: item["metrics"].get("saves") or 0, reverse=True)
        elif sort_by == "recent":
            items.sort(key=lambda item: _parse_created_at(item.get("created_at")), reverse=True)
        for rank, item in enumerate(items, 1):
            item["result_rank"] = rank
        return {
            "kind": "pinterest_pin_search",
            "access": "anonymous_web_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "query": {"query": normalized_query, "scope": normalized_scope, "sort_by": sort_by},
            "count": len(items),
            "items": items,
            "related_queries": guides,
            "pagination": {
                "input_bookmark": input_bookmark or None,
                "next_bookmark": next_bookmark or None,
                "pages_fetched": pages,
                "stop_reason": stop_reason,
            },
            "metric_scope": {
                "saves": "公开 Pin repin_count 或 aggregated saves；缺失时应对入围项调用 pin",
                "views": "not_published",
                "ranking_rule": (
                    "saves 与 recent 只在本次已采集样本内排序"
                    if sort_by != "upstream"
                    else "保留 Pinterest 上游返回顺序"
                ),
            },
        }

    def pin(self, pin_id: str, *, include_raw: bool = False) -> dict[str, Any]:
        normalized_id = _validate_id(pin_id, field="pin_id")
        response, _ = self._resource(
            base_url=PINTEREST_BASE_URL,
            resource_path=PIN_RESOURCE_PATH,
            source_url=f"/pin/{normalized_id}/",
            options={
                "id": normalized_id,
                "field_set_key": "auth_web_main_pin",
                "noCache": True,
            },
        )
        return {
            "kind": "pinterest_pin",
            "access": "anonymous_web_api",
            "retrieved_at": _iso_now(),
            "protocol_verified": LAST_PROTOCOL_VERIFIED,
            "item": _normalize_pin(
                _mapping(response.get("data")), include_raw=include_raw
            ),
            "metric_scope": {
                "saves": "公开 Pin repin_count 或 aggregated saves",
                "comments": "公开 Pin comment_count",
                "shares": "公开 Pin share_count",
                "views": "not_published",
            },
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
        normalized_max = _validate_limit(
            max_bytes, maximum=2 * 1024 * 1024 * 1024, field="max_bytes"
        )
        path = Path(destination).expanduser()
        if path.exists() and not overwrite:
            raise PinterestAdsInputError("媒体 destination 已存在；使用 overwrite 覆盖")
        if path.exists() and path.is_dir():
            raise PinterestAdsInputError("媒体 destination 不得是目录")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        digest = sha256()
        byte_count = 0
        response = self._open(
            Request(
                media_url,
                headers={"Accept": "*/*", "User-Agent": self.user_agent},
                method="GET",
            )
        )
        final_url = media_url
        try:
            final_url = _require_media_url(
                response.geturl() if hasattr(response, "geturl") else media_url
            )
            content_length = _optional_int(response.headers.get("Content-Length"))
            if content_length is not None and content_length > normalized_max:
                raise PinterestAdsResponseError(
                    "Pinterest 媒体超过 max_bytes", code="media_too_large"
                )
            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(min(1024 * 1024, normalized_max + 1))
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    if byte_count > normalized_max:
                        raise PinterestAdsResponseError(
                            "Pinterest 媒体超过 max_bytes", code="media_too_large"
                        )
                    handle.write(chunk)
                    digest.update(chunk)
            if path.exists() and not overwrite:
                raise PinterestAdsInputError(
                    "媒体 destination 在下载期间被创建；使用 overwrite 覆盖"
                )
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            response.close()
        return {
            "kind": "pinterest_media_download",
            "source_url": media_url,
            "final_url": final_url,
            "destination": str(path.resolve()),
            "bytes": byte_count,
            "sha256": digest.hexdigest(),
            "content_type": _text(response.headers.get("Content-Type")).partition(";")[0]
            or None,
        }
