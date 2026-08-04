from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .errors import YouTubeInputError, YouTubeResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_WATCH_URL = "https://www.youtube.com/watch"
_SEARCH_URL = "https://www.youtube.com/results"
_OEMBED_URL = "https://www.youtube.com/oembed"
_INNERTUBE_PLAYER_URL = "https://www.youtube.com/youtubei/v1/player"
_INNERTUBE_SEARCH_URL = "https://www.youtube.com/youtubei/v1/search"
_INNERTUBE_NEXT_URL = "https://www.youtube.com/youtubei/v1/next"
_INNERTUBE_BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
_CHARTS_BROWSE_URL = "https://charts.youtube.com/youtubei/v1/browse"
_SEARCH_SUGGEST_URL = "https://suggestqueries-clients6.youtube.com/complete/search"
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,30}$")
_CHANNEL_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_REGION_RE = re.compile(r"^[A-Za-z]{2}$")
_PLAYER_ASSIGNMENT_RE = re.compile(
    r"(?:\bvar\s+)?(?:window\s*\[\s*['\"]ytInitialPlayerResponse['\"]\s*\]|"
    r"ytInitialPlayerResponse)\s*=\s*"
)
_INITIAL_DATA_ASSIGNMENT_RE = re.compile(
    r"(?:\bvar\s+)?(?:window\s*\[\s*['\"]ytInitialData['\"]\s*\]|"
    r"ytInitialData)\s*=\s*"
)
_YTCFG_SET_RE = re.compile(r"\bytcfg\.set\s*\(")
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_DISCOVERY_LIMIT = 100
_MAX_SUGGEST_LIMIT = 50
_MAX_TRENDING_LIMIT = 30
_MAX_CONTINUATION_LENGTH = 8192
_MAX_PAGES = 10
_COMMENTS_SECTION_IDS = {"comment-item-section", "engagement-panel-comments-section"}
_CONFIG_FIELDS = (
    "INNERTUBE_API_KEY",
    "INNERTUBE_CLIENT_NAME",
    "INNERTUBE_CLIENT_VERSION",
    "INNERTUBE_CONTEXT_CLIENT_NAME",
    "INNERTUBE_CONTEXT",
    "VISITOR_DATA",
    "STS",
    "HL",
    "GL",
)
_TRENDING_SECTIONS = {
    "music": {
        "chart_type": "TRENDING_VIDEOS",
        "response_type": "CHART_TYPE_TRENDING_VIDEOS",
        "route": "TrendingVideos",
        "label": "Trending Music",
    },
    "movies": {
        "chart_type": "TRENDING_MOVIES",
        "response_type": "CHART_TYPE_TRENDING_MOVIES",
        "route": "TrendingTrailers",
        "label": "Trending Movie Trailers",
    },
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> int | float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    item = _mapping(value)
    if "simpleText" in item:
        return str(item.get("simpleText") or "").strip()
    return "".join(
        str(_mapping(run).get("text") or "") for run in _list(item.get("runs"))
    ).strip()


def _thumbnails(value: Any) -> list[dict[str, Any]]:
    source = _mapping(value)
    values = source.get("thumbnails") if "thumbnails" in source else value
    output: list[dict[str, Any]] = []
    for item in _list(values):
        thumbnail = _mapping(item)
        url = str(thumbnail.get("url") or "").strip()
        if not url:
            continue
        output.append(
            {
                "url": url,
                "width": _integer(thumbnail.get("width")),
                "height": _integer(thumbnail.get("height")),
            }
        )
    return output


def _absolute_youtube_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    result = urljoin("https://www.youtube.com/", text)
    split = urlsplit(result)
    if split.scheme == "http" and (split.hostname or "").endswith("youtube.com"):
        return urlunsplit(("https", split.netloc, split.path, split.query, split.fragment))
    return result


def _append_query(url: str, name: str, value: str) -> str:
    split = urlsplit(url)
    query = parse_qsl(split.query, keep_blank_values=True)
    query = [(key, item) for key, item in query if key != name]
    query.append((name, value))
    return urlunsplit(
        (split.scheme, split.netloc, split.path, urlencode(query), split.fragment)
    )


def _walk_mappings(value: Any):
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _walk_mappings(item)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            yield from _walk_mappings(item)


def _compact_integer(value: Any) -> int:
    text = str(value or "").strip().upper().replace(",", "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMB]?)", text)
    if not match:
        return 0
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
        match.group(2)
    ]
    try:
        return int(float(match.group(1)) * multiplier)
    except (TypeError, ValueError, OverflowError):
        return 0


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise YouTubeInputError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise YouTubeInputError(f"{label} must not be empty")
    if len(text) > maximum:
        raise YouTubeInputError(f"{label} is too long")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise YouTubeInputError(f"{label} contains control characters")
    return text


def _continuation(value: Any) -> str:
    if value is None or value == "":
        return ""
    text = _bounded_text(value, "continuation", _MAX_CONTINUATION_LENGTH)
    if any(char.isspace() for char in text):
        raise YouTubeInputError("continuation contains whitespace")
    return text


def _limit(value: Any, *, default: int, maximum: int = _MAX_DISCOVERY_LIMIT) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise YouTubeInputError(f"limit must be between 1 and {maximum}")
    return value


class YouTubeClient:
    """无需浏览器运行时即可匿名读取 YouTube 公开视频数据。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
        language: str = "en",
        region: str = "US",
    ) -> None:
        normalized_language = language.strip() if isinstance(language, str) else ""
        normalized_region = region.strip().upper() if isinstance(region, str) else ""
        if not _LANGUAGE_RE.fullmatch(normalized_language):
            raise YouTubeInputError("language must be a BCP-47 language tag")
        if not _REGION_RE.fullmatch(normalized_region):
            raise YouTubeInputError("region must be a two-letter country code")

        self.session = session or requests.Session(impersonate="chrome")
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(0, retries)
        self.language = normalized_language
        self.region = normalized_region
        self.session.headers.update(
            {
                "Accept-Language": f"{self.language},en;q=0.8",
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def resolve_video_id(video_url_or_id: str) -> str:
        if not isinstance(video_url_or_id, str):
            raise YouTubeInputError("video reference must be a string")
        value = video_url_or_id.strip()
        if _VIDEO_ID_RE.fullmatch(value):
            return value
        if not value:
            raise YouTubeInputError("video reference is empty")

        candidate = value
        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        elif "://" not in candidate:
            candidate = f"https://{candidate}"
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")

        video_id = ""
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = parsed.path.strip("/").split("/", 1)[0]
        elif host in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "gaming.youtube.com",
            "youtube-nocookie.com",
            "www.youtube-nocookie.com",
        }:
            if parsed.path.rstrip("/") == "/watch":
                video_id = (parse_qs(parsed.query).get("v") or [""])[0]
            else:
                parts = [part for part in parsed.path.split("/") if part]
                if len(parts) >= 2 and parts[0].lower() in {
                    "embed",
                    "shorts",
                    "live",
                    "v",
                }:
                    video_id = parts[1]

        if not _VIDEO_ID_RE.fullmatch(video_id):
            raise YouTubeInputError(f"invalid YouTube video reference: {value}")
        return video_id

    @staticmethod
    def resolve_channel_reference(reference: str) -> dict[str, str]:
        value = _bounded_text(reference, "channel reference", 500)
        kind = ""
        identifier = ""
        if _CHANNEL_ID_RE.fullmatch(value):
            kind, identifier = "channel", value
        elif value.startswith("@") and _CHANNEL_SLUG_RE.fullmatch(value[1:]):
            kind, identifier = "handle", value[1:]
        elif _CHANNEL_SLUG_RE.fullmatch(value):
            kind, identifier = "handle", value
        else:
            candidate = value
            if candidate.startswith("//"):
                candidate = f"https:{candidate}"
            elif "://" not in candidate:
                candidate = f"https://{candidate}"
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").lower().rstrip(".")
            if host not in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
                "music.youtube.com",
            }:
                raise YouTubeInputError(f"invalid YouTube channel reference: {value}")
            parts = [part for part in parsed.path.split("/") if part]
            if not parts:
                raise YouTubeInputError(f"invalid YouTube channel reference: {value}")
            head = parts[0]
            if head.startswith("@") and _CHANNEL_SLUG_RE.fullmatch(head[1:]):
                kind, identifier = "handle", head[1:]
            elif (
                len(parts) >= 2
                and head.lower() in {"channel", "c", "user"}
                and _CHANNEL_SLUG_RE.fullmatch(parts[1])
            ):
                kind, identifier = head.lower(), parts[1]
            else:
                raise YouTubeInputError(f"invalid YouTube channel reference: {value}")

        prefix = f"/@{identifier}" if kind == "handle" else f"/{kind}/{identifier}"
        return {
            "kind": kind,
            "id": identifier if kind == "channel" else "",
            "handle": identifier if kind == "handle" else "",
            "url": f"https://www.youtube.com{prefix}",
            "videos_url": f"https://www.youtube.com{prefix}/videos",
        }

    @staticmethod
    def extract_initial_data(source: str) -> dict[str, Any]:
        if not isinstance(source, str) or not source:
            raise YouTubeResponseError("YouTube HTML is empty")
        decoder = json.JSONDecoder()
        for match in _INITIAL_DATA_ASSIGNMENT_RE.finditer(source):
            try:
                value, _ = decoder.raw_decode(source, match.end())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, Mapping):
                return dict(value)
        value = YouTubeClient._extract_named_json_value(source, "ytInitialData")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                value = None
        if isinstance(value, Mapping):
            return dict(value)
        raise YouTubeResponseError("YouTube HTML does not contain ytInitialData")

    @staticmethod
    def extract_player_response(source: str) -> dict[str, Any]:
        if not isinstance(source, str) or not source:
            raise YouTubeResponseError("watch HTML is empty")
        decoder = json.JSONDecoder()
        for match in _PLAYER_ASSIGNMENT_RE.finditer(source):
            try:
                value, _ = decoder.raw_decode(source, match.end())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, Mapping):
                return dict(value)

        for name in ("PLAYER_RESPONSE", "ytInitialPlayerResponse"):
            value = YouTubeClient._extract_named_json_value(source, name)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    value = None
            if isinstance(value, Mapping):
                return dict(value)
        raise YouTubeResponseError("watch HTML does not contain ytInitialPlayerResponse")

    @staticmethod
    def extract_innertube_config(source: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        merged: dict[str, Any] = {}
        for match in _YTCFG_SET_RE.finditer(source):
            offset = match.end()
            while offset < len(source) and source[offset].isspace():
                offset += 1
            try:
                value, _ = decoder.raw_decode(source, offset)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, Mapping):
                merged.update(value)

        for name in _CONFIG_FIELDS:
            if name not in merged:
                value = YouTubeClient._extract_named_json_value(source, name)
                if value is not None:
                    merged[name] = value

        context = copy.deepcopy(dict(_mapping(merged.get("INNERTUBE_CONTEXT"))))
        client = _mapping(context.get("client"))
        visitor_data = str(
            merged.get("VISITOR_DATA") or client.get("visitorData") or ""
        )
        return {
            "api_key": str(merged.get("INNERTUBE_API_KEY") or ""),
            "client_name": str(
                merged.get("INNERTUBE_CLIENT_NAME")
                or client.get("clientName")
                or "WEB"
            ),
            "client_version": str(
                merged.get("INNERTUBE_CLIENT_VERSION")
                or client.get("clientVersion")
                or ""
            ),
            "client_name_id": _integer(
                merged.get("INNERTUBE_CONTEXT_CLIENT_NAME")
            ),
            "visitor_data": visitor_data,
            "signature_timestamp": _integer(merged.get("STS")),
            "hl": str(merged.get("HL") or client.get("hl") or ""),
            "gl": str(merged.get("GL") or client.get("gl") or ""),
            "context": context,
        }

    @staticmethod
    def _extract_named_json_value(source: str, name: str) -> Any:
        decoder = json.JSONDecoder()
        pattern = re.compile(rf"['\"]{re.escape(name)}['\"]\s*:\s*")
        for match in pattern.finditer(source):
            try:
                value, _ = decoder.raw_decode(source, match.end())
            except (json.JSONDecodeError, TypeError):
                continue
            return value
        return None

    @staticmethod
    def _endpoint_channel(value: Any) -> dict[str, str]:
        endpoint = _mapping(value)
        browse = _mapping(endpoint.get("browseEndpoint"))
        command = _mapping(endpoint.get("commandMetadata"))
        web = _mapping(command.get("webCommandMetadata"))
        channel_id = str(browse.get("browseId") or "")
        relative = str(browse.get("canonicalBaseUrl") or web.get("url") or "")
        return {
            "id": channel_id,
            "name": "",
            "url": _absolute_youtube_url(relative),
        }

    @classmethod
    def _channel_from_runs(cls, value: Any) -> dict[str, str]:
        runs = _list(_mapping(value).get("runs"))
        if not runs:
            return {"id": "", "name": _text(value), "url": ""}
        run = _mapping(runs[0])
        channel = cls._endpoint_channel(run.get("navigationEndpoint"))
        channel["name"] = str(run.get("text") or "")
        return channel

    @staticmethod
    def _discovery_thumbnails(value: Any) -> list[dict[str, Any]]:
        thumbnails = _thumbnails(value)
        for thumbnail in thumbnails:
            thumbnail["url"] = _absolute_youtube_url(thumbnail["url"])
        return thumbnails

    @staticmethod
    def _badges(value: Any) -> list[str]:
        output: list[str] = []
        for item in _list(value):
            renderer = _mapping(_mapping(item).get("metadataBadgeRenderer"))
            text = str(
                renderer.get("label")
                or renderer.get("tooltip")
                or _mapping(renderer.get("accessibilityData")).get("label")
                or ""
            ).strip()
            if text and text not in output:
                output.append(text)
        return output

    @classmethod
    def _normalize_video_renderer(cls, value: Mapping[str, Any]) -> dict[str, Any] | None:
        video_id = str(value.get("videoId") or "")
        if not _VIDEO_ID_RE.fullmatch(video_id):
            return None
        channel = cls._channel_from_runs(
            value.get("longBylineText")
            or value.get("ownerText")
            or value.get("shortBylineText")
        )
        badges = cls._badges(value.get("badges"))
        for badge in cls._badges(value.get("ownerBadges")):
            if badge not in badges:
                badges.append(badge)
        description = _text(value.get("descriptionSnippet"))
        if not description:
            description = " ".join(
                part
                for part in (
                    _text(_mapping(item).get("snippetText"))
                    for item in _list(value.get("detailedMetadataSnippets"))
                )
                if part
            )
        return {
            "type": "video",
            "id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": _text(value.get("title")),
            "description": description,
            "channel": channel,
            "duration_text": _text(value.get("lengthText")),
            "published_text": _text(value.get("publishedTimeText")),
            "views_text": _text(
                value.get("viewCountText") or value.get("shortViewCountText")
            ),
            "thumbnails": cls._discovery_thumbnails(value.get("thumbnail")),
            "badges": badges,
        }

    @classmethod
    def _normalize_channel_renderer(cls, value: Mapping[str, Any]) -> dict[str, Any] | None:
        channel_id = str(value.get("channelId") or "")
        if not channel_id:
            return None
        channel = cls._endpoint_channel(value.get("navigationEndpoint"))
        url = channel["url"] or f"https://www.youtube.com/channel/{channel_id}"
        path = urlsplit(url).path.strip("/")
        handle = path if path.startswith("@") else ""
        return {
            "type": "channel",
            "id": channel_id,
            "url": url,
            "title": _text(value.get("title")),
            "handle": handle,
            "description": _text(value.get("descriptionSnippet")),
            "subscribers_text": _text(value.get("subscriberCountText")),
            "video_count_text": _text(value.get("videoCountText")),
            "thumbnails": cls._discovery_thumbnails(value.get("thumbnail")),
            "badges": cls._badges(value.get("ownerBadges")),
        }

    @classmethod
    def _normalize_playlist_renderer(cls, value: Mapping[str, Any]) -> dict[str, Any] | None:
        playlist_id = str(value.get("playlistId") or "")
        if not playlist_id:
            return None
        channel = cls._channel_from_runs(
            value.get("longBylineText") or value.get("shortBylineText")
        )
        return {
            "type": "playlist",
            "id": playlist_id,
            "url": f"https://www.youtube.com/playlist?list={quote(playlist_id)}",
            "title": _text(value.get("title")),
            "channel": channel,
            "video_count_text": _text(value.get("videoCountText")),
            "thumbnails": cls._discovery_thumbnails(value.get("thumbnails")),
            "badges": cls._badges(value.get("badges")),
        }

    @classmethod
    def _normalize_lockup_video(cls, value: Mapping[str, Any]) -> dict[str, Any] | None:
        if str(value.get("contentType") or "") != "LOCKUP_CONTENT_TYPE_VIDEO":
            return None
        video_id = str(value.get("contentId") or "")
        if not _VIDEO_ID_RE.fullmatch(video_id):
            return None
        metadata = _mapping(_mapping(value.get("metadata")).get("lockupMetadataViewModel"))
        content_metadata = _mapping(
            _mapping(metadata.get("metadata")).get("contentMetadataViewModel")
        )
        parts: list[str] = []
        for row in _list(content_metadata.get("metadataRows")):
            for part in _list(_mapping(row).get("metadataParts")):
                text = str(_mapping(_mapping(part).get("text")).get("content") or "")
                if text:
                    parts.append(text)
        image = _mapping(
            _mapping(_mapping(value.get("contentImage")).get("thumbnailViewModel")).get("image")
        )
        duration = ""
        for node in _walk_mappings(value.get("contentImage")):
            badge = _mapping(node.get("thumbnailBadgeViewModel"))
            candidate = str(badge.get("text") or "")
            if re.fullmatch(r"\d+(?::\d+)+", candidate):
                duration = candidate
                break
        return {
            "type": "video",
            "id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": str(_mapping(metadata.get("title")).get("content") or ""),
            "description": "",
            "channel": {"id": "", "name": "", "url": ""},
            "duration_text": duration,
            "published_text": parts[1] if len(parts) > 1 else "",
            "views_text": parts[0] if parts else "",
            "thumbnails": cls._discovery_thumbnails(image.get("sources")),
            "badges": [],
        }

    @classmethod
    def _normalize_short_lockup(cls, value: Mapping[str, Any]) -> dict[str, Any] | None:
        video_id = str(value.get("videoId") or value.get("contentId") or "")
        if not _VIDEO_ID_RE.fullmatch(video_id):
            endpoint = _mapping(_mapping(value.get("onTap")).get("innertubeCommand"))
            video_id = str(_mapping(endpoint.get("reelWatchEndpoint")).get("videoId") or "")
        if not _VIDEO_ID_RE.fullmatch(video_id):
            return None
        title = _text(value.get("headline")) or str(
            _mapping(_mapping(value.get("accessibilityText")).get("accessibilityData")).get("label")
            or ""
        )
        image = _mapping(
            _mapping(_mapping(value.get("thumbnail")).get("thumbnailViewModel")).get("image")
        )
        return {
            "type": "video",
            "id": video_id,
            "url": f"https://www.youtube.com/shorts/{video_id}",
            "title": title,
            "description": "",
            "channel": {"id": "", "name": "", "url": ""},
            "duration_text": "",
            "published_text": "",
            "views_text": _text(value.get("viewCountText")),
            "thumbnails": cls._discovery_thumbnails(
                image.get("sources") or value.get("thumbnail")
            ),
            "badges": ["Shorts"],
        }

    @classmethod
    def normalize_discovery_items(
        cls, value: Any, *, videos_only: bool = False
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for node in _walk_mappings(value):
            item: dict[str, Any] | None = None
            if isinstance(node.get("videoRenderer"), Mapping):
                item = cls._normalize_video_renderer(_mapping(node["videoRenderer"]))
            elif not videos_only and isinstance(node.get("channelRenderer"), Mapping):
                item = cls._normalize_channel_renderer(_mapping(node["channelRenderer"]))
            elif not videos_only and isinstance(node.get("playlistRenderer"), Mapping):
                item = cls._normalize_playlist_renderer(_mapping(node["playlistRenderer"]))
            elif isinstance(node.get("lockupViewModel"), Mapping):
                item = cls._normalize_lockup_video(_mapping(node["lockupViewModel"]))
            elif isinstance(node.get("shortsLockupViewModel"), Mapping):
                item = cls._normalize_short_lockup(_mapping(node["shortsLockupViewModel"]))
            if not item:
                continue
            key = (str(item["type"]), str(item["id"]))
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

    @staticmethod
    def _continuation_candidates(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, str]]:
        output: list[tuple[str, str]] = []
        if isinstance(value, Mapping):
            command = _mapping(value.get("continuationCommand"))
            token = str(command.get("token") or "")
            if token:
                output.append((".".join(path), token))
            for key, item in value.items():
                output.extend(YouTubeClient._continuation_candidates(item, (*path, str(key))))
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for index, item in enumerate(value):
                output.extend(
                    YouTubeClient._continuation_candidates(item, (*path, str(index)))
                )
        return output

    @classmethod
    def next_continuation(cls, value: Any) -> str:
        candidates = cls._continuation_candidates(value)
        standalone = [
            (path, token)
            for path, token in candidates
            if "continuationItemRenderer" in path and "commentRepliesRenderer" not in path
        ]
        if not standalone:
            return ""

        def rank(candidate: tuple[str, str]) -> tuple[int, int, int, str, str]:
            path, token = candidate
            segments = path.split(".")
            return (
                0
                if any(
                    segment
                    in {
                        "onResponseReceivedActions",
                        "onResponseReceivedCommands",
                        "onResponseReceivedEndpoints",
                    }
                    for segment in segments
                )
                else 1,
                0 if "continuationItems" in segments else 1,
                0
                if any(
                    segment
                    in {
                        "appendContinuationItemsAction",
                        "reloadContinuationItemsCommand",
                    }
                    for segment in segments
                )
                else 1,
                path,
                token,
            )

        return min(standalone, key=rank)[1]

    @classmethod
    def initial_comments_continuation(cls, value: Any) -> str:
        root = _mapping(value)
        identified_panel_seen = False
        comments_panel_seen = False
        selected: list[tuple[str, str]] = []
        for index, panel_value in enumerate(_list(root.get("engagementPanels"))):
            renderer = _mapping(_mapping(panel_value).get("engagementPanelSectionListRenderer"))
            identifiers = {
                str(renderer.get("panelIdentifier") or ""),
                str(renderer.get("targetId") or ""),
            }
            identifiers.discard("")
            if identifiers:
                identified_panel_seen = True
            if not identifiers.intersection(_COMMENTS_SECTION_IDS):
                continue
            comments_panel_seen = True
            for path, token in cls._continuation_candidates(renderer.get("content")):
                if (
                    "continuationItemRenderer" in path
                    and "header" not in path
                    and "commentRepliesRenderer" not in path
                ):
                    selected.append((f"{index}.{path}", token))
        if selected:
            return min(selected)[1]
        if comments_panel_seen or identified_panel_seen:
            return ""

        # 旧页面缺少面板标识符，因此保留边界明确的结构兜底。
        candidates = cls._continuation_candidates(value)
        preferred = [
            (path, token)
            for path, token in candidates
            if "engagementPanels" in path
            and "content" in path
            and "continuationItemRenderer" in path
            and "header" not in path
            and "commentRepliesRenderer" not in path
        ]
        if preferred:
            return min(preferred)[1]
        return ""

    @classmethod
    def normalize_comments(cls, value: Any) -> list[dict[str, Any]]:
        reply_cursors: dict[str, str] = {}
        comment_meta: dict[str, dict[str, Any]] = {}
        for node in _walk_mappings(value):
            thread = _mapping(node.get("commentThreadRenderer"))
            if thread:
                comment = _mapping(thread.get("comment"))
                legacy = _mapping(comment.get("commentRenderer"))
                modern_container = _mapping(comment.get("commentViewModel"))
                modern = _mapping(modern_container.get("commentViewModel")) or modern_container
                comment_id = str(
                    legacy.get("commentId")
                    or modern.get("commentId")
                    or modern.get("commentKey")
                    or ""
                )
                if comment_id:
                    token = ""
                    for path, candidate in cls._continuation_candidates(thread.get("replies")):
                        if "commentRepliesRenderer" in path:
                            token = candidate
                            break
                    if token:
                        reply_cursors[comment_id] = token
                    comment_meta[comment_id] = {
                        "is_pinned": bool(modern.get("pinnedText"))
                        or bool(legacy.get("pinnedCommentBadge"))
                    }

        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        updates = _mapping(_mapping(value).get("frameworkUpdates"))
        batch = _mapping(updates.get("entityBatchUpdate"))
        mutations = _list(batch.get("mutations"))
        for mutation in mutations:
            entity = _mapping(_mapping(_mapping(mutation).get("payload")).get("commentEntityPayload"))
            if not entity:
                continue
            properties = _mapping(entity.get("properties"))
            author = _mapping(entity.get("author"))
            toolbar = _mapping(entity.get("toolbar"))
            comment_id = str(properties.get("commentId") or "")
            if not comment_id or comment_id in seen:
                continue
            seen.add(comment_id)
            channel = cls._endpoint_channel(
                _mapping(_mapping(author.get("channelCommand")).get("innertubeCommand"))
            )
            output.append(
                {
                    "id": comment_id,
                    "text": str(_mapping(properties.get("content")).get("content") or ""),
                    "published_text": str(properties.get("publishedTime") or ""),
                    "reply_level": _integer(properties.get("replyLevel")),
                    "author": {
                        "id": str(author.get("channelId") or channel["id"]),
                        "name": str(author.get("displayName") or ""),
                        "url": channel["url"],
                        "avatar_url": str(author.get("avatarThumbnailUrl") or ""),
                        "is_verified": bool(author.get("isVerified")),
                        "is_creator": bool(author.get("isCreator")),
                    },
                    "likes": _compact_integer(
                        toolbar.get("likeCountNotliked") or toolbar.get("likeCountLiked")
                    ),
                    "likes_text": str(
                        toolbar.get("likeCountNotliked") or toolbar.get("likeCountLiked") or ""
                    ),
                    "reply_count": _compact_integer(toolbar.get("replyCount")),
                    "reply_count_text": str(toolbar.get("replyCount") or ""),
                    "is_pinned": bool(comment_meta.get(comment_id, {}).get("is_pinned")),
                    "is_hearted": bool(toolbar.get("heartActiveTooltip")),
                    "replies_cursor": reply_cursors.get(comment_id, ""),
                }
            )

        for node in _walk_mappings(value):
            renderer = _mapping(node.get("commentRenderer"))
            comment_id = str(renderer.get("commentId") or "")
            if not comment_id or comment_id in seen:
                continue
            seen.add(comment_id)
            endpoint = _mapping(renderer.get("authorEndpoint"))
            channel = cls._endpoint_channel(endpoint)
            avatar = cls._discovery_thumbnails(renderer.get("authorThumbnail"))
            likes_text = _text(renderer.get("voteCount"))
            reply_count = _integer(renderer.get("replyCount"))
            output.append(
                {
                    "id": comment_id,
                    "text": _text(renderer.get("contentText")),
                    "published_text": _text(renderer.get("publishedTimeText")),
                    "reply_level": 0,
                    "author": {
                        "id": channel["id"],
                        "name": _text(renderer.get("authorText")),
                        "url": channel["url"],
                        "avatar_url": avatar[-1]["url"] if avatar else "",
                        "is_verified": bool(renderer.get("authorCommentBadge")),
                        "is_creator": bool(renderer.get("authorIsChannelOwner")),
                    },
                    "likes": _compact_integer(likes_text),
                    "likes_text": likes_text,
                    "reply_count": reply_count,
                    "reply_count_text": str(reply_count) if reply_count else "",
                    "is_pinned": bool(renderer.get("pinnedCommentBadge")),
                    "is_hearted": bool(renderer.get("creatorHeart")),
                    "replies_cursor": reply_cursors.get(comment_id, ""),
                }
            )
        return output

    @staticmethod
    def comments_count_text(value: Any) -> str:
        for node in _walk_mappings(value):
            renderer = _mapping(node.get("commentsHeaderRenderer"))
            if renderer:
                return _text(renderer.get("countText"))
        return ""

    @classmethod
    def normalize_channel_identity(
        cls, value: Any, fallback: Mapping[str, str]
    ) -> dict[str, str]:
        result = {
            "id": str(fallback.get("id") or ""),
            "name": "",
            "handle": str(fallback.get("handle") or ""),
            "url": str(fallback.get("url") or ""),
        }
        for node in _walk_mappings(value):
            metadata = _mapping(node.get("channelMetadataRenderer"))
            if not metadata:
                continue
            result["id"] = str(metadata.get("externalId") or result["id"])
            result["name"] = str(metadata.get("title") or result["name"])
            result["url"] = str(
                metadata.get("vanityChannelUrl")
                or metadata.get("channelUrl")
                or result["url"]
            )
            path = urlsplit(result["url"]).path.strip("/")
            if path.startswith("@"):
                result["handle"] = path[1:]
            break
        return result

    @classmethod
    def parse_watch_html(
        cls,
        source: str,
        *,
        expected_video_id: str | None = None,
    ) -> dict[str, Any]:
        response = cls.extract_player_response(source)
        return cls.normalize_player_response(
            response,
            expected_video_id=expected_video_id,
            source="watch_html",
        )

    @classmethod
    def normalize_player_response(
        cls,
        response: Mapping[str, Any],
        *,
        expected_video_id: str | None = None,
        source: str = "player_response",
    ) -> dict[str, Any]:
        details = _mapping(response.get("videoDetails"))
        playability = _mapping(response.get("playabilityStatus"))
        if not details:
            status = str(playability.get("status") or "UNKNOWN")
            reason = cls._playability_reason(playability)
            suffix = f": {reason}" if reason else ""
            raise YouTubeResponseError(f"YouTube player status {status}{suffix}")

        video_id = str(details.get("videoId") or "")
        if not _VIDEO_ID_RE.fullmatch(video_id):
            raise YouTubeResponseError("player response does not contain a valid video ID")
        if expected_video_id and video_id != expected_video_id:
            raise YouTubeResponseError(
                f"player response video ID mismatch: expected {expected_video_id}, got {video_id}"
            )

        microformat = _mapping(
            _mapping(response.get("microformat")).get("playerMicroformatRenderer")
        )
        streaming = _mapping(response.get("streamingData"))
        formats = [
            cls._normalize_format(item)
            for item in _list(streaming.get("formats"))
            if isinstance(item, Mapping)
        ]
        adaptive_formats = [
            cls._normalize_format(item)
            for item in _list(streaming.get("adaptiveFormats"))
            if isinstance(item, Mapping)
        ]
        thumbnails = _thumbnails(details.get("thumbnail"))
        if not thumbnails:
            thumbnails = _thumbnails(microformat.get("thumbnail"))
        channel_id = str(
            details.get("channelId") or microformat.get("externalChannelId") or ""
        )
        author_name = str(
            details.get("author") or microformat.get("ownerChannelName") or ""
        )
        author_url = _absolute_youtube_url(microformat.get("ownerProfileUrl"))
        if not author_url and channel_id:
            author_url = f"https://www.youtube.com/channel/{channel_id}"

        caption_data = cls._normalize_captions(response.get("captions"))
        status = str(playability.get("status") or "UNKNOWN")
        return {
            "id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "source": source,
            "title": str(details.get("title") or _text(microformat.get("title"))),
            "description": str(
                details.get("shortDescription")
                or _text(microformat.get("description"))
            ),
            "duration_seconds": _integer(
                details.get("lengthSeconds") or microformat.get("lengthSeconds")
            ),
            "author": {
                "id": channel_id,
                "name": author_name,
                "url": author_url,
            },
            "stats": {
                "views": _integer(
                    details.get("viewCount") or microformat.get("viewCount")
                ),
                "likes": _integer(microformat.get("likeCount")),
            },
            "thumbnails": thumbnails,
            "thumbnail_url": thumbnails[-1]["url"] if thumbnails else "",
            "keywords": [
                str(item) for item in _list(details.get("keywords")) if str(item)
            ],
            "category": str(microformat.get("category") or ""),
            "publish_date": str(microformat.get("publishDate") or ""),
            "upload_date": str(microformat.get("uploadDate") or ""),
            "available_countries": [
                str(item)
                for item in _list(microformat.get("availableCountries"))
                if str(item)
            ],
            "is_live": bool(details.get("isLiveContent")),
            "is_private": bool(details.get("isPrivate")),
            "is_unlisted": bool(microformat.get("isUnlisted")),
            "is_family_safe": bool(microformat.get("isFamilySafe")),
            "playability": {
                "status": status,
                "reason": cls._playability_reason(playability),
                "playable_in_embed": bool(playability.get("playableInEmbed")),
            },
            "streams": {
                "expires_in_seconds": _integer(streaming.get("expiresInSeconds")),
                "hls_manifest_url": str(streaming.get("hlsManifestUrl") or ""),
                "dash_manifest_url": str(streaming.get("dashManifestUrl") or ""),
                "server_abr_streaming_url": str(
                    streaming.get("serverAbrStreamingUrl") or ""
                ),
                "formats": formats,
                "adaptive_formats": adaptive_formats,
                "total": len(formats) + len(adaptive_formats),
            },
            "captions": caption_data,
        }

    @staticmethod
    def _playability_reason(playability: Mapping[str, Any]) -> str:
        reason = _text(playability.get("reason"))
        if reason:
            return reason
        messages = [_text(item) for item in _list(playability.get("messages"))]
        return " ".join(item for item in messages if item)

    @staticmethod
    def _normalize_format(value: Mapping[str, Any]) -> dict[str, Any]:
        mime_value = str(value.get("mimeType") or "")
        mime_type = mime_value.split(";", 1)[0].strip()
        codecs_match = re.search(r'codecs\s*=\s*["\']([^"\']+)["\']', mime_value)
        codecs = (
            [item.strip() for item in codecs_match.group(1).split(",")]
            if codecs_match
            else []
        )

        cipher_value = str(value.get("signatureCipher") or value.get("cipher") or "")
        cipher = parse_qs(cipher_value, keep_blank_values=True)
        url = str(value.get("url") or (cipher.get("url") or [""])[0])
        encrypted_signature = (cipher.get("s") or [""])[0]
        signature = (cipher.get("sig") or cipher.get("signature") or [""])[0]
        signature_parameter = (cipher.get("sp") or ["signature"])[0] or "signature"
        if url and signature:
            url = _append_query(url, signature_parameter, signature)
        query = parse_qs(urlsplit(url).query, keep_blank_values=True) if url else {}

        is_video = mime_type.startswith("video/")
        is_audio = mime_type.startswith("audio/")
        has_audio = is_audio or bool(value.get("audioQuality")) or (
            is_video and len(codecs) > 1
        )
        has_video = is_video
        if has_audio and has_video:
            stream_type = "muxed"
        elif has_video:
            stream_type = "video"
        elif has_audio:
            stream_type = "audio"
        else:
            stream_type = "unknown"

        return {
            "itag": _integer(value.get("itag")),
            "type": stream_type,
            "mime_type": mime_type,
            "codecs": codecs,
            "container": mime_type.split("/", 1)[1] if "/" in mime_type else "",
            "url": url,
            "has_direct_url": bool(value.get("url")),
            "requires_signature": bool(encrypted_signature),
            "requires_n_transform": bool(query.get("n")),
            "signature_parameter": signature_parameter if cipher_value else "",
            "encrypted_signature": encrypted_signature,
            "signature_cipher": cipher_value,
            "bitrate": _integer(value.get("bitrate")),
            "average_bitrate": _integer(value.get("averageBitrate")),
            "width": _integer(value.get("width")),
            "height": _integer(value.get("height")),
            "fps": _number(value.get("fps")),
            "quality": str(value.get("quality") or ""),
            "quality_label": str(value.get("qualityLabel") or ""),
            "audio_quality": str(value.get("audioQuality") or ""),
            "audio_sample_rate": _integer(value.get("audioSampleRate")),
            "audio_channels": _integer(value.get("audioChannels")),
            "content_length": _integer(value.get("contentLength")),
            "approx_duration_ms": _integer(value.get("approxDurationMs")),
            "last_modified": str(value.get("lastModified") or ""),
            "projection_type": str(value.get("projectionType") or ""),
            "init_range": dict(_mapping(value.get("initRange"))),
            "index_range": dict(_mapping(value.get("indexRange"))),
            "color_info": dict(_mapping(value.get("colorInfo"))),
            "audio_track": dict(_mapping(value.get("audioTrack"))),
        }

    @staticmethod
    def _normalize_captions(value: Any) -> dict[str, Any]:
        renderer = _mapping(
            _mapping(value).get("playerCaptionsTracklistRenderer")
        )
        tracks: list[dict[str, Any]] = []
        for item in _list(renderer.get("captionTracks")):
            track = _mapping(item)
            base_url = str(track.get("baseUrl") or "")
            if not base_url:
                continue
            kind = str(track.get("kind") or "")
            tracks.append(
                {
                    "id": str(track.get("vssId") or ""),
                    "url": base_url,
                    "name": _text(track.get("name")),
                    "language_code": str(track.get("languageCode") or ""),
                    "kind": kind,
                    "is_auto_generated": kind == "asr",
                    "is_translatable": bool(track.get("isTranslatable")),
                }
            )

        audio_tracks: list[dict[str, Any]] = []
        for item in _list(renderer.get("audioTracks")):
            track = _mapping(item)
            audio_tracks.append(
                {
                    "id": str(track.get("audioTrackId") or ""),
                    "caption_track_indices": [
                        _integer(index)
                        for index in _list(track.get("captionTrackIndices"))
                    ],
                    "default_caption_track_index": (
                        _integer(track.get("defaultCaptionTrackIndex"))
                        if track.get("defaultCaptionTrackIndex") is not None
                        else None
                    ),
                    "visibility": str(track.get("visibility") or ""),
                    "has_default_track": bool(track.get("hasDefaultTrack")),
                }
            )

        translations = [
            {
                "language_code": str(_mapping(item).get("languageCode") or ""),
                "name": _text(_mapping(item).get("languageName")),
            }
            for item in _list(renderer.get("translationLanguages"))
            if isinstance(item, Mapping)
        ]
        default_index = renderer.get("defaultAudioTrackIndex")
        return {
            "total": len(tracks),
            "tracks": tracks,
            "audio_tracks": audio_tracks,
            "translation_languages": translations,
            "default_audio_track_index": (
                _integer(default_index) if default_index is not None else None
            ),
        }

    def get_oembed(self, video_url_or_id: str) -> dict[str, Any]:
        video_id = self.resolve_video_id(video_url_or_id)
        response = self._request(
            "get",
            _OEMBED_URL,
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json",
            },
            headers={"Accept": "application/json"},
        )
        payload = self._response_json(response, "oEmbed")
        if not isinstance(payload, Mapping) or not payload.get("title"):
            raise YouTubeResponseError("YouTube oEmbed response is missing video metadata")
        return {
            "id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": str(payload.get("title") or ""),
            "author": {
                "name": str(payload.get("author_name") or ""),
                "url": str(payload.get("author_url") or ""),
            },
            "provider": {
                "name": str(payload.get("provider_name") or ""),
                "url": str(payload.get("provider_url") or ""),
            },
            "type": str(payload.get("type") or ""),
            "version": str(payload.get("version") or ""),
            "thumbnail": {
                "url": str(payload.get("thumbnail_url") or ""),
                "width": _integer(payload.get("thumbnail_width")),
                "height": _integer(payload.get("thumbnail_height")),
            },
            "embed": {
                "html": str(payload.get("html") or ""),
                "width": _integer(payload.get("width")),
                "height": _integer(payload.get("height")),
            },
        }

    def get_player_response(
        self,
        video_url_or_id: str,
        *,
        innertube_fallback: bool = True,
    ) -> dict[str, Any]:
        video_id = self.resolve_video_id(video_url_or_id)
        watch_html = self._get_watch_html(video_id)
        config = self.extract_innertube_config(watch_html)
        initial_error: YouTubeResponseError | None = None
        player_response: dict[str, Any] = {}
        try:
            player_response = self.extract_player_response(watch_html)
        except YouTubeResponseError as exc:
            initial_error = exc

        details = _mapping(player_response.get("videoDetails"))
        if details:
            return {
                "video_id": video_id,
                "source": "watch_html",
                "response": player_response,
                "innertube_config": config,
            }
        if not innertube_fallback:
            if initial_error:
                raise initial_error
            return {
                "video_id": video_id,
                "source": "watch_html",
                "response": player_response,
                "innertube_config": config,
            }

        try:
            fallback = self._request_innertube_player(video_id, config)
        except YouTubeResponseError as fallback_error:
            if player_response:
                return {
                    "video_id": video_id,
                    "source": "watch_html",
                    "response": player_response,
                    "innertube_config": config,
                }
            if initial_error:
                raise YouTubeResponseError(
                    f"{initial_error}; Innertube fallback failed: {fallback_error}"
                ) from fallback_error
            raise
        return {
            "video_id": video_id,
            "source": "innertube",
            "response": fallback,
            "innertube_config": config,
        }

    def get_innertube_player(
        self,
        video_url_or_id: str,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        video_id = self.resolve_video_id(video_url_or_id)
        resolved_config = dict(config or {})
        if not resolved_config:
            resolved_config = self.extract_innertube_config(
                self._get_watch_html(video_id)
            )
        response = self._request_innertube_player(video_id, resolved_config)
        return {
            "video_id": video_id,
            "source": "innertube",
            "response": response,
            "innertube_config": resolved_config,
        }

    def get_video(
        self,
        video_url_or_id: str,
        *,
        innertube_fallback: bool = True,
    ) -> dict[str, Any]:
        player = self.get_player_response(
            video_url_or_id,
            innertube_fallback=innertube_fallback,
        )
        return self.normalize_player_response(
            _mapping(player.get("response")),
            expected_video_id=str(player["video_id"]),
            source=str(player["source"]),
        )

    def get_caption_tracks(
        self,
        video_url_or_id: str,
        *,
        innertube_fallback: bool = True,
    ) -> dict[str, Any]:
        video = self.get_video(
            video_url_or_id,
            innertube_fallback=innertube_fallback,
        )
        captions = dict(_mapping(video.get("captions")))
        return {
            "video_id": video["id"],
            "source": video["source"],
            **captions,
        }

    def search(
        self,
        query: str,
        *,
        limit: int | None = 20,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        keyword = _bounded_text(query, "query", 200)
        requested_limit = _limit(limit, default=20)
        requested_cursor = _continuation(continuation)
        page_html = self._get_html(
            _SEARCH_URL,
            params={"search_query": keyword, "hl": self.language, "gl": self.region},
        )
        config = self.extract_innertube_config(page_html)
        initial = self.extract_initial_data(page_html)
        page = self._collect_pages(
            initial_payload=None if requested_cursor else initial,
            initial_cursor=requested_cursor,
            limit=requested_limit,
            parser=self.normalize_discovery_items,
            item_key=lambda item: (str(item.get("type") or ""), str(item.get("id") or "")),
            fetch=lambda token: self._request_innertube_continuation(
                _INNERTUBE_SEARCH_URL,
                config,
                token,
                referer=f"{_SEARCH_URL}?{urlencode({'search_query': keyword})}",
            ),
        )
        return {
            "kind": "search",
            "source": "youtube_ssr+innertube",
            "query": keyword,
            **page,
        }

    def get_trending_videos(
        self,
        section: str = "music",
        *,
        limit: int | None = 30,
    ) -> dict[str, Any]:
        section_key = self._trending_section(section)
        requested_limit = _limit(
            limit,
            default=_MAX_TRENDING_LIMIT,
            maximum=_MAX_TRENDING_LIMIT,
        )
        config = _TRENDING_SECTIONS[section_key]
        chart_query = urlencode(
            {
                "perspective": "CHART_DETAILS",
                "chart_params_country_code": self.region.lower(),
                "chart_params_chart_type": config["chart_type"],
            }
        )
        body = {
            "context": {
                "client": {
                    "clientName": "WEB_MUSIC_ANALYTICS",
                    "clientVersion": "2.0",
                    "hl": self.language,
                    "gl": self.region,
                }
            },
            "browseId": "FEmusic_analytics_charts_home",
            "query": chart_query,
        }
        referer = (
            "https://charts.youtube.com/charts/"
            f"{config['route']}/{self.region.lower()}/daily"
        )
        response = self._request(
            "post",
            _CHARTS_BROWSE_URL,
            params={"prettyPrint": "false"},
            json=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://charts.youtube.com",
                "Referer": referer,
                "X-YouTube-Client-Name": "31",
                "X-YouTube-Client-Version": "2.0",
            },
        )
        payload = self._response_json(response, "YouTube charts")
        if not isinstance(payload, Mapping):
            raise YouTubeResponseError("YouTube charts response is not an object")
        return self.normalize_trending_chart(
            payload,
            section=section_key,
            region=self.region,
            limit=requested_limit,
        )

    @staticmethod
    def _trending_section(value: Any) -> str:
        if not isinstance(value, str):
            raise YouTubeInputError("trending section must be a string")
        section = value.strip().lower()
        if section in {"now", "gaming"}:
            raise YouTubeInputError(
                f"YouTube retired the {section!r} Web trending section; "
                "supported sections are music and movies"
            )
        if section not in _TRENDING_SECTIONS:
            raise YouTubeInputError(
                "trending section must be one of: music, movies"
            )
        return section

    @classmethod
    def normalize_trending_chart(
        cls,
        payload: Mapping[str, Any],
        *,
        section: str,
        region: str,
        limit: int,
    ) -> dict[str, Any]:
        section_key = cls._trending_section(section)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise YouTubeInputError("trending limit must be an integer")
        if not 1 <= limit <= _MAX_TRENDING_LIMIT:
            raise YouTubeInputError(
                f"trending limit must be between 1 and {_MAX_TRENDING_LIMIT}"
            )

        content: Mapping[str, Any] = {}
        for node in _walk_mappings(payload):
            renderer = _mapping(node.get("musicAnalyticsSectionRenderer"))
            candidate = _mapping(renderer.get("content"))
            if isinstance(candidate.get("videos"), Sequence):
                content = candidate
                break
        if not content:
            raise YouTubeResponseError(
                "YouTube charts response does not contain a video chart"
            )

        metadata = _mapping(content.get("perspectiveMetadata"))
        request_params = _mapping(metadata.get("requestParams"))
        chart_params = _mapping(request_params.get("chartParams"))
        expected_type = _TRENDING_SECTIONS[section_key]["response_type"]
        response_type = str(chart_params.get("chartType") or "")
        if response_type != expected_type:
            raise YouTubeResponseError(
                "YouTube charts response chart type does not match the request"
            )

        raw_entries: list[Any] = []
        for group_value in _list(content.get("videos")):
            raw_entries.extend(_list(_mapping(group_value).get("videoViews")))
        if not raw_entries:
            raise YouTubeResponseError("YouTube charts response contains no videos")

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, value in enumerate(raw_entries):
            item = _mapping(value)
            video_id = str(item.get("id") or "")
            if not _VIDEO_ID_RE.fullmatch(video_id) or video_id in seen:
                continue
            seen.add(video_id)
            position = _integer(
                _mapping(item.get("chartEntryMetadata")).get("currentPosition")
            )
            if position <= 0:
                position = index + 1
            release = _mapping(item.get("releaseDate"))
            year = _integer(release.get("year"))
            month = _integer(release.get("month"))
            day = _integer(release.get("day"))
            release_date = (
                f"{year:04d}-{month:02d}-{day:02d}"
                if year > 0 and 1 <= month <= 12 and 1 <= day <= 31
                else None
            )
            artists: list[dict[str, str]] = []
            for artist_value in _list(item.get("artists")):
                artist = _mapping(artist_value)
                name = str(artist.get("name") or "").strip()
                if name:
                    artists.append(
                        {
                            "id": str(artist.get("kgMid") or ""),
                            "name": name,
                        }
                    )
            channel_id = str(item.get("externalChannelId") or "")
            channel_url = (
                f"https://www.youtube.com/channel/{channel_id}"
                if _CHANNEL_ID_RE.fullmatch(channel_id)
                else ""
            )
            items.append(
                {
                    "rank": position,
                    "id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": str(item.get("title") or "").strip(),
                    "duration_seconds": _integer(item.get("videoDuration")),
                    "thumbnails": _thumbnails(item.get("thumbnail")),
                    "channel": {
                        "id": channel_id,
                        "name": str(item.get("channelName") or "").strip(),
                        "url": channel_url,
                    },
                    "artists": artists,
                    "release_date": release_date,
                    "available": item.get("isAvailable") is True,
                    "visible": item.get("isVisible") is True,
                    "songwriters": [
                        str(name).strip()
                        for name in _list(item.get("songwriters"))
                        if str(name).strip()
                    ],
                    "producers": [
                        str(name).strip()
                        for name in _list(item.get("songProducers"))
                        if str(name).strip()
                    ],
                    "share_card_url": str(item.get("shareCardUrl") or ""),
                }
            )
            if len(items) >= limit:
                break
        if not items:
            raise YouTubeResponseError(
                "YouTube charts response contains no valid video IDs"
            )

        response_region = str(chart_params.get("countryCode") or region).upper()
        return {
            "kind": "trending_videos",
            "source": "youtube_music_analytics_charts",
            "transport": "web_api",
            "section": section_key,
            "chart": _TRENDING_SECTIONS[section_key]["label"],
            "chart_type": response_type,
            "region": response_region,
            "requested_limit": limit,
            "total": len(items),
            "raw_count": len(raw_entries),
            "available_count": sum(
                1
                for item in items
                if item["available"] and item["visible"]
            ),
            "has_more": len(raw_entries) > len(items),
            "items": items,
        }

    def get_comments(
        self,
        video_url_or_id: str,
        *,
        limit: int | None = 20,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        video_id = self.resolve_video_id(video_url_or_id)
        requested_limit = _limit(limit, default=20)
        requested_cursor = _continuation(continuation)
        watch_html = self._get_watch_html(video_id)
        config = self.extract_innertube_config(watch_html)
        initial = self.extract_initial_data(watch_html)
        count_text = self.comments_count_text(initial)
        cursor = requested_cursor or self.initial_comments_continuation(initial)
        if not cursor:
            return {
                "kind": "comments",
                "source": "youtube_ssr+innertube",
                "video_id": video_id,
                "count_text": count_text,
                "comments_disabled": True,
                "requested_limit": requested_limit,
                "total": 0,
                "pages_fetched": 0,
                "has_more": False,
                "next_cursor": None,
                "cursor_stalled": False,
                "page_truncated": False,
                "items": [],
            }
        page = self._collect_pages(
            initial_payload=None,
            initial_cursor=cursor,
            limit=requested_limit,
            parser=self.normalize_comments,
            item_key=lambda item: str(item.get("id") or ""),
            fetch=lambda token: self._request_innertube_continuation(
                _INNERTUBE_NEXT_URL,
                config,
                token,
                referer=f"https://www.youtube.com/watch?v={quote(video_id)}",
            ),
        )
        return {
            "kind": "comments",
            "source": "youtube_ssr+innertube",
            "video_id": video_id,
            "count_text": count_text,
            "comments_disabled": False,
            **page,
        }

    def get_channel_videos(
        self,
        channel_reference: str,
        *,
        limit: int | None = 20,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        reference = self.resolve_channel_reference(channel_reference)
        requested_limit = _limit(limit, default=20)
        requested_cursor = _continuation(continuation)
        page_html = self._get_html(
            reference["videos_url"],
            params={"hl": self.language, "gl": self.region},
        )
        config = self.extract_innertube_config(page_html)
        initial = self.extract_initial_data(page_html)
        page = self._collect_pages(
            initial_payload=None if requested_cursor else initial,
            initial_cursor=requested_cursor,
            limit=requested_limit,
            parser=lambda payload: self.normalize_discovery_items(
                payload, videos_only=True
            ),
            item_key=lambda item: str(item.get("id") or ""),
            fetch=lambda token: self._request_innertube_continuation(
                _INNERTUBE_BROWSE_URL,
                config,
                token,
                referer=reference["videos_url"],
            ),
        )
        return {
            "kind": "channel_videos",
            "source": "youtube_ssr+innertube",
            "channel": self.normalize_channel_identity(initial, reference),
            **page,
        }

    def get_search_suggestions(
        self, query: str, *, limit: int | None = 10
    ) -> dict[str, Any]:
        keyword = _bounded_text(query, "query", 200)
        requested_limit = _limit(limit, default=10, maximum=_MAX_SUGGEST_LIMIT)
        response = self._request(
            "get",
            _SEARCH_SUGGEST_URL,
            params={
                "client": "firefox",
                "ds": "yt",
                "q": keyword,
                "hl": self.language,
                "gl": self.region,
            },
            headers={"Accept": "application/json"},
        )
        payload = self._response_json(response, "YouTube search suggestions")
        rows = _list(payload)
        values = _list(rows[1]) if len(rows) > 1 else []
        all_suggestions: list[str] = []
        for value in values:
            candidate = _list(value)
            text = str((candidate[0] if candidate else value) or "").strip()
            if text and text not in all_suggestions:
                all_suggestions.append(text)
        suggestions = all_suggestions[:requested_limit]
        return {
            "kind": "search_suggestions",
            "source": "youtube_suggest",
            "query": keyword,
            "requested_limit": requested_limit,
            "total": len(suggestions),
            "pages_fetched": 1,
            "has_more": False,
            "next_cursor": None,
            "cursor_stalled": False,
            "page_truncated": len(all_suggestions) > len(suggestions),
            "items": suggestions,
        }

    def _collect_pages(
        self,
        *,
        initial_payload: Mapping[str, Any] | None,
        initial_cursor: str,
        limit: int,
        parser: Any,
        item_key: Any,
        fetch: Any,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        seen_items: set[Any] = set()
        seen_cursors: set[str] = set()
        cursor = initial_cursor
        payload: Mapping[str, Any] | None = initial_payload
        pages_fetched = 0
        cursor_stalled = False
        page_truncated = False

        while pages_fetched < _MAX_PAGES and len(items) < limit:
            if payload is None:
                if not cursor:
                    break
                if cursor in seen_cursors:
                    cursor_stalled = True
                    cursor = ""
                    break
                seen_cursors.add(cursor)
                payload = fetch(cursor)
            pages_fetched += 1

            page_items: list[dict[str, Any]] = []
            for item in parser(payload):
                key = item_key(item)
                if not key or key in seen_items:
                    continue
                seen_items.add(key)
                page_items.append(item)

            remaining = limit - len(items)
            if len(page_items) > remaining:
                items.extend(page_items[:remaining])
                page_truncated = True
                cursor = ""
                break
            items.extend(page_items)

            next_cursor = self.next_continuation(payload)
            if next_cursor and (next_cursor == cursor or next_cursor in seen_cursors):
                cursor_stalled = True
                cursor = ""
                break
            cursor = next_cursor
            payload = None
            if not cursor:
                break

        return {
            "requested_limit": limit,
            "total": len(items),
            "pages_fetched": pages_fetched,
            "has_more": bool(cursor) and not page_truncated and not cursor_stalled,
            "next_cursor": cursor or None,
            "cursor_stalled": cursor_stalled,
            "page_truncated": page_truncated,
            "items": items,
        }

    def _get_html(self, url: str, *, params: Mapping[str, Any]) -> str:
        response = self._request(
            "get",
            url,
            params=dict(params),
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
        )
        source = str(response.text or "")
        if not source:
            raise YouTubeResponseError("YouTube HTML response is empty")
        return source

    def _request_innertube_continuation(
        self,
        url: str,
        config: Mapping[str, Any],
        continuation: str,
        *,
        referer: str,
    ) -> dict[str, Any]:
        api_key = str(config.get("api_key") or "")
        client_version = str(config.get("client_version") or "")
        if not api_key or not client_version:
            raise YouTubeResponseError(
                "YouTube HTML is missing the Innertube API key or client version"
            )
        context = copy.deepcopy(dict(_mapping(config.get("context"))))
        client = dict(_mapping(context.get("client")))
        client.update(
            {
                "clientName": str(config.get("client_name") or "WEB"),
                "clientVersion": client_version,
                "hl": self.language,
                "gl": self.region,
            }
        )
        visitor_data = str(config.get("visitor_data") or "")
        if visitor_data:
            client["visitorData"] = visitor_data
        context["client"] = client
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.youtube.com",
            "Referer": referer,
            "X-YouTube-Client-Version": client_version,
        }
        client_name_id = _integer(config.get("client_name_id"))
        if client_name_id:
            headers["X-YouTube-Client-Name"] = str(client_name_id)
        if visitor_data:
            headers["X-Goog-Visitor-Id"] = visitor_data
        response = self._request(
            "post",
            url,
            params={"key": api_key, "prettyPrint": "false"},
            json={"context": context, "continuation": continuation},
            headers=headers,
        )
        payload = self._response_json(response, "Innertube continuation")
        if not isinstance(payload, Mapping):
            raise YouTubeResponseError("Innertube continuation response is not an object")
        return dict(payload)

    def _get_watch_html(self, video_id: str) -> str:
        response = self._request(
            "get",
            _WATCH_URL,
            params={
                "v": video_id,
                "hl": self.language,
                "gl": self.region,
                "bpctr": "9999999999",
                "has_verified": "1",
            },
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
        )
        source = str(response.text or "")
        if not source:
            raise YouTubeResponseError("YouTube watch response is empty")
        return source

    def _request_innertube_player(
        self,
        video_id: str,
        config: Mapping[str, Any],
    ) -> dict[str, Any]:
        api_key = str(config.get("api_key") or "")
        client_version = str(config.get("client_version") or "")
        if not api_key or not client_version:
            raise YouTubeResponseError(
                "watch HTML is missing the Innertube API key or client version"
            )

        context = copy.deepcopy(dict(_mapping(config.get("context"))))
        client = dict(_mapping(context.get("client")))
        client.update(
            {
                "clientName": str(config.get("client_name") or "WEB"),
                "clientVersion": client_version,
                "hl": str(config.get("hl") or self.language),
                "gl": str(config.get("gl") or self.region),
            }
        )
        visitor_data = str(config.get("visitor_data") or "")
        if visitor_data:
            client["visitorData"] = visitor_data
        context["client"] = client

        content_playback_context: dict[str, Any] = {
            "html5Preference": "HTML5_PREF_WANTS"
        }
        signature_timestamp = _integer(config.get("signature_timestamp"))
        if signature_timestamp:
            content_playback_context["signatureTimestamp"] = signature_timestamp
        body = {
            "context": context,
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
            "playbackContext": {
                "contentPlaybackContext": content_playback_context,
            },
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.youtube.com",
            "Referer": f"https://www.youtube.com/watch?v={quote(video_id)}",
            "X-YouTube-Client-Version": client_version,
        }
        client_name_id = _integer(config.get("client_name_id"))
        if client_name_id:
            headers["X-YouTube-Client-Name"] = str(client_name_id)
        if visitor_data:
            headers["X-Goog-Visitor-Id"] = visitor_data

        response = self._request(
            "post",
            _INNERTUBE_PLAYER_URL,
            params={"key": api_key, "prettyPrint": "false"},
            json=body,
            headers=headers,
        )
        payload = self._response_json(response, "Innertube player")
        if not isinstance(payload, Mapping):
            raise YouTubeResponseError("Innertube player response is not an object")
        return dict(payload)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self.timeout)
        request = getattr(self.session, method)
        for attempt in range(self.retries + 1):
            try:
                response = request(url, **kwargs)
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise YouTubeResponseError(
                        f"YouTube request failed: {exc}"
                    ) from exc
                time.sleep(0.4 * (2**attempt))
                continue

            status = _integer(getattr(response, "status_code", 0))
            if 200 <= status < 300:
                return response
            if status in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            raise YouTubeResponseError(f"YouTube returned HTTP {status} for {url}")
        raise AssertionError("request retry loop ended unexpectedly")

    @staticmethod
    def _response_json(response: Any, label: str) -> Any:
        try:
            return response.json()
        except (ValueError, TypeError) as exc:
            raise YouTubeResponseError(f"{label} response is not valid JSON") from exc
