from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import KuaishouInputError, KuaishouResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 "
    "Mobile Safari/537.36"
)
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

_BASE_URL = "https://www.kuaishou.com"
_HOT_LIST_ENDPOINT = f"{_BASE_URL}/graphql"
_HOT_LIST_MAX_ITEMS = 50
_HOT_LIST_QUERY = """query hotRankQuery($page: String) {
  visionHotRank(page: $page) {
    result
    pcursor
    webPageArea
    items {
      rank
      id
      name
      viewCount
      hotValue
      tagType
      photoIds
    }
  }
}"""
_INIT_STATE_RE = re.compile(r"\bwindow\.INIT_STATE\s*=\s*")
_PHOTO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_SHARE_URL_RE = re.compile(
    r"(?<![A-Za-z0-9.-])(?:https?://)?"
    r"(?:[A-Za-z0-9-]+\.)*(?:kuaishou\.com|gifshow\.com|chenzhongtech\.com)"
    r"(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>，。；：！？）】》、"
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


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


def _number(value: Any) -> int | float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return int(number) if number.is_integer() else number


def _timestamp_seconds(value: Any) -> int:
    timestamp = _integer(value)
    while timestamp >= 10_000_000_000:
        timestamp //= 1000
    return timestamp if timestamp > 0 else 0


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _timestamp_seconds(value)
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _query_value(query: Mapping[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = query.get(name)
        if values:
            value = str(values[0] or "").strip()
            if value:
                return value
    return None


def _unique_urls(value: Any) -> list[dict[str, str | None]]:
    output: list[dict[str, str | None]] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            url = item.strip()
            if url.startswith(("https://", "http://")) and url not in seen:
                seen.add(url)
                output.append({"url": url, "cdn": None})
            return
        if isinstance(item, Mapping):
            url = str(item.get("url") or item.get("src") or "").strip()
            if url.startswith(("https://", "http://")) and url not in seen:
                seen.add(url)
                output.append(
                    {
                        "url": url,
                        "cdn": str(item.get("cdn") or "").strip() or None,
                    }
                )
            for key, child in item.items():
                if key not in {"url", "src", "cdn"}:
                    visit(child)
            return
        for child in _list(item):
            visit(child)

    visit(value)
    return output


class KuaishouClient:
    """读取 Kuaishou 公开分享 hydration 数据和 Web 热榜。"""

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
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    def get_post(self, reference: str) -> dict[str, Any]:
        response, resolution = self._fetch_share(reference)
        result = self.parse_share_html(
            response.text,
            expected_photo_id=resolution.get("photo_id"),
        )
        photo_id = str(resolution.get("photo_id") or result.get("photo_id") or "") or None
        if photo_id:
            result["id"] = photo_id
            result["photo_id"] = photo_id
            result["url"] = f"{_BASE_URL}/short-video/{photo_id}"
        result.update(
            {
                "source_url": resolution["source_url"],
                "resolved_url": resolution["resolved_url"],
                "redirect_chain": resolution["redirect_chain"],
                "share_token": resolution.get("share_token"),
                "share_user_id": resolution.get("user_id"),
                "short_code": resolution.get("short_code"),
            }
        )
        return result

    def get_author(self, reference: str) -> dict[str, Any]:
        post = self.get_post(reference)
        profile = post.get("author_profile")
        return dict(profile) if isinstance(profile, Mapping) else dict(post["author"])

    def resolve_share(self, reference: str) -> dict[str, Any]:
        response, resolution = self._fetch_share(reference)
        return {
            **resolution,
            "has_hydration": bool(_INIT_STATE_RE.search(response.text or "")),
        }

    def get_hot_list(self, *, limit: int = 50) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise KuaishouInputError("Kuaishou hot-list limit must be an integer")
        if limit < 0 or limit > _HOT_LIST_MAX_ITEMS:
            raise KuaishouInputError(
                f"Kuaishou hot-list limit must be in 0..{_HOT_LIST_MAX_ITEMS}"
            )
        if limit == 0:
            return self._empty_hot_list()
        response = self._request_hot_list()
        return self.parse_hot_list_payload(response.text, limit=limit)

    @classmethod
    def parse_hot_list_payload(
        cls,
        source: str | bytes | bytearray | Mapping[str, Any],
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise KuaishouInputError("Kuaishou hot-list limit must be an integer")
        if limit < 0 or limit > _HOT_LIST_MAX_ITEMS:
            raise KuaishouInputError(
                f"Kuaishou hot-list limit must be in 0..{_HOT_LIST_MAX_ITEMS}"
            )
        if isinstance(source, Mapping):
            payload: Any = source
        else:
            if isinstance(source, (bytes, bytearray)):
                try:
                    source = bytes(source).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise KuaishouResponseError(
                        "Kuaishou hot-list response is not UTF-8"
                    ) from exc
            if not isinstance(source, str) or not source.strip():
                raise KuaishouResponseError("Kuaishou hot-list response is empty")
            try:
                payload = json.loads(source)
            except (json.JSONDecodeError, TypeError) as exc:
                raise KuaishouResponseError(
                    "Kuaishou hot-list response is not valid JSON"
                ) from exc
        if not isinstance(payload, Mapping):
            raise KuaishouResponseError("Kuaishou hot-list response is not an object")

        errors = payload.get("errors")
        if errors is not None and (
            not isinstance(errors, list) or len(errors) > 0
        ):
            raise KuaishouResponseError("Kuaishou hot-list GraphQL returned errors")
        data = payload.get("data")
        rank = data.get("visionHotRank") if isinstance(data, Mapping) else None
        if not isinstance(rank, Mapping):
            raise KuaishouResponseError(
                "Kuaishou hot-list response is missing data.visionHotRank"
            )
        if _integer(rank.get("result")) != 1:
            raise KuaishouResponseError(
                f"Kuaishou hot-list returned result={rank.get('result')}"
            )
        raw_items = rank.get("items")
        if not isinstance(raw_items, Sequence) or isinstance(
            raw_items, (str, bytes, bytearray)
        ):
            raise KuaishouResponseError("Kuaishou hot-list items is not a list")
        if len(raw_items) > 200:
            raise KuaishouResponseError("Kuaishou hot-list items exceeds safety limit")

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if len(items) >= limit:
                break
            if not isinstance(raw_item, Mapping):
                raise KuaishouResponseError("Kuaishou hot-list item is not an object")
            trend_id = str(raw_item.get("id") or "").strip()
            name = str(raw_item.get("name") or "").strip()
            if not trend_id or not name:
                raise KuaishouResponseError(
                    "Kuaishou hot-list item is missing id/name"
                )
            raw_photo_ids = raw_item.get("photoIds")
            if not isinstance(raw_photo_ids, Sequence) or isinstance(
                raw_photo_ids, (str, bytes, bytearray)
            ):
                raise KuaishouResponseError(
                    "Kuaishou hot-list photoIds is not a list"
                )
            photo_ids: list[str] = []
            seen_photo_ids: set[str] = set()
            for raw_id in raw_photo_ids:
                photo_id = str(raw_id or "").strip()
                if not _PHOTO_ID_RE.fullmatch(photo_id):
                    raise KuaishouResponseError(
                        "Kuaishou hot-list photoIds contains malformed value"
                    )
                if photo_id not in seen_photo_ids:
                    seen_photo_ids.add(photo_id)
                    photo_ids.append(photo_id)
            if trend_id in seen:
                continue
            seen.add(trend_id)
            items.append(
                {
                    "rank": _integer(raw_item.get("rank")),
                    "trend_id": trend_id,
                    "name": name,
                    "hot_value": cls._nullable_hot_scalar(
                        raw_item.get("hotValue")
                    ),
                    "view_count": cls._nullable_hot_scalar(
                        raw_item.get("viewCount")
                    ),
                    "tag_type": str(raw_item.get("tagType") or "").strip() or None,
                    "photo_ids": photo_ids,
                    "primary_photo_id": photo_ids[0] if photo_ids else None,
                    "search_url": f"{_BASE_URL}/search/{quote(name, safe='')}",
                }
            )

        cursor = str(rank.get("pcursor") or "").strip() or None
        return {
            "board": "hot",
            "source": "visionHotRank",
            "total": len(items),
            "available": len(raw_items),
            "cursor": cursor,
            "has_more": cursor not in (None, "no_more"),
            "web_page_area": str(rank.get("webPageArea") or "").strip() or None,
            "items": items,
        }

    @staticmethod
    def _nullable_hot_scalar(value: Any) -> str | int | float | bool | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        if isinstance(value, (int, float, bool)):
            return value
        return None

    @staticmethod
    def _empty_hot_list() -> dict[str, Any]:
        return {
            "board": "hot",
            "source": "visionHotRank",
            "total": 0,
            "available": 0,
            "cursor": None,
            "has_more": False,
            "web_page_area": None,
            "items": [],
        }

    @classmethod
    def resolve_reference(cls, reference: str) -> dict[str, Any]:
        if not isinstance(reference, str):
            raise KuaishouInputError("Kuaishou reference must be a string")
        text = reference.strip()
        if not text:
            raise KuaishouInputError("Kuaishou reference is empty")

        if _PHOTO_ID_RE.fullmatch(text):
            return {
                "source_url": f"{_BASE_URL}/short-video/{text}",
                "photo_id": text,
                "share_token": None,
                "user_id": None,
                "short_code": None,
            }

        match = _SHARE_URL_RE.search(text)
        if not match:
            raise KuaishouInputError("reference does not contain a supported Kuaishou URL")
        candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        return cls._parse_url_reference(candidate)

    @classmethod
    def extract_init_state(cls, source: str) -> dict[str, Any]:
        if not isinstance(source, str) or not source.strip():
            raise KuaishouResponseError("Kuaishou share response is empty")
        decoder = json.JSONDecoder()
        for match in _INIT_STATE_RE.finditer(source):
            try:
                state, _ = decoder.raw_decode(source, match.end())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(state, Mapping):
                return dict(state)

        stripped = source.lstrip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                payload = None
            if isinstance(payload, Mapping) and "result" in payload:
                raise KuaishouResponseError(
                    "Kuaishou share endpoint returned a JSON gate "
                    f"(result={payload.get('result')}, request_id={payload.get('request_id')})"
                )
        raise KuaishouResponseError("Kuaishou share HTML does not contain window.INIT_STATE")

    @classmethod
    def parse_share_html(
        cls,
        source: str,
        *,
        expected_photo_id: str | None = None,
    ) -> dict[str, Any]:
        state = cls.extract_init_state(source)
        candidates = cls._find_photo_candidates(state)
        if not candidates:
            raise KuaishouResponseError("Kuaishou hydration does not contain public photo data")

        selected: Mapping[str, Any] | None = None
        if expected_photo_id:
            selected = next(
                (
                    photo
                    for photo in candidates
                    if expected_photo_id
                    in {
                        str(photo.get("photoId") or ""),
                        str(cls._share_fields(photo).get("photoId") or ""),
                    }
                ),
                None,
            )
        if selected is None and len(candidates) == 1:
            selected = candidates[0]
        if selected is None:
            selected = max(candidates, key=cls._photo_score)

        profile = cls._find_profile(state, selected)
        return cls._normalize_photo(
            selected,
            profile=profile,
            expected_photo_id=expected_photo_id,
        )

    def _fetch_share(
        self,
        reference: str,
    ) -> tuple[requests.Response, dict[str, Any]]:
        initial = self.resolve_reference(reference)
        response = self._request(initial["source_url"])
        chain: list[str] = []
        for value in [
            initial["source_url"],
            *(str(item.url) for item in getattr(response, "history", []) if item.url),
            str(getattr(response, "url", "") or initial["source_url"]),
        ]:
            if value and (not chain or value != chain[-1]):
                chain.append(value)

        merged = dict(initial)
        for url in chain[1:]:
            try:
                item = self._parse_url_reference(url)
            except KuaishouInputError as exc:
                raise KuaishouResponseError(
                    f"Kuaishou redirect left the supported share hosts: {url}"
                ) from exc
            for key in ("photo_id", "share_token", "user_id", "short_code"):
                if item.get(key):
                    merged[key] = item[key]
        merged["resolved_url"] = chain[-1]
        merged["redirect_chain"] = chain
        return response, merged

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
                    raise KuaishouResponseError(
                        f"Kuaishou request failed for {path}: {exc}"
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = _integer(getattr(response, "status_code", 0))
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            if status < 200 or status >= 300:
                raise KuaishouResponseError(f"Kuaishou returned HTTP {status} for {path}")
            return response
        raise KuaishouResponseError(f"Kuaishou request exhausted retries for {path}")

    def _request_hot_list(self) -> requests.Response:
        request_body = {
            "operationName": "hotRankQuery",
            "variables": {"page": "home"},
            "query": _HOT_LIST_QUERY,
        }
        headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "Origin": _BASE_URL,
            "Referer": f"{_BASE_URL}/?isHome=1",
            "User-Agent": DESKTOP_USER_AGENT,
        }
        path = "/graphql"
        for attempt in range(self.retries + 1):
            try:
                response = self.session.post(
                    _HOT_LIST_ENDPOINT,
                    json=request_body,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestsError as exc:
                if attempt >= self.retries:
                    raise KuaishouResponseError(
                        f"Kuaishou request failed for {path}: {exc}"
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = _integer(getattr(response, "status_code", 0))
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            if status < 200 or status >= 300:
                raise KuaishouResponseError(
                    f"Kuaishou returned HTTP {status} for {path}"
                )
            return response
        raise KuaishouResponseError(
            f"Kuaishou request exhausted retries for {path}"
        )

    @classmethod
    def _parse_url_reference(cls, value: str) -> dict[str, Any]:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise KuaishouInputError("Kuaishou URL must use HTTP or HTTPS")
        if not cls._is_share_host(parsed.hostname):
            raise KuaishouInputError("URL must use a supported Kuaishou share host")

        parts = [unquote(part) for part in parsed.path.split("/") if part]
        query = parse_qs(parsed.query, keep_blank_values=True)
        host = (parsed.hostname or "").lower().rstrip(".")
        photo_id = _query_value(query, "photoId", "photo_id")
        share_token = _query_value(query, "shareToken", "share_token")
        user_id = _query_value(query, "userId", "authorId", "user_id")
        short_code: str | None = None

        if len(parts) >= 2 and parts[0].lower() == "short-video":
            photo_id = parts[1]
        elif len(parts) >= 3 and parts[0].lower() == "fw" and parts[1].lower() == "photo":
            photo_id = parts[2]
        elif len(parts) >= 2 and parts[0].lower() == "f":
            share_token = share_token or parts[1]
        elif host == "v.kuaishou.com" and parts:
            short_code = parts[0]

        for name, item in (
            ("photo id", photo_id),
            ("share token", share_token),
            ("short code", short_code),
        ):
            if item and not _PHOTO_ID_RE.fullmatch(item):
                raise KuaishouInputError(f"Kuaishou {name} is malformed")
        if not any((photo_id, share_token, short_code)):
            raise KuaishouInputError("URL is not a supported Kuaishou photo/share URL")

        normalized_url = urlunsplit(
            (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, "")
        )
        return {
            "source_url": normalized_url,
            "photo_id": photo_id,
            "share_token": share_token,
            "user_id": user_id,
            "short_code": short_code,
        }

    @staticmethod
    def _is_share_host(hostname: str | None) -> bool:
        host = (hostname or "").lower().rstrip(".")
        return any(
            host == suffix or host.endswith(f".{suffix}")
            for suffix in ("kuaishou.com", "gifshow.com", "chenzhongtech.com")
        )

    @classmethod
    def _find_photo_candidates(cls, value: Any) -> list[Mapping[str, Any]]:
        found: list[Mapping[str, Any]] = []
        seen: set[int] = set()

        def visit(item: Any) -> None:
            if isinstance(item, Mapping):
                if cls._photo_score(item) >= 4 and id(item) not in seen:
                    seen.add(id(item))
                    found.append(item)
                for child in item.values():
                    visit(child)
            else:
                for child in _list(item):
                    visit(child)

        visit(value)
        return found

    @staticmethod
    def _photo_score(value: Mapping[str, Any]) -> int:
        score = 0
        for key in (
            "photoId",
            "caption",
            "userEid",
            "timestamp",
            "coverUrls",
            "mainMvUrls",
            "manifest",
            "photoType",
        ):
            if key in value:
                score += 1
        return score

    @classmethod
    def _find_profile(
        cls,
        state: Mapping[str, Any],
        photo: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        candidates: list[Mapping[str, Any]] = []

        def visit(item: Any) -> None:
            if isinstance(item, Mapping):
                profile = item.get("profile")
                if isinstance(profile, Mapping) and (
                    "eid" in profile or "user_id" in profile or "user_name" in profile
                ):
                    candidates.append(item)
                for child in item.values():
                    visit(child)
            else:
                for child in _list(item):
                    visit(child)

        visit(state)
        expected = {
            str(photo.get("userEid") or ""),
            str(photo.get("userId") or ""),
        } - {""}
        for candidate in candidates:
            profile = _mapping(candidate.get("profile"))
            identities = {
                str(profile.get("eid") or ""),
                str(profile.get("user_id") or ""),
            } - {""}
            if expected & identities:
                return candidate
        return candidates[0] if len(candidates) == 1 else {}

    @staticmethod
    def _share_fields(photo: Mapping[str, Any]) -> dict[str, str]:
        value = str(photo.get("share_info") or "").strip()
        if not value:
            return {}
        return {
            key: str(values[0])
            for key, values in parse_qs(value, keep_blank_values=True).items()
            if values and values[0]
        }

    @classmethod
    def _normalize_photo(
        cls,
        photo: Mapping[str, Any],
        *,
        profile: Mapping[str, Any],
        expected_photo_id: str | None,
    ) -> dict[str, Any]:
        share_fields = cls._share_fields(photo)
        internal_photo_id = str(photo.get("photoId") or "") or None
        photo_id = (
            str(expected_photo_id or "")
            or str(share_fields.get("photoId") or "")
            or str(internal_photo_id or "")
        )
        covers: list[dict[str, Any]] = []
        seen_cover_urls: set[str] = set()
        for kind, key in (
            ("cover", "coverUrls"),
            ("webp_cover", "webpCoverUrls"),
            ("override_cover", "overrideCoverUrls"),
            ("ccc_cover", "cccCoverMap"),
        ):
            for item in _unique_urls(photo.get(key)):
                if item["url"] in seen_cover_urls:
                    continue
                seen_cover_urls.add(str(item["url"]))
                covers.append({**item, "kind": kind})

        images: list[dict[str, Any]] = []
        seen_image_urls: set[str] = set()
        for key in (
            "imageUrls",
            "pictureUrls",
            "atlas",
            "atlasList",
            "images",
            "pictures",
            "singlePicture",
        ):
            for item in _unique_urls(photo.get(key)):
                if item["url"] in seen_image_urls:
                    continue
                seen_image_urls.add(str(item["url"]))
                images.append(item)

        videos: list[dict[str, Any]] = []
        seen_video_urls: set[str] = set()
        for item in _unique_urls(photo.get("mainMvUrls")):
            url = str(item["url"])
            if url in seen_video_urls:
                continue
            seen_video_urls.add(url)
            videos.append(
                {
                    **item,
                    "source": "main",
                    "quality_label": None,
                    "quality_type": None,
                    "codec": None,
                    "width": _integer(photo.get("width")),
                    "height": _integer(photo.get("height")),
                    "frame_rate": None,
                    "average_bitrate": None,
                    "file_size": None,
                    "backup_urls": [],
                }
            )

        manifest = _mapping(photo.get("manifest"))
        for adaptation in _list(manifest.get("adaptationSet")):
            adaptation_item = _mapping(adaptation)
            for raw_representation in _list(adaptation_item.get("representation")):
                representation = _mapping(raw_representation)
                url = str(representation.get("url") or "").strip()
                if not url or url in seen_video_urls:
                    continue
                seen_video_urls.add(url)
                videos.append(
                    {
                        "url": url,
                        "cdn": urlsplit(url).hostname,
                        "source": "manifest",
                        "quality_label": str(representation.get("qualityLabel") or "") or None,
                        "quality_type": str(representation.get("qualityType") or "") or None,
                        "quality": _number(representation.get("quality")),
                        "codec": str(representation.get("videoCodec") or "") or None,
                        "width": _integer(representation.get("width")),
                        "height": _integer(representation.get("height")),
                        "frame_rate": _number(representation.get("frameRate")),
                        "average_bitrate": _integer(representation.get("avgBitrate")),
                        "file_size": _integer(representation.get("fileSize")),
                        "default": bool(representation.get("defaultSelect")),
                        "hidden": bool(representation.get("hidden")),
                        "backup_urls": [
                            str(item["url"])
                            for item in _unique_urls(representation.get("backupUrl"))
                        ],
                    }
                )

        photo_type = str(photo.get("photoType") or "").upper()
        if videos or photo_type == "VIDEO":
            media_type = "video"
        elif len(images) > 1 or photo_type in {"ATLAS", "ALBUM", "SLIDE"}:
            media_type = "album"
        else:
            media_type = "image"

        normalized_profile = cls._normalize_profile(profile) if profile else None
        author = {
            "id": str(photo.get("userId") or "") or None,
            "eid": str(photo.get("userEid") or share_fields.get("userId") or "") or None,
            "name": str(photo.get("userName") or "") or None,
            "kwai_id": str(photo.get("kwaiId") or "") or None,
            "avatar": str(photo.get("headUrl") or "") or None,
            "avatars": _unique_urls(photo.get("headUrls")),
            "gender": str(photo.get("userSex") or "") or None,
            "verified": bool(photo.get("verified")),
        }
        if normalized_profile:
            for key in ("id", "eid", "name", "kwai_id", "avatar", "gender"):
                if not author.get(key) and normalized_profile.get(key):
                    author[key] = normalized_profile[key]
            author["verified"] = bool(author["verified"] or normalized_profile["verified"])

        timestamp = photo.get("timestamp")
        duration_ms = _integer(photo.get("duration"))
        statistics = {
            "likes": _integer(photo.get("likeCount")),
            "comments": _integer(photo.get("commentCount")),
            "views": _integer(photo.get("viewCount")),
            "shares": _integer(photo.get("shareCount")),
            "forwards": _integer(photo.get("forwardCount")),
        }
        sound = cls._normalize_sound(_mapping(photo.get("soundTrack")))
        return {
            "id": photo_id or internal_photo_id,
            "photo_id": photo_id or internal_photo_id,
            "internal_photo_id": internal_photo_id,
            "url": f"{_BASE_URL}/short-video/{photo_id}" if photo_id else None,
            "media_type": media_type,
            "photo_type": photo_type or None,
            "title": str(photo.get("caption") or ""),
            "caption": str(photo.get("caption") or ""),
            "published_timestamp": _timestamp_seconds(timestamp) or None,
            "published_at": _timestamp_iso(timestamp),
            "timestamp_ms": _integer(timestamp) or None,
            "duration_ms": duration_ms or None,
            "duration_seconds": round(duration_ms / 1000, 3) if duration_ms else None,
            "width": _integer(photo.get("width")),
            "height": _integer(photo.get("height")),
            "cover_url": covers[0]["url"] if covers else None,
            "covers": covers,
            "images": images,
            "video_url": videos[0]["url"] if videos else None,
            "videos": videos,
            "like_count": statistics["likes"],
            "comment_count": statistics["comments"],
            "view_count": statistics["views"],
            "share_count": statistics["shares"],
            "forward_count": statistics["forwards"],
            "statistics": statistics,
            "author": author,
            "author_profile": normalized_profile,
            "sound": sound,
        }

    @staticmethod
    def _normalize_profile(wrapper: Mapping[str, Any]) -> dict[str, Any]:
        profile = _mapping(wrapper.get("profile"))
        counts = _mapping(wrapper.get("ownerCount"))
        eid = str(profile.get("eid") or "") or None
        return {
            "id": str(profile.get("user_id") or "") or None,
            "eid": eid,
            "name": str(profile.get("user_name") or "") or None,
            "kwai_id": str(profile.get("kwaiId") or "") or None,
            "profile_url": f"{_BASE_URL}/profile/{eid}" if eid else None,
            "bio": str(profile.get("user_text") or ""),
            "avatar": str(profile.get("headurl") or "") or None,
            "avatars": _unique_urls(profile.get("headurls")),
            "large_avatars": _unique_urls(profile.get("bigHeadUrls")),
            "backgrounds": _unique_urls(profile.get("user_profile_bg_urls")),
            "gender": str(profile.get("user_sex") or "") or None,
            "verified": bool(profile.get("verified") or wrapper.get("verified")),
            "city": str(wrapper.get("cityName") or "") or None,
            "city_code": str(wrapper.get("cityCode") or "") or None,
            "constellation": str(wrapper.get("constellation") or "") or None,
            "followers": _integer(counts.get("fan")),
            "following": _integer(counts.get("follow")),
            "post_count": _integer(counts.get("photo")),
            "public_post_count": _integer(counts.get("photo_public")),
        }

    @staticmethod
    def _normalize_sound(sound: Mapping[str, Any]) -> dict[str, Any] | None:
        if not sound:
            return None
        user = _mapping(sound.get("user"))
        return {
            "id": str(sound.get("id") or "") or None,
            "photo_id": str(sound.get("photoId") or "") or None,
            "name": str(sound.get("name") or "") or None,
            "artist": str(sound.get("artist") or "") or None,
            "audio_type": _integer(sound.get("audioType")),
            "usage_count": _integer(sound.get("usageCount") or sound.get("photoCount")),
            "audio_urls": _unique_urls(sound.get("audioUrls")),
            "image_urls": _unique_urls(sound.get("imageUrls")),
            "author_eid": str(user.get("eid") or "") or None,
        }
