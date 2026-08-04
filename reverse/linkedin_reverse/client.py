from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

from curl_cffi import requests

from .ad_library import (
    normalize_ad_search_params,
    parse_ad_detail_html,
    parse_ad_search_html,
)
from .errors import LinkedInInputError, LinkedInResponseError

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_BASE_URL = "https://www.linkedin.com"
_AD_ID_RE = re.compile(r"^[1-9]\d{5,19}$")
_AD_DETAIL_PATH_RE = re.compile(r"^/ad-library/detail/([1-9]\d{5,19})/?$")
_AD_SEARCH_URL = f"{_BASE_URL}/ad-library/search"
_AD_PAGINATION_URL = f"{_BASE_URL}/ad-library/searchPaginationFragment"
_AD_MAX_PAGES = 100
_ACTIVITY_ID_RE = re.compile(r"^[1-9]\d{9,21}$")
_URN_RE = re.compile(r"^urn:li:(activity|share|ugcPost):([1-9]\d{9,21})$")
_POST_ACTIVITY_RE = re.compile(r"(?:^|-)activity-([1-9]\d{9,21})(?:-|$)")
_POST_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{9,399}$")
_ENTITY_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,99}$")
_ARTICLE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{4,399}$")
_URL_IN_TEXT_RE = re.compile(
    r"https?://[^\s<>\"'，。；：！？）】》」』]+", re.IGNORECASE
)
_LINKEDIN_HOST_PREFIX_RE = re.compile(
    r"^(?:(?:www|[a-z]{2})\.)?linkedin\.com/", re.IGNORECASE
)
_POST_PATH_RE = re.compile(r"^/posts/([^/]+)/?$")
_FEED_PATH_RE = re.compile(
    r"^/(?:embed/)?feed/update/(urn:li:(?:activity|share|ugcPost):[1-9]\d{9,21})/?$"
)
_PROFILE_PATH_RE = re.compile(r"^/in/([^/]+)/?$")
_AUTHOR_ARTICLES_PATH_RE = re.compile(
    r"^/in/([^/]+)/recent-activity/articles/?$", re.IGNORECASE
)
_COMPANY_PATH_RE = re.compile(r"^/company/([^/]+)(?:/about)?/?$")
_ARTICLE_PATH_RE = re.compile(r"^/pulse/([^/]+)/?$")
_JOB_ID_RE = re.compile(r"^[1-9]\d{5,19}$")
_JOB_URN_RE = re.compile(r"^urn:li:jobPosting:([1-9]\d{5,19})$")
_JOB_VIEW_PATH_RE = re.compile(
    r"^/jobs/view/(?:[^/]*-)?([1-9]\d{5,19})/?$", re.IGNORECASE
)
_JOB_DETAIL_PATH_RE = re.compile(
    r"^/jobs-guest/jobs/api/jobPosting/([1-9]\d{5,19})/?$", re.IGNORECASE
)
_JOBS_SEARCH_PATH_RE = re.compile(
    r"^/(?:jobs/search|jobs-guest/jobs/api/seeMoreJobPostings/search)/?$",
    re.IGNORECASE,
)
_JOBS_SEO_PATH_RE = re.compile(
    r"^/jobs/([A-Za-z0-9][A-Za-z0-9-]{0,199})-jobs/?$", re.IGNORECASE
)
_JOB_DETAIL_URL = f"{_BASE_URL}/jobs-guest/jobs/api/jobPosting"
_JOBS_SEARCH_URL = f"{_BASE_URL}/jobs-guest/jobs/api/seeMoreJobPostings/search"
_COMPANY_JOB_COUNT_URL = f"{_BASE_URL}/jobs/search"
_LOCATION_SUGGEST_URL = f"{_BASE_URL}/jobs-guest/api/typeaheadHits"
_ORGANIZATION_FEED_PATH_RE = re.compile(
    r"^/organization-guest/api/feedUpdates/([1-9]\d{0,19})/?$"
)
_SHOWCASE_PATH_RE = re.compile(r"^/showcase/([^/]+)/?$")
_ORGANIZATION_FEED_STARTS = tuple(range(10, 61, 10))
_JOBS_MAX_START = 1000
_JOBS_MAX_STALE_PAGES = 3
_TIME_RANGE_CODES = {
    "day": "r86400",
    "past-day": "r86400",
    "past_24h": "r86400",
    "r86400": "r86400",
    "week": "r604800",
    "past-week": "r604800",
    "past_week": "r604800",
    "r604800": "r604800",
    "month": "r2592000",
    "past-month": "r2592000",
    "past_month": "r2592000",
    "r2592000": "r2592000",
}
_JOB_TYPE_CODES = {
    "f": "F",
    "full-time": "F",
    "full_time": "F",
    "p": "P",
    "part-time": "P",
    "part_time": "P",
    "c": "C",
    "contract": "C",
    "t": "T",
    "temporary": "T",
    "i": "I",
    "internship": "I",
    "v": "V",
    "volunteer": "V",
    "o": "O",
    "other": "O",
}
_EXPERIENCE_CODES = {
    "1": "1",
    "internship": "1",
    "2": "2",
    "entry-level": "2",
    "entry_level": "2",
    "3": "3",
    "associate": "3",
    "4": "4",
    "mid-senior": "4",
    "mid_senior": "4",
    "5": "5",
    "director": "5",
    "6": "6",
    "executive": "6",
}
_REMOTE_CODES = {
    "1": "1",
    "on-site": "1",
    "on_site": "1",
    "onsite": "1",
    "2": "2",
    "remote": "2",
    "3": "3",
    "hybrid": "3",
}
_SORT_BY_CODES = {
    "relevant": "R",
    "r": "R",
    "recent": "DD",
    "dd": "DD",
}
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_COMMENT_SUFFIX_RE = re.compile(
    r"\s*\|\s*([0-9][0-9,]*)\s+comments?\s+on\s+LinkedIn\s*$",
    re.IGNORECASE,
)
_FOLLOWER_RE = re.compile(r"([0-9][0-9,]*)\s+followers?\s+on\s+LinkedIn", re.IGNORECASE)
_CONNECTION_RE = re.compile(r"([0-9][0-9,]*\+?)\s+connections?\s+on\s+LinkedIn", re.IGNORECASE)
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _schema_types(value: Mapping[str, Any]) -> set[str]:
    raw = value.get("@type")
    return {str(item) for item in _list(raw)} if isinstance(raw, list) else {str(raw or "")}


def _datetime_parts(value: Any) -> tuple[str | None, int | None]:
    source = _text(value)
    if not source:
        return None, None
    try:
        parsed = datetime.fromisoformat(source.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return source, None
    return parsed.isoformat(), int(parsed.timestamp())


def _duration_seconds(value: Any) -> int | float | None:
    source = _text(value)
    match = re.fullmatch(
        r"P(?:([0-9]+)D)?T(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+(?:\.[0-9]+)?)S)?",
        source,
    )
    if not match:
        return None
    seconds = (
        int(match.group(1) or 0) * 86400
        + int(match.group(2) or 0) * 3600
        + int(match.group(3) or 0) * 60
        + float(match.group(4) or 0)
    )
    return int(seconds) if seconds.is_integer() else seconds


def _clean_block_text(value: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _absolute_url(value: Any, *, base: str = _BASE_URL) -> str:
    source = html.unescape(_text(value))
    return urljoin(f"{base}/", source) if source else ""


def _image_url(value: Any) -> str:
    if isinstance(value, str):
        return _absolute_url(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            result = _image_url(item)
            if result:
                return result
        return ""
    image = _mapping(value)
    for key in ("url", "contentUrl", "thumbnailUrl"):
        result = _absolute_url(image.get(key))
        if result:
            return result
    return ""


def _interaction_counts(raw: Mapping[str, Any]) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "likes": None,
        "comments": None,
        "reposts": None,
    }
    values = raw.get("interactionStatistic")
    statistics = _list(values) if isinstance(values, list) else [values]
    for item in statistics:
        statistic = _mapping(item)
        action = _text(statistic.get("interactionType")).lower()
        count = _optional_int(statistic.get("userInteractionCount"))
        if "likeaction" in action:
            result["likes"] = count
        elif "commentaction" in action:
            result["comments"] = count
        elif "shareaction" in action or "repostaction" in action:
            result["reposts"] = count
    comment_count = _optional_int(raw.get("commentCount"))
    if comment_count is not None:
        result["comments"] = comment_count
    return result


def _follow_count(raw: Mapping[str, Any]) -> int | None:
    values = raw.get("interactionStatistic")
    statistics = _list(values) if isinstance(values, list) else [values]
    for item in statistics:
        statistic = _mapping(item)
        if "followaction" in _text(statistic.get("interactionType")).lower():
            return _optional_int(statistic.get("userInteractionCount"))
    return None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.canonical = ""
        self.json_ld: list[str] = []
        self.code: dict[str, str] = {}
        self.article_text_blocks: list[str] = []
        self.article_images: list[dict[str, str]] = []
        self.article_videos: list[dict[str, str]] = []
        self.article_embeds: list[str] = []
        self._script = False
        self._script_buffer: list[str] = []
        self._title = False
        self._title_buffer: list[str] = []
        self._code_id: str | None = None
        self._code_buffer: list[str] = []
        self._text_depth = 0
        self._text_buffer: list[str] = []
        self._image_depth = 0
        self._video_depth = 0
        self._embed_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lower_tag = tag.lower()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        test_id = values.get("data-test-id", "")

        if lower_tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = values.get("content", "")
        elif lower_tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "") or self.canonical
        elif lower_tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._script = True
            self._script_buffer = []
        elif lower_tag == "title":
            self._title = True
            self._title_buffer = []
        elif lower_tag == "code" and values.get("id"):
            self._code_id = values["id"]
            self._code_buffer = []

        self._start_capture(lower_tag, test_id)
        if self._image_depth and lower_tag == "img":
            url = values.get("data-delayed-url") or values.get("data-src") or values.get("src")
            if url:
                self.article_images.append(
                    {"url": _absolute_url(url), "alt": values.get("alt", "")}
                )
        if self._video_depth and lower_tag == "video":
            self.article_videos.append(values)
        if self._embed_depth and lower_tag in {"iframe", "embed"} and values.get("src"):
            self.article_embeds.append(_absolute_url(values["src"]))

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag == "script" and self._script:
            self.json_ld.append("".join(self._script_buffer))
            self._script = False
            self._script_buffer = []
        if lower_tag == "title" and self._title:
            self.title = _clean_block_text("".join(self._title_buffer))
            self._title = False
            self._title_buffer = []
        if lower_tag == "code" and self._code_id is not None:
            self.code[self._code_id] = "".join(self._code_buffer).strip()
            self._code_id = None
            self._code_buffer = []

        if self._text_depth:
            if lower_tag in {"p", "li", "div"}:
                self._text_buffer.append("\n")
            self._text_depth -= 1
            if not self._text_depth:
                value = _clean_block_text("".join(self._text_buffer))
                if value:
                    self.article_text_blocks.append(value)
                self._text_buffer = []
        if self._image_depth:
            self._image_depth -= 1
        if self._video_depth:
            self._video_depth -= 1
        if self._embed_depth:
            self._embed_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._script:
            self._script_buffer.append(data)
        if self._title:
            self._title_buffer.append(data)
        if self._code_id is not None:
            self._code_buffer.append(data)
        if self._text_depth:
            self._text_buffer.append(data)

    def handle_comment(self, data: str) -> None:
        if self._code_id is not None:
            self._code_buffer.append(data)

    def _start_capture(self, tag: str, test_id: str) -> None:
        is_void = tag in _VOID_TAGS
        if self._text_depth:
            if tag == "br":
                self._text_buffer.append("\n")
            if not is_void:
                self._text_depth += 1
        elif test_id == "publishing-text-block":
            self._text_depth = 1
            self._text_buffer = []

        self._image_depth = self._next_depth(
            self._image_depth, test_id == "publishing-image-block", is_void
        )
        self._video_depth = self._next_depth(
            self._video_depth, test_id == "publishing-video-block", is_void
        )
        self._embed_depth = self._next_depth(
            self._embed_depth, test_id == "publishing-embed-block", is_void
        )

    @staticmethod
    def _next_depth(current: int, starts: bool, is_void: bool) -> int:
        if current:
            return current if is_void else current + 1
        return 1 if starts else 0


def _parse_page(source: str) -> _PageParser:
    if not isinstance(source, str) or not source.strip():
        raise LinkedInResponseError("LinkedIn HTML is empty")
    parser = _PageParser()
    try:
        parser.feed(source.replace("\x00", ""))
        parser.close()
    except (TypeError, ValueError) as exc:
        raise LinkedInResponseError("LinkedIn HTML could not be parsed") from exc
    return parser


def _json_ld_items(page: _PageParser) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    for source in page.json_ld:
        try:
            value = json.loads(source.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            mapping = _mapping(item)
            graph = _list(mapping.get("@graph"))
            if graph:
                output.extend(_mapping(child) for child in graph if isinstance(child, Mapping))
            elif mapping:
                output.append(mapping)
    return output


def _decode_code(value: str) -> Any:
    decoded: Any = value.strip()
    for _ in range(2):
        if not isinstance(decoded, str):
            break
        try:
            decoded = json.loads(decoded)
        except (json.JSONDecodeError, TypeError, ValueError):
            break
    return decoded


class _CaptureParser(HTMLParser):
    """用于 LinkedIn 访客 HTML 片段的轻量级深度感知文本收集器。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.canonical = ""
        self._depth = 0
        self._captures: list[dict[str, Any]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lower_tag = tag.lower()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        classes = set(values.get("class", "").split())
        is_void = lower_tag in _VOID_TAGS

        if lower_tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = values.get("content", "")
        elif lower_tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "") or self.canonical
        is_title = lower_tag == "title"

        if lower_tag == "br":
            self._append_separator()
        if not is_void:
            self._depth += 1
        if is_title:
            self._begin("__page_title")
        self._handle_element(lower_tag, values, classes)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag in {"div", "li", "ol", "p", "section", "ul"}:
            self._append_separator()
        ending = [item for item in self._captures if item["depth"] == self._depth]
        if ending:
            self._captures = [
                item for item in self._captures if item["depth"] != self._depth
            ]
            for item in ending:
                value = _clean_block_text("".join(item["buffer"]))
                if item["key"] == "__page_title":
                    self.title = value
                else:
                    self._capture_complete(item["key"], value, item["target"])
        self._handle_element_end(lower_tag, self._depth)
        if lower_tag not in _VOID_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        for item in self._captures:
            item["buffer"].append(data)

    def handle_comment(self, data: str) -> None:
        for item in self._captures:
            item["buffer"].append(data)

    def _begin(self, key: str, target: Any = None) -> None:
        self._captures.append(
            {"key": key, "depth": self._depth, "buffer": [], "target": target}
        )

    def _append_separator(self) -> None:
        for item in self._captures:
            item["buffer"].append("\n")

    def _handle_element(
        self, tag: str, attrs: Mapping[str, str], classes: set[str]
    ) -> None:
        del tag, attrs, classes

    def _handle_element_end(self, tag: str, depth: int) -> None:
        del tag, depth

    def _capture_complete(self, key: str, value: str, target: Any) -> None:
        del key, value, target


class _JobDetailParser(_CaptureParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, Any] = {
            "criteria_labels": [],
            "criteria_values": [],
            "benefits": [],
        }

    def _handle_element(
        self, tag: str, attrs: Mapping[str, str], classes: set[str]
    ) -> None:
        if tag == "a" and "topcard__link" in classes and not self.values.get("url"):
            self.values["url"] = _absolute_url(attrs.get("href"))
        if tag == "a" and "topcard__org-name-link" in classes:
            self.values.setdefault("company_url", _absolute_url(attrs.get("href")))
            self._begin("company")
        elif "topcard__title" in classes:
            self._begin("title")
        elif tag == "span" and "topcard__flavor--bullet" in classes:
            self._begin("location")
        elif "posted-time-ago__text" in classes:
            self._begin("posted_text")
        elif "num-applicants__caption" in classes:
            self._begin("applicants_text")
        elif "closed-job__flavor--closed" in classes:
            self._begin("closed_text")
        elif "show-more-less-html__markup" in classes:
            self._begin("description")
        elif "compensation__salary" in classes:
            self._begin("salary")
        elif "description__job-criteria-subheader" in classes:
            self._begin("criteria_label")
        elif "description__job-criteria-text--criteria" in classes:
            self._begin("criteria_value")
        elif "job-posting-benefits__text" in classes:
            self._begin("benefit")
        elif tag == "code" and attrs.get("id") == "decoratedJobPostingId":
            self._begin("decorated_id")

        if (
            tag == "img"
            and "artdeco-entity-image--square-5" in classes
            and not self.values.get("company_logo")
        ):
            self.values["company_logo"] = _absolute_url(
                attrs.get("data-delayed-url") or attrs.get("data-src") or attrs.get("src")
            )

    def _capture_complete(self, key: str, value: str, target: Any) -> None:
        del target
        if not value:
            return
        if key == "criteria_label":
            self.values["criteria_labels"].append(value)
        elif key == "criteria_value":
            self.values["criteria_values"].append(value)
        elif key == "benefit":
            self.values["benefits"].append(value)
        else:
            self.values.setdefault(key, value)


class _JobSearchParser(_CaptureParser):
    def __init__(self) -> None:
        super().__init__()
        self.cards: list[dict[str, Any]] = []
        self.total: int | None = None
        self._card: dict[str, Any] | None = None
        self._card_depth = 0

    def _handle_element(
        self, tag: str, attrs: Mapping[str, str], classes: set[str]
    ) -> None:
        if (
            tag == "div"
            and "job-search-card" in classes
            and self._card is None
        ):
            self._card = {
                "urn": attrs.get("data-entity-urn", ""),
                "benefits": [],
            }
            self._card_depth = self._depth

        if tag == "code" and attrs.get("id") == "totalResults":
            self._begin("total")
        if self._card is None:
            return
        if tag == "a" and "base-card__full-link" in classes:
            self._card.setdefault("url", _absolute_url(attrs.get("href")))
        elif "base-search-card__title" in classes:
            self._begin("title", self._card)
        elif "base-search-card__subtitle" in classes:
            self._begin("company", self._card)
        elif tag == "a" and "hidden-nested-link" in classes:
            self._card.setdefault("company_url", _absolute_url(attrs.get("href")))
        elif "job-search-card__location" in classes:
            self._begin("location", self._card)
        elif tag == "time" and (
            "job-search-card__listdate" in classes
            or "job-search-card__listdate--new" in classes
        ):
            self._card.setdefault("posted_at", _text(attrs.get("datetime")))
            self._begin("posted_text", self._card)
        elif "job-posting-benefits__text" in classes:
            self._begin("benefit", self._card)

        if (
            tag == "img"
            and "artdeco-entity-image" in classes
            and not self._card.get("company_logo")
        ):
            self._card["company_logo"] = _absolute_url(
                attrs.get("data-delayed-url") or attrs.get("data-src") or attrs.get("src")
            )

    def _handle_element_end(self, tag: str, depth: int) -> None:
        if tag == "div" and self._card is not None and depth == self._card_depth:
            self.cards.append(self._card)
            self._card = None
            self._card_depth = 0

    def _capture_complete(self, key: str, value: str, target: Any) -> None:
        if key == "total":
            self.total = _optional_int(_decode_code(value))
            return
        if not value or not isinstance(target, dict):
            return
        if key == "benefit":
            target["benefits"].append(value)
        else:
            target.setdefault(key, value)


class _CompanyPublicParser(_CaptureParser):
    def __init__(self) -> None:
        super().__init__()
        self.feed_cards: list[dict[str, Any]] = []
        self.people: list[dict[str, Any]] = []
        self.affiliates: list[dict[str, Any]] = []
        self.saw_feed_markup = False
        self.saw_people_section = False
        self.saw_affiliates_section = False
        self._feed_card: dict[str, Any] | None = None
        self._feed_card_depth = 0
        self._feed_container_depth = 0
        self._feed_container_url = ""
        self._feed_container_card: dict[str, Any] | None = None
        self._actor_depth = 0
        self._people_depth = 0
        self._affiliates_depth = 0
        self._employee: dict[str, Any] | None = None
        self._employee_depth = 0
        self._affiliate: dict[str, Any] | None = None
        self._affiliate_depth = 0

    def _handle_element(
        self, tag: str, attrs: Mapping[str, str], classes: set[str]
    ) -> None:
        test_id = attrs.get("data-test-id", "")
        data_id = attrs.get("data-id", "")
        tracking = attrs.get("data-tracking-control-name", "")

        if tag == "section" and test_id == "employees-at":
            self.saw_people_section = True
            self._people_depth = self._depth
        elif tag == "section" and test_id == "affiliated-pages":
            self.saw_affiliates_section = True
            self._affiliates_depth = self._depth

        if (
            tag == "div"
            and data_id == "entire-feed-card-link"
            and not self._feed_container_depth
        ):
            self.saw_feed_markup = True
            self._feed_container_depth = self._depth
            self._feed_container_url = ""
            self._feed_container_card = None
        if (
            tag == "article"
            and data_id == "main-feed-card"
            and self._feed_card is None
        ):
            self.saw_feed_markup = True
            self._feed_card = {
                "urn": attrs.get("data-activity-urn", ""),
                "featured_urn": attrs.get("data-featured-activity-urn", ""),
                "attributed_urn": attrs.get("data-attributed-urn", ""),
                "media": [],
                "author": {},
            }
            if self._feed_container_url:
                self._feed_card["url"] = self._feed_container_url
            self._feed_card_depth = self._depth

        if tag == "a" and data_id == "main-feed-card__full-link":
            full_link = _absolute_url(attrs.get("href"))
            if self._feed_card is not None:
                self._feed_card.setdefault("url", full_link)
            elif self._feed_container_card is not None:
                self._feed_container_card.setdefault("url", full_link)
            elif self._feed_container_depth:
                self._feed_container_url = full_link

        if self._feed_card is not None:
            self._handle_feed_element(tag, attrs, classes, test_id, data_id)
        if self._people_depth:
            self._handle_people_element(tag, attrs, classes, tracking)
        if self._affiliates_depth:
            self._handle_affiliate_element(tag, attrs, classes, tracking)

    def _handle_feed_element(
        self,
        tag: str,
        attrs: Mapping[str, str],
        classes: set[str],
        test_id: str,
        data_id: str,
    ) -> None:
        assert self._feed_card is not None
        if test_id == "main-feed-activity-card__entity-lockup":
            self._actor_depth = self._depth
        if test_id == "main-feed-activity-card__commentary":
            self._begin("body", self._feed_card)
        elif test_id == "social-actions__reactions":
            self._feed_card["likes_attribute"] = attrs.get("data-num-reactions", "")
            self._begin("likes", self._feed_card)
        elif test_id == "social-actions__comments":
            self._feed_card["comments_attribute"] = attrs.get("data-num-comments", "")
            self._begin("comments", self._feed_card)
        elif tag == "time":
            self._feed_card.setdefault("posted_at", _text(attrs.get("datetime")))
            self._begin("posted_text", self._feed_card)

        if self._actor_depth:
            if tag == "a" and "/company/" in attrs.get("href", ""):
                author = self._feed_card["author"]
                author.setdefault("url", _absolute_url(attrs.get("href")))
                self._begin("author_name", author)
            elif tag == "img" and not self._feed_card["author"].get("image"):
                self._feed_card["author"]["image"] = _absolute_url(
                    attrs.get("data-delayed-url")
                    or attrs.get("data-src")
                    or attrs.get("src")
                )
                self._feed_card["author"]["image_alt"] = attrs.get("alt", "")
        elif tag == "img" and "w-main-feed-card-media" in classes:
            image_url = _absolute_url(
                attrs.get("data-delayed-url") or attrs.get("data-src") or attrs.get("src")
            )
            if image_url:
                self._feed_card["media"].append(
                    {"type": "image", "url": image_url, "alt": attrs.get("alt", "")}
                )

        if tag == "video" and "share-native-video__node" in classes:
            sources: list[dict[str, Any]] = []
            try:
                raw_sources = json.loads(_text(attrs.get("data-sources")) or "[]")
            except (json.JSONDecodeError, TypeError, ValueError):
                raw_sources = []
            if isinstance(raw_sources, list):
                for item in raw_sources:
                    if not isinstance(item, Mapping):
                        continue
                    source_url = _absolute_url(item.get("src"))
                    if source_url:
                        bitrate = item.get("bitrate")
                        if bitrate is None:
                            bitrate = item.get("data-bitrate")
                        sources.append(
                            {
                                "url": source_url,
                                "type": _text(item.get("type")),
                                "bitrate": _optional_int(bitrate),
                            }
                        )
            poster_url = _absolute_url(
                attrs.get("data-poster-url") or attrs.get("poster")
            )
            if sources or poster_url:
                self._feed_card["media"].append(
                    {
                        "type": "video",
                        "url": sources[0]["url"] if sources else "",
                        "poster_url": poster_url,
                        "sources": sources,
                    }
                )

    def _handle_people_element(
        self,
        tag: str,
        attrs: Mapping[str, str],
        classes: set[str],
        tracking: str,
    ) -> None:
        if tag == "a" and tracking == "org-employees" and self._employee is None:
            self._employee = {"url": _absolute_url(attrs.get("href"))}
            self._employee_depth = self._depth
            self._begin("employee_text", self._employee)
        if self._employee is None:
            return
        if tag == "h3" and "base-main-card__title" in classes:
            self._begin("name", self._employee)
        elif "base-main-card__subtitle" in classes:
            self._begin("headline", self._employee)
        elif tag == "img" and not self._employee.get("image"):
            self._employee["image"] = _absolute_url(
                attrs.get("data-delayed-url") or attrs.get("data-src") or attrs.get("src")
            )
            self._employee["image_alt"] = attrs.get("alt", "")

    def _handle_affiliate_element(
        self,
        tag: str,
        attrs: Mapping[str, str],
        classes: set[str],
        tracking: str,
    ) -> None:
        if (
            tag == "a"
            and tracking == "affiliated-pages"
            and self._affiliate is None
        ):
            self._affiliate = {"url": _absolute_url(attrs.get("href"))}
            self._affiliate_depth = self._depth
            self._begin("affiliate_text", self._affiliate)
        if self._affiliate is None:
            return
        if tag == "h3" and "base-aside-card__title" in classes:
            self._begin("name", self._affiliate)
        elif "base-aside-card__second-subtitle" in classes:
            self._begin("location", self._affiliate)
        elif "base-aside-card__subtitle" in classes:
            self._begin("industry", self._affiliate)
        elif tag == "img" and not self._affiliate.get("logo"):
            self._affiliate["logo"] = _absolute_url(
                attrs.get("data-delayed-url") or attrs.get("data-src") or attrs.get("src")
            )
            self._affiliate["image_alt"] = attrs.get("alt", "")

    def _handle_element_end(self, tag: str, depth: int) -> None:
        if tag == "article" and self._feed_card is not None and depth == self._feed_card_depth:
            if self._feed_container_depth:
                self._feed_container_card = self._feed_card
            else:
                self.feed_cards.append(self._feed_card)
            self._feed_card = None
            self._feed_card_depth = 0
            self._actor_depth = 0
        if tag == "div" and self._feed_container_depth and depth == self._feed_container_depth:
            if self._feed_container_card is not None:
                if self._feed_container_url:
                    self._feed_container_card.setdefault("url", self._feed_container_url)
                self.feed_cards.append(self._feed_container_card)
            self._feed_container_depth = 0
            self._feed_container_url = ""
            self._feed_container_card = None
        if self._actor_depth and depth == self._actor_depth:
            self._actor_depth = 0
        if tag == "a" and self._employee is not None and depth == self._employee_depth:
            self.people.append(self._employee)
            self._employee = None
            self._employee_depth = 0
        if tag == "a" and self._affiliate is not None and depth == self._affiliate_depth:
            self.affiliates.append(self._affiliate)
            self._affiliate = None
            self._affiliate_depth = 0
        if tag == "section" and self._people_depth and depth == self._people_depth:
            self._people_depth = 0
        if tag == "section" and self._affiliates_depth and depth == self._affiliates_depth:
            self._affiliates_depth = 0

    def _capture_complete(self, key: str, value: str, target: Any) -> None:
        if not isinstance(target, dict):
            return
        if key in {"likes", "comments"}:
            match = re.search(r"[0-9][0-9,]*", value)
            target[key] = _optional_int(match.group(0)) if match else None
        elif key == "author_name":
            if value:
                target.setdefault("name", value)
        elif key in {"employee_text", "affiliate_text"}:
            target.setdefault("text", value)
        elif value:
            target.setdefault(key, value)


def _parse_capture_html(source: str, parser: _CaptureParser) -> _CaptureParser:
    if not isinstance(source, str) or not source.strip():
        raise LinkedInResponseError("LinkedIn HTML is empty")
    try:
        parser.feed(source.replace("\x00", ""))
        parser.close()
    except (TypeError, ValueError) as exc:
        raise LinkedInResponseError("LinkedIn HTML could not be parsed") from exc
    return parser


class LinkedInClient:
    """不执行页面 JavaScript，读取 LinkedIn 访客页面。"""

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

    @classmethod
    def parse_post_reference(cls, value: str | int) -> dict[str, Any]:
        source = cls._reference(value, "post")
        if source.isdecimal():
            identifier = cls._activity_id(source)
            urn = f"urn:li:activity:{identifier}"
            return cls._post_reference(identifier, urn, None, f"{_BASE_URL}/feed/update/{urn}")
        urn_match = _URN_RE.fullmatch(source)
        if urn_match:
            identifier = urn_match.group(2)
            return cls._post_reference(
                identifier,
                source,
                None,
                f"{_BASE_URL}/feed/update/{source}",
            )
        if _POST_SLUG_RE.fullmatch(source):
            activity = _POST_ACTIVITY_RE.search(source)
            if activity:
                identifier = activity.group(1)
                return cls._post_reference(
                    identifier,
                    f"urn:li:activity:{identifier}",
                    source,
                    f"{_BASE_URL}/posts/{source}",
                )

        candidate = cls._linkedin_url(source)
        path = unquote(urlsplit(candidate).path)
        post_match = _POST_PATH_RE.fullmatch(path)
        if post_match:
            slug = post_match.group(1)
            if not _POST_SLUG_RE.fullmatch(slug):
                raise LinkedInInputError("LinkedIn post slug contains invalid characters")
            activity = _POST_ACTIVITY_RE.search(slug)
            if not activity:
                raise LinkedInInputError("LinkedIn post URL does not contain an activity id")
            identifier = activity.group(1)
            return cls._post_reference(
                identifier,
                f"urn:li:activity:{identifier}",
                slug,
                f"{_BASE_URL}/posts/{slug}",
            )
        feed_match = _FEED_PATH_RE.fullmatch(path)
        if feed_match:
            urn = feed_match.group(1)
            urn_parts = _URN_RE.fullmatch(urn)
            assert urn_parts is not None
            identifier = urn_parts.group(2)
            return cls._post_reference(
                identifier,
                urn,
                None,
                f"{_BASE_URL}/feed/update/{urn}",
            )
        raise LinkedInInputError("reference is not a LinkedIn public post URL, URN, or slug")

    @classmethod
    def parse_person_reference(cls, value: str) -> dict[str, str]:
        return cls._entity_reference(value, "person")

    @classmethod
    def parse_author_articles_reference(cls, value: str) -> dict[str, str]:
        source = cls._reference(value, "author articles")
        if _ENTITY_SLUG_RE.fullmatch(source):
            slug = source
        else:
            candidate = cls._linkedin_url(source)
            path = unquote(urlsplit(candidate).path)
            match = _AUTHOR_ARTICLES_PATH_RE.fullmatch(path) or _PROFILE_PATH_RE.fullmatch(
                path
            )
            if not match:
                raise LinkedInInputError(
                    "reference is not a LinkedIn author articles or public profile URL"
                )
            slug = match.group(1)
            cls._slug(slug, "person", _ENTITY_SLUG_RE)
        return {
            "kind": "author_articles",
            "slug": slug,
            "url": f"{_BASE_URL}/in/{slug}",
            "articles_url": f"{_BASE_URL}/in/{slug}/recent-activity/articles/",
        }

    @classmethod
    def parse_company_reference(cls, value: str) -> dict[str, str]:
        return cls._entity_reference(value, "company")

    @classmethod
    def parse_article_reference(cls, value: str) -> dict[str, str]:
        source = cls._reference(value, "article")
        if _ARTICLE_SLUG_RE.fullmatch(source):
            slug = source
        else:
            candidate = cls._linkedin_url(source)
            match = _ARTICLE_PATH_RE.fullmatch(unquote(urlsplit(candidate).path))
            if not match:
                raise LinkedInInputError("reference is not a LinkedIn Pulse article URL or slug")
            slug = match.group(1)
            if not _ARTICLE_SLUG_RE.fullmatch(slug):
                raise LinkedInInputError("LinkedIn article slug contains invalid characters")
        return {"kind": "article", "slug": slug, "url": f"{_BASE_URL}/pulse/{slug}"}

    @classmethod
    def parse_ad_reference(cls, value: str | int) -> dict[str, str]:
        source = cls._reference(value, "ad")
        if _AD_ID_RE.fullmatch(source):
            identifier = source
        else:
            candidate = cls._linkedin_url(source)
            match = _AD_DETAIL_PATH_RE.fullmatch(unquote(urlsplit(candidate).path))
            if not match:
                raise LinkedInInputError(
                    "reference is not a LinkedIn Ad Library detail URL or id"
                )
            identifier = match.group(1)
        return {
            "kind": "ad",
            "ad_id": identifier,
            "url": f"{_BASE_URL}/ad-library/detail/{identifier}",
        }

    @classmethod
    def parse_job_reference(cls, value: str | int) -> dict[str, str]:
        source = cls._reference(value, "job")
        urn_match = _JOB_URN_RE.fullmatch(source)
        if source.isdecimal():
            identifier = cls._job_id(source)
            public_url = f"{_BASE_URL}/jobs/view/{identifier}"
        elif urn_match:
            identifier = urn_match.group(1)
            public_url = f"{_BASE_URL}/jobs/view/{identifier}"
        else:
            candidate = cls._linkedin_url(source)
            path = unquote(urlsplit(candidate).path)
            match = _JOB_VIEW_PATH_RE.fullmatch(path)
            if match:
                identifier = match.group(1)
                public_url = cls._clean_linkedin_url(candidate)
            else:
                match = _JOB_DETAIL_PATH_RE.fullmatch(path)
                if not match:
                    raise LinkedInInputError(
                        "reference is not a LinkedIn public job URL, URN, or id"
                    )
                identifier = match.group(1)
                public_url = f"{_BASE_URL}/jobs/view/{identifier}"
        urn = f"urn:li:jobPosting:{identifier}"
        return {
            "kind": "job",
            "id": identifier,
            "urn": urn,
            "url": public_url,
            "request_url": f"{_JOB_DETAIL_URL}/{identifier}",
        }

    @classmethod
    def parse_jobs_reference(
        cls,
        value: str = "",
        *,
        location: str | None = None,
        geo_id: str | int | None = None,
        company_id: str | int | Sequence[str | int] | None = None,
        time_range: str | None = None,
        job_type: str | Sequence[str] | None = None,
        experience_level: str | int | Sequence[str | int] | None = None,
        remote: str | int | Sequence[str | int] | None = None,
        sort_by: str | None = None,
        easy_apply: bool | str | None = None,
        under_10_applicants: bool | str | None = None,
        start: int | None = None,
        count: int = 25,
    ) -> dict[str, Any]:
        if value is None:
            source = ""
        elif not isinstance(value, str):
            source = cls._reference(value, "jobs")
        else:
            source = html.unescape(value.strip())
            match = _URL_IN_TEXT_RE.search(source)
            source = match.group(0) if match else source

        url_query: dict[str, list[str]] = {}
        if source and (
            "://" in source
            or bool(_LINKEDIN_HOST_PREFIX_RE.match(source))
        ):
            candidate = cls._linkedin_url(source)
            parsed = urlsplit(candidate)
            path = unquote(parsed.path)
            seo_match = _JOBS_SEO_PATH_RE.fullmatch(path)
            if not _JOBS_SEARCH_PATH_RE.fullmatch(path) and not seo_match:
                raise LinkedInInputError("reference is not a LinkedIn public jobs search URL")
            url_query = parse_qs(parsed.query, keep_blank_values=True)
            keyword = cls._last_query_value(url_query, "keywords")
            if not keyword and seo_match and not cls._last_query_value(url_query, "f_C"):
                keyword = seo_match.group(1).replace("-", " ")
        else:
            keyword = source

        keyword = cls._search_text(keyword, "job keyword", maximum=500)
        selected_location = cls._search_text(
            location
            if location is not None
            else cls._last_query_value(url_query, "location"),
            "job location",
            maximum=300,
        )
        selected_geo = cls._numeric_filter(
            geo_id if geo_id is not None else cls._last_query_value(url_query, "geoId"),
            "geo id",
        )
        selected_company = cls._numeric_filter(
            company_id
            if company_id is not None
            else cls._last_query_value(url_query, "f_C"),
            "company id",
            multiple=True,
        )
        selected_time = cls._time_range_filter(
            time_range
            if time_range is not None
            else cls._last_query_value(url_query, "f_TPR")
        )
        selected_job_type = cls._coded_filter(
            job_type
            if job_type is not None
            else cls._last_query_value(url_query, "f_JT"),
            "job type",
            _JOB_TYPE_CODES,
        )
        selected_experience = cls._coded_filter(
            experience_level
            if experience_level is not None
            else cls._last_query_value(url_query, "f_E"),
            "experience level",
            _EXPERIENCE_CODES,
        )
        selected_remote = cls._coded_filter(
            remote if remote is not None else cls._last_query_value(url_query, "f_WT"),
            "remote filter",
            _REMOTE_CODES,
        )
        selected_sort = cls._sort_by_filter(
            sort_by
            if sort_by is not None
            else cls._last_query_value(url_query, "sortBy")
        )
        selected_easy_apply = cls._boolean_filter(
            easy_apply
            if easy_apply is not None
            else cls._last_query_value(url_query, "f_AL"),
            "easy apply filter",
        )
        selected_under_10 = cls._boolean_filter(
            under_10_applicants
            if under_10_applicants is not None
            else cls._last_query_value(url_query, "f_EA"),
            "under 10 applicants filter",
        )
        selected_start = cls._bounded_integer(
            start if start is not None else cls._last_query_value(url_query, "start") or 0,
            "start",
            minimum=0,
            maximum=_JOBS_MAX_START - 1,
        )
        selected_count = cls._bounded_integer(
            count, "count", minimum=1, maximum=100
        )
        query = {
            "keywords": keyword,
            "location": selected_location,
            "geoId": selected_geo,
            "f_C": selected_company,
            "f_TPR": selected_time,
            "f_JT": selected_job_type,
            "f_E": selected_experience,
            "f_WT": selected_remote,
            "sortBy": selected_sort,
            "f_AL": selected_easy_apply,
            "f_EA": selected_under_10,
        }
        filters = {
            "location": selected_location or None,
            "geo_id": selected_geo or None,
            "company_id": selected_company or None,
            "time_range": selected_time or None,
            "job_type": selected_job_type or None,
            "experience_level": selected_experience or None,
            "remote": selected_remote or None,
            "sort_by": selected_sort or None,
            "easy_apply": True if selected_easy_apply else None,
            "under_10_applicants": True if selected_under_10 else None,
        }
        return {
            "kind": "jobs",
            "keyword": keyword or None,
            "filters": filters,
            "start": selected_start,
            "count": selected_count,
            "url": cls._jobs_search_url(query, selected_start),
            "search_url": cls._jobs_search_url(
                query, selected_start, base=f"{_BASE_URL}/jobs/search"
            ),
            "query": query,
        }

    def get_post(self, value: str | int) -> dict[str, Any]:
        reference = self.parse_post_reference(value)
        response = self._request(reference["url"])
        self._validate_final_url(str(response.url or reference["url"]))
        result = self.parse_post_html(
            response.text,
            expected_id=reference["id"],
            expected_urn=reference["urn"],
            page_url=str(response.url or reference["url"]),
        )
        result["requested_url"] = reference["url"]
        return result

    def get_article(self, value: str) -> dict[str, Any]:
        reference = self.parse_article_reference(value)
        response = self._request(reference["url"])
        self._validate_final_url(str(response.url or reference["url"]))
        return self.parse_article_html(
            response.text,
            expected_slug=reference["slug"],
            page_url=str(response.url or reference["url"]),
        )

    def get_person_profile(self, value: str) -> dict[str, Any]:
        reference = self.parse_person_reference(value)
        response = self._request(reference["url"])
        self._validate_final_url(str(response.url or reference["url"]))
        return self.parse_person_html(
            response.text,
            expected_slug=reference["slug"],
            page_url=str(response.url or reference["url"]),
        )

    def get_person(self, value: str) -> dict[str, Any]:
        return self.get_person_profile(value)

    def get_author_articles(
        self, value: str, *, limit: int = 10
    ) -> dict[str, Any]:
        requested_limit = self._bounded_integer(
            limit, "limit", minimum=1, maximum=100
        )
        reference = self.parse_author_articles_reference(value)
        profile = self.get_person_profile(reference["url"])
        embedded = profile.get("embedded_articles")
        items = list(embedded) if isinstance(embedded, list) else []
        items = items[:requested_limit]
        return {
            "kind": "author_articles",
            "source": f"person_{_text(profile.get('source'))}",
            "author": {
                "slug": _text(profile.get("slug")) or reference["slug"],
                "name": _text(profile.get("name")),
                "url": _text(profile.get("url")) or reference["url"],
            },
            "articles_url": reference["articles_url"],
            "requested_limit": requested_limit,
            "count": len(items),
            "items": items,
            "partial": True,
            "embedded_lists_partial": True,
        }

    def get_company_profile(self, value: str) -> dict[str, Any]:
        reference = self.parse_company_reference(value)
        response = self._request(reference["url"])
        self._validate_final_url(str(response.url or reference["url"]))
        return self.parse_company_html(
            response.text,
            expected_slug=reference["slug"],
            page_url=str(response.url or reference["url"]),
        )

    def get_company(self, value: str) -> dict[str, Any]:
        return self.get_company_profile(value)

    def get_company_posts(self, value: str, *, limit: int = 10) -> dict[str, Any]:
        requested_limit = self._bounded_integer(
            limit, "limit", minimum=1, maximum=70
        )
        reference, profile, page, parser, requested_url = self._company_public_page(value)
        company_id, token, feed_path = self._company_feed_reference(page)
        company = self._company_result_identity(profile, company_id)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        def append_cards(cards: Sequence[Mapping[str, Any]]) -> None:
            for raw in cards:
                item = self._normalize_company_feed_card(raw, reference["slug"])
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                if len(items) < requested_limit:
                    items.append(item)

        append_cards(parser.feed_cards)
        requested_urls = [requested_url]
        for start in _ORGANIZATION_FEED_STARTS:
            if len(items) >= requested_limit:
                break
            query = urlencode(
                {"paginationToken": token, "paginationStart": str(start)}
            )
            request_url = f"{_BASE_URL}{feed_path}?{query}"
            response = self._request(request_url, accepted_statuses={400})
            final_url = str(response.url or request_url)
            self._validate_final_url(final_url)
            requested_urls.append(request_url)
            if response.status_code == 400:
                break
            fragment = self._parse_company_feed_fragment(
                response.text,
                page_url=final_url,
            )
            if not fragment:
                break
            append_cards(fragment)

        return {
            "kind": "company_posts",
            "source": "company_ssr+organization_guest",
            "company": company,
            "requested_limit": requested_limit,
            "count": len(items),
            "pages_fetched": len(requested_urls),
            "requested_urls": requested_urls,
            "items": items,
            "partial": True,
            "embedded_lists_partial": True,
        }

    def get_company_people(self, value: str) -> dict[str, Any]:
        _, profile, page, parser, _ = self._company_public_page(value)
        company_id = self._company_feed_identity(page)
        items = self._normalize_company_people(parser.people)
        return {
            "kind": "company_people",
            "source": "company_ssr",
            "company": self._company_result_identity(profile, company_id),
            "count": len(items),
            "items": items,
            "partial": True,
            "embedded_lists_partial": True,
        }

    def get_company_affiliates(self, value: str) -> dict[str, Any]:
        _, profile, page, parser, _ = self._company_public_page(value)
        company_id = self._company_feed_identity(page)
        items = self._normalize_company_affiliates(parser.affiliates)
        return {
            "kind": "company_affiliates",
            "source": "company_ssr",
            "company": self._company_result_identity(profile, company_id),
            "count": len(items),
            "items": items,
            "partial": True,
            "embedded_lists_partial": True,
        }

    def get_ad(self, value: str | int) -> dict[str, Any]:
        reference = self.parse_ad_reference(value)
        response = self._request(reference["url"])
        final_url = str(response.url or reference["url"])
        self._validate_final_url(final_url)
        result = self.parse_ad_html(
            response.text,
            expected_id=reference["ad_id"],
            page_url=final_url,
        )
        result["requested_url"] = reference["url"]
        return result

    def get_job(self, value: str | int) -> dict[str, Any]:
        reference = self.parse_job_reference(value)
        response = self._request(reference["request_url"])
        self._validate_final_url(str(response.url or reference["request_url"]))
        result = self.parse_job_html(
            response.text,
            expected_id=reference["id"],
            page_url=str(response.url or reference["request_url"]),
        )
        result["requested_url"] = reference["request_url"]
        return result

    def search_jobs(
        self,
        value: str = "",
        *,
        location: str | None = None,
        geo_id: str | int | None = None,
        company_id: str | int | Sequence[str | int] | None = None,
        time_range: str | None = None,
        job_type: str | Sequence[str] | None = None,
        experience_level: str | int | Sequence[str | int] | None = None,
        remote: str | int | Sequence[str | int] | None = None,
        sort_by: str | None = None,
        easy_apply: bool | str | None = None,
        under_10_applicants: bool | str | None = None,
        start: int | None = None,
        count: int = 25,
    ) -> dict[str, Any]:
        reference = self.parse_jobs_reference(
            value,
            location=location,
            geo_id=geo_id,
            company_id=company_id,
            time_range=time_range,
            job_type=job_type,
            experience_level=experience_level,
            remote=remote,
            sort_by=sort_by,
            easy_apply=easy_apply,
            under_10_applicants=under_10_applicants,
            start=start,
            count=count,
        )
        cursor = reference["start"]
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        pages_fetched = 0
        total: int | None = None
        has_more = False
        stale_pages = 0

        while len(items) < reference["count"] and cursor < _JOBS_MAX_START:
            request_url = self._jobs_search_url(reference["query"], cursor)
            response = self._request(request_url, accepted_statuses={400})
            self._validate_final_url(str(response.url or request_url))
            pages_fetched += 1
            if response.status_code == 400:
                has_more = False
                break
            page = self.parse_jobs_html(
                response.text, page_url=str(response.url or request_url)
            )
            if total is None and page["total"] is not None:
                total = page["total"]
            raw_items = page["items"]
            if not raw_items:
                has_more = False
                break
            new_items = [item for item in raw_items if item["id"] not in seen]
            cursor += max(1, len(raw_items))
            if not new_items:
                stale_pages += 1
                if stale_pages >= _JOBS_MAX_STALE_PAGES:
                    has_more = False
                    break
                continue
            stale_pages = 0
            for item in new_items:
                seen.add(item["id"])
                if len(items) < reference["count"]:
                    items.append(item)
            has_more = cursor < _JOBS_MAX_START

        return {
            "kind": "jobs",
            "source": "guest_jobs_search",
            "keyword": reference["keyword"],
            "filters": reference["filters"],
            "start": reference["start"],
            "requested_count": reference["count"],
            "count": len(items),
            "total": total,
            "pages_fetched": pages_fetched,
            "next_start": cursor,
            "has_more": has_more,
            "items": items,
        }

    def get_company_jobs(
        self,
        company_id: str | int,
        *,
        location: str | None = None,
        geo_id: str | int | None = None,
        time_range: str | None = None,
        job_type: str | Sequence[str] | None = None,
        experience_level: str | int | Sequence[str | int] | None = None,
        remote: str | int | Sequence[str | int] | None = None,
        sort_by: str | None = None,
        easy_apply: bool | str | None = None,
        under_10_applicants: bool | str | None = None,
        start: int | None = None,
        count: int = 25,
    ) -> dict[str, Any]:
        identifier = self._company_numeric_id(company_id)
        result = self.search_jobs(
            "",
            location=location,
            geo_id=geo_id,
            company_id=identifier,
            time_range=time_range,
            job_type=job_type,
            experience_level=experience_level,
            remote=remote,
            sort_by=sort_by,
            easy_apply=easy_apply,
            under_10_applicants=under_10_applicants,
            start=start,
            count=count,
        )
        result["kind"] = "company_jobs"
        result["company_id"] = identifier
        return result

    def get_company_job_count(self, company_id: str | int) -> dict[str, Any]:
        identifier = self._company_numeric_id(company_id)
        request_url = f"{_COMPANY_JOB_COUNT_URL}?{urlencode({'f_C': identifier})}"
        response = self._request(request_url)
        final_url = str(response.url or request_url)
        self._validate_final_url(final_url)
        page = self.parse_jobs_html(response.text, page_url=final_url)
        if page["total"] is None:
            raise LinkedInResponseError("LinkedIn company jobs page has no totalResults")
        return {
            "kind": "company_job_count",
            "company_id": identifier,
            "count": page["total"],
            "url": request_url,
        }

    def suggest_job_locations(
        self, keyword: str, *, count: int = 10
    ) -> dict[str, Any]:
        return self._suggest(
            keyword,
            count=count,
            kind="location_suggestions",
            label="location keyword",
            params={
                "origin": "jserp",
                "typeaheadType": "GEO",
                "geoTypes": (
                    "POPULATED_PLACE,ADMIN_DIVISION_2,MARKET_AREA,COUNTRY_REGION"
                ),
            },
        )

    def suggest_job_keywords(self, keyword: str, *, count: int = 10) -> dict[str, Any]:
        return self._suggest(
            keyword,
            count=count,
            kind="job_suggestions",
            label="job suggestion keyword",
            params={},
        )

    def suggest_job_companies(self, keyword: str, *, count: int = 10) -> dict[str, Any]:
        return self._suggest(
            keyword,
            count=count,
            kind="company_suggestions",
            label="company suggestion keyword",
            params={"typeaheadType": "COMPANY"},
        )

    def _suggest(
        self,
        keyword: str,
        *,
        count: int,
        kind: str,
        label: str,
        params: Mapping[str, str],
    ) -> dict[str, Any]:
        query = self._search_text(keyword, label, maximum=300)
        if not query:
            raise LinkedInInputError(f"{label} must not be empty")
        requested_count = self._bounded_integer(
            count, "count", minimum=1, maximum=100
        )
        request_params = dict(params)
        request_params["query"] = query
        request_url = f"{_LOCATION_SUGGEST_URL}?{urlencode(request_params)}"
        response = self._request(request_url)
        final_url = str(response.url or request_url)
        self._validate_final_url(final_url)
        try:
            raw = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LinkedInResponseError("LinkedIn suggestions JSON is invalid") from exc
        if not isinstance(raw, list):
            raise LinkedInResponseError("LinkedIn suggestions must be a JSON array")

        items: list[dict[str, str]] = []
        for value in raw[:requested_count]:
            if not isinstance(value, Mapping):
                raise LinkedInResponseError("LinkedIn suggestion contains an invalid item")
            items.append(
                {
                    "id": _text(value.get("id")),
                    "type": _text(value.get("type")),
                    "name": _text(value.get("displayName")),
                    "tracking_id": _text(value.get("trackingId")),
                }
            )
        return {
            "kind": kind,
            "query": query,
            "count": len(items),
            "items": items,
        }

    def search_ads(
        self,
        *,
        keyword: str | None = None,
        advertiser_name: str | None = None,
        countries: str | Sequence[str] | None = None,
        date_option: str | None = None,
        sort_order: str | None = None,
        payer: str | None = None,
        startdate: str | None = None,
        enddate: str | None = None,
        impressions_min: str | int | float | None = None,
        impressions_max: str | int | float | None = None,
        included_facets: str | Sequence[str] | None = None,
        excluded_facets: str | Sequence[str] | None = None,
        pagination_token: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        params, query = normalize_ad_search_params(
            keyword=keyword,
            advertiser_name=advertiser_name,
            countries=countries,
            date_option=date_option,
            sort_order=sort_order,
            payer=payer,
            startdate=startdate,
            enddate=enddate,
            impressions_min=impressions_min,
            impressions_max=impressions_max,
            included_facets=included_facets,
            excluded_facets=excluded_facets,
            pagination_token=pagination_token,
        )
        requested_limit = self._bounded_integer(limit, "limit", minimum=1, maximum=100)
        base_params = [(key, value) for key, value in params if key != "paginationToken"]
        token = _text(query.get("pagination_token"))
        requested_tokens: set[str] = set()
        requested_urls: list[str] = []
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        total: int | None = None
        pagination: dict[str, Any] = {
            "token": token or None,
            "is_last_page": None,
        }

        while len(items) < requested_limit and len(requested_urls) < _AD_MAX_PAGES:
            request_params = list(base_params)
            endpoint = _AD_SEARCH_URL
            if token:
                endpoint = _AD_PAGINATION_URL
                request_params.append(("paginationToken", token))
                requested_tokens.add(token)
            request_url = f"{endpoint}?{urlencode(request_params)}"
            response = self._request(request_url)
            final_url = str(response.url or request_url)
            self._validate_final_url(final_url)
            requested_urls.append(request_url)

            page = self.parse_ads_html(response.text, page_url=final_url)
            if total is None and page["total"] is not None:
                total = page["total"]
            raw_items = page["items"]
            for item in raw_items:
                identifier = _text(item.get("ad_id"))
                if not identifier or identifier in seen_ids:
                    continue
                seen_ids.add(identifier)
                items.append(item)
                if len(items) == requested_limit:
                    break

            page_pagination = page["pagination"]
            next_token = _text(page_pagination.get("token"))
            is_last_page = page_pagination.get("is_last_page")
            pagination = {
                "token": next_token or None,
                "is_last_page": is_last_page,
            }
            if (
                len(items) >= requested_limit
                or is_last_page is True
                or not raw_items
                or not next_token
                or next_token == token
                or next_token in requested_tokens
            ):
                break
            token = next_token

        return {
            "kind": "ad_search",
            "source": "ssr_html",
            "query": query,
            "total": total,
            "items": items,
            "count": len(items),
            "pagination": pagination,
            "pages_fetched": len(requested_urls),
            "requested_urls": requested_urls,
        }

    @staticmethod
    def parse_ad_html(
        source: str,
        *,
        expected_id: str,
        page_url: str = "",
    ) -> dict[str, Any]:
        return parse_ad_detail_html(
            source,
            expected_id=expected_id,
            page_url=page_url,
        )

    @staticmethod
    def parse_ads_html(source: str, *, page_url: str = "") -> dict[str, Any]:
        return parse_ad_search_html(source, page_url=page_url)

    @classmethod
    def parse_post_html(
        cls,
        source: str,
        *,
        expected_id: str | None = None,
        expected_urn: str | None = None,
        page_url: str = "",
    ) -> dict[str, Any]:
        page = _parse_page(source)
        cls._reject_login_page(page, page_url)
        items = _json_ld_items(page)
        post = next(
            (
                item
                for item in items
                if _schema_types(item)
                & {"SocialMediaPosting", "DiscussionForumPosting", "VideoObject"}
            ),
            None,
        )
        if post is None:
            return cls._post_open_graph(
                page,
                expected_id=expected_id,
                expected_urn=expected_urn,
                page_url=page_url,
            )
        return cls._normalize_post(
            post,
            page,
            expected_id=expected_id,
            expected_urn=expected_urn,
            page_url=page_url,
        )

    @classmethod
    def parse_article_html(
        cls,
        source: str,
        *,
        expected_slug: str,
        page_url: str = "",
    ) -> dict[str, Any]:
        cls._slug(expected_slug, "article", _ARTICLE_SLUG_RE)
        page = _parse_page(source)
        cls._reject_login_page(page, page_url)
        items = _json_ld_items(page)
        article = next((item for item in items if "Article" in _schema_types(item)), None)
        canonical = cls._canonical(page, page_url)
        actual_slug = cls._path_slug(canonical, _ARTICLE_PATH_RE)
        if actual_slug and actual_slug != expected_slug:
            raise LinkedInResponseError(
                f"LinkedIn returned article {actual_slug}, expected {expected_slug}"
            )
        if article is None:
            return cls._article_open_graph(page, expected_slug, canonical)

        published_at, published_timestamp = _datetime_parts(article.get("datePublished"))
        modified_at, modified_timestamp = _datetime_parts(article.get("dateModified"))
        body = "\n\n".join(page.article_text_blocks).strip()
        if not body:
            body = _text(article.get("articleBody") or article.get("headline"))
        images = cls._article_images(article, page)
        videos = cls._article_videos(page)
        stats = _interaction_counts(article)
        code_data = {key: _decode_code(value) for key, value in page.code.items()}
        view_data = _mapping(code_data.get("articleViewEventData"))
        reading_time = _text(page.meta.get("twitter:data2"))
        reading_match = re.search(r"([0-9]+)\s+min", reading_time, re.IGNORECASE)
        return {
            "kind": "article",
            "source": "json_ld+ssr_html" if page.article_text_blocks else "json_ld",
            "slug": expected_slug,
            "url": canonical or f"{_BASE_URL}/pulse/{expected_slug}",
            "title": _text(article.get("name") or page.meta.get("og:title")),
            "summary": _text(article.get("headline") or page.meta.get("og:description")),
            "body": body,
            "author": cls._normalize_author(_mapping(article.get("author"))),
            "stats": stats,
            "published_at": published_at,
            "published_timestamp": published_timestamp,
            "modified_at": modified_at,
            "modified_timestamp": modified_timestamp,
            "images": images,
            "videos": videos,
            "embeds": list(dict.fromkeys(page.article_embeds)),
            "reading_time": reading_time or None,
            "reading_time_minutes": int(reading_match.group(1)) if reading_match else None,
            "accessible_for_free": article.get("isAccessibleForFree"),
            "article_id": _text(view_data.get("articleId")) or None,
            "article_urn": _text(
                code_data.get("articleUrn") or view_data.get("linkedInArticleUrn")
            )
            or None,
            "legacy_article_urn": _text(
                code_data.get("legacyArticleUrn") or view_data.get("articleUrn")
            )
            or None,
            "ugc_post_urn": _text(
                code_data.get("ugcPostUrn") or code_data.get("ugcPost")
            )
            or None,
            "open_graph": cls._open_graph(page),
        }

    @classmethod
    def parse_person_html(
        cls,
        source: str,
        *,
        expected_slug: str,
        page_url: str = "",
    ) -> dict[str, Any]:
        cls._slug(expected_slug, "person", _ENTITY_SLUG_RE)
        page = _parse_page(source)
        cls._reject_login_page(page, page_url)
        items = _json_ld_items(page)
        person = next((item for item in items if "Person" in _schema_types(item)), None)
        canonical = cls._canonical(page, page_url)
        actual_slug = cls._path_slug(canonical, _PROFILE_PATH_RE)
        if actual_slug and actual_slug.lower() != expected_slug.lower():
            raise LinkedInResponseError(
                f"LinkedIn returned person {actual_slug}, expected {expected_slug}"
            )
        posts = [
            cls._normalize_embedded_item(item)
            for item in items
            if "DiscussionForumPosting" in _schema_types(item)
        ]
        articles = [
            cls._normalize_embedded_item(item)
            for item in items
            if "Article" in _schema_types(item)
        ]
        if person is None:
            return cls._person_open_graph(page, expected_slug, canonical)
        address = _mapping(person.get("address"))
        connection_text, connections = cls._connections(page.meta.get("og:description"))
        return {
            "kind": "person",
            "source": "json_ld",
            "slug": expected_slug,
            "url": canonical or f"{_BASE_URL}/in/{expected_slug}",
            "name": _text(person.get("name")),
            "headline": cls._string_list(person.get("jobTitle")),
            "description": _text(person.get("description")),
            "image": _image_url(person.get("image")),
            "followers": _follow_count(person),
            "connections": connections,
            "connections_text": connection_text or None,
            "badges": _text(person.get("disambiguatingDescription")),
            "location": {
                "name": _text(address.get("addressLocality")),
                "country": _text(address.get("addressCountry")),
                "region": _text(address.get("addressRegion")),
            },
            "works_for": [
                cls._normalize_organization(item) for item in _list(person.get("worksFor"))
            ],
            "alumni_of": [
                cls._normalize_organization(item) for item in _list(person.get("alumniOf"))
            ],
            "languages": cls._string_list(person.get("knowsLanguage")),
            "awards": [dict(_mapping(item)) for item in _list(person.get("awards"))],
            "embedded_posts": posts,
            "embedded_articles": articles,
            "embedded_lists_partial": True,
            "open_graph": cls._open_graph(page),
        }

    @classmethod
    def parse_company_html(
        cls,
        source: str,
        *,
        expected_slug: str,
        page_url: str = "",
    ) -> dict[str, Any]:
        cls._slug(expected_slug, "company", _ENTITY_SLUG_RE)
        page = _parse_page(source)
        cls._reject_login_page(page, page_url)
        items = _json_ld_items(page)
        organization = next(
            (
                item
                for item in reversed(items)
                if "Organization" in _schema_types(item) and item.get("description")
            ),
            None,
        )
        canonical = cls._canonical(page, page_url)
        actual_slug = cls._path_slug(canonical, _COMPANY_PATH_RE)
        if actual_slug and actual_slug.lower() != expected_slug.lower():
            raise LinkedInResponseError(
                f"LinkedIn returned company {actual_slug}, expected {expected_slug}"
            )
        posts = [
            cls._normalize_embedded_item(item)
            for item in items
            if "DiscussionForumPosting" in _schema_types(item)
        ]
        if organization is None:
            return cls._company_open_graph(page, expected_slug, canonical)
        address = _mapping(organization.get("address"))
        employee_value = _mapping(organization.get("numberOfEmployees")).get("value")
        followers = cls._followers(page.meta.get("og:description"))
        return {
            "kind": "company",
            "source": "json_ld",
            "slug": expected_slug,
            "url": canonical or f"{_BASE_URL}/company/{expected_slug}",
            "name": _text(organization.get("name")),
            "description": _text(organization.get("description")),
            "logo": _image_url(organization.get("logo")),
            "website": cls._first_url(organization.get("sameAs")),
            "followers": followers,
            "employee_count": _optional_int(employee_value),
            "address": {
                "locality": _text(address.get("addressLocality")),
                "region": _text(address.get("addressRegion")),
                "postal_code": _text(address.get("postalCode")),
                "country": _text(address.get("addressCountry")),
            },
            "embedded_posts": posts,
            "embedded_lists_partial": True,
            "open_graph": cls._open_graph(page),
        }

    @classmethod
    def parse_job_html(
        cls,
        source: str,
        *,
        expected_id: str | None = None,
        page_url: str = "",
    ) -> dict[str, Any]:
        if expected_id is not None:
            expected_id = cls._job_id(expected_id)
        parser = _JobDetailParser()
        _parse_capture_html(source, parser)
        cls._reject_login_page(parser, page_url)  # type: ignore[arg-type]
        values = parser.values

        decorated_id = _text(_decode_code(_text(values.get("decorated_id"))))
        if decorated_id and not _JOB_ID_RE.fullmatch(decorated_id):
            raise LinkedInResponseError("LinkedIn job metadata contains an invalid id")
        raw_url = _absolute_url(values.get("url"), base=page_url or _BASE_URL)
        url_id = None
        if raw_url:
            cls._validate_final_url(raw_url)
            url_id = cls._job_from_value(raw_url)
        if decorated_id and url_id and decorated_id != url_id:
            raise LinkedInResponseError(
                f"LinkedIn returned job URL {url_id}, metadata id {decorated_id}"
            )
        identifier = decorated_id or url_id or expected_id
        if not identifier:
            raise LinkedInResponseError("LinkedIn job metadata has no job id")
        if expected_id and identifier != expected_id:
            raise LinkedInResponseError(
                f"LinkedIn returned job {identifier}, expected {expected_id}"
            )
        title = _text(values.get("title"))
        if not title:
            raise LinkedInResponseError("LinkedIn page has no public job metadata")

        company_url = _absolute_url(values.get("company_url"))
        if company_url:
            cls._validate_final_url(company_url)
            company_url = cls._clean_linkedin_url(company_url)
        criteria: list[dict[str, str]] = []
        criteria_by_name: dict[str, str] = {}
        labels = _list(values.get("criteria_labels"))
        criterion_values = _list(values.get("criteria_values"))
        for label, criterion_value in zip(labels, criterion_values):
            clean_label = _text(label)
            clean_value = _text(criterion_value)
            if not clean_label or not clean_value:
                continue
            name = cls._criterion_name(clean_label)
            criteria.append({"name": name, "label": clean_label, "value": clean_value})
            criteria_by_name.setdefault(name, clean_value)
        benefits = list(
            dict.fromkeys(_text(item) for item in _list(values.get("benefits")) if _text(item))
        )
        closed_text = _text(values.get("closed_text")) or None
        return {
            "kind": "job",
            "source": "guest_job",
            "id": identifier,
            "urn": f"urn:li:jobPosting:{identifier}",
            "url": cls._clean_linkedin_url(raw_url)
            if raw_url
            else f"{_BASE_URL}/jobs/view/{identifier}",
            "title": title,
            "company": {
                "name": _text(values.get("company")),
                "slug": cls._path_slug(company_url, _COMPANY_PATH_RE),
                "url": company_url,
                "logo": _absolute_url(values.get("company_logo")),
            },
            "location": _text(values.get("location")),
            "posted_at": None,
            "posted_timestamp": None,
            "posted_text": _text(values.get("posted_text")) or None,
            "applicants_text": _text(values.get("applicants_text")) or None,
            "closed": closed_text is not None,
            "closed_text": closed_text,
            "salary": _text(values.get("salary")) or None,
            "description": _text(values.get("description")),
            "criteria": criteria,
            "seniority_level": criteria_by_name.get("seniority_level"),
            "employment_type": criteria_by_name.get("employment_type"),
            "job_function": criteria_by_name.get("job_function"),
            "industries": criteria_by_name.get("industries"),
            "benefits": benefits,
        }

    @classmethod
    def parse_jobs_html(
        cls, source: str, *, page_url: str = ""
    ) -> dict[str, Any]:
        parser = _JobSearchParser()
        _parse_capture_html(source, parser)
        cls._reject_login_page(parser, page_url)  # type: ignore[arg-type]
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in parser.cards:
            item = cls._normalize_job_card(raw)
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)
        return {"items": items, "count": len(items), "total": parser.total}

    @classmethod
    def _normalize_post(
        cls,
        raw: Mapping[str, Any],
        page: _PageParser,
        *,
        expected_id: str | None,
        expected_urn: str | None,
        page_url: str,
    ) -> dict[str, Any]:
        canonical = _absolute_url(
            raw.get("@id") or raw.get("url") or page.canonical or page.meta.get("og:url"),
            base=page_url or _BASE_URL,
        )
        if canonical:
            cls._validate_final_url(canonical)
        identifier = cls._activity_from_value(canonical) or expected_id
        if not identifier:
            raise LinkedInResponseError("LinkedIn post metadata has no activity id")
        if expected_id and identifier != expected_id:
            raise LinkedInResponseError(
                f"LinkedIn returned activity {identifier}, expected {expected_id}"
            )
        meta_urn = cls._urn_from_value(page.meta.get("lnkd:url"))
        meta_urn_id = cls._activity_from_value(meta_urn)
        if meta_urn_id and meta_urn_id != identifier:
            raise LinkedInResponseError(
                f"LinkedIn returned URN id {meta_urn_id}, expected activity {identifier}"
            )
        urn = meta_urn or expected_urn or f"urn:li:activity:{identifier}"
        body = _text(raw.get("articleBody") or raw.get("description") or raw.get("text"))
        published_at, published_timestamp = _datetime_parts(
            raw.get("datePublished") or raw.get("uploadDate")
        )
        comments = [
            cls._normalize_comment(item)
            for item in _list(raw.get("comment"))
            if isinstance(item, Mapping)
        ]
        schema_type = next(iter(_schema_types(raw) - {""}), "")
        images = cls._post_images(raw, page)
        video = cls._post_video(raw) if schema_type == "VideoObject" or raw.get("contentUrl") else None
        return {
            "kind": "post",
            "source": "json_ld",
            "schema_type": schema_type,
            "id": identifier,
            "activity_id": identifier,
            "urn": urn,
            "url": canonical or f"{_BASE_URL}/feed/update/{urn}",
            "title": _text(raw.get("headline") or raw.get("name")),
            "body": body,
            "author": cls._normalize_author(
                _mapping(raw.get("author") or raw.get("creator"))
            ),
            "stats": _interaction_counts(raw),
            "published_at": published_at,
            "published_timestamp": published_timestamp,
            "media_type": "video" if video else ("image" if images else "text"),
            "images": images,
            "video": video,
            "comments_total": _interaction_counts(raw)["comments"],
            "comments_embedded": len(comments),
            "comments": comments,
            "open_graph": cls._open_graph(page),
        }

    @classmethod
    def _post_open_graph(
        cls,
        page: _PageParser,
        *,
        expected_id: str | None,
        expected_urn: str | None,
        page_url: str,
    ) -> dict[str, Any]:
        og = cls._open_graph(page)
        if not og.get("title") and not og.get("description"):
            raise LinkedInResponseError("LinkedIn page has no public post metadata")
        canonical = cls._canonical(page, page_url)
        identifier = cls._activity_from_value(canonical) or expected_id
        if not identifier:
            raise LinkedInResponseError("LinkedIn OpenGraph metadata has no activity id")
        if expected_id and identifier != expected_id:
            raise LinkedInResponseError(
                f"LinkedIn returned activity {identifier}, expected {expected_id}"
            )
        body, comments = cls._description_and_comments(_text(og.get("description")))
        image = _absolute_url(og.get("image"), base=canonical or _BASE_URL)
        urn = expected_urn or f"urn:li:activity:{identifier}"
        return {
            "kind": "post",
            "source": "open_graph",
            "schema_type": None,
            "id": identifier,
            "activity_id": identifier,
            "urn": urn,
            "url": canonical or f"{_BASE_URL}/feed/update/{urn}",
            "title": _text(og.get("title")),
            "body": body,
            "author": cls._normalize_author({}),
            "stats": {"likes": None, "comments": comments, "reposts": None},
            "published_at": None,
            "published_timestamp": None,
            "media_type": "image" if image else "text",
            "images": [{"url": image, "role": "open_graph"}] if image else [],
            "video": None,
            "comments_total": comments,
            "comments_embedded": 0,
            "comments": [],
            "open_graph": og,
        }

    @classmethod
    def _article_open_graph(
        cls, page: _PageParser, slug: str, canonical: str
    ) -> dict[str, Any]:
        og = cls._open_graph(page)
        if not og.get("title") and not og.get("description"):
            raise LinkedInResponseError("LinkedIn page has no public article metadata")
        image = _absolute_url(og.get("image"), base=canonical or _BASE_URL)
        return {
            "kind": "article",
            "source": "open_graph",
            "slug": slug,
            "url": canonical or f"{_BASE_URL}/pulse/{slug}",
            "title": _text(og.get("title")),
            "summary": _text(og.get("description")),
            "body": _text(og.get("description")),
            "author": cls._normalize_author({}),
            "stats": {"likes": None, "comments": None, "reposts": None},
            "published_at": None,
            "published_timestamp": None,
            "modified_at": None,
            "modified_timestamp": None,
            "images": [{"url": image, "role": "open_graph"}] if image else [],
            "videos": [],
            "embeds": [],
            "reading_time": _text(page.meta.get("twitter:data2")) or None,
            "reading_time_minutes": None,
            "accessible_for_free": None,
            "article_id": None,
            "article_urn": None,
            "legacy_article_urn": None,
            "ugc_post_urn": None,
            "open_graph": og,
        }

    @classmethod
    def _person_open_graph(
        cls, page: _PageParser, slug: str, canonical: str
    ) -> dict[str, Any]:
        og = cls._open_graph(page)
        if not og.get("title") and not og.get("description"):
            raise LinkedInResponseError("LinkedIn page has no public person metadata")
        first = _text(page.meta.get("profile:first_name"))
        last = _text(page.meta.get("profile:last_name"))
        name = " ".join(value for value in (first, last) if value)
        connection_text, connections = cls._connections(og.get("description"))
        return {
            "kind": "person",
            "source": "open_graph",
            "slug": slug,
            "url": canonical or f"{_BASE_URL}/in/{slug}",
            "name": name or _text(og.get("title")).split(" - ", 1)[0],
            "headline": [],
            "description": _text(og.get("description")),
            "image": _absolute_url(og.get("image")),
            "followers": None,
            "connections": connections,
            "connections_text": connection_text or None,
            "badges": "",
            "location": {"name": "", "country": "", "region": ""},
            "works_for": [],
            "alumni_of": [],
            "languages": [],
            "awards": [],
            "embedded_posts": [],
            "embedded_articles": [],
            "embedded_lists_partial": True,
            "open_graph": og,
        }

    @classmethod
    def _company_open_graph(
        cls, page: _PageParser, slug: str, canonical: str
    ) -> dict[str, Any]:
        og = cls._open_graph(page)
        if not og.get("title") and not og.get("description"):
            raise LinkedInResponseError("LinkedIn page has no public company metadata")
        return {
            "kind": "company",
            "source": "open_graph",
            "slug": slug,
            "url": canonical or f"{_BASE_URL}/company/{slug}",
            "name": _text(og.get("title")).removesuffix(" | LinkedIn"),
            "description": _text(og.get("description")),
            "logo": _absolute_url(og.get("image")),
            "website": "",
            "followers": cls._followers(og.get("description")),
            "employee_count": None,
            "address": {"locality": "", "region": "", "postal_code": "", "country": ""},
            "embedded_posts": [],
            "embedded_lists_partial": True,
            "open_graph": og,
        }

    @classmethod
    def _normalize_job_card(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        urn = _text(raw.get("urn"))
        urn_match = _JOB_URN_RE.fullmatch(urn)
        raw_url = _absolute_url(raw.get("url"))
        url_id = None
        if raw_url:
            cls._validate_final_url(raw_url)
            url_id = cls._job_from_value(raw_url)
        urn_id = urn_match.group(1) if urn_match else None
        if urn and not urn_id:
            raise LinkedInResponseError("LinkedIn job card contains an invalid URN")
        if urn_id and url_id and urn_id != url_id:
            raise LinkedInResponseError(
                f"LinkedIn job card URL {url_id} does not match URN {urn_id}"
            )
        identifier = urn_id or url_id
        if not identifier:
            raise LinkedInResponseError("LinkedIn job card has no job id")
        title = _text(raw.get("title"))
        if not title:
            raise LinkedInResponseError(
                f"LinkedIn job card {identifier} has no public title"
            )
        company_url = _absolute_url(raw.get("company_url"))
        if company_url:
            cls._validate_final_url(company_url)
            company_url = cls._clean_linkedin_url(company_url)
        posted_at, posted_timestamp = _datetime_parts(raw.get("posted_at"))
        benefits = list(
            dict.fromkeys(
                _text(item) for item in _list(raw.get("benefits")) if _text(item)
            )
        )
        return {
            "kind": "job",
            "source": "guest_jobs_search",
            "id": identifier,
            "urn": urn or f"urn:li:jobPosting:{identifier}",
            "url": cls._clean_linkedin_url(raw_url)
            if raw_url
            else f"{_BASE_URL}/jobs/view/{identifier}",
            "title": title,
            "company": {
                "name": _text(raw.get("company")),
                "slug": cls._path_slug(company_url, _COMPANY_PATH_RE),
                "url": company_url,
                "logo": _absolute_url(raw.get("company_logo")),
            },
            "location": _text(raw.get("location")),
            "posted_at": posted_at,
            "posted_timestamp": posted_timestamp,
            "posted_text": _text(raw.get("posted_text")) or None,
            "benefits": benefits,
        }

    @classmethod
    def _normalize_embedded_item(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        url = _absolute_url(raw.get("url") or raw.get("mainEntityOfPage"))
        published_at, published_timestamp = _datetime_parts(raw.get("datePublished"))
        types = _schema_types(raw)
        kind = "article" if "Article" in types else "post"
        return {
            "kind": kind,
            "id": cls._activity_from_value(url) if kind == "post" else None,
            "slug": cls._path_slug(url, _ARTICLE_PATH_RE) if kind == "article" else None,
            "url": url,
            "title": _text(raw.get("name") or raw.get("headline")),
            "body": _text(raw.get("articleBody") or raw.get("text") or raw.get("headline")),
            "author": cls._normalize_author(_mapping(raw.get("author") or raw.get("creator"))),
            "likes": _interaction_counts(raw)["likes"],
            "image": _image_url(raw.get("image")),
            "published_at": published_at,
            "published_timestamp": published_timestamp,
        }

    @classmethod
    def _normalize_comment(cls, raw: Any) -> dict[str, Any]:
        comment = _mapping(raw)
        published_at, published_timestamp = _datetime_parts(comment.get("datePublished"))
        return {
            "body": _text(comment.get("text")),
            "author": cls._normalize_author(
                _mapping(comment.get("author") or comment.get("creator"))
            ),
            "likes": _interaction_counts(comment)["likes"],
            "published_at": published_at,
            "published_timestamp": published_timestamp,
        }

    @classmethod
    def _normalize_author(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        types = _schema_types(raw)
        kind = "company" if "Organization" in types else ("person" if raw else None)
        image = _image_url(raw.get("image"))
        url = _absolute_url(raw.get("url"))
        slug = None
        if kind == "person":
            slug = cls._path_slug(url, _PROFILE_PATH_RE)
        elif kind == "company":
            slug = cls._path_slug(url, _COMPANY_PATH_RE)
        return {
            "kind": kind,
            "name": _text(raw.get("name")),
            "slug": slug,
            "url": url,
            "image": image,
            "followers": _follow_count(raw),
        }

    @classmethod
    def _normalize_organization(cls, value: Any) -> dict[str, Any]:
        raw = _mapping(value)
        member = _mapping(raw.get("member"))
        location = raw.get("location")
        location_name = _text(location)
        if isinstance(location, Mapping):
            location_name = _text(location.get("name") or location.get("addressLocality"))
        return {
            "type": next(iter(_schema_types(raw) - {""}), ""),
            "name": _text(raw.get("name")),
            "url": _absolute_url(raw.get("url")),
            "location": location_name,
            "start_date": _text(member.get("startDate")) or None,
            "end_date": _text(member.get("endDate")) or None,
        }

    @classmethod
    def _post_images(
        cls, raw: Mapping[str, Any], page: _PageParser
    ) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        seen: set[str] = set()

        def append(value: Any, role: str) -> None:
            url = _image_url(value)
            if url and url not in seen:
                seen.add(url)
                output.append({"url": url, "role": role})

        values = raw.get("image")
        for value in (_list(values) if isinstance(values, list) else [values]):
            append(value, "attachment")
        thumbnail = raw.get("thumbnailUrl")
        for value in (_list(thumbnail) if isinstance(thumbnail, list) else [thumbnail]):
            append(value, "thumbnail")
        if not output:
            append(page.meta.get("og:image"), "open_graph")
        return output

    @staticmethod
    def _post_video(raw: Mapping[str, Any]) -> dict[str, Any]:
        thumbnail = raw.get("thumbnailUrl")
        if isinstance(thumbnail, list):
            thumbnail = thumbnail[0] if thumbnail else None
        return {
            "url": _absolute_url(raw.get("contentUrl")),
            "embed_url": _absolute_url(raw.get("embedUrl")),
            "thumbnail_url": _image_url(thumbnail),
            "duration": _duration_seconds(raw.get("duration")),
            "width": _optional_int(raw.get("width")),
            "height": _optional_int(raw.get("height")),
        }

    @classmethod
    def _article_images(
        cls, article: Mapping[str, Any], page: _PageParser
    ) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        seen: set[str] = set()

        def append(url: str, role: str, alt: str = "") -> None:
            if url and url not in seen:
                seen.add(url)
                output.append({"url": url, "role": role, "alt": alt})

        append(_image_url(article.get("image")) or _absolute_url(page.meta.get("og:image")), "cover")
        for item in page.article_images:
            append(item["url"], "inline", item.get("alt", ""))
        return output

    @staticmethod
    def _article_videos(page: _PageParser) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in page.article_videos:
            try:
                decoded = json.loads(raw.get("data-sources", "[]"))
            except (json.JSONDecodeError, TypeError, ValueError):
                decoded = []
            sources = [
                {
                    "url": _absolute_url(_mapping(item).get("src")),
                    "type": _text(_mapping(item).get("type")),
                    "bitrate": _optional_int(_mapping(item).get("bitrate")),
                }
                for item in _list(decoded)
                if _mapping(item).get("src")
            ]
            output.append(
                {
                    "urn": _text(raw.get("data-digitalmedia-asset-urn")) or None,
                    "poster_url": _absolute_url(raw.get("data-poster-url")),
                    "captions_url": _absolute_url(raw.get("data-captions-url")),
                    "language": _text(raw.get("data-language")) or None,
                    "sources": sources,
                }
            )
        return output

    def _company_public_page(
        self, value: str
    ) -> tuple[
        dict[str, str],
        dict[str, Any],
        _PageParser,
        _CompanyPublicParser,
        str,
    ]:
        reference = self.parse_company_reference(value)
        response = self._request(reference["url"])
        final_url = str(response.url or reference["url"])
        self._validate_final_url(final_url)
        profile = self.parse_company_html(
            response.text,
            expected_slug=reference["slug"],
            page_url=final_url,
        )
        page = _parse_page(response.text)
        self._reject_login_page(page, final_url)
        canonical = self._canonical(page, final_url)
        actual_slug = self._path_slug(canonical, _COMPANY_PATH_RE)
        if not actual_slug:
            raise LinkedInResponseError(
                "LinkedIn company page has no canonical company identity"
            )
        if actual_slug.lower() != reference["slug"].lower():
            raise LinkedInResponseError(
                f"LinkedIn returned company {actual_slug}, expected {reference['slug']}"
            )
        parser = _parse_capture_html(response.text, _CompanyPublicParser())
        self._reject_login_page(parser, final_url)  # type: ignore[arg-type]
        return reference, profile, page, parser, reference["url"]

    @classmethod
    def _company_feed_reference(cls, page: _PageParser) -> tuple[str, str, str]:
        company_id, feed_path, query_token = cls._company_feed_base(page, required=True)
        raw_token = _decode_code(page.code.get("paginationToken", ""))
        code_token = _text(raw_token) if isinstance(raw_token, str) else ""
        if query_token and code_token and query_token != code_token:
            raise LinkedInResponseError(
                "LinkedIn company pagination tokens do not match"
            )
        token = code_token or query_token
        if (
            not token
            or len(token) > 512
            or any(ord(character) < 32 for character in token)
        ):
            raise LinkedInResponseError(
                "LinkedIn company pagination token is malformed"
            )
        assert company_id is not None
        return company_id, token, feed_path

    @classmethod
    def _company_feed_identity(cls, page: _PageParser) -> str | None:
        company_id, _, _ = cls._company_feed_base(page, required=False)
        return company_id

    @classmethod
    def _company_feed_base(
        cls, page: _PageParser, *, required: bool
    ) -> tuple[str | None, str, str]:
        raw_base = _decode_code(page.code.get("feedUpdatesBaseUrl", ""))
        if not isinstance(raw_base, str) or not raw_base.strip():
            if required:
                raise LinkedInResponseError(
                    "LinkedIn company page has no public feedUpdatesBaseUrl"
                )
            return None, "", ""
        resolved = _absolute_url(raw_base)
        cls._validate_final_url(resolved)
        try:
            parsed = urlsplit(resolved)
        except ValueError as exc:
            raise LinkedInResponseError(
                "LinkedIn company feedUpdatesBaseUrl is malformed"
            ) from exc
        feed_path = unquote(parsed.path)
        match = _ORGANIZATION_FEED_PATH_RE.fullmatch(feed_path)
        if not match:
            raise LinkedInResponseError(
                "LinkedIn company feedUpdatesBaseUrl has an invalid path"
            )
        query_token = cls._last_query_value(
            parse_qs(parsed.query, keep_blank_values=True), "paginationToken"
        )
        return match.group(1), feed_path, query_token

    @classmethod
    def _parse_company_feed_fragment(
        cls, source: str, *, page_url: str
    ) -> list[dict[str, Any]]:
        parser = _parse_capture_html(source, _CompanyPublicParser())
        cls._reject_login_page(parser, page_url)  # type: ignore[arg-type]
        if not parser.saw_feed_markup:
            raise LinkedInResponseError(
                "LinkedIn company feed fragment has no public feed metadata"
            )
        return parser.feed_cards

    @classmethod
    def _normalize_company_feed_card(
        cls, raw: Mapping[str, Any], expected_slug: str
    ) -> dict[str, Any]:
        urn = _text(raw.get("urn"))
        urn_match = _URN_RE.fullmatch(urn)
        if not urn_match or urn_match.group(1) != "activity":
            raise LinkedInResponseError(
                "LinkedIn company feed card has an invalid activity URN"
            )
        identifier = urn_match.group(2)
        raw_url = _absolute_url(raw.get("url"))
        if not raw_url:
            raise LinkedInResponseError("LinkedIn company feed card has no public URL")
        cls._validate_final_url(raw_url)
        url_id = cls._activity_from_value(raw_url)
        if not url_id:
            raise LinkedInResponseError(
                "LinkedIn company feed card URL has no activity id"
            )
        if url_id != identifier:
            raise LinkedInResponseError(
                f"LinkedIn company feed card URL {url_id} does not match URN {identifier}"
            )
        clean_url = cls._clean_linkedin_url(raw_url)

        raw_author = _mapping(raw.get("author"))
        author_url = _absolute_url(raw_author.get("url"))
        if not author_url:
            raise LinkedInResponseError(
                "LinkedIn company feed card has no author company URL"
            )
        cls._validate_final_url(author_url)
        author_url = cls._clean_linkedin_url(author_url)
        author_slug = cls._path_slug(author_url, _COMPANY_PATH_RE)
        if not author_slug or author_slug.lower() != expected_slug.lower():
            raise LinkedInResponseError(
                "LinkedIn company feed author identity mismatch: "
                f"expected {expected_slug}, received {author_slug or 'unknown'}"
            )

        media: list[dict[str, Any]] = []
        seen_media: set[tuple[str, str, str]] = set()
        for value in _list(raw.get("media")):
            item = dict(_mapping(value))
            media_type = _text(item.get("type"))
            media_url = _absolute_url(item.get("url"))
            poster_url = _absolute_url(item.get("poster_url"))
            key = (media_type, media_url, poster_url)
            if not media_type or (not media_url and not poster_url) or key in seen_media:
                continue
            seen_media.add(key)
            item["type"] = media_type
            item["url"] = media_url
            if "poster_url" in item:
                item["poster_url"] = poster_url
            media.append(item)

        return {
            "kind": "post",
            "source": "ssr_html",
            "id": identifier,
            "urn": urn,
            "url": clean_url,
            "body": _text(raw.get("body")),
            "posted_text": _text(raw.get("posted_text") or raw.get("posted_at")),
            "author": {
                "name": _text(
                    raw_author.get("name")
                    or _text(raw_author.get("image_alt")).removeprefix(
                        "View organization page for "
                    )
                ),
                "slug": author_slug,
                "url": author_url,
                "image": _absolute_url(raw_author.get("image")),
            },
            "likes": _optional_int(
                raw.get("likes")
                if raw.get("likes") is not None
                else raw.get("likes_attribute")
            ),
            "comments": _optional_int(
                raw.get("comments")
                if raw.get("comments") is not None
                else raw.get("comments_attribute")
            ),
            "media": media,
        }

    @classmethod
    def _normalize_company_people(
        cls, values: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in values:
            raw_url = _absolute_url(raw.get("url"))
            if not raw_url:
                raise LinkedInResponseError(
                    "LinkedIn public employee card has no profile URL"
                )
            cls._validate_final_url(raw_url)
            clean_url = cls._clean_linkedin_url(raw_url)
            slug = cls._path_slug(clean_url, _PROFILE_PATH_RE)
            if not slug:
                raise LinkedInResponseError(
                    "LinkedIn public employee card URL is not a profile"
                )
            if slug.lower() in seen:
                continue
            seen.add(slug.lower())
            name = _text(raw.get("name") or raw.get("image_alt"))
            if not name:
                raise LinkedInResponseError(
                    "LinkedIn public employee card has no name"
                )
            output.append(
                {
                    "kind": "person",
                    "name": name,
                    "slug": slug,
                    "url": clean_url,
                    "image": _absolute_url(raw.get("image")),
                    "headline": _text(raw.get("headline")),
                }
            )
        return output

    @classmethod
    def _normalize_company_affiliates(
        cls, values: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in values:
            raw_url = _absolute_url(raw.get("url"))
            if not raw_url:
                raise LinkedInResponseError(
                    "LinkedIn affiliated page card has no public URL"
                )
            cls._validate_final_url(raw_url)
            clean_url = cls._clean_linkedin_url(raw_url)
            slug = cls._path_slug(clean_url, _COMPANY_PATH_RE)
            kind = "company"
            if not slug:
                slug = cls._path_slug(clean_url, _SHOWCASE_PATH_RE)
                kind = "showcase"
            if not slug or not _ENTITY_SLUG_RE.fullmatch(slug):
                raise LinkedInResponseError(
                    "LinkedIn affiliated page card URL has an invalid identity"
                )
            key = (kind, slug.lower())
            if key in seen:
                continue
            seen.add(key)
            name = _text(raw.get("name") or raw.get("image_alt"))
            if not name:
                raise LinkedInResponseError(
                    "LinkedIn affiliated page card has no name"
                )
            output.append(
                {
                    "kind": kind,
                    "name": name,
                    "slug": slug,
                    "url": clean_url,
                    "logo": _absolute_url(raw.get("logo")),
                    "industry": _text(raw.get("industry")),
                    "location": _text(raw.get("location")),
                }
            )
        return output

    @staticmethod
    def _company_result_identity(
        profile: Mapping[str, Any], company_id: str | None
    ) -> dict[str, Any]:
        return {
            "id": company_id,
            "slug": _text(profile.get("slug")),
            "name": _text(profile.get("name")),
            "url": _text(profile.get("url")),
        }

    def _request(
        self, url: str, *, accepted_statuses: set[int] | None = None
    ) -> requests.Response:
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers={"Referer": f"{_BASE_URL}/"},
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.exceptions.RequestException as exc:
                if attempt >= self.retries:
                    raise LinkedInResponseError(f"LinkedIn request failed: {exc}") from exc
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code == 200 or response.status_code in (
                accepted_statuses or set()
            ):
                return response
            if response.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                time.sleep(0.4 * (2**attempt))
                continue
            raise LinkedInResponseError(f"LinkedIn returned HTTP {response.status_code}")
        raise LinkedInResponseError("LinkedIn request exhausted all retries")

    @classmethod
    def _entity_reference(cls, value: str, kind: str) -> dict[str, str]:
        source = cls._reference(value, kind)
        if _ENTITY_SLUG_RE.fullmatch(source):
            slug = source
        else:
            candidate = cls._linkedin_url(source)
            pattern = _PROFILE_PATH_RE if kind == "person" else _COMPANY_PATH_RE
            match = pattern.fullmatch(unquote(urlsplit(candidate).path))
            if not match:
                raise LinkedInInputError(f"reference is not a LinkedIn public {kind} URL or slug")
            slug = match.group(1)
            cls._slug(slug, kind, _ENTITY_SLUG_RE)
        route = "in" if kind == "person" else "company"
        return {"kind": kind, "slug": slug, "url": f"{_BASE_URL}/{route}/{slug}"}

    @staticmethod
    def _post_reference(
        identifier: str, urn: str, slug: str | None, url: str
    ) -> dict[str, Any]:
        return {"kind": "post", "id": identifier, "urn": urn, "slug": slug, "url": url}

    @staticmethod
    def _reference(value: Any, label: str) -> str:
        if isinstance(value, bool):
            raise LinkedInInputError(f"{label} reference must be a string or integer id")
        if isinstance(value, int):
            return str(value)
        if not isinstance(value, str) or not value.strip():
            raise LinkedInInputError(f"{label} reference must be a non-empty string")
        source = html.unescape(value.strip())
        match = _URL_IN_TEXT_RE.search(source)
        return match.group(0) if match else source

    @staticmethod
    def _activity_id(value: Any) -> str:
        identifier = _text(value)
        if not _ACTIVITY_ID_RE.fullmatch(identifier):
            raise LinkedInInputError("LinkedIn activity id must be 10 to 22 decimal digits")
        return identifier

    @staticmethod
    def _slug(value: Any, label: str, pattern: re.Pattern[str]) -> str:
        slug = unquote(_text(value))
        if not pattern.fullmatch(slug):
            raise LinkedInInputError(f"LinkedIn {label} slug contains invalid characters")
        return slug

    @staticmethod
    def _linkedin_url(value: str) -> str:
        candidate = value
        if "://" not in candidate and _LINKEDIN_HOST_PREFIX_RE.match(candidate):
            candidate = f"https://{candidate}"
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise LinkedInInputError("LinkedIn URL is malformed") from exc
        host = (parsed.hostname or "").lower().rstrip(".")
        scheme = parsed.scheme.lower()
        expected_port = 80 if scheme == "http" else 443
        if (
            scheme not in {"http", "https"}
            or not LinkedInClient._owned_host(host)
            or parsed.username is not None
            or parsed.password is not None
            or (port is not None and port != expected_port)
        ):
            raise LinkedInInputError("URL must use an owned LinkedIn HTTP host")
        return urlunsplit(("https", "www.linkedin.com", parsed.path, parsed.query, ""))

    @staticmethod
    def _owned_host(host: str) -> bool:
        return host == "linkedin.com" or bool(
            re.fullmatch(r"(?:www|[a-z]{2})\.linkedin\.com", host)
        )

    @classmethod
    def _validate_final_url(cls, value: str) -> None:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise LinkedInResponseError("LinkedIn returned a malformed final URL") from exc
        scheme = parsed.scheme.lower()
        expected_port = 80 if scheme == "http" else 443
        if (
            scheme not in {"http", "https"}
            or not cls._owned_host((parsed.hostname or "").lower().rstrip("."))
            or parsed.username is not None
            or parsed.password is not None
            or (port is not None and port != expected_port)
        ):
            raise LinkedInResponseError("LinkedIn request left the owned hosts")

    @classmethod
    def _activity_from_value(cls, value: Any) -> str | None:
        source = _text(value)
        urn = cls._urn_from_value(source)
        if urn:
            match = _URN_RE.fullmatch(urn)
            return match.group(2) if match else None
        try:
            path = unquote(urlsplit(source).path)
        except ValueError:
            path = source
        post = _POST_PATH_RE.fullmatch(path)
        if post:
            match = _POST_ACTIVITY_RE.search(post.group(1))
            return match.group(1) if match else None
        return None

    @staticmethod
    def _urn_from_value(value: Any) -> str | None:
        source = _text(value)
        direct = _URN_RE.fullmatch(source)
        if direct:
            return source
        try:
            path = unquote(urlsplit(source).path)
        except ValueError:
            return None
        match = _FEED_PATH_RE.fullmatch(path)
        return match.group(1) if match else None

    @staticmethod
    def _path_slug(value: str, pattern: re.Pattern[str]) -> str | None:
        if not value:
            return None
        try:
            path = unquote(urlsplit(value).path)
        except ValueError:
            return None
        match = pattern.fullmatch(path)
        return match.group(1) if match else None

    @staticmethod
    def _canonical(page: _PageParser, page_url: str) -> str:
        value = page.canonical or page.meta.get("og:url") or page_url
        result = _absolute_url(value, base=page_url or _BASE_URL)
        if result:
            LinkedInClient._validate_final_url(result)
        return result

    @staticmethod
    def _open_graph(page: _PageParser) -> dict[str, str]:
        return {
            "title": page.meta.get("og:title", ""),
            "description": page.meta.get("og:description", ""),
            "url": _absolute_url(page.meta.get("og:url")),
            "image": _absolute_url(page.meta.get("og:image")),
            "type": page.meta.get("og:type", ""),
            "locale": page.meta.get("og:locale", ""),
        }

    @staticmethod
    def _reject_login_page(page: _PageParser, page_url: str = "") -> None:
        title = " ".join((page.title, page.meta.get("og:title", ""))).lower()
        login_titles = (
            "linkedin login",
            "sign in | linkedin",
            "sign up | linkedin",
            "log in or sign up",
            "join linkedin",
        )
        login_path = re.compile(r"^/(?:authwall|checkpoint|login|signup)(?:/|$)")
        blocked_url = False
        for value in (page.canonical, page.meta.get("og:url", ""), page_url):
            try:
                path = urlsplit(value).path.lower()
            except ValueError:
                continue
            if login_path.match(path):
                blocked_url = True
                break
        if any(value in title for value in login_titles) or blocked_url:
            raise LinkedInResponseError("LinkedIn returned its login page")

    @staticmethod
    def _description_and_comments(value: str) -> tuple[str, int | None]:
        match = _COMMENT_SUFFIX_RE.search(value)
        if not match:
            return value.strip(), None
        return value[: match.start()].rstrip(), _optional_int(match.group(1))

    @staticmethod
    def _followers(value: Any) -> int | None:
        match = _FOLLOWER_RE.search(_text(value))
        return _optional_int(match.group(1)) if match else None

    @staticmethod
    def _connections(value: Any) -> tuple[str, int | None]:
        match = _CONNECTION_RE.search(_text(value))
        if not match:
            return "", None
        raw = match.group(1)
        return raw, _optional_int(raw.rstrip("+"))

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        values = _list(value) if isinstance(value, list) else [value]
        return [_text(item) for item in values if _text(item)]

    @staticmethod
    def _first_url(value: Any) -> str:
        values = _list(value) if isinstance(value, list) else [value]
        return next((_absolute_url(item) for item in values if _text(item)), "")

    @staticmethod
    def _job_id(value: Any) -> str:
        identifier = _text(value)
        if not _JOB_ID_RE.fullmatch(identifier):
            raise LinkedInInputError("LinkedIn job id must be 6 to 20 decimal digits")
        return identifier

    @classmethod
    def _company_numeric_id(cls, value: Any) -> str:
        identifier = cls._numeric_filter(value, "company id")
        if not identifier:
            raise LinkedInInputError("company id must not be empty")
        return identifier

    @staticmethod
    def _job_from_value(value: Any) -> str | None:
        source = _text(value)
        urn = _JOB_URN_RE.fullmatch(source)
        if urn:
            return urn.group(1)
        try:
            path = unquote(urlsplit(source).path)
        except ValueError:
            return None
        for pattern in (_JOB_VIEW_PATH_RE, _JOB_DETAIL_PATH_RE):
            match = pattern.fullmatch(path)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _clean_linkedin_url(value: Any) -> str:
        source = _absolute_url(value)
        if not source:
            return ""
        LinkedInClient._validate_final_url(source)
        parsed = urlsplit(source)
        return urlunsplit(("https", "www.linkedin.com", parsed.path, "", ""))

    @staticmethod
    def _last_query_value(query: Mapping[str, Sequence[str]], key: str) -> str:
        values = query.get(key, ())
        return _text(values[-1]) if values else ""

    @staticmethod
    def _search_text(value: Any, label: str, *, maximum: int) -> str:
        if value in (None, ""):
            return ""
        if not isinstance(value, str):
            raise LinkedInInputError(f"{label} must be text")
        result = " ".join(html.unescape(value).split())
        if len(result) > maximum:
            raise LinkedInInputError(f"{label} must be at most {maximum} characters")
        return result

    @staticmethod
    def _filter_items(value: Any, label: str) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, bool):
            raise LinkedInInputError(f"{label} is invalid")
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            sources = list(value)
        else:
            sources = [value]
        output: list[str] = []
        for source in sources:
            if isinstance(source, bool):
                raise LinkedInInputError(f"{label} is invalid")
            for item in str(source).split(","):
                clean = item.strip()
                if clean:
                    output.append(clean)
        return output

    @classmethod
    def _numeric_filter(
        cls, value: Any, label: str, *, multiple: bool = False
    ) -> str:
        items = cls._filter_items(value, label)
        if not multiple and len(items) > 1:
            raise LinkedInInputError(f"{label} accepts one numeric id")
        output: list[str] = []
        for item in items:
            if not re.fullmatch(r"[1-9]\d{0,19}", item):
                raise LinkedInInputError(f"{label} must contain positive decimal ids")
            if item not in output:
                output.append(item)
        return ",".join(output)

    @classmethod
    def _time_range_filter(cls, value: Any) -> str:
        items = cls._filter_items(value, "time range")
        if not items:
            return ""
        if len(items) != 1:
            raise LinkedInInputError("time range accepts one value")
        source = items[0].lower()
        code = _TIME_RANGE_CODES.get(source)
        if not code and re.fullmatch(r"r[1-9]\d{0,8}", source):
            code = source
        if not code:
            raise LinkedInInputError(
                "time range must be past_24h, past_week, past_month, or rSECONDS"
            )
        return code

    @classmethod
    def _coded_filter(
        cls, value: Any, label: str, codes: Mapping[str, str]
    ) -> str:
        output: list[str] = []
        for item in cls._filter_items(value, label):
            code = codes.get(item.lower())
            if not code:
                raise LinkedInInputError(f"{label} contains an unsupported value")
            if code not in output:
                output.append(code)
        return ",".join(output)

    @classmethod
    def _sort_by_filter(cls, value: Any) -> str:
        items = cls._filter_items(value, "sort by")
        if not items:
            return ""
        if len(items) != 1:
            raise LinkedInInputError("sort by accepts one value")
        code = _SORT_BY_CODES.get(items[0].lower())
        if not code:
            raise LinkedInInputError("sort by must be relevant/R or recent/DD")
        return code

    @staticmethod
    def _boolean_filter(value: Any, label: str) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, bool):
            return "true" if value else ""
        if isinstance(value, str):
            source = value.strip().lower()
            if source == "true":
                return "true"
        raise LinkedInInputError(f"{label} only accepts true")

    @staticmethod
    def _bounded_integer(
        value: Any,
        label: str,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        if isinstance(value, bool):
            raise LinkedInInputError(f"{label} must be an integer")
        try:
            source = str(value).strip()
            if not re.fullmatch(r"-?\d+", source):
                raise ValueError
            result = int(source)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LinkedInInputError(f"{label} must be an integer") from exc
        if result < minimum or (maximum is not None and result > maximum):
            if maximum is None:
                expected = f"at least {minimum}"
            else:
                expected = f"between {minimum} and {maximum}"
            raise LinkedInInputError(f"{label} must be {expected}")
        return result

    @staticmethod
    def _jobs_search_url(
        query: Mapping[str, Any], start: int, *, base: str = _JOBS_SEARCH_URL
    ) -> str:
        params = [
            (key, _text(query.get(key)))
            for key in (
                "keywords",
                "location",
                "geoId",
                "f_C",
                "f_TPR",
                "f_JT",
                "f_E",
                "f_WT",
                "sortBy",
                "f_AL",
                "f_EA",
            )
            if _text(query.get(key))
        ]
        params.append(("start", str(start)))
        return f"{base}?{urlencode(params)}"

    @staticmethod
    def _criterion_name(label: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        aliases = {
            "seniority_level": "seniority_level",
            "employment_type": "employment_type",
            "job_function": "job_function",
            "industries": "industries",
        }
        return aliases.get(normalized, normalized or "other")
