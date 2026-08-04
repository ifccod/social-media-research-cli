from __future__ import annotations

import html
import math
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlsplit

from curl_cffi import requests

from .errors import WeChatChannelsInputError, WeChatChannelsResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

_BASE_URL = "https://channels.weixin.qq.com"
_API_PATH = "/finder-preview/api/feed/get_feed_info"
_API_URL = f"{_BASE_URL}{_API_PATH}"
_SHARE_HOST = "weixin.qq.com"
_PREVIEW_HOST = "channels.weixin.qq.com"
_SHORT_URI_RE = re.compile(r"^[A-Za-z0-9]{6,128}$")
_EXPORT_ID_RE = re.compile(r"^export/[A-Za-z0-9._~-]{16,2040}$")
_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>，。；：！？）】》、"
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_COUNT_FIELDS = {
    "favorites": ("favCount", "favoriteCount", "favCountFmt"),
    "likes": ("likeCount", "likeCountFmt"),
    "forwards": ("forwardCount", "forwardCountFmt"),
    "comments": ("commentCount", "commentCountFmt"),
}


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


def _positive_integer(value: Any) -> int | None:
    result = _integer(value)
    return result if result > 0 else None


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _integer(value)
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _url(value: Any) -> str:
    source = html.unescape(str(value or "")).strip()
    if source.startswith("//"):
        return f"https:{source}"
    if source.lower().startswith("http://"):
        return f"https://{source[7:]}"
    return source


def _count_details(value: Any) -> tuple[int, bool, bool]:
    if isinstance(value, bool):
        return int(value), False, False
    if isinstance(value, (int, float)):
        try:
            return max(0, int(value)), False, False
        except (ValueError, OverflowError):
            return 0, False, False
    source = str(value or "").strip().replace(",", "")
    lower_bound = source.endswith("+")
    if lower_bound:
        source = source[:-1].strip()
    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)\s*(万|亿|[kKmMwW])?",
        source,
    )
    if not match:
        return 0, False, lower_bound
    multiplier = {
        "": Decimal(1),
        "k": Decimal(1_000),
        "m": Decimal(1_000_000),
        "w": Decimal(10_000),
        "万": Decimal(10_000),
        "亿": Decimal(100_000_000),
    }[(match.group(2) or "").lower()]
    try:
        result = int(Decimal(match.group(1)) * multiplier)
    except (InvalidOperation, ValueError, OverflowError):
        return 0, False, lower_bound
    approximate = bool(match.group(2)) or "." in match.group(1) or lower_bound
    return max(0, result), approximate, lower_bound


def _first_value(source: Mapping[str, Any], names: Sequence[str]) -> tuple[Any, str]:
    for name in names:
        if name in source and source.get(name) not in (None, ""):
            return source.get(name), name
    return "", names[-1] if names else ""


def _normalize_stats(
    feed: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, str], dict[str, dict[str, bool]]]:
    stats: dict[str, int] = {}
    formatted: dict[str, str] = {}
    metadata: dict[str, dict[str, bool]] = {}
    for output_name, field_names in _COUNT_FIELDS.items():
        value, field_name = _first_value(feed, field_names)
        count, approximate, lower_bound = _count_details(value)
        text_value = str(feed.get(field_names[-1]) or value or "")
        stats[output_name] = count
        formatted[output_name] = text_value
        metadata[output_name] = {
            "approximate": approximate
            or field_name.endswith("Fmt")
            and not text_value.isdigit(),
            "lower_bound": lower_bound,
        }
    return stats, formatted, metadata


def _normalize_video_info(value: Any, *, codec: str) -> dict[str, Any] | None:
    if isinstance(value, str):
        source: Mapping[str, Any] = {"videoUrl": value}
    else:
        source = _mapping(value)
    media_url = _url(
        source.get("videoUrl")
        or source.get("url")
        or source.get("mediaUrl")
        or source.get("fullUrl")
    )
    if not media_url:
        return None
    return {
        "codec": codec,
        "url": media_url,
        "width": _positive_integer(source.get("width") or source.get("videoWidth")),
        "height": _positive_integer(source.get("height") or source.get("videoHeight")),
        "duration_seconds": _positive_integer(
            source.get("duration") or source.get("durationSeconds")
        ),
        "file_size": _positive_integer(source.get("fileSize") or source.get("size")),
    }


def _normalize_videos(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        (feed.get("h264VideoInfo"), "h264"),
        (feed.get("h265VideoInfo"), "h265"),
        (feed.get("videoUrl"), "unknown"),
    )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value, codec in candidates:
        item = _normalize_video_info(value, codec=codec)
        if not item or item["url"] in seen:
            continue
        seen.add(item["url"])
        output.append(item)
    return output


def _normalize_images(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in _list(feed.get("picInfo")):
        if isinstance(value, str):
            source: Mapping[str, Any] = {"url": value}
        else:
            source = _mapping(value)
        media_url = _url(
            source.get("url")
            or source.get("picUrl")
            or source.get("mediaUrl")
            or source.get("fullUrl")
        )
        if not media_url or media_url in seen:
            continue
        seen.add(media_url)
        output.append(
            {
                "url": media_url,
                "thumb_url": _url(source.get("thumbUrl") or source.get("coverUrl")),
                "width": _positive_integer(source.get("width") or source.get("picWidth")),
                "height": _positive_integer(source.get("height") or source.get("picHeight")),
                "file_size": _positive_integer(source.get("fileSize") or source.get("size")),
            }
        )
    return output


class WeChatChannelsClient:
    """通过普通 HTTP 读取微信视频号公开分享元数据。"""

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
            raise WeChatChannelsInputError("timeout must be a positive finite number")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise WeChatChannelsInputError("retries must be a non-negative integer")
        if (
            not isinstance(user_agent, str)
            or not user_agent.strip()
            or "\r" in user_agent
            or "\n" in user_agent
        ):
            raise WeChatChannelsInputError(
                "user_agent must be a non-empty single-line string"
            )
        self.session = session if session is not None else requests.Session()
        self.timeout = float(timeout)
        self.retries = retries
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Content-Type": "application/json",
                "Origin": _BASE_URL,
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def resolve_short_uri(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise WeChatChannelsInputError("share reference must be a non-empty string")
        source = html.unescape(value.strip())
        if _SHORT_URI_RE.fullmatch(source):
            return source

        match = _HTTP_URL_RE.search(source)
        if not match:
            raise WeChatChannelsInputError(
                "reference does not contain a WeChat Channels share URL"
            )
        candidate = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise WeChatChannelsInputError("share URL is malformed") from exc
        if parsed.username or parsed.password:
            raise WeChatChannelsInputError("share URL must not contain credentials")
        if port is not None and port not in {80, 443}:
            raise WeChatChannelsInputError("share URL uses a non-standard port")
        if "%" in parsed.path or "\\" in parsed.path:
            raise WeChatChannelsInputError("share URL path must not be encoded")

        host = (parsed.hostname or "").lower()
        pieces = [piece for piece in parsed.path.split("/") if piece]
        short_uri = ""
        if host in {_SHARE_HOST, _PREVIEW_HOST} and len(pieces) == 2 and pieces[0] == "sph":
            short_uri = pieces[1]
        elif host == _PREVIEW_HOST and pieces == ["finder-preview", "pages", "sph"]:
            ids = parse_qs(parsed.query, keep_blank_values=True).get("id") or []
            if len(ids) == 1:
                short_uri = ids[0]
        else:
            raise WeChatChannelsInputError("URL is not a public WeChat Channels share route")
        if not _SHORT_URI_RE.fullmatch(short_uri):
            raise WeChatChannelsInputError("share short URI is malformed")
        return short_uri

    @staticmethod
    def resolve_export_id(value: str) -> str:
        if not isinstance(value, str):
            raise WeChatChannelsInputError("export ID must be a string")
        source = value.strip()
        if not _EXPORT_ID_RE.fullmatch(source):
            raise WeChatChannelsInputError(
                "export ID must start with export/ and contain a valid opaque token"
            )
        return source

    @classmethod
    def parse_feed_payload(
        cls,
        payload: object,
        *,
        short_uri: str = "",
        export_id: str = "",
    ) -> dict[str, Any]:
        if short_uri and export_id:
            raise WeChatChannelsInputError(
                "feed payload reference must use either short_uri or export_id"
            )
        if short_uri:
            short_uri = cls.resolve_short_uri(short_uri)
        if export_id:
            export_id = cls.resolve_export_id(export_id)
        root = _mapping(payload)
        if not root:
            raise WeChatChannelsResponseError(
                "WeChat Channels response root is not an object", payload=payload
            )
        cls._check_api_result(root)
        data = _mapping(root.get("data"))
        if not data:
            raise WeChatChannelsResponseError(
                "WeChat Channels response does not contain data", payload=payload
            )

        author = _mapping(data.get("authorInfo"))
        feed = _mapping(data.get("feedInfo"))
        scene = _mapping(data.get("sceneInfo"))
        warning_source = _mapping(data.get("errMsg"))
        warning = {
            "type": _integer(warning_source.get("type")),
            "title": str(warning_source.get("title") or ""),
            "content": str(warning_source.get("content") or ""),
        }
        if not author and not feed and not scene and not any(warning.values()):
            raise WeChatChannelsResponseError(
                "WeChat Channels response contains no feed metadata", payload=payload
            )

        stats, stats_formatted, stats_metadata = _normalize_stats(feed)
        videos = _normalize_videos(feed)
        images = _normalize_images(feed)
        media_type_code = _integer(feed.get("mediaType"))
        if media_type_code == 4 or videos:
            media_type = "video"
        elif media_type_code == 2 or images:
            media_type = "images"
        elif feed.get("coverUrl"):
            media_type = "preview"
        else:
            media_type = "unknown"

        published_timestamp = _integer(feed.get("createtime") or feed.get("createTime"))
        expired_timestamp = _integer(scene.get("expiredTime"))
        dynamic_export_id = str(scene.get("dynamicExportId") or "")
        reference_kind = "short_uri" if short_uri else "export_id" if export_id else "unknown"
        reference = {
            "kind": reference_kind,
            "short_uri": short_uri,
            "share_url": f"https://{_SHARE_HOST}/sph/{short_uri}" if short_uri else "",
            "preview_url": (
                f"{_BASE_URL}/finder-preview/pages/sph?id={short_uri}"
                if short_uri
                else ""
            ),
            "export_id": export_id,
        }
        return {
            "source": "finder_preview_api",
            "reference": reference,
            "available": bool(feed) and warning["type"] == 0,
            "description": str(feed.get("description") or ""),
            "published_timestamp": published_timestamp,
            "published_at": _timestamp_iso(published_timestamp),
            "author": {
                "nickname": str(author.get("nickname") or author.get("nickName") or ""),
                "username": str(
                    author.get("username")
                    or author.get("userName")
                    or author.get("finderUsername")
                    or ""
                ),
                "signature": str(author.get("signature") or ""),
                "avatar_url": _url(author.get("headImgUrl") or author.get("avatarUrl")),
                "auth_icon_url": _url(author.get("authIconUrl")),
                "verified": bool(author.get("authIconUrl") or author.get("authInfo")),
                "auth_info": str(author.get("authInfo") or ""),
            },
            "ids": {
                "object_id": str(feed.get("objectId") or feed.get("id") or ""),
                "object_nonce_id": str(feed.get("objectNonceId") or ""),
                "dynamic_export_id": dynamic_export_id,
            },
            "stats": stats,
            "stats_formatted": stats_formatted,
            "stats_metadata": stats_metadata,
            "media": {
                "type": media_type,
                "type_code": media_type_code,
                "cover_url": _url(feed.get("coverUrl")),
                "videos": videos,
                "images": images,
            },
            "is_hard_ad": bool(feed.get("isHardAd")),
            "warning": warning,
            "scene": {
                "dynamic_export_id": dynamic_export_id,
                "comment_scene": _integer(scene.get("commentScene")),
                "expired_timestamp": expired_timestamp,
                "expired_at": _timestamp_iso(expired_timestamp),
                "request_scene": _integer(scene.get("requestScene")),
                "entry_scene": _integer(scene.get("entryScene")),
                "entry_card_type": _integer(scene.get("entryCardType")),
            },
            "raw": dict(root),
        }

    def get_feed(self, share_reference: str) -> dict[str, Any]:
        short_uri = self.resolve_short_uri(share_reference)
        payload = self._post_feed(
            {"baseReq": {"generalToken": ""}, "shortUri": short_uri},
            referer=f"{_BASE_URL}/finder-preview/pages/sph?id={short_uri}",
        )
        return self.parse_feed_payload(payload, short_uri=short_uri)

    def get_feed_by_export_id(self, export_id: str) -> dict[str, Any]:
        resolved = self.resolve_export_id(export_id)
        payload = self._post_feed(
            {"baseReq": {"generalToken": ""}, "exportId": resolved},
            referer=f"{_BASE_URL}/finder-preview/{resolved}",
        )
        return self.parse_feed_payload(payload, export_id=resolved)

    def _post_feed(self, body: Mapping[str, Any], *, referer: str) -> Mapping[str, Any]:
        response = self._send(
            _API_URL,
            json=dict(body),
            headers={"Referer": referer},
        )
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise WeChatChannelsResponseError(
                "WeChat Channels response is not JSON",
                status_code=response.status_code,
                url=str(response.url or _API_URL),
            ) from exc
        root = _mapping(payload)
        try:
            self._check_api_result(root)
        except WeChatChannelsResponseError as exc:
            status = int(response.status_code or 0)
            exc.status_code = status or None
            exc.url = str(response.url or _API_URL)
            exc.retryable = status in _RETRYABLE_STATUS
            raise
        status = int(response.status_code or 0)
        if status >= 400 or status <= 0:
            raise WeChatChannelsResponseError(
                f"WeChat Channels HTTP {status}",
                status_code=status,
                url=str(response.url or _API_URL),
                payload=payload,
                retryable=status in _RETRYABLE_STATUS,
            )
        return root

    @staticmethod
    def _check_api_result(root: Mapping[str, Any]) -> None:
        error = _mapping(root.get("error"))
        error_code = root.get("errCode")
        if error:
            message = str(error.get("message") or "WeChat Channels API returned an error")
            raise WeChatChannelsResponseError(
                message,
                error_code=str(error.get("name") or error_code or "ServerError"),
                payload=dict(root),
            )
        if error_code not in (None, 0, "0"):
            raise WeChatChannelsResponseError(
                str(root.get("errMsg") or "WeChat Channels API returned an error"),
                error_code=error_code,
                payload=dict(root),
            )

    def _send(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", False)
        for attempt in range(self.retries + 1):
            try:
                response = self.session.post(url, **kwargs)
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise WeChatChannelsResponseError(
                        f"WeChat Channels request failed: {exc}",
                        url=url,
                        retryable=True,
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue
            status = int(response.status_code or 0)
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            return response
        raise AssertionError("request retry loop exhausted")
