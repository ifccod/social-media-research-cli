from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from .errors import LinkedInInputError, LinkedInResponseError


_BASE_URL = "https://www.linkedin.com"
_DETAIL_PREFIX = "/ad-library/detail/"
_AD_ID_RE = re.compile(r"^[1-9]\d{5,19}$")
_COUNT_RE = re.compile(r"([0-9][0-9,]*)\s+ads?\s+match", re.IGNORECASE)
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_IMPRESSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)(?:\.([0-9]+))?\s*(k|m|thousand|million)?$",
    re.IGNORECASE,
)
_DATE_OPTIONS = {
    "last-30-days",
    "current-month",
    "current-year",
    "last-year",
    "custom-date-range",
}
_FACET_ALIASES = {
    "language": "LANGUAGE",
    "location": "LOCATION",
    "audience": "AUDIENCE",
    "demographic": "DEMOGRAPHIC",
    "company": "COMPANY",
    "education": "EDUCATION",
    "job": "JOB",
    "interests_and_traits": "INTERESTS_AND_TRAITS",
    "interestsandtraits": "INTERESTS_AND_TRAITS",
}
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
_MEDIA_TRACKING_NAMES = {
    "ad_library_ad_preview_carousel_item_image",
    "ad_library_ad_preview_content_image",
    "ad_library_ad_preview_native_document_image",
    "ad_library_ad_preview_video_thumbnail_image",
}


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _clean_text(value: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _absolute_url(value: Any, *, base: str = _BASE_URL) -> str:
    source = html.unescape(_text(value))
    return urljoin(f"{base}/", source) if source else ""


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError, OverflowError):
        return None


def _company_id(value: str) -> str | None:
    try:
        parts = [part for part in urlsplit(value).path.split("/") if part]
    except ValueError:
        return None
    if len(parts) >= 2 and parts[0] == "company" and parts[1].isdecimal():
        return parts[1]
    return None


def _detail_id(value: str) -> str | None:
    try:
        path = urlsplit(value).path
    except ValueError:
        return None
    if not path.startswith(_DETAIL_PREFIX):
        return None
    identifier = path[len(_DETAIL_PREFIX) :].strip("/")
    return identifier if identifier.isdecimal() else None


def _owned_linkedin_host(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    return normalized == "linkedin.com" or bool(
        re.fullmatch(r"(?:www|[a-z]{2})\.linkedin\.com", normalized)
    )


def _linkedin_detail_id(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise LinkedInResponseError("LinkedIn Ad Library detail URL is invalid") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not _owned_linkedin_host(parsed.hostname or "")
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise LinkedInResponseError("LinkedIn Ad Library detail URL left LinkedIn")
    identifier = _detail_id(value)
    if identifier is None or not _AD_ID_RE.fullmatch(identifier):
        raise LinkedInResponseError("LinkedIn Ad Library detail URL has no valid ad id")
    return identifier


def _external_ad_href(value: Any) -> str:
    resolved = _absolute_url(value)
    if not resolved:
        return ""
    try:
        parsed = urlsplit(resolved)
    except ValueError:
        return ""
    if _owned_linkedin_host(parsed.hostname or "") and parsed.path.startswith(
        _DETAIL_PREFIX
    ):
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _decode_json(value: str) -> Mapping[str, Any]:
    source = value.strip()
    try:
        decoded = json.loads(source)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, Mapping) else {}


def _new_card() -> dict[str, Any]:
    return {
        "kind": "ad",
        "source": "ssr_html",
        "ad_id": None,
        "detail_url": "",
        "creative_type": "",
        "advertiser": {"name": "", "url": "", "id": None},
        "logo": "",
        "commentary": "",
        "media": [],
        "headline": "",
        "landing_url": "",
        "cta": "",
    }


class _AdLibraryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.canonical = ""
        self.cards: list[dict[str, Any]] = []
        self.total: int | None = None
        self.pagination: dict[str, Any] = {"token": None, "is_last_page": None}
        self.about: dict[str, Any] = {
            "ad_format": "",
            "advertiser": {"name": "", "url": "", "id": None},
            "payer": "",
            "run_from": None,
            "run_to": None,
            "run_text": "",
        }
        self.impressions: dict[str, Any] = {"total_range": "", "countries": []}
        self.targeting: dict[str, Any] = {
            "included": [],
            "excluded": [],
            "facets": [],
        }

        self._depth = 0
        self._captures: list[dict[str, Any]] = []
        self._card: dict[str, Any] | None = None
        self._card_tag = ""
        self._card_depth = 0
        self._media_anchor_depth = 0
        self._seen_about = False
        self._seen_impressions = False
        self._seen_targeting = False
        self._target_category = ""
        self._target_row: dict[str, Any] | None = None
        self._target_row_depth = 0
        self._target_cell = -1

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

        if lower_tag == "br":
            self._append_separator()
        if not is_void:
            self._depth += 1
        if lower_tag == "title":
            self._begin("page_title")

        if lower_tag == "li" and "search-result-item" in classes and self._card is None:
            self._start_card(lower_tag)
        if lower_tag == "div" and "ad-preview" in classes:
            if self._card is None:
                self._start_card(lower_tag)
            if self._card is not None:
                self._card["creative_type"] = values.get("data-creative-type", "")

        self._handle_card_element(lower_tag, values, classes)
        self._handle_detail_element(lower_tag, values, classes)

        if lower_tag == "h1" and self._card is None:
            self._begin("result_heading")
        if lower_tag == "code" and values.get("id") == "paginationMetadata":
            self._begin("pagination")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag in {"div", "h1", "h2", "h3", "li", "p", "section", "span", "td"}:
            self._append_separator()

        ending = [item for item in self._captures if item["depth"] == self._depth]
        if ending:
            self._captures = [item for item in self._captures if item["depth"] != self._depth]
            for item in ending:
                self._capture_complete(
                    item["key"], _clean_text("".join(item["buffer"])), item["target"]
                )

        if lower_tag == "a" and self._media_anchor_depth == self._depth:
            self._media_anchor_depth = 0
        if (
            lower_tag == "tr"
            and self._target_row is not None
            and self._target_row_depth == self._depth
        ):
            if self._target_row.get("category"):
                self.targeting["facets"].append(self._target_row)
            self._target_row = None
            self._target_row_depth = 0
            self._target_cell = -1
        if (
            self._card is not None
            and lower_tag == self._card_tag
            and self._card_depth == self._depth
        ):
            self._finish_card()

        if lower_tag not in _VOID_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        for item in self._captures:
            item["buffer"].append(data)

    def handle_comment(self, data: str) -> None:
        for item in self._captures:
            item["buffer"].append(data)

    def _start_card(self, tag: str) -> None:
        self._card = _new_card()
        self._card_tag = tag
        self._card_depth = self._depth

    def _finish_card(self) -> None:
        assert self._card is not None
        detail_url = _text(self._card.get("detail_url"))
        identifier = _linkedin_detail_id(detail_url) if detail_url else None
        if identifier:
            self._card["ad_id"] = identifier
        self._card["media"] = self._dedupe_media(self._card.get("media", []))
        self.cards.append(self._card)
        self._card = None
        self._card_tag = ""
        self._card_depth = 0
        self._media_anchor_depth = 0

    def _handle_card_element(
        self, tag: str, attrs: Mapping[str, str], classes: set[str]
    ) -> None:
        card = self._card
        if card is None:
            return
        tracking = attrs.get("data-tracking-control-name", "")
        href = _absolute_url(attrs.get("href")) if tag == "a" else ""

        if tracking == "ad_library_view_ad_detail" and href:
            card["detail_url"] = href
        elif _detail_id(href) and not card.get("detail_url"):
            card["detail_url"] = href

        if tracking in {
            "ad_library_ad_preview_advertiser",
            "ad_library_about_ad_advertiser",
        }:
            advertiser = card["advertiser"]
            advertiser["url"] = href
            advertiser["id"] = _company_id(href)
            self._begin("advertiser_name", advertiser)
        elif {"block", "text-md", "font-bold", "leading-[20px]"}.issubset(classes):
            self._begin("advertiser_name", card["advertiser"])

        if tag == "img":
            image_url = _absolute_url(
                attrs.get("data-delayed-url") or attrs.get("data-src") or attrs.get("src")
            )
            alt = _text(attrs.get("alt"))
            if alt.lower() in {"advertiser logo", "member logo"} and not card.get("logo"):
                card["logo"] = image_url
            elif "ad-preview__dynamic-dimensions-image" in classes or self._media_anchor_depth:
                self._append_media(
                    card,
                    {"type": "image", "url": image_url, "poster_url": "", "alt": alt},
                )

        if "base-ad-preview-card" in classes and not card["advertiser"]["name"]:
            aria_label = _text(attrs.get("aria-label"))
            name, separator, _ = aria_label.partition(", ")
            if separator:
                card["advertiser"]["name"] = name

        if tag == "a" and tracking in _MEDIA_TRACKING_NAMES:
            self._media_anchor_depth = self._depth
        if "commentary__content" in classes or "sponsored-message__content" in classes:
            self._begin("commentary", card)
        if tag == "h2" and not card.get("headline"):
            self._begin("headline", card)
        elif tracking == "ad_library_ad_preview_carousel_item_title" and not card.get(
            "headline"
        ):
            self._begin("headline", card)
        landing_url = _external_ad_href(attrs.get("href")) if tag == "a" else ""
        if tracking == "ad_library_ad_preview_headline_content" and landing_url:
            card["landing_url"] = landing_url
        elif (
            tracking == "ad_library_ad_preview_content_image"
            and landing_url
            and not card.get("landing_url")
        ):
            card["landing_url"] = landing_url
        if tracking == "ad_library_ad_detail_cta":
            self._begin("cta", card)

        if tag == "video":
            sources: list[dict[str, Any]] = []
            raw_sources = _text(attrs.get("data-sources"))
            if raw_sources:
                try:
                    decoded = json.loads(raw_sources)
                except (json.JSONDecodeError, TypeError, ValueError):
                    decoded = []
                if isinstance(decoded, list):
                    for item in decoded:
                        if not isinstance(item, Mapping):
                            continue
                        url = _absolute_url(item.get("src"))
                        if url:
                            sources.append(
                                {
                                    "url": url,
                                    "type": _text(item.get("type")),
                                    "bitrate": _optional_int(item.get("bitrate")),
                                }
                            )
            poster = _absolute_url(attrs.get("data-poster-url") or attrs.get("poster"))
            self._append_media(
                card,
                {
                    "type": "video",
                    "url": sources[0]["url"] if sources else "",
                    "poster_url": poster,
                    "alt": "",
                    "sources": sources,
                },
            )

        if tag == "iframe" and attrs.get("data-native-document-config"):
            config = _decode_json(attrs["data-native-document-config"])
            document = config.get("doc")
            if isinstance(document, Mapping):
                covers: list[str] = []
                for cover in document.get("coverPages", []):
                    if not isinstance(cover, Mapping):
                        continue
                    cover_config = cover.get("config")
                    if isinstance(cover_config, Mapping):
                        cover_url = _absolute_url(cover_config.get("src"))
                        if cover_url:
                            covers.append(cover_url)
                self._append_media(
                    card,
                    {
                        "type": "document",
                        "url": _absolute_url(document.get("manifestUrl")),
                        "poster_url": covers[0] if covers else "",
                        "alt": _text(document.get("title")),
                        "page_count": _optional_int(document.get("totalPageCount")),
                        "cover_urls": covers,
                    },
                )

    def _handle_detail_element(
        self, tag: str, attrs: Mapping[str, str], classes: set[str]
    ) -> None:
        tracking = attrs.get("data-tracking-control-name", "")
        if tag == "h2":
            self._begin("section_heading")

        if self._seen_about:
            if tracking == "ad_library_about_ad_advertiser":
                href = _absolute_url(attrs.get("href"))
                self.about["advertiser"]["url"] = href
                self.about["advertiser"]["id"] = _company_id(href)
                self._begin("about_advertiser")
            elif "about-ad__paying-entity" in classes:
                self._begin("payer")
            elif "about-ad__availability-duration" in classes:
                self._begin("run_text")
            elif (
                tag == "p"
                and "text-sm" in classes
                and "mb-1" in classes
                and not self.about["ad_format"]
            ):
                self._begin("ad_format")

        if self._seen_impressions:
            if tag == "div" and {"flex", "justify-between"}.issubset(classes):
                self._begin("impressions_total")
            if tag == "span" and "ad-analytics__country-impressions" in classes:
                self._append_country(attrs)

        if self._seen_targeting:
            if tag == "h3":
                self._begin("target_category")
            if tag == "span" and "ad-targeting__segments" in classes:
                self._begin("target_segment", {"category": self._target_category})
            if tag == "tr" and self._target_row is None:
                self._target_row = {"category": "", "included": False, "excluded": False}
                self._target_row_depth = self._depth
                self._target_cell = -1
            if tag == "td" and self._target_row is not None:
                self._target_cell += 1
                if self._target_cell == 0:
                    self._begin("target_facet_category", self._target_row)
            if tag == "li-icon" and self._target_row is not None and attrs.get("type") == "check":
                if self._target_cell == 1:
                    self._target_row["included"] = True
                elif self._target_cell == 2:
                    self._target_row["excluded"] = True

    def _begin(self, key: str, target: Any = None) -> None:
        self._captures.append(
            {"key": key, "depth": self._depth, "buffer": [], "target": target}
        )

    def _append_separator(self) -> None:
        for item in self._captures:
            item["buffer"].append("\n")

    def _capture_complete(self, key: str, value: str, target: Any) -> None:
        if key == "page_title":
            self.title = value
        elif key == "result_heading":
            match = _COUNT_RE.search(value)
            if match:
                self.total = _optional_int(match.group(1))
        elif key == "pagination":
            raw = _decode_json(value)
            if raw:
                token = _text(raw.get("paginationToken")) or None
                last_page = raw.get("isLastPage")
                self.pagination = {
                    "token": token,
                    "is_last_page": last_page if isinstance(last_page, bool) else None,
                }
        elif key in {"advertiser_name", "commentary", "headline", "cta"}:
            if value and isinstance(target, dict):
                target["name" if key == "advertiser_name" else key] = value
        elif key == "section_heading":
            if value == "About the ad":
                self._seen_about = True
            elif value == "Ad Impressions":
                self._seen_impressions = True
            elif value == "Ad Targeting":
                self._seen_targeting = True
        elif key == "about_advertiser" and value:
            self.about["advertiser"]["name"] = value
        elif key == "ad_format" and value:
            self.about["ad_format"] = value
        elif key == "payer" and value:
            self.about["payer"] = value.removeprefix("Paid for by ").strip()
        elif key == "run_text" and value:
            self.about["run_text"] = value
            period = value.removeprefix("Ran from ")
            start, separator, end = period.partition(" to ")
            if separator:
                self.about["run_from"] = start.strip() or None
                self.about["run_to"] = end.strip() or None
        elif key == "impressions_total" and value:
            lines = value.splitlines()
            if len(lines) >= 2 and lines[0].casefold() == "total impressions":
                self.impressions["total_range"] = lines[1]
        elif key == "target_category" and value:
            self._target_category = value
        elif key == "target_segment" and value and isinstance(target, Mapping):
            self._append_target_segment(_text(target.get("category")), value)
        elif key == "target_facet_category" and value and isinstance(target, dict):
            target["category"] = value

    def _append_country(self, attrs: Mapping[str, str]) -> None:
        label = _text(attrs.get("aria-label"))
        country, separator, share = label.rpartition(", impressions ")
        if not separator or not country or not share:
            return
        percent: int | None = None
        if share.endswith("%") and share[:-1].strip().isdecimal():
            percent = int(share[:-1].strip())
        self.impressions["countries"].append(
            {"country": country, "share_text": share, "share_percent": percent}
        )

    def _append_target_segment(self, category: str, value: str) -> None:
        relation = ""
        remainder = value
        if value.startswith("Targeting includes "):
            relation = "included"
            remainder = value.removeprefix("Targeting includes ")
        elif value.startswith("Targeting excludes "):
            relation = "excluded"
            remainder = value.removeprefix("Targeting excludes ")
        if not relation:
            return

        values: list[str] = []
        for line in remainder.splitlines():
            candidate = line.strip().removesuffix(" and").strip()
            if not candidate or candidate.endswith(" others"):
                continue
            values.extend(part.strip() for part in candidate.split(",") if part.strip())
        item = {"category": category, "text": value, "values": values}
        if item not in self.targeting[relation]:
            self.targeting[relation].append(item)

    @staticmethod
    def _append_media(card: dict[str, Any], item: dict[str, Any]) -> None:
        if item.get("url") or item.get("poster_url"):
            card["media"].append(item)

    @staticmethod
    def _dedupe_media(values: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        if not isinstance(values, list):
            return output
        for item in values:
            if not isinstance(item, dict):
                continue
            key = (
                _text(item.get("type")),
                _text(item.get("url")),
                _text(item.get("poster_url")),
            )
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output


def _parse(source: str) -> _AdLibraryParser:
    if not isinstance(source, str) or not source.strip():
        raise LinkedInResponseError("LinkedIn HTML is empty")
    parser = _AdLibraryParser()
    try:
        parser.feed(source.replace("\x00", ""))
        parser.close()
    except (TypeError, ValueError) as exc:
        raise LinkedInResponseError("LinkedIn Ad Library HTML could not be parsed") from exc
    title = " ".join((parser.title, parser.meta.get("og:title", ""))).casefold()
    if "linkedin login" in title or "sign in | linkedin" in title:
        raise LinkedInResponseError("LinkedIn returned its login page")
    return parser


def parse_ad_search_html(source: str, *, page_url: str = "") -> dict[str, Any]:
    parser = _parse(source)
    if not parser.cards and parser.total not in {0} and parser.pagination["is_last_page"] is None:
        raise LinkedInResponseError("LinkedIn returned no public ad search metadata")
    return {
        "source": "ssr_html",
        "page_url": page_url,
        "total": parser.total,
        "items": parser.cards,
        "count": len(parser.cards),
        "pagination": parser.pagination,
    }


def parse_ad_detail_html(
    source: str,
    *,
    expected_id: str,
    page_url: str = "",
) -> dict[str, Any]:
    parser = _parse(source)
    canonical = _absolute_url(parser.canonical, base=page_url or _BASE_URL)
    actual_id = (
        _linkedin_detail_id(canonical)
        if canonical
        else _linkedin_detail_id(page_url) if page_url else None
    )
    if actual_id and actual_id != expected_id:
        raise LinkedInResponseError(
            f"LinkedIn ad id {actual_id!r} did not match expected {expected_id!r}"
        )
    if not parser.cards:
        raise LinkedInResponseError("LinkedIn returned no public ad detail metadata")

    card = parser.cards[0]
    card["ad_id"] = actual_id or expected_id
    card["detail_url"] = canonical or f"{_BASE_URL}{_DETAIL_PREFIX}{expected_id}"
    if not parser.about["advertiser"]["name"]:
        parser.about["advertiser"] = dict(card["advertiser"])
    return {
        "source": "ssr_html",
        "page_url": page_url,
        **card,
        "about": parser.about,
        "impressions": parser.impressions,
        "targeting": parser.targeting,
    }


def normalize_ad_search_params(
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
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    normalized_keyword = _search_text(keyword, "keyword")
    normalized_advertiser = _search_text(advertiser_name, "advertiser name")
    if not normalized_keyword and not normalized_advertiser:
        raise LinkedInInputError("LinkedIn ad search requires keyword or advertiser name")
    normalized_payer = _search_text(payer, "payer")
    normalized_countries = _normalize_countries(countries)
    normalized_included = _normalize_facets(included_facets, "included facets")
    normalized_excluded = _normalize_facets(excluded_facets, "excluded facets")
    normalized_start, normalized_end, normalized_date = _normalize_dates(
        startdate, enddate, date_option
    )
    normalized_sort = _normalize_sort_order(sort_order)
    min_value, min_unit, min_total = _normalize_impressions(impressions_min, "minimum")
    max_value, max_unit, max_total = _normalize_impressions(impressions_max, "maximum")
    if min_total is not None and max_total is not None and max_total <= min_total:
        raise LinkedInInputError("maximum impressions must be greater than minimum impressions")

    token = _text(pagination_token)
    if token and (len(token) > 512 or any(ord(char) < 32 for char in token)):
        raise LinkedInInputError("LinkedIn ad pagination token is malformed")

    params: list[tuple[str, str]] = []
    for key, value in (
        ("accountOwner", normalized_advertiser),
        ("payer", normalized_payer),
        ("keyword", normalized_keyword),
    ):
        if value:
            params.append((key, value))
    params.extend(("countries", country) for country in normalized_countries)
    for key, value in (
        ("dateOption", normalized_date),
        ("sortOrder", "ASCENDING" if normalized_sort == "oldest" else ""),
        ("startdate", normalized_start),
        ("enddate", normalized_end),
        ("impressionsMinValue", min_value),
        ("impressionsMinUnit", min_unit if min_value else ""),
        ("impressionsMaxValue", max_value),
        ("impressionsMaxUnit", max_unit if max_value else ""),
        ("includedTargetingFacetCategories", ",".join(normalized_included)),
        ("excludedTargetingFacetCategories", ",".join(normalized_excluded)),
        ("paginationToken", token),
    ):
        if value:
            params.append((key, value))

    query = {
        "keyword": normalized_keyword,
        "advertiser_name": normalized_advertiser,
        "payer": normalized_payer,
        "countries": normalized_countries,
        "date_option": normalized_date or None,
        "sort_order": normalized_sort or None,
        "startdate": normalized_start or None,
        "enddate": normalized_end or None,
        "impressions_min": _impression_echo(min_value, min_unit),
        "impressions_max": _impression_echo(max_value, max_unit),
        "included_facets": normalized_included,
        "excluded_facets": normalized_excluded,
        "pagination_token": token or None,
    }
    return params, query


def _normalize_sort_order(value: str | None) -> str:
    source = _text(value).casefold()
    if not source:
        return ""
    if source in {"newest", "descending"}:
        return "newest"
    if source in {"oldest", "ascending"}:
        return "oldest"
    raise LinkedInInputError("LinkedIn ad sort order must be newest or oldest")


def _search_text(value: Any, label: str) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise LinkedInInputError(f"LinkedIn ad {label} must be a string")
    result = value.strip()
    if len(result) > 500:
        raise LinkedInInputError(f"LinkedIn ad {label} must be at most 500 characters")
    return result


def _split_values(value: str | Sequence[str] | None, label: str) -> list[str]:
    if value in (None, ""):
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, Sequence) or isinstance(values, (bytes, bytearray)):
        raise LinkedInInputError(f"LinkedIn ad {label} must be text values")
    output: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise LinkedInInputError(f"LinkedIn ad {label} must be text values")
        output.extend(part.strip() for part in item.split(",") if part.strip())
    return output


def _normalize_countries(value: str | Sequence[str] | None) -> list[str]:
    output: list[str] = []
    for item in _split_values(value, "countries"):
        country = item.upper()
        if country != "ALL" and not _COUNTRY_RE.fullmatch(country):
            raise LinkedInInputError("LinkedIn ad country must be a two-letter code or ALL")
        if country not in output:
            output.append(country)
    return output


def _normalize_facets(value: str | Sequence[str] | None, label: str) -> list[str]:
    output: list[str] = []
    allowed = set(_FACET_ALIASES.values())
    for item in _split_values(value, label):
        source = item.strip()
        key = source.casefold().replace("-", "_").replace(" ", "_")
        facet = _FACET_ALIASES.get(key, source.upper())
        if facet not in allowed:
            raise LinkedInInputError(f"LinkedIn ad {label} contains unsupported facet {item!r}")
        if facet not in output:
            output.append(facet)
    return output


def _normalize_dates(
    startdate: str | None, enddate: str | None, date_option: str | None
) -> tuple[str, str, str]:
    start = _text(startdate)
    end = _text(enddate)
    option = _text(date_option).casefold()
    if option and option not in _DATE_OPTIONS:
        raise LinkedInInputError("LinkedIn ad date option is unsupported")
    if bool(start) != bool(end):
        raise LinkedInInputError("LinkedIn ad startdate and enddate must be provided together")
    if start:
        try:
            start_value = date.fromisoformat(start)
            end_value = date.fromisoformat(end)
        except ValueError as exc:
            raise LinkedInInputError("LinkedIn ad dates must use YYYY-MM-DD") from exc
        if end_value <= start_value:
            raise LinkedInInputError("LinkedIn ad enddate must be greater than startdate")
        option = "custom-date-range"
    elif option == "custom-date-range":
        raise LinkedInInputError("custom date range requires startdate and enddate")
    return start, end, option


def _normalize_impressions(
    value: str | int | float | None, label: str
) -> tuple[str, str, Decimal | None]:
    if value in (None, ""):
        return "", "", None
    if isinstance(value, bool):
        raise LinkedInInputError(f"LinkedIn ad {label} impressions is malformed")
    source = str(value).strip()
    match = _IMPRESSION_RE.fullmatch(source)
    if not match:
        raise LinkedInInputError(
            f"LinkedIn ad {label} impressions must be a number with optional k or m suffix"
        )
    number = match.group(1)
    if match.group(2):
        number = f"{number}.{match.group(2)}"
    suffix = (match.group(3) or "").casefold()
    unit = {
        "k": "thousand",
        "thousand": "thousand",
        "m": "million",
        "million": "million",
    }.get(suffix, "none")
    try:
        numeric = Decimal(number)
    except InvalidOperation as exc:
        raise LinkedInInputError(f"LinkedIn ad {label} impressions is malformed") from exc
    multiplier = Decimal(1_000 if unit == "thousand" else 1_000_000 if unit == "million" else 1)
    normalized = format(numeric.normalize(), "f")
    return normalized, unit, numeric * multiplier


def _impression_echo(value: str, unit: str) -> dict[str, Any] | None:
    if not value:
        return None
    return {"value": value, "unit": unit}
