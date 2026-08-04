from __future__ import annotations

import base64
import json
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from curl_cffi import requests

from .errors import TikTokInputError, TikTokResponseError
from .signer import TikTokSigner
from .telemetry import build_telemetry

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

_PROFILE_RE = re.compile(r"/@([^/?#]+)")
_VIDEO_RE = re.compile(r"/video/([0-9]+)")
_TIKTOK_HOST_RE = re.compile(r"(^|\.)tiktok\.com$", re.IGNORECASE)
_ASCII_NUMERIC_ID_RE = re.compile(r"[0-9]+\Z")
_MS_TOKEN_URL = "https://mssdk.tiktokw.us/web/report"
_MAX_REQUEST_INTERVAL = 10.0
_CREATIVE_CENTER_BASE_URL = "https://ads.tiktok.com"
_CREATIVE_TRENDING_HASHTAGS_PATH = "/CreativeOne/KnowledgeAPI/GetHashtagList"
_CREATIVE_HASHTAG_DETAIL_PATH = "/CreativeOne/KnowledgeAPI/GetHashtagDetail"
_CREATIVE_TRENDING_HASHTAGS_REFERER = (
    f"{_CREATIVE_CENTER_BASE_URL}/creative/creativeCenter/trends/hashtag"
)
_CREATIVE_TRENDING_VIDEOS_OVERVIEW_PATH = (
    "/CreativeOne/Report/GetTopContentsOverview"
)
_CREATIVE_TRENDING_VIDEOS_LIST_PATH = (
    "/CreativeOne/Report/CreativeCenterGetTopContentsList"
)
_CREATIVE_TRENDING_VIDEO_DETAIL_PATH = (
    "/CreativeOne/Report/CreativeCenterGetTopContentsItemDetail"
)
_CREATIVE_TRENDING_VIDEOS_REFERER = (
    f"{_CREATIVE_CENTER_BASE_URL}"
    "/business/creativecenter/inspiration/popular/video/pc/en"
)
_CREATIVE_TOP_ADS_FILTERS_PATH = "/creative_radar_api/v1/top_ads/v2/filters"
_CREATIVE_TOP_ADS_SEARCH_PATH = "/creative_radar_api/v1/top_ads/v2/list"
_CREATIVE_TOP_ADS_PERFORMANCE_PATH = "/CreativeOne/TopAds/SearchMaterial"
_CREATIVE_TOP_ADS_SUGGEST_PATH = (
    "/creative_radar_api/v1/top_ads/query_suggestion"
)
_CREATIVE_TOP_ADS_DETAIL_PATH = "/creative_radar_api/v1/top_ads/v2/detail"
_CREATIVE_TOP_ADS_RECOMMEND_PATH = (
    "/creative_radar_api/v1/top_ads/v2/recommend"
)
_CREATIVE_TOP_ADS_KEYFRAME_PATH = "/creative_radar_api/v1/top_ads/keyframe"
_CREATIVE_TOP_ADS_PERCENTILE_PATH = "/creative_radar_api/v1/top_ads/percentile"
_CREATIVE_TOP_ADS_ANALYSIS_PATH = (
    "/creative_radar_api/v1/top_ads/v2/detail_analysis"
)
_CREATIVE_TOP_ADS_LIBRARY_REFERER = (
    f"{_CREATIVE_CENTER_BASE_URL}"
    "/business/creativecenter/inspiration/topads/pc/en"
)
_CREATIVE_TOP_ADS_PERFORMANCE_REFERER = (
    f"{_CREATIVE_CENTER_BASE_URL}/creative/inspiration/top-ads/library"
)
_CREATIVE_STUDIO_REFERER = (
    f"{_CREATIVE_CENTER_BASE_URL}/creative/creativestudio/create"
    "?from_creative=signup&region=row"
)
_CREATIVE_STUDIO_CREDITS_PATH = (
    "/CreativeOne/SymphonyPlatform/QueryCreditAccount"
)
_CREATIVE_STUDIO_GENERATE_PATH = (
    "/creative_bff_i18n/api/cue/t2v/create_generate_task"
)
_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH = (
    "/creative_bff_i18n/api/cue/upload/local-image"
)
_CREATIVE_STUDIO_I2V_GENERATE_PATH = (
    "/creative_bff_i18n/api/cue/i2v/create_generate_task"
)
_CREATIVE_STUDIO_TASK_PATH = (
    "/creative_bff_i18n/api/cue/generate-task/check"
)
_CREATIVE_STUDIO_PERMISSIONS_PATH = (
    "/creative_bff_i18n/api/cue/get_miniapp_permission_with_allowlist"
)
_CREATIVE_STUDIO_GENERATING_COUNT_PATH = (
    "/creative_bff_i18n/api/cue/generating-task-count"
)
_CREATIVE_STUDIO_MAX_COUNT_PATH = (
    "/creative_bff_i18n/api/cue/get_generate_max_count"
)
_CREATIVE_STUDIO_LEDGER_PATH = (
    "/CreativeOne/SymphonyPlatform/QueryCreditLedgerEntries"
)
_CREATIVE_STUDIO_HISTORY_PATH = (
    "/creative_bff_i18n/api/cue/history/tasks"
)
_CREATIVE_STUDIO_TASK_DETAIL_PATH = (
    "/creative_bff_i18n/api/cue/history/task/detail"
)
_CREATIVE_STUDIO_VIDEO_INFO_PATH = (
    "/creative_bff_i18n/api/cue/video_info"
)
_CREATIVE_STUDIO_MODEL_ID = "5000005"
_CREATIVE_STUDIO_T2V_SUB_APP = "CreativeStudio/MiniApp/TextToVideo"
_CREATIVE_STUDIO_I2V_MODEL_ID = "4000005"
_CREATIVE_STUDIO_I2V_SUB_APP = "CreativeStudio/MiniApp/ImageToVideo"
_CREATIVE_STUDIO_R2V_MODEL_ID = "2000004"
_CREATIVE_STUDIO_R2V_SUB_APP = (
    "CreativeStudio/ReferenceToVideo/ReferenceToVideo"
)
_CREATIVE_STUDIO_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_CREATIVE_STUDIO_R2V_MAX_VIDEOS = 3
_CREATIVE_STUDIO_R2V_MIN_VIDEO_DURATION = 2.0
_CREATIVE_STUDIO_R2V_MAX_VIDEO_DURATION_SUM = 15.2
_TIKTOK_ONE_REFERER = (
    f"{_CREATIVE_CENTER_BASE_URL}/creative/forpartners/creator/explore?region=row"
)
_TIKTOK_ONE_FILTERS_PATH = (
    "/CreativeOne/MatchMaking/QueryPartnerSearchFilterOption"
)
_TIKTOK_ONE_SUGGEST_PATH = (
    "/CreativeOne/MatchMaking/QueryPartnerSearchSuggestWords"
)
_TIKTOK_ONE_SEARCH_PATH = (
    "/CreativeOne/MatchMaking/QueryPartnerCreatorSquare"
)
_ADS_KEYWORD_PLANNER_REFERER = (
    f"{_CREATIVE_CENTER_BASE_URL}"
    "/i18n/search_ads_center/keyword-planner/creation"
)
_ADS_KEYWORD_IDEAS_PATH = (
    "/api/v4/i18n/search_ads/search_keyword/mget_keyword_ideas/"
)
_ADS_KEYWORD_SUMMARY_PATH = (
    "/api/v4/i18n/search_ads/search_keyword/keyword_plan_summary/"
)
_ADS_KEYWORD_COUNTRY_IDS = {
    "AE": 290557,
    "AU": 2077456,
    "BR": 3469034,
    "CA": 6251999,
    "DE": 2921044,
    "ES": 2510769,
    "FR": 3017382,
    "GB": 2635167,
    "ID": 1643084,
    "IT": 3175395,
    "MX": 3996063,
    "MY": 1733045,
    "PH": 1694008,
    "SA": 102358,
    "TH": 1605651,
    "US": 6252001,
    "VN": 1562822,
}
_ADS_KEYWORD_BRAND_OPTIONS = {"all": 0, "branded": 1, "non_branded": 2}
_ADS_KEYWORD_SORT_FIELDS = {
    "default": 0,
    "volume": 1,
    "three_month": 2,
    "yoy": 3,
    "cpc": 4,
    "source": 5,
    "competition": 6,
}
_ADS_KEYWORD_SORT_ORDERS = {"default": 0, "descending": 1, "ascending": 2}
_ADS_KEYWORD_COMPETITION = {"limited": 1, "medium": 2, "high": 3}
_ADS_KEYWORD_MATCH_TYPES = {"exact": 1, "phrase": 2, "broad": 3}
_TIKTOK_ONE_PAGE_SIZE = 24
_TIKTOK_ONE_SORT_FIELDS = {
    "relevance": 1,
    "followers": 2,
    "average_views": 3,
    "engagement": 4,
    "median_views": 5,
    "price": 6,
    "recent_video_count": 7,
    "submission_rate": 8,
    "audience_relevance": 9,
    "creator_value": 10,
}
_CREATIVE_TOP_ADS_OBJECTIVES = frozenset({1, 2, 3, 4, 5, 8, 15})
_CREATIVE_TOP_ADS_PERFORMANCE_OBJECTIVES = frozenset(
    {1, 2, 3, 4, 5, 6, 8, 9, 14, 15, 16}
)
_CREATIVE_TOP_ADS_FORMATS = frozenset({"spark", "non_spark"})
_CREATIVE_TOP_ADS_KEYFRAME_METRICS = frozenset(
    {
        "retain_ctr",
        "retain_cvr",
        "click_cnt",
        "convert_cnt",
        "play_retain_cnt",
    }
)
_CREATIVE_CENTER_EU_COUNTRIES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "CH",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GB",
        "GR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    }
)
_CREATIVE_TRENDING_VIDEO_DETAIL_CDN_SUFFIXES = (
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-us.net",
    "tiktokcdn-eu.com",
    "tiktokcdn-eu.net",
)
_SEARCH_WEB_CODE = json.dumps(
    {
        "tiktok": {
            "client_params_x": {
                "search_engine": {
                    "ies_mt_user_live_video_card_use_libra": 1,
                    "mt_search_general_user_live_card": 1,
                }
            },
            "search_server": {},
        }
    },
    separators=(",", ":"),
)
_GENERAL_SEARCH_PATH = "/api/search/general/full/"
_USER_SEARCH_PATH = "/api/search/user/full/"
_MUSIC_SEARCH_PATH = "/api/search/music/full/"
_LIVE_SEARCH_PATH = "/api/search/live/full/"
_PHOTO_SEARCH_PATH = "/api/search/photo/full/"
_SEARCH_SUGGEST_PATH = "/api/search/general/preview/"
_TRENDING_SEARCH_WORDS_PATH = "/api/trending/searchwords/"
_GENERAL_SEARCH_PAGE_SIZE = 12
_MUSIC_SEARCH_PAGE_SIZE = 10
_LIVE_SEARCH_PAGE_SIZE = 12
_PHOTO_SEARCH_PAGE_SIZE = 12


class _UniversalDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capturing = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attributes = dict(attrs)
        self._capturing = attributes.get("id") == "__UNIVERSAL_DATA_FOR_REHYDRATION__"

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capturing:
            self._capturing = False

    @property
    def value(self) -> str:
        return "".join(self._parts)


def _cookie_value(
    session: requests.Session,
    name: str,
    *,
    domain: str | None = None,
) -> str | None:
    if domain:
        for candidate in (domain, f".{domain}"):
            try:
                value = session.cookies.get(name, domain=candidate)
            except (KeyError, TypeError, ValueError):
                value = None
            if value:
                return str(value)
    try:
        value = session.cookies.get(name)
    except (KeyError, TypeError, ValueError):
        return None
    return str(value) if value else None


def _first_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            result = _first_url(item)
            if result:
                return result
    if isinstance(value, Mapping):
        for key in ("urlList", "UrlList", "url_list", "playAddr", "PlayAddr"):
            if key in value:
                result = _first_url(value[key])
                if result:
                    return result
    return None


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _boolean(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _status_ok(payload: Mapping[str, Any]) -> bool:
    value = payload.get("statusCode", payload.get("status_code", 0))
    return value in (None, 0, "0")


def _first_value(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


class TikTokClient:
    def __init__(
        self,
        *,
        signer: TikTokSigner | None = None,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
        region: str = "US",
        language: str = "en",
        request_interval: float = 3.0,
        creative_fetch: (
            Callable[
                [str, Sequence[tuple[str, str]], str],
                Mapping[str, Any],
            ]
            | None
        ) = None,
    ) -> None:
        try:
            normalized_request_interval = float(request_interval)
        except (TypeError, ValueError) as exc:
            raise TikTokInputError(
                "request_interval must be a finite number in the range 0..10 seconds"
            ) from exc
        if (
            not math.isfinite(normalized_request_interval)
            or normalized_request_interval < 0
            or normalized_request_interval > _MAX_REQUEST_INTERVAL
        ):
            raise TikTokInputError(
                "request_interval must be a finite number in the range 0..10 seconds"
            )
        self._signer = signer
        self.session = session or requests.Session(impersonate="chrome")
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(0, retries)
        self.region = region
        self.language = language
        self.web_id_last_time = int(time.time())
        self.device_id = ""
        self.odin_id = ""
        self.client_ab_versions = ""
        self.root_referer = ""
        self.ms_token = ""
        self._ms_token_ready = False
        self._request_count = 0
        self.request_interval = normalized_request_interval
        self.creative_fetch = creative_fetch
        self._last_request_started_at: float | None = None
        self._request_slot_lock = threading.Lock()
        self.session.headers.update(
            {
                "Accept": "*/*",
                "Accept-Language": f"{language},en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": user_agent,
            }
        )

    @property
    def signer(self) -> TikTokSigner:
        if self._signer is None:
            self._signer = TikTokSigner()
        return self._signer

    def get_profile(self, profile_url: str) -> dict[str, Any]:
        url = self._validate_tiktok_url(profile_url)
        response, data = self._get_hydration(url, "profile")
        default_scope = data.get("__DEFAULT_SCOPE__", {})
        if not isinstance(default_scope, Mapping):
            raise TikTokResponseError("profile HTML default scope is not an object")
        self._apply_app_context(default_scope.get("webapp.app-context"))
        detail = default_scope.get("webapp.user-detail")
        if not isinstance(detail, Mapping) or not _status_ok(detail):
            raise TikTokResponseError("profile HTML does not contain a usable user-detail payload")
        user_info = detail.get("userInfo")
        if not isinstance(user_info, Mapping):
            raise TikTokResponseError("profile payload does not contain userInfo")
        user = user_info.get("user")
        if not isinstance(user, Mapping) or not user.get("secUid"):
            raise TikTokResponseError("profile payload does not contain secUid")
        self._refresh_ms_token(response)
        return {
            "url": response.url,
            "user": dict(user),
            "stats": dict(user_info.get("stats") or user_info.get("statsV2") or {}),
            "item_list": list(user_info.get("itemList") or []),
        }

    def get_user_videos(
        self,
        profile_url: str,
        *,
        limit: int | None = None,
        page_size: int = 16,
    ) -> dict[str, Any]:
        if limit is not None and limit < 0:
            raise TikTokInputError("limit must be non-negative")
        profile = self.get_profile(profile_url)
        user = profile["user"]
        videos: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        cursor = "0"
        has_more = True
        seen_cursors: set[str] = set()

        while has_more and (limit is None or len(videos) < limit):
            if cursor in seen_cursors:
                raise TikTokResponseError(f"video pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            payload = self._signed_get(
                "/api/post/item_list/",
                self._post_params(str(user["secUid"]), cursor, min(max(page_size, 1), 35)),
                referer=profile["url"],
            )
            items = payload.get("itemList", payload.get("item_list", []))
            if not isinstance(items, list):
                raise TikTokResponseError("video response itemList is not a list")
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                video_id = str(item.get("id") or item.get("aweme_id") or "")
                if not video_id or video_id in seen_ids:
                    continue
                seen_ids.add(video_id)
                videos.append(self._normalize_video(item))
                if limit is not None and len(videos) >= limit:
                    break
            has_more = _boolean(payload.get("hasMore", payload.get("has_more", False)))
            next_cursor = str(payload.get("cursor", ""))
            if not has_more:
                cursor = next_cursor or cursor
                break
            if not next_cursor or next_cursor == cursor:
                raise TikTokResponseError("video response did not advance its cursor")
            cursor = next_cursor

        return {
            "profile_url": profile["url"],
            "user": user,
            "stats": profile["stats"],
            "total": len(videos),
            "cursor": cursor,
            "has_more": has_more,
            "videos": videos,
        }

    def get_video(self, video_url_or_id: str) -> dict[str, Any]:
        video_id, referer = self._resolve_video(video_url_or_id)
        self._ensure_ms_token()
        payload = self._signed_get(
            "/api/item/detail/",
            self._common_params() + [("itemId", video_id)],
            referer=referer,
        )
        item_info = payload.get("itemInfo", payload.get("item_info", {}))
        item = None
        if isinstance(item_info, Mapping):
            item = item_info.get("itemStruct", item_info.get("item_struct", item_info.get("item")))
        if not isinstance(item, Mapping):
            item = payload.get("item")
        if not isinstance(item, Mapping):
            raise TikTokResponseError("video detail response does not contain an item")
        return self._normalize_video(item)

    def search_videos(
        self,
        keyword: str,
        *,
        limit: int | None = 20,
        page_size: int = 20,
    ) -> dict[str, Any]:
        query = keyword.strip()
        if not query:
            raise TikTokInputError("keyword must not be empty")
        self._validate_limit(limit)
        if limit == 0:
            return {
                "keyword": query,
                "total": 0,
                "cursor": "0",
                "search_id": "",
                "rid": "",
                "has_more": False,
                "videos": [],
            }

        videos: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor = "0"
        search_id = ""
        rid = ""
        has_more = True
        referer = f"https://www.tiktok.com/search?q={quote(query, safe='')}"

        while has_more and (limit is None or len(videos) < limit):
            if cursor in seen_cursors:
                raise TikTokResponseError(f"search pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            self._ensure_ms_token()
            count = self._request_count_for_limit(page_size, 20, limit, len(videos))
            payload = self._signed_get(
                "/api/search/item/full/",
                self._common_params()
                + [
                    ("count", str(count)),
                    ("cursor", cursor),
                    ("from_page", "search"),
                    ("keyword", query),
                    ("offset", cursor),
                    ("search_id", search_id or rid),
                    ("web_search_code", _SEARCH_WEB_CODE),
                ],
                referer=referer,
            )
            items = self._video_items(payload, "search")
            self._append_videos(videos, seen_ids, items, limit)

            has_more = self._has_more(payload)
            next_cursor = self._response_token(payload.get("cursor"), "search cursor")
            page_search_id, page_rid = self._search_tokens(payload)
            if page_search_id:
                search_id = page_search_id
            if page_rid:
                rid = page_rid
            if not has_more:
                cursor = next_cursor or cursor
                break
            if not next_cursor or next_cursor == cursor:
                raise TikTokResponseError("search response did not advance its cursor")
            if not search_id:
                raise TikTokResponseError("search response did not contain search_id or rid")
            cursor = next_cursor

        return {
            "keyword": query,
            "total": len(videos),
            "cursor": cursor,
            "search_id": search_id,
            "rid": rid,
            "has_more": has_more,
            "videos": videos,
        }

    def search_general(
        self,
        keyword: str,
        *,
        limit: int = _GENERAL_SEARCH_PAGE_SIZE,
        offset: int = 0,
        search_id: str = "",
    ) -> dict[str, Any]:
        """读取一页综合搜索卡片，并保留续页所需的游标和搜索会话标识。"""
        query, cursor, initial_search_id = self._search_input(
            keyword,
            limit=limit,
            offset=offset,
            search_id=search_id,
        )
        if limit == 0:
            return self._empty_search_result(
                query,
                cursor,
                initial_search_id,
                "results",
                offset=cursor,
            )
        count = min(limit, _GENERAL_SEARCH_PAGE_SIZE)
        params = self._common_params() + [
            ("count", str(count)),
            ("cursor", cursor),
            ("is_non_personalized_search", "0"),
            ("keyword", query),
            ("offset", cursor),
            ("web_search_code", _SEARCH_WEB_CODE),
        ]
        if initial_search_id:
            params.append(("search_id", initial_search_id))
        payload = self._signed_get(
            _GENERAL_SEARCH_PATH,
            params,
            referer=self._search_referer(query),
        )
        return self._normalize_general_search_page(
            query,
            limit,
            cursor,
            initial_search_id,
            payload,
        )

    def search_users(
        self,
        keyword: str,
        *,
        limit: int = 20,
        offset: int = 0,
        search_id: str = "",
    ) -> dict[str, Any]:
        """分页搜索公开用户资料。"""
        query, cursor, initial_search_id = self._search_input(
            keyword,
            limit=limit,
            offset=offset,
            search_id=search_id,
        )
        return self._collect_search_results(
            query=query,
            cursor=cursor,
            search_id=initial_search_id,
            limit=limit,
            page_size=20,
            path=_USER_SEARCH_PATH,
            referer=self._search_referer(query, category="user"),
            label="user search",
            result_field="users",
            item_keys=("userList", "user_list"),
            params_builder=self._user_search_params,
            normalizer=self._normalize_user_search_item,
            require_search_id=True,
        )

    def search_music(
        self,
        keyword: str,
        *,
        limit: int = 20,
        offset: int = 0,
        search_id: str = "",
    ) -> dict[str, Any]:
        """分页搜索公开音乐。"""
        query, cursor, initial_search_id = self._search_input(
            keyword,
            limit=limit,
            offset=offset,
            search_id=search_id,
        )
        return self._collect_search_results(
            query=query,
            cursor=cursor,
            search_id=initial_search_id,
            limit=limit,
            page_size=_MUSIC_SEARCH_PAGE_SIZE,
            path=_MUSIC_SEARCH_PATH,
            referer=self._search_referer(query),
            label="music search",
            result_field="music",
            item_keys=("data",),
            params_builder=self._music_search_params,
            normalizer=self._normalize_music_search_item,
        )

    def search_live(
        self,
        keyword: str,
        *,
        limit: int = _LIVE_SEARCH_PAGE_SIZE,
        offset: int = 0,
        search_id: str = "",
    ) -> dict[str, Any]:
        """分页搜索公开直播间摘要。"""
        query, cursor, initial_search_id = self._search_input(
            keyword,
            limit=limit,
            offset=offset,
            search_id=search_id,
        )
        return self._collect_search_results(
            query=query,
            cursor=cursor,
            search_id=initial_search_id,
            limit=limit,
            page_size=_LIVE_SEARCH_PAGE_SIZE,
            path=_LIVE_SEARCH_PATH,
            referer=self._search_referer(query, category="live"),
            label="live search",
            result_field="rooms",
            item_keys=("data",),
            params_builder=self._live_search_params,
            normalizer=self._normalize_live_search_item,
            require_search_id=True,
        )

    def search_photos(
        self,
        keyword: str,
        *,
        limit: int = _PHOTO_SEARCH_PAGE_SIZE,
        offset: int = 0,
        search_id: str = "",
    ) -> dict[str, Any]:
        """分页搜索图文，并保留完整图片列表。"""
        query, cursor, initial_search_id = self._search_input(
            keyword,
            limit=limit,
            offset=offset,
            search_id=search_id,
        )
        return self._collect_search_results(
            query=query,
            cursor=cursor,
            search_id=initial_search_id,
            limit=limit,
            page_size=_PHOTO_SEARCH_PAGE_SIZE,
            path=_PHOTO_SEARCH_PATH,
            referer=self._search_referer(query, category="photo"),
            label="photo search",
            result_field="photos",
            item_keys=("itemList", "item_list"),
            params_builder=self._photo_search_params,
            normalizer=self._normalize_photo_search_item,
            require_search_id=True,
        )

    def search_suggestions(
        self,
        keyword: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        """查询无需签名的公开搜索联想词。"""
        query, _cursor, _search_id = self._search_input(
            keyword,
            limit=limit,
            offset=0,
            search_id="",
        )
        if limit == 0:
            return {
                "keyword": query,
                "total": 0,
                "query_id": "",
                "rid": "",
                "suggestions": [],
            }
        payload = self._public_get(
            _SEARCH_SUGGEST_PATH,
            [
                ("aid", "1988"),
                ("app_language", self.language),
                ("is_non_personalized_search", "1"),
                ("keyword", query),
            ],
            referer="https://www.tiktok.com/search",
        )
        return self._normalize_search_suggestions(query, limit, payload)

    def get_trending_search_words(
        self,
        *,
        region: str = "US",
        limit: int = 15,
    ) -> dict[str, Any]:
        """查询 Explore 页面展示的公开热门搜索词。"""
        normalized_region = str(region).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_region) is None:
            raise TikTokInputError(
                "region must be a two-letter ASCII country code"
            )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 50
        ):
            raise TikTokInputError("limit must be between 1 and 50")
        payload = self._public_get(
            _TRENDING_SEARCH_WORDS_PATH,
            [("count", str(limit)), ("region", normalized_region)],
            referer="https://www.tiktok.com/explore",
        )
        return self._normalize_trending_search_words(
            limit,
            normalized_region,
            payload,
        )

    def get_creative_trending_hashtags(
        self,
        *,
        country: str = "US",
        time_range: int = 7,
        industry_id: int | str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        (
            normalized_country,
            normalized_time_range,
            normalized_industry_id,
            normalized_page,
            normalized_limit,
        ) = self._creative_trending_hashtag_inputs(
            country=country,
            time_range=time_range,
            industry_id=industry_id,
            page=page,
            limit=limit,
        )

        request_body: dict[str, Any] = {
            "timeRange": normalized_time_range,
            "countryCode": normalized_country,
            "page": normalized_page,
            "limit": normalized_limit,
        }
        if normalized_industry_id is not None:
            request_body["industryID"] = normalized_industry_id
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": _CREATIVE_CENTER_BASE_URL,
            "Referer": _CREATIVE_TRENDING_HASHTAGS_REFERER,
        }

        last_error: TikTokResponseError | None = None
        payload: dict[str, Any] | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_request_slot()
            try:
                response = self.session.post(
                    _CREATIVE_CENTER_BASE_URL + _CREATIVE_TRENDING_HASHTAGS_PATH,
                    headers=headers,
                    json=request_body,
                    timeout=self.timeout,
                )
            except requests.RequestsError as exc:
                last_error = TikTokResponseError(
                    f"TikTok Creative Center hashtag request failed: {exc}"
                )
            else:
                if response.status_code == 200:
                    try:
                        decoded = response.json()
                    except (requests.exceptions.JSONDecodeError, ValueError) as exc:
                        raise TikTokResponseError(
                            "TikTok Creative Center hashtag response is not valid JSON"
                        ) from exc
                    if not isinstance(decoded, dict):
                        raise TikTokResponseError(
                            "TikTok Creative Center hashtag response is not an object"
                        )
                    payload = decoded
                    break
                last_error = TikTokResponseError(
                    "TikTok Creative Center returned HTTP "
                    f"{response.status_code} for {_CREATIVE_TRENDING_HASHTAGS_PATH}"
                )
                if response.status_code != 429 and response.status_code < 500:
                    raise last_error
            if attempt >= self.retries:
                break
            time.sleep(0.4 * (2**attempt))
        if payload is None:
            raise last_error or TikTokResponseError(
                "TikTok Creative Center hashtag request failed"
            )

        base_response = payload.get("BaseResp")
        if isinstance(base_response, Mapping):
            status = _integer(base_response.get("StatusCode"))
            if status:
                message = str(base_response.get("StatusMessage") or "unknown error")
                raise TikTokResponseError(
                    f"TikTok Creative Center API status {status}: {message}"
                )
        code = str(payload.get("code") or "").strip()
        if code and code != "0":
            message = str(
                payload.get("message") or payload.get("msg") or "unknown error"
            )
            raise TikTokResponseError(
                f"TikTok Creative Center API status {code}: {message}"
            )

        raw_items = payload.get("items")
        pagination = payload.get("pagination")
        if not isinstance(raw_items, list):
            raise TikTokResponseError(
                "TikTok Creative Center hashtag response does not contain items"
            )
        if len(raw_items) > normalized_limit:
            raise TikTokResponseError(
                "TikTok Creative Center hashtag response exceeds requested limit"
            )
        if not isinstance(pagination, Mapping):
            raise TikTokResponseError(
                "TikTok Creative Center hashtag response does not contain pagination"
            )

        hashtags: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise TikTokResponseError(
                    f"TikTok Creative Center hashtag item {index} is not an object"
                )
            identifier = str(raw_item.get("hashtagID") or "").strip()
            name = str(raw_item.get("hashtagName") or "").strip()
            if not identifier or not name:
                raise TikTokResponseError(
                    f"TikTok Creative Center hashtag item {index} has no id or name"
                )
            if identifier in seen_ids:
                continue
            seen_ids.add(identifier)
            rank = _integer(raw_item.get("rankIndex")) or len(hashtags) + 1
            hashtags.append(
                {
                    "rank": rank,
                    "id": identifier,
                    "name": name,
                    "post_count": max(0, _integer(raw_item.get("publishCnt"))),
                    "view_count": max(0, _integer(raw_item.get("vv"))),
                    "industry_ids": list(raw_item.get("industryIDs") or []),
                    "popularity_curve": list(raw_item.get("popularityCurve") or []),
                    "top_creators": list(raw_item.get("topCreators") or []),
                }
            )

        upstream_page = _integer(pagination.get("page")) or normalized_page
        total_count = max(0, _integer(pagination.get("totalCount")))
        has_more = _boolean(pagination.get("hasMore"))
        anonymous_preview = (
            not has_more
            and len(hashtags) <= 3
            and normalized_limit > len(hashtags)
            and total_count == len(raw_items)
        )
        result: dict[str, Any] = {
            "source": "tiktok_creative_center",
            "transport": "web_api",
            "endpoint": _CREATIVE_TRENDING_HASHTAGS_PATH,
            "country": normalized_country,
            "time_range_days": normalized_time_range,
            "page": upstream_page,
            "requested_limit": normalized_limit,
            "total_count": total_count,
            "has_more": has_more,
            "anonymous_preview": anonymous_preview,
            "available": len(hashtags),
            "hashtags": hashtags,
        }
        if normalized_industry_id is not None:
            result["industry_id"] = normalized_industry_id
        return result

    def get_creative_trending_hashtags_full(
        self,
        *,
        country: str = "US",
        time_range: int = 7,
        industry_id: int | str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """通过 Chrome 登录态读取 Creative Center 热门标签完整分页。"""
        (
            normalized_country,
            normalized_time_range,
            normalized_industry_id,
            normalized_page,
            normalized_limit,
        ) = self._creative_trending_hashtag_inputs(
            country=country,
            time_range=time_range,
            industry_id=industry_id,
            page=page,
            limit=limit,
        )
        entries = [
            ("timeRange", str(normalized_time_range)),
            ("countryCode", normalized_country),
            ("page", str(normalized_page)),
            ("limit", str(normalized_limit)),
        ]
        if normalized_industry_id is not None:
            entries.append(("industryID", str(normalized_industry_id)))
        payload = self._creative_browser_fetch(
            _CREATIVE_TRENDING_HASHTAGS_PATH,
            entries,
            _CREATIVE_TRENDING_HASHTAGS_REFERER,
        )
        raw_items = payload.get("items")
        pagination = payload.get("pagination")
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > normalized_limit
            or not isinstance(pagination, Mapping)
        ):
            raise TikTokResponseError(
                "TikTok Creative Center hashtag pagination response is invalid"
            )
        response_page = _integer(pagination.get("page"))
        response_limit = _integer(pagination.get("limit"))
        total_count = _integer(pagination.get("totalCount"))
        has_more = pagination.get("hasMore")
        consumed = (
            (normalized_page - 1) * normalized_limit + len(raw_items)
        )
        if (
            response_page != normalized_page
            or response_limit != normalized_limit
            or total_count < consumed
            or not isinstance(has_more, bool)
            or has_more != (consumed < total_count)
        ):
            raise TikTokResponseError(
                "TikTok Creative Center hashtag pagination response is invalid"
            )

        hashtags: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise TikTokResponseError(
                    f"TikTok Creative Center hashtag item {index} is not an object"
                )
            identifier = str(raw_item.get("hashtagID") or "").strip()
            name = str(raw_item.get("hashtagName") or "").strip()
            industry_ids = raw_item.get("industryIDs", [])
            popularity_curve = raw_item.get("popularityCurve", [])
            top_creators = raw_item.get("topCreators", [])
            if (
                re.fullmatch(r"[1-9][0-9]{0,31}", identifier) is None
                or not name
                or not isinstance(industry_ids, list)
                or not isinstance(popularity_curve, list)
                or not isinstance(top_creators, list)
                or identifier in seen_ids
            ):
                raise TikTokResponseError(
                    f"TikTok Creative Center hashtag item {index} is invalid"
                )
            seen_ids.add(identifier)
            rank = _integer(raw_item.get("rankIndex"))
            hashtags.append(
                {
                    "rank": rank if rank > 0 else len(hashtags) + 1,
                    "id": identifier,
                    "name": name,
                    "post_count": max(0, _integer(raw_item.get("publishCnt"))),
                    "view_count": max(0, _integer(raw_item.get("vv"))),
                    "industry_ids": list(industry_ids),
                    "popularity_curve": list(popularity_curve),
                    "top_creators": list(top_creators),
                }
            )

        result: dict[str, Any] = {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_TRENDING_HASHTAGS_PATH,
            "source_url": _CREATIVE_TRENDING_HASHTAGS_REFERER,
            "browser_session": True,
            "country": normalized_country,
            "time_range_days": normalized_time_range,
            "page": normalized_page,
            "limit": normalized_limit,
            "available": len(hashtags),
            "total_count": total_count,
            "has_more": has_more,
            "anonymous_preview": False,
            "continuation_restricted": False,
            "hashtags": hashtags,
        }
        if has_more:
            result["next_page"] = normalized_page + 1
        if normalized_industry_id is not None:
            result["industry_id"] = normalized_industry_id
        return result

    def get_creative_trending_videos(
        self,
        *,
        country: str = "US",
        time_range: int = 30,
        metric: str = "views",
        content_label_ids: str | Sequence[int | str] | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized_country = str(country).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_country) is None:
            raise TikTokInputError("country must be a two-letter ASCII country code")
        if (
            not isinstance(time_range, int)
            or isinstance(time_range, bool)
            or time_range not in (7, 30)
        ):
            raise TikTokInputError("time_range must be 7 or 30")
        normalized_metric = str(metric).strip().lower().replace("_", "-")
        metric_options = {
            "views": ("views", 1),
            "video-views": ("views", 1),
            "engagement": ("engagement", 2),
            "engagement-rate": ("engagement", 2),
            "completion": ("completion", 3),
            "six-second-vtr": ("completion", 3),
        }
        if normalized_metric not in metric_options:
            raise TikTokInputError(
                "metric must be views, engagement, or completion"
            )
        normalized_metric, order_by_metric = metric_options[normalized_metric]
        if not isinstance(page, int) or isinstance(page, bool) or page != 1:
            raise TikTokInputError(
                "page must be 1 for the anonymous Creative Center preview"
            )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 20
        ):
            raise TikTokInputError("limit must be between 1 and 20")
        labels = self._creative_content_labels(content_label_ids)
        period_dimension = 3 if time_range == 7 else 5
        base_url = self._creative_center_origin(normalized_country)

        overview = self._creative_center_get(
            base_url,
            _CREATIVE_TRENDING_VIDEOS_OVERVIEW_PATH,
        )
        period_end_timestamp = _integer(overview.get("lastDailyEndTimestamp"))
        if period_end_timestamp <= 0:
            raise TikTokResponseError(
                "TikTok Creative Center video overview has no daily timestamp"
            )
        payload = self._creative_center_get(
            base_url,
            _CREATIVE_TRENDING_VIDEOS_LIST_PATH,
            params={
                "periodDimension": period_dimension,
                "periodEndTimestamp": str(period_end_timestamp),
                "orderByMetric": order_by_metric,
                "countryCode": normalized_country,
                "contentLabelIDs": ",".join(labels),
                "organicOnly": "false",
                "limit": 20,
                "page": 1,
            },
        )

        raw_items = payload.get("entityInfos")
        pagination = payload.get("pagination")
        if not isinstance(raw_items, list):
            raise TikTokResponseError(
                "TikTok Creative Center video response does not contain entityInfos"
            )
        if not isinstance(pagination, Mapping):
            raise TikTokResponseError(
                "TikTok Creative Center video response does not contain pagination"
            )

        videos = self._normalize_creative_trending_video_items(
            raw_items,
            limit=limit,
        )

        total_count = max(0, _integer(pagination.get("totalCount")))
        upstream_page = max(0, _integer(pagination.get("page")))
        upstream_limit = max(0, _integer(pagination.get("limit")))
        upstream_page_count = max(0, _integer(pagination.get("pageCount")))
        upstream_has_more = _boolean(pagination.get("hasMore"))
        anonymous_preview = (
            total_count > len(raw_items)
            and upstream_page == 1
            and 0 < upstream_limit <= 4
        )
        return {
            "source": "tiktok_creative_center",
            "transport": "web_api",
            "overview_endpoint": _CREATIVE_TRENDING_VIDEOS_OVERVIEW_PATH,
            "endpoint": _CREATIVE_TRENDING_VIDEOS_LIST_PATH,
            "origin": base_url,
            "country": normalized_country,
            "time_range_days": time_range,
            "period_dimension": period_dimension,
            "period_end_timestamp": str(period_end_timestamp),
            "metric": normalized_metric,
            "order_by_metric": order_by_metric,
            "content_label_ids": labels,
            "page": 1,
            "requested_limit": limit,
            "available": len(videos),
            "total_count": total_count,
            "has_more": False,
            "anonymous_preview": anonymous_preview,
            "upstream_page": upstream_page,
            "upstream_limit": upstream_limit,
            "upstream_page_count": upstream_page_count,
            "upstream_has_more": upstream_has_more,
            "continuation_restricted": anonymous_preview and upstream_has_more,
            "videos": videos,
        }

    def get_creative_trending_videos_full(
        self,
        *,
        country: str = "US",
        time_range: int = 30,
        metric: str = "views",
        content_label_ids: str | Sequence[int | str] | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """通过 Chrome 分页读取 Creative Center 热门视频完整榜单。"""
        normalized_country = str(country).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_country) is None:
            raise TikTokInputError("country must be a two-letter ASCII country code")
        if (
            not isinstance(time_range, int)
            or isinstance(time_range, bool)
            or time_range not in (7, 30)
        ):
            raise TikTokInputError("time_range must be 7 or 30")
        metric_options = {
            "views": ("views", 1),
            "video-views": ("views", 1),
            "engagement": ("engagement", 2),
            "engagement-rate": ("engagement", 2),
            "completion": ("completion", 3),
            "six-second-vtr": ("completion", 3),
        }
        normalized_metric = str(metric).strip().lower().replace("_", "-")
        if normalized_metric not in metric_options:
            raise TikTokInputError("metric must be views, engagement, or completion")
        normalized_metric, order_by_metric = metric_options[normalized_metric]
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= 1000
        ):
            raise TikTokInputError("page must be between 1 and 1000")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 20
        ):
            raise TikTokInputError("limit must be between 1 and 20")
        labels = self._creative_content_labels(content_label_ids)
        period_dimension = 3 if time_range == 7 else 5
        base_url = self._creative_center_origin(normalized_country)
        overview = self._creative_browser_fetch(
            _CREATIVE_TRENDING_VIDEOS_OVERVIEW_PATH,
            [],
            _CREATIVE_TRENDING_VIDEOS_REFERER,
        )
        period_end_timestamp = _integer(overview.get("lastDailyEndTimestamp"))
        if period_end_timestamp <= 0:
            raise TikTokResponseError(
                "TikTok Creative Center video overview has no daily timestamp"
            )
        payload = self._creative_browser_fetch(
            _CREATIVE_TRENDING_VIDEOS_LIST_PATH,
            [
                ("periodDimension", str(period_dimension)),
                ("periodEndTimestamp", str(period_end_timestamp)),
                ("orderByMetric", str(order_by_metric)),
                ("countryCode", normalized_country),
                ("contentLabelIDs", ",".join(labels)),
                ("page", str(page)),
                ("limit", str(limit)),
            ],
            _CREATIVE_TRENDING_VIDEOS_REFERER,
        )
        raw_items = payload.get("entityInfos")
        pagination = payload.get("pagination")
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > limit
            or not isinstance(pagination, Mapping)
        ):
            raise TikTokResponseError(
                "TikTok Creative Center video pagination response is invalid"
            )
        response_page = _integer(pagination.get("page"))
        response_limit = _integer(pagination.get("limit"))
        total_count = _integer(pagination.get("totalCount"))
        has_more = pagination.get("hasMore")
        consumed = (page - 1) * limit + len(raw_items)
        if (
            response_page != page
            or response_limit != limit
            or total_count < consumed
            or not isinstance(has_more, bool)
            or has_more != (consumed < total_count)
        ):
            raise TikTokResponseError(
                "TikTok Creative Center video pagination response is invalid"
            )
        videos = self._normalize_creative_trending_video_items(
            raw_items,
            limit=limit,
        )
        result: dict[str, Any] = {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "overview_endpoint": _CREATIVE_TRENDING_VIDEOS_OVERVIEW_PATH,
            "endpoint": _CREATIVE_TRENDING_VIDEOS_LIST_PATH,
            "source_url": _CREATIVE_TRENDING_VIDEOS_REFERER,
            "browser_session": True,
            "origin": base_url,
            "country": normalized_country,
            "time_range_days": time_range,
            "period_dimension": period_dimension,
            "period_end_timestamp": str(period_end_timestamp),
            "metric": normalized_metric,
            "order_by_metric": order_by_metric,
            "content_label_ids": labels,
            "page": page,
            "limit": limit,
            "available": len(videos),
            "total_count": total_count,
            "has_more": has_more,
            "anonymous_preview": False,
            "continuation_restricted": False,
            "videos": videos,
        }
        if has_more:
            result["next_page"] = page + 1
        return result

    def get_creative_trending_video_detail(
        self,
        item_id: str,
        *,
        country: str = "US",
        time_range: int = 30,
    ) -> dict[str, Any]:
        """查询一个 TikTok Creative Center 热门视频的公开详情。"""
        normalized_id = self._creative_trending_video_detail_input_id(item_id)
        normalized_country = str(country).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_country) is None:
            raise TikTokInputError("country must be a two-letter ASCII country code")
        if (
            not isinstance(time_range, int)
            or isinstance(time_range, bool)
            or time_range not in (7, 30)
        ):
            raise TikTokInputError("time_range must be 7 or 30")

        period_dimension = 3 if time_range == 7 else 5
        base_url = self._creative_center_origin(normalized_country)
        overview = self._creative_center_get(
            base_url,
            _CREATIVE_TRENDING_VIDEOS_OVERVIEW_PATH,
        )
        period_end_timestamp = self._creative_trending_video_detail_identifier(
            overview.get("lastDailyEndTimestamp"),
            field="overview lastDailyEndTimestamp",
        )
        payload = self._creative_center_get(
            base_url,
            _CREATIVE_TRENDING_VIDEO_DETAIL_PATH,
            params={
                "itemID": normalized_id,
                "periodDimension": period_dimension,
                "periodEndTimestamp": period_end_timestamp,
            },
        )
        entity = payload.get("entityInfo")
        if not isinstance(entity, Mapping):
            raise TikTokResponseError(
                "TikTok Creative Center video detail response has no entityInfo"
            )
        item_info = self._creative_trending_video_detail_object(entity, "itemInfo")
        author_info = self._creative_trending_video_detail_object(
            entity,
            "itemAuthorInfo",
        )
        author_metrics = self._creative_trending_video_detail_object(
            entity,
            "itemAuthorMetrics",
        )
        item_metrics = self._creative_trending_video_detail_object(
            entity,
            "itemMetrics",
        )

        response_id = self._creative_trending_video_detail_identifier(
            item_info.get("itemID"),
            field="entityInfo.itemInfo.itemID",
        )
        if response_id != normalized_id:
            raise TikTokResponseError(
                "TikTok Creative Center video detail itemID does not match target"
            )
        author_id = self._creative_trending_video_detail_identifier(
            item_info.get("authorID"),
            field="entityInfo.itemInfo.authorID",
        )
        creator_id = self._creative_trending_video_detail_identifier(
            item_info.get("creatorID"),
            field="entityInfo.itemInfo.creatorID",
        )
        title = self._creative_trending_video_detail_text(
            item_info.get("title"),
            field="entityInfo.itemInfo.title",
            maximum_length=4096,
            allow_text_whitespace=True,
        )
        handle = self._creative_trending_video_detail_handle(
            author_info.get("handlerName"),
            field="entityInfo.itemAuthorInfo.handlerName",
        )
        cover_url = self._creative_trending_video_detail_asset_url(
            item_info.get("coverURL"),
            field="entityInfo.itemInfo.coverURL",
        )
        media_url = self._creative_trending_video_detail_asset_url(
            item_info.get("videoURL"),
            field="entityInfo.itemInfo.videoURL",
        )
        author_avatar_url = self._creative_trending_video_detail_asset_url(
            author_info.get("avatarURI"),
            field="entityInfo.itemAuthorInfo.avatarURI",
        )
        cover_variants = self._creative_trending_video_detail_covers(
            item_info.get("coverURLList")
        )
        comments = self._creative_trending_video_detail_comments(
            entity.get("commentInfos")
        )
        public_url = (
            f"https://www.tiktok.com/@{quote(handle, safe='')}/video/{response_id}"
            if handle
            else ""
        )

        return {
            "source": "tiktok_creative_center",
            "transport": "web_api",
            "overview_endpoint": _CREATIVE_TRENDING_VIDEOS_OVERVIEW_PATH,
            "endpoint": _CREATIVE_TRENDING_VIDEO_DETAIL_PATH,
            "origin": base_url,
            "country": normalized_country,
            "time_range_days": time_range,
            "period_dimension": period_dimension,
            "period_end_timestamp": period_end_timestamp,
            "id": response_id,
            "title": title,
            "url": public_url,
            "cover_url": cover_url,
            "media_url": media_url,
            "cover_variants": cover_variants,
            "created_at": self._creative_trending_video_detail_nonnegative_integer(
                item_info.get("createTime"),
                field="entityInfo.itemInfo.createTime",
            ),
            "content_type": self._creative_trending_video_detail_nonnegative_integer(
                item_info.get("contentType"),
                field="entityInfo.itemInfo.contentType",
            ),
            "author": {
                "id": author_id,
                "creator_id": creator_id,
                "handle": handle,
                "nickname": self._creative_trending_video_detail_text(
                    author_info.get("nickName"),
                    field="entityInfo.itemAuthorInfo.nickName",
                    maximum_length=256,
                ),
                "avatar_url": author_avatar_url,
                "bio": self._creative_trending_video_detail_text(
                    author_info.get("bio"),
                    field="entityInfo.itemAuthorInfo.bio",
                    maximum_length=1024,
                    allow_text_whitespace=True,
                ),
                "creator_type": self._creative_trending_video_detail_nonnegative_integer(
                    author_info.get("creatorType"),
                    field="entityInfo.itemAuthorInfo.creatorType",
                ),
                "followers": self._creative_trending_video_detail_nonnegative_integer(
                    author_metrics.get("followers"),
                    field="entityInfo.itemAuthorMetrics.followers",
                ),
            },
            "metrics": self._creative_trending_video_detail_metrics(item_metrics),
            "available_comments": len(comments),
            "comments": comments,
        }

    def get_creative_hashtag_detail(
        self,
        hashtag_id: str,
        *,
        country: str = "US",
        time_range: int = 7,
    ) -> dict[str, Any]:
        """通过 Chrome 读取热门标签受众、地域 TGI 和代表视频。"""
        normalized_id = str(hashtag_id).strip()
        if (
            not normalized_id.isascii()
            or not normalized_id.isdecimal()
            or normalized_id.startswith("0")
            or len(normalized_id) > 32
        ):
            raise TikTokInputError("hashtag_id must be a positive decimal id")
        normalized_country = str(country).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_country) is None:
            raise TikTokInputError("country must be a two-letter ASCII country code")
        if time_range not in (7, 30, 90):
            raise TikTokInputError("time_range must be 7, 30, or 90")
        payload = self._creative_browser_fetch(
            _CREATIVE_HASHTAG_DETAIL_PATH,
            [
                ("hashtagID", normalized_id),
                ("timeRange", str(time_range)),
                ("countryCode", normalized_country),
            ],
            _CREATIVE_TRENDING_HASHTAGS_REFERER,
        )
        response_id = str(payload.get("hashtagID") or "")
        name = str(payload.get("hashtagName") or "").strip()
        if response_id != normalized_id or not name:
            raise TikTokResponseError(
                "TikTok Creative Center hashtag detail response is invalid"
            )
        popularity_curve = payload.get("popularityCurve")
        age_profile = payload.get("ageProfile")
        country_profile = payload.get("representativeCountryProfile")
        raw_videos = payload.get("videoList")
        if not all(
            isinstance(value, list)
            for value in (
                popularity_curve,
                age_profile,
                country_profile,
                raw_videos,
            )
        ):
            raise TikTokResponseError(
                "TikTok Creative Center hashtag detail fields are invalid"
            )
        videos: list[dict[str, Any]] = []
        for index, item in enumerate(raw_videos):
            if not isinstance(item, Mapping):
                raise TikTokResponseError(
                    f"TikTok Creative Center hashtag video {index} is invalid"
                )
            item_id = str(item.get("itemID") or "")
            video_id = str(item.get("vid") or "")
            video_urls = item.get("videoURL")
            if (
                not item_id.isdecimal()
                or not video_id
                or not isinstance(video_urls, Mapping)
            ):
                raise TikTokResponseError(
                    f"TikTok Creative Center hashtag video {index} is invalid"
                )
            videos.append(
                {
                    "item_id": item_id,
                    "video_id": video_id,
                    "cover_url": str(item.get("coverURL") or ""),
                    "video_urls": dict(video_urls),
                }
            )
        return {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_HASHTAG_DETAIL_PATH,
            "browser_session": True,
            "hashtag": {
                "id": response_id,
                "name": name,
                "industry_ids": list(payload.get("industryIDs") or []),
                "post_count": max(0, _integer(payload.get("publishCnt"))),
                "view_count": max(0, _integer(payload.get("vv"))),
            },
            "country": normalized_country,
            "time_range_days": time_range,
            "popularity_curve": list(popularity_curve),
            "age_profile": list(age_profile),
            "representative_country_profile": list(country_profile),
            "representative_videos": videos,
        }

    def get_creative_top_ads_filters(
        self,
    ) -> dict[str, Any]:
        """通过 Chrome Creative Center 页面读取 Top Ads 可用筛选项。"""
        payload = self._creative_browser_fetch(
            _CREATIVE_TOP_ADS_FILTERS_PATH,
            [],
            _CREATIVE_TOP_ADS_LIBRARY_REFERER,
        )
        fields = {
            name: payload.get(name)
            for name in (
                "adLanguage",
                "country",
                "industry",
                "objective",
                "patternLabel",
                "period",
            )
        }
        if any(not isinstance(value, list) or not value for value in fields.values()):
            raise TikTokResponseError("TikTok Top Ads filters response is invalid")
        return {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_TOP_ADS_FILTERS_PATH,
            "browser_session": True,
            "country_codes": [
                str(item.get("id"))
                for item in fields["country"]
                if isinstance(item, Mapping)
            ],
            "countries": fields["country"],
            "industries": fields["industry"],
            "objectives": fields["objective"],
            "languages": fields["adLanguage"],
            "pattern_labels": fields["patternLabel"],
            "periods": fields["period"],
        }

    def get_ads_keyword_ideas(
        self,
        keywords: Sequence[str],
        *,
        country: str = "US",
        language: str = "en",
        brand: str = "all",
        competitions: Sequence[str] = ("limited", "medium", "high"),
        sort: str = "default",
        order: str = "default",
        limit: int = 50,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        """通过 Ads Manager Keyword Planner 查询搜索量、CPC 和竞争度。"""
        seeds = self._ads_keyword_list(keywords, maximum=10)
        normalized_country, country_id = self._ads_keyword_country(country)
        if language != "en":
            raise TikTokInputError("language must be en")
        if brand not in _ADS_KEYWORD_BRAND_OPTIONS:
            raise TikTokInputError(
                "brand must be all, branded, or non_branded"
            )
        if sort not in _ADS_KEYWORD_SORT_FIELDS:
            raise TikTokInputError(
                "sort must be default, volume, three_month, yoy, cpc, "
                "source, or competition"
            )
        if order not in _ADS_KEYWORD_SORT_ORDERS:
            raise TikTokInputError(
                "order must be default, descending, or ascending"
            )
        competition_ids = self._ads_keyword_competitions(competitions)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 0 <= limit <= 200
        ):
            raise TikTokInputError("limit must be between 0 and 200")
        normalized_start, normalized_end = self._ads_keyword_time_range(
            start_time,
            end_time,
        )
        payload = self._creative_browser_fetch(
            _ADS_KEYWORD_IDEAS_PATH,
            [
                (
                    "keywords",
                    json.dumps(
                        seeds,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
                ("startTime", str(normalized_start)),
                ("endTime", str(normalized_end)),
                (
                    "brandOption",
                    str(_ADS_KEYWORD_BRAND_OPTIONS[brand]),
                ),
                ("sortField", str(_ADS_KEYWORD_SORT_FIELDS[sort])),
                ("sortOrder", str(_ADS_KEYWORD_SORT_ORDERS[order])),
                ("countryId", str(country_id)),
                ("languageCode", "en"),
                ("languageName", "English"),
            ],
            _ADS_KEYWORD_PLANNER_REFERER,
        )
        raw_ideas = payload.get("keywordIdeaInfoList")
        if not isinstance(raw_ideas, list) or len(raw_ideas) > 200:
            raise TikTokResponseError(
                "TikTok Ads keyword ideas response is invalid"
            )
        ideas = [
            self._normalize_ads_keyword_idea(item, index)
            for index, item in enumerate(raw_ideas)
        ]
        ideas = [
            item
            for item in ideas
            if item["competition"]["id"] in competition_ids
        ][:limit]
        validation = payload.get("validation", {})
        if not isinstance(validation, Mapping):
            raise TikTokResponseError(
                "TikTok Ads keyword validation response is invalid"
            )
        return {
            "source": "tiktok_ads_manager_keyword_planner",
            "transport": "browser_web",
            "endpoint": _ADS_KEYWORD_IDEAS_PATH,
            "browser_session": True,
            "country": normalized_country,
            "country_id": country_id,
            "language": "en",
            "seeds": seeds,
            "brand": brand,
            "competitions": list(competitions),
            "sort": sort,
            "order": order,
            "time_range": {
                "start_time": normalized_start,
                "end_time": normalized_end,
            },
            "available": len(ideas),
            "ideas": ideas,
            "upstream_totals": {
                "search_volume": self._ads_keyword_range(
                    payload.get("totalSearchVol"),
                    "totalSearchVol",
                    allow_none=True,
                ),
                "budget_estimate": self._ads_keyword_range(
                    payload.get("totalBudgetEstimate"),
                    "totalBudgetEstimate",
                    allow_none=True,
                ),
            },
            "validation": dict(validation),
        }

    def get_ads_keyword_summary(
        self,
        words: Sequence[str],
        *,
        country: str = "US",
        match_type: str = "broad",
        source_type: int = 1,
    ) -> dict[str, Any]:
        """汇总一个 TikTok Search Ads 关键词包的搜索量和预算区间。"""
        normalized_words = self._ads_keyword_list(words, maximum=20)
        normalized_country, _country_id = self._ads_keyword_country(country)
        if match_type not in _ADS_KEYWORD_MATCH_TYPES:
            raise TikTokInputError(
                "match_type must be exact, phrase, or broad"
            )
        if (
            not isinstance(source_type, int)
            or isinstance(source_type, bool)
            or not 1 <= source_type <= 20
        ):
            raise TikTokInputError("source_type must be between 1 and 20")
        request_words = [
            {
                "keyword": keyword,
                "matchType": _ADS_KEYWORD_MATCH_TYPES[match_type],
                "sourceType": source_type,
            }
            for keyword in normalized_words
        ]
        payload = self._creative_browser_fetch(
            _ADS_KEYWORD_SUMMARY_PATH,
            [
                (
                    "words",
                    json.dumps(
                        request_words,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
                ("countryName", normalized_country),
            ],
            _ADS_KEYWORD_PLANNER_REFERER,
        )
        return {
            "source": "tiktok_ads_manager_keyword_planner",
            "transport": "browser_web",
            "endpoint": _ADS_KEYWORD_SUMMARY_PATH,
            "browser_session": True,
            "country": normalized_country,
            "words": normalized_words,
            "match_type": match_type,
            "source_type": source_type,
            "total_search_volume": self._ads_keyword_range(
                payload.get("totalSearchVol"),
                "totalSearchVol",
            ),
            "total_budget_estimate": self._ads_keyword_range(
                payload.get("totalBudgetEstimate"),
                "totalBudgetEstimate",
                allow_none=True,
            ),
        }

    def get_creative_top_ads_suggestions(
        self,
        keyword: str = "",
        *,
        country: str = "US",
        limit: int = 20,
    ) -> dict[str, Any]:
        """查询 Top Ads 热门词或输入词的相关搜索词。"""
        query = self._one_keyword(keyword)
        normalized_country = str(country).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_country) is None:
            raise TikTokInputError("country must be a two-letter country code")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 0 <= limit <= 50
        ):
            raise TikTokInputError("limit must be between 0 and 50")
        scenario = 2 if query else 1
        suggestions: list[str] = []
        if limit:
            payload = self._creative_browser_fetch(
                _CREATIVE_TOP_ADS_SUGGEST_PATH,
                [
                    ("query", query),
                    ("count", str(limit)),
                    ("scenario", str(scenario)),
                    ("countryCode", normalized_country),
                ],
                _CREATIVE_TOP_ADS_LIBRARY_REFERER,
            )
            raw_suggestions = payload.get("query")
            if (
                not isinstance(raw_suggestions, list)
                or len(raw_suggestions) > limit
                or not all(isinstance(item, str) for item in raw_suggestions)
            ):
                raise TikTokResponseError(
                    "TikTok Top Ads suggestions response is invalid"
                )
            suggestions = list(dict.fromkeys(raw_suggestions))
        return {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_TOP_ADS_SUGGEST_PATH,
            "browser_session": True,
            "keyword": query,
            "country": normalized_country,
            "scenario": scenario,
            "suggestions": suggestions[:limit],
        }

    def get_creative_top_ads(
        self,
        search_word: str = "",
        *,
        countries: str | Sequence[str] = (),
        time_range: int = 30,
        industry_label_ids: str | Sequence[int | str] = (),
        objectives: str | Sequence[int | str] = (),
        ad_format: str | None = None,
        duration: str | None = None,
        like_range: str | None = None,
        pattern_label_ids: str | Sequence[int | str] = (),
        languages: str | Sequence[str] = (),
        order: str = "for_you",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """通过 Chrome Creative Center 页面筛选和搜索 Top Ads 素材。"""
        query = str(search_word)
        if (
            query != query.strip()
            or len(query) > 256
            or any(character in query for character in "\r\n\0")
        ):
            raise TikTokInputError("search_word is invalid")
        country_codes = self._creative_top_ads_values(
            countries,
            maximum_items=249,
            label="countries",
            validator=lambda value: re.fullmatch(r"[A-Z]{2}", value) is not None,
            transform=lambda value: value.upper(),
        )
        industry_ids = self._creative_top_ads_values(
            industry_label_ids,
            maximum_items=20,
            label="industry_label_ids",
            validator=self._creative_safe_decimal,
        )
        objective_values = self._creative_top_ads_values(
            objectives,
            maximum_items=len(_CREATIVE_TOP_ADS_OBJECTIVES),
            label="objectives",
            validator=lambda value: (
                value.isascii()
                and value.isdecimal()
                and int(value) in _CREATIVE_TOP_ADS_OBJECTIVES
            ),
        )
        pattern_labels = self._creative_top_ads_values(
            pattern_label_ids,
            maximum_items=50,
            label="pattern_label_ids",
            validator=self._creative_safe_decimal,
        )
        language_codes = self._creative_top_ads_values(
            languages,
            maximum_items=20,
            label="languages",
            validator=lambda value: (
                re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z]{2,8})?", value)
                is not None
            ),
        )
        if time_range not in {7, 30, 180}:
            raise TikTokInputError("time_range must be 7, 30, or 180")
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= 1000
        ):
            raise TikTokInputError("page must be between 1 and 1000")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 20
        ):
            raise TikTokInputError("limit must be between 1 and 20")
        normalized_ad_format = (
            str(ad_format).strip().lower().replace("-", "_")
            if ad_format is not None
            else None
        )
        if (
            normalized_ad_format is not None
            and normalized_ad_format not in _CREATIVE_TOP_ADS_FORMATS
        ):
            raise TikTokInputError("ad_format is invalid")
        if duration is not None and duration not in {
            "0-15",
            "15-30",
            "30-60",
            "60-999",
        }:
            raise TikTokInputError("duration is invalid")
        if like_range is not None and like_range not in {
            "0-100",
            "100-1000",
            "1000-10000",
            "10000-999999999",
        }:
            raise TikTokInputError("like_range is invalid")
        order_name = self._creative_top_ads_order(order)

        entries = [
            ("period", str(time_range)),
            ("orderBy", order_name),
            ("countryCode", ",".join(country_codes) if country_codes else "US"),
            ("page", str(page)),
            ("limit", str(limit)),
        ]
        if industry_ids:
            entries.append(("industry", ",".join(industry_ids)))
        if query:
            entries.append(("keyword", query))
        if objective_values:
            entries.append(("objective", ",".join(objective_values)))
        if duration is not None:
            entries.append(("duration", duration))
        if like_range is not None:
            entries.append(("like", like_range))
        if pattern_labels:
            entries.append(("patternLabel", ",".join(pattern_labels)))
        if normalized_ad_format is not None:
            entries.append(("adFormat", normalized_ad_format))
        if language_codes:
            entries.append(("adLanguage", ",".join(language_codes)))

        payload = self._creative_browser_fetch(
            _CREATIVE_TOP_ADS_SEARCH_PATH,
            entries,
            _CREATIVE_TOP_ADS_LIBRARY_REFERER,
        )
        raw_items = payload.get("materials")
        pagination = payload.get("pagination")
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > limit
            or not isinstance(pagination, Mapping)
        ):
            raise TikTokResponseError("TikTok Top Ads search response is invalid")
        response_page = _integer(pagination.get("page"))
        response_size = _integer(
            pagination.get("size")
        )
        has_more = pagination.get("hasMore")
        total = _integer(
            pagination.get("totalCount")
        )
        if (
            response_page != page
            or response_size != limit
            or not isinstance(has_more, bool)
            or total < (page - 1) * limit + len(raw_items)
        ):
            raise TikTokResponseError(
                "TikTok Top Ads pagination response is invalid"
            )
        source_country = country_codes[0] if country_codes else "US"
        ads = [
            self._normalize_creative_top_ad(
                item,
                index,
                country=source_country,
                time_range=time_range,
            )
            for index, item in enumerate(raw_items)
        ]
        result: dict[str, Any] = {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_TOP_ADS_SEARCH_PATH,
            "browser_session": True,
            "search_word": query,
            "country_codes": country_codes or ["US"],
            "source_country": source_country,
            "time_range_days": time_range,
            "industry_labels": industry_ids,
            "objectives": [int(value) for value in objective_values],
            "ad_format": normalized_ad_format,
            "duration": duration,
            "like_range": like_range,
            "pattern_labels": pattern_labels,
            "languages": language_codes,
            "order": order_name,
            "page": page,
            "limit": limit,
            "available": len(ads),
            "total_count": total,
            "has_more": has_more,
            "ads": ads,
        }
        if has_more:
            result["next_page"] = page + 1
        return result

    def get_creative_top_ads_performance(
        self,
        search_word: str = "",
        *,
        countries: str | Sequence[str] = (),
        time_range: int = 30,
        industry_label_ids: str | Sequence[int | str] = (),
        objectives: str | Sequence[int | str] = (),
        ad_format: int | str | None = None,
        like_count_filter: int | None = None,
        order: str = "views",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """读取 Top Ads Library 的数值表现素材页。"""
        query = str(search_word)
        if (
            query != query.strip()
            or len(query) > 256
            or any(character in query for character in "\r\n\0")
        ):
            raise TikTokInputError("search_word is invalid")
        country_codes = self._creative_top_ads_values(
            countries,
            maximum_items=249,
            label="countries",
            validator=lambda value: re.fullmatch(r"[A-Z]{2}", value) is not None,
            transform=lambda value: value.upper(),
        )
        industry_ids = self._creative_top_ads_values(
            industry_label_ids,
            maximum_items=20,
            label="industry_label_ids",
            validator=self._creative_safe_decimal,
        )
        objective_values = self._creative_top_ads_values(
            objectives,
            maximum_items=len(_CREATIVE_TOP_ADS_PERFORMANCE_OBJECTIVES),
            label="objectives",
            validator=lambda value: (
                value.isascii()
                and value.isdecimal()
                and int(value) in _CREATIVE_TOP_ADS_PERFORMANCE_OBJECTIVES
            ),
        )
        if time_range not in {7, 30, 180}:
            raise TikTokInputError("time_range must be 7, 30, or 180")
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= 1000
        ):
            raise TikTokInputError("page must be between 1 and 1000")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 20
        ):
            raise TikTokInputError("limit must be between 1 and 20")
        normalized_ad_format = self._creative_top_ads_performance_ad_format(
            ad_format
        )
        if (
            like_count_filter is not None
            and (
                not isinstance(like_count_filter, int)
                or isinstance(like_count_filter, bool)
                or not 1 <= like_count_filter <= 5
            )
        ):
            raise TikTokInputError("like_count_filter must be between 1 and 5")
        order_name, order_field = self._creative_top_ads_performance_order(order)

        entries = [
            ("timeRange", str(time_range)),
            ("orderField", str(order_field)),
            ("page", str(page)),
            ("limit", str(limit)),
            ("sourceModule", "2"),
        ]
        if country_codes:
            entries.append(("countryCodeList", ",".join(country_codes)))
        if industry_ids:
            entries.append(("industryLabelList", ",".join(industry_ids)))
        if query:
            entries.append(("searchWord", query))
        if objective_values:
            entries.append(("objectiveList", ",".join(objective_values)))
        if normalized_ad_format is not None:
            entries.append(("adFormat", str(normalized_ad_format)))
        if like_count_filter is not None:
            entries.append(("likeCntFilter", str(like_count_filter)))

        payload = self._creative_browser_fetch(
            _CREATIVE_TOP_ADS_PERFORMANCE_PATH,
            entries,
            _CREATIVE_TOP_ADS_PERFORMANCE_REFERER,
        )
        raw_items = payload.get("itemList")
        pagination = payload.get("pagination")
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > limit
            or not isinstance(pagination, Mapping)
        ):
            raise TikTokResponseError(
                "TikTok Top Ads performance response is invalid"
            )
        response_page = self._creative_top_ads_performance_integer(
            pagination.get("page"),
            field="pagination.page",
        )
        raw_size = pagination.get("size", pagination.get("limit"))
        response_size = self._creative_top_ads_performance_integer(
            raw_size,
            field="pagination.size",
        )
        if "size" in pagination and "limit" in pagination:
            alternate_size = self._creative_top_ads_performance_integer(
                pagination["limit"],
                field="pagination.limit",
            )
            if alternate_size != response_size:
                raise TikTokResponseError(
                    "TikTok Top Ads performance pagination is invalid"
                )
        total = self._creative_top_ads_performance_integer(
            pagination.get("total"),
            field="pagination.total",
        )
        if "totalCount" in pagination:
            alternate_total = self._creative_top_ads_performance_integer(
                pagination["totalCount"],
                field="pagination.totalCount",
            )
            if alternate_total != total:
                raise TikTokResponseError(
                    "TikTok Top Ads performance pagination is invalid"
                )
        has_more = pagination.get("hasMore")
        consumed = (page - 1) * limit + len(raw_items)
        if (
            response_page != page
            or response_size != limit
            or not isinstance(has_more, bool)
            or total < consumed
            or has_more != (consumed < total)
        ):
            raise TikTokResponseError(
                "TikTok Top Ads performance pagination is invalid"
            )
        seen_ids: set[str] = set()
        ads: list[dict[str, Any]] = []
        for index, item in enumerate(raw_items):
            ad = self._normalize_creative_top_ads_performance(item, index)
            if ad["id"] in seen_ids:
                raise TikTokResponseError(
                    "TikTok Top Ads performance response has duplicate material IDs"
                )
            seen_ids.add(ad["id"])
            ads.append(ad)
        result: dict[str, Any] = {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_TOP_ADS_PERFORMANCE_PATH,
            "browser_session": True,
            "source_url": _CREATIVE_TOP_ADS_PERFORMANCE_REFERER,
            "scope": "library",
            "source_module": 2,
            "search_word": query,
            "country_codes": country_codes,
            "time_range_days": time_range,
            "industry_labels": industry_ids,
            "objectives": [int(value) for value in objective_values],
            "ad_format": normalized_ad_format,
            "like_count_filter": like_count_filter,
            "order": order_name,
            "order_field": order_field,
            "page": page,
            "limit": limit,
            "available": len(ads),
            "total_count": total,
            "has_more": has_more,
            "ads": ads,
        }
        if has_more:
            result["next_page"] = page + 1
        return result

    def get_creative_top_ads_keyframes(
        self,
        material_id: str,
        *,
        metrics: Sequence[str] = ("retain_ctr",),
    ) -> dict[str, Any]:
        """查询 Top Ads 视频逐秒留存、点击或转化曲线。"""
        normalized_id = self._creative_top_ads_material_id(material_id)
        normalized_metrics = self._creative_top_ads_metrics(metrics)
        curves: dict[str, Any] = {}
        for metric in normalized_metrics:
            payload = self._creative_browser_fetch(
                _CREATIVE_TOP_ADS_KEYFRAME_PATH,
                [("materialId", normalized_id), ("metric", metric)],
                _CREATIVE_TOP_ADS_LIBRARY_REFERER,
            )
            if (
                not isinstance(payload.get("duration"), int)
                or not isinstance(payload.get("analysis"), list)
                or not isinstance(payload.get("highlight"), list)
            ):
                raise TikTokResponseError(
                    "TikTok Top Ads keyframe response is invalid"
                )
            curves[metric] = dict(payload)
        return {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_TOP_ADS_KEYFRAME_PATH,
            "browser_session": True,
            "material_id": normalized_id,
            "metrics": normalized_metrics,
            "curves": curves,
        }

    def get_creative_top_ads_detail(
        self,
        material_id: str,
        *,
        country: str = "US",
        time_range: int = 180,
        metrics: Sequence[str] = ("retain_ctr", "play_retain_cnt"),
        include_recommendations: bool = True,
        include_ai_analysis: bool = True,
    ) -> dict[str, Any]:
        """组合 Top Ads 素材详情、逐秒曲线、CTR 分位和相关推荐。"""
        normalized_id = self._creative_top_ads_material_id(material_id)
        normalized_country = str(country).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_country) is None:
            raise TikTokInputError("country must be a two-letter country code")
        if time_range not in {7, 30, 180}:
            raise TikTokInputError("time_range must be 7, 30, or 180")
        material = self._normalize_creative_top_ad(
            self._creative_browser_fetch(
                _CREATIVE_TOP_ADS_DETAIL_PATH,
                [("materialId", normalized_id)],
                _CREATIVE_TOP_ADS_LIBRARY_REFERER,
            ),
            0,
            country=normalized_country,
            time_range=time_range,
        )
        curves = self.get_creative_top_ads_keyframes(
            normalized_id,
            metrics=metrics,
        )
        percentile_payload = self._creative_browser_fetch(
            _CREATIVE_TOP_ADS_PERCENTILE_PATH,
            [
                ("materialId", normalized_id),
                ("metric", "ctr_percentile"),
                ("periodType", str(time_range)),
            ],
            _CREATIVE_TOP_ADS_LIBRARY_REFERER,
        )
        percentile = percentile_payload.get("ctrPercentile")
        if (
            not isinstance(percentile, (int, float, str))
            or isinstance(percentile, bool)
            or not 0 <= float(percentile) <= 1
        ):
            raise TikTokResponseError(
                "TikTok Top Ads percentile response is invalid"
            )
        recommendations: list[dict[str, Any]] = []
        if include_recommendations:
            industry = self._creative_top_ads_industry_id(
                material.get("industry_key")
            )
            payload = self._creative_browser_fetch(
                _CREATIVE_TOP_ADS_RECOMMEND_PATH,
                [
                    ("materialId", normalized_id),
                    ("industry", industry),
                    ("countryCode", normalized_country),
                ],
                _CREATIVE_TOP_ADS_LIBRARY_REFERER,
            )
            raw_recommendations = payload.get("materials")
            if not isinstance(raw_recommendations, list):
                raise TikTokResponseError(
                    "TikTok Top Ads recommendations response is invalid"
                )
            recommendations = [
                self._normalize_creative_top_ad(
                    item,
                    index,
                    country=normalized_country,
                    time_range=time_range,
                )
                for index, item in enumerate(raw_recommendations)
            ]
        ai_analysis: dict[str, Any] = {"available": False}
        if include_ai_analysis:
            try:
                analysis = self._creative_browser_fetch(
                    _CREATIVE_TOP_ADS_ANALYSIS_PATH,
                    [("materialId", normalized_id)],
                    _CREATIVE_TOP_ADS_LIBRARY_REFERER,
                )
                ai_analysis = {"available": True, "data": dict(analysis)}
            except TikTokResponseError as exc:
                ai_analysis = {"available": False, "error": str(exc)}
        return {
            "source": "tiktok_creative_center",
            "transport": "browser_web",
            "endpoint": _CREATIVE_TOP_ADS_DETAIL_PATH,
            "browser_session": True,
            "material_id": normalized_id,
            "country": normalized_country,
            "time_range_days": time_range,
            "ad": material,
            "keyframes": curves["curves"],
            "ctr_percentile": float(percentile),
            "recommendations": recommendations,
            "ai_analysis": ai_analysis,
        }

    def get_creative_studio_credits(self) -> dict[str, Any]:
        """查询当前 Symphony Creative Studio 周额度。"""
        payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_CREDITS_PATH,
            [],
            _CREATIVE_STUDIO_REFERER,
        )
        credits = self._creative_studio_credits_payload(payload)
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_CREDITS_PATH,
            "browser_session": True,
            **credits,
        }

    def get_creative_studio_permissions(self) -> dict[str, Any]:
        """查询 Symphony Creative Studio 当前模型入口权限。"""
        payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_PERMISSIONS_PATH,
            [],
            _CREATIVE_STUDIO_REFERER,
        )
        permissions = payload.get("permissions")
        allowlist = payload.get("allowlist")
        if (
            not isinstance(permissions, Mapping)
            or not isinstance(allowlist, list)
            or not all(
                isinstance(name, str)
                and name
                and isinstance(item, Mapping)
                and all(isinstance(value, bool) for value in item.values())
                for name, item in permissions.items()
            )
            or not all(
                isinstance(item, Mapping)
                and isinstance(item.get("tool"), str)
                and item.get("tool")
                and isinstance(item.get("auth"), list)
                and all(
                    isinstance(auth, str) and auth
                    for auth in item["auth"]
                )
                for item in allowlist
            )
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio permissions response is invalid"
            )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_PERMISSIONS_PATH,
            "browser_session": True,
            "permissions": dict(permissions),
            "allowlist": allowlist,
        }

    def get_creative_studio_generation_limits(self) -> dict[str, Any]:
        """查询 Symphony Creative Studio 当前任务数和模型并发上限。"""
        count_payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_GENERATING_COUNT_PATH,
            [],
            _CREATIVE_STUDIO_REFERER,
        )
        max_payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_MAX_COUNT_PATH,
            [],
            _CREATIVE_STUDIO_REFERER,
        )
        total = count_payload.get("total")
        limits = max_payload.get("limits")
        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
            or not isinstance(limits, Mapping)
            or _CREATIVE_STUDIO_T2V_SUB_APP not in limits
            or not all(
                isinstance(name, str)
                and name
                and isinstance(limit, int)
                and not isinstance(limit, bool)
                and limit >= 0
                for name, limit in limits.items()
            )
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio generation limits response is invalid"
            )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoints": [
                _CREATIVE_STUDIO_GENERATING_COUNT_PATH,
                _CREATIVE_STUDIO_MAX_COUNT_PATH,
            ],
            "browser_session": True,
            "generating_tasks": total,
            "limits": dict(limits),
        }

    @staticmethod
    def get_creative_studio_models() -> dict[str, Any]:
        """返回已研究确认的 Seedance 模型和当前命令覆盖状态。"""
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "local_catalog",
            "models": [
                {
                    "mode": "t2v",
                    "name": "Seedance 2.0",
                    "model_id": _CREATIVE_STUDIO_MODEL_ID,
                    "sub_app": _CREATIVE_STUDIO_T2V_SUB_APP,
                    "duration": {"minimum": 4, "maximum": 15, "default": 5},
                    "input_images": {"minimum": 0, "maximum": 0},
                    "callable": True,
                },
                {
                    "mode": "i2v",
                    "name": "Seedance 2.0",
                    "model_id": _CREATIVE_STUDIO_I2V_MODEL_ID,
                    "sub_app": _CREATIVE_STUDIO_I2V_SUB_APP,
                    "duration": {"minimum": 4, "maximum": 15, "default": 5},
                    "input_images": {"minimum": 1, "maximum": 2},
                    "callable": True,
                },
                {
                    "mode": "r2v",
                    "name": "Seedance 2.0",
                    "model_id": _CREATIVE_STUDIO_R2V_MODEL_ID,
                    "sub_app": _CREATIVE_STUDIO_R2V_SUB_APP,
                    "duration": {"minimum": 4, "maximum": 15, "default": 5},
                    "reference_inputs": {
                        "minimum_image_or_video": 1,
                        "maximum_total": 12,
                        "images": {"minimum": 0, "maximum": 9},
                        "videos": {
                            "minimum": 0,
                            "maximum": _CREATIVE_STUDIO_R2V_MAX_VIDEOS,
                            "minimum_duration": (
                                _CREATIVE_STUDIO_R2V_MIN_VIDEO_DURATION
                            ),
                            "duration_sum_exclusive_maximum": (
                                _CREATIVE_STUDIO_R2V_MAX_VIDEO_DURATION_SUM
                            ),
                        },
                        "audio": {
                            "minimum": 0,
                            "maximum": 3,
                            "minimum_duration": (
                                _CREATIVE_STUDIO_R2V_MIN_VIDEO_DURATION
                            ),
                            "duration_sum_exclusive_maximum": (
                                _CREATIVE_STUDIO_R2V_MAX_VIDEO_DURATION_SUM
                            ),
                        },
                    },
                    "preflight_callable": True,
                    "submission_evidence": "static_contract_only",
                    "callable": False,
                },
            ],
        }

    def get_creative_studio_status(self) -> dict[str, Any]:
        """汇总 Seedance 权限、积分和并发状态。"""
        credits = self.get_creative_studio_credits()
        permissions = self.get_creative_studio_permissions()
        generation = self.get_creative_studio_generation_limits()
        t2v_permission = permissions["permissions"].get(
            _CREATIVE_STUDIO_T2V_SUB_APP,
            {},
        )
        i2v_permission = permissions["permissions"].get(
            _CREATIVE_STUDIO_I2V_SUB_APP,
            {},
        )
        r2v_permission = permissions["permissions"].get(
            _CREATIVE_STUDIO_R2V_SUB_APP,
            {},
        )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "browser_session": True,
            "t2v_ready": t2v_permission.get("entry_pass") is True,
            "i2v_ready": i2v_permission.get("entry_pass") is True,
            "r2v_ready": r2v_permission.get("entry_pass") is True,
            "credits": {
                name: credits[name]
                for name in (
                    "credits",
                    "bonus",
                    "weekly_spent",
                    "tier",
                    "is_unlimited",
                )
            },
            "permissions": permissions["permissions"],
            "allowlist": permissions["allowlist"],
            "generating_tasks": generation["generating_tasks"],
            "generation_limits": generation["limits"],
            "models": self.get_creative_studio_models()["models"],
        }

    def prepare_creative_studio_video(
        self,
        prompt: str,
        *,
        duration: int = 5,
        enhance_prompt: bool = False,
    ) -> dict[str, Any]:
        """校验 T2V 输入、权限、积分和并发，不提交生成任务。"""
        normalized_prompt = self._creative_studio_prompt(prompt)
        self._creative_studio_generation_options(
            duration=duration,
            enhance_prompt=enhance_prompt,
        )
        status = self.get_creative_studio_status()
        credits = status["credits"]
        balance = int(credits["credits"])
        concurrent = status["generating_tasks"]
        maximum = status["generation_limits"][_CREATIVE_STUDIO_T2V_SUB_APP]
        blockers: list[str] = []
        if not status["t2v_ready"]:
            blockers.append("permission_missing")
        if not credits["is_unlimited"] and balance < duration:
            blockers.append("insufficient_credits")
        if concurrent >= maximum:
            blockers.append("concurrency_limit")
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "browser_session": True,
            "mode": "text",
            "model": "dreamina_seedance_2",
            "model_id": _CREATIVE_STUDIO_MODEL_ID,
            "sub_app": _CREATIVE_STUDIO_T2V_SUB_APP,
            "prompt": normalized_prompt,
            "duration": duration,
            "enhance_prompt": enhance_prompt,
            "estimated_credits": duration,
            "ready": not blockers,
            "blockers": blockers,
            "credits": credits,
            "concurrency": {
                "active": concurrent,
                "maximum": maximum,
                "available": max(0, maximum - concurrent),
            },
            "permission": status["permissions"].get(
                _CREATIVE_STUDIO_T2V_SUB_APP,
                {},
            ),
        }

    def upload_creative_studio_image(
        self,
        image_path: str | Path,
    ) -> dict[str, Any]:
        """把本机参考图上传到当前 Creative Studio 会话。"""
        path = Path(image_path).expanduser()
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise TikTokInputError(
                f"cannot read reference image: {path}"
            ) from exc
        mime_type = self._creative_studio_image_mime(path.name, data)
        if not data or len(data) > _CREATIVE_STUDIO_MAX_IMAGE_BYTES:
            raise TikTokInputError(
                "reference image must be between 1 byte and 5 MiB"
            )
        payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_UPLOAD_IMAGE_PATH,
            [
                ("name", path.name),
                ("mimeType", mime_type),
                ("dataBase64", base64.b64encode(data).decode("ascii")),
            ],
            _CREATIVE_STUDIO_REFERER,
        )
        image_url = str(payload.get("image_url") or "")
        image_uri = str(payload.get("image_uri") or "")
        width = payload.get("width")
        height = payload.get("height")
        if (
            not self._creative_studio_image_url(image_url)
            or not image_uri
            or not isinstance(width, int)
            or isinstance(width, bool)
            or width <= 0
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height <= 0
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio image upload response is invalid"
            )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_UPLOAD_IMAGE_PATH,
            "browser_session": True,
            "name": path.name,
            "mime_type": mime_type,
            "size": len(data),
            "image_url": image_url,
            "image_uri": image_uri,
            "width": width,
            "height": height,
        }

    def prepare_creative_studio_i2v(
        self,
        prompt: str,
        *,
        first_frame_url: str,
        last_frame_url: str | None = None,
        duration: int = 5,
    ) -> dict[str, Any]:
        """校验 I2V 首尾帧、权限、积分和并发，不提交任务。"""
        normalized_prompt = self._creative_studio_prompt(prompt)
        self._creative_studio_generation_options(
            duration=duration,
            enhance_prompt=False,
        )
        first_frame = self._creative_studio_image_url(first_frame_url)
        last_frame = (
            self._creative_studio_image_url(last_frame_url)
            if last_frame_url is not None
            else ""
        )
        status = self.get_creative_studio_status()
        credits = status["credits"]
        balance = int(credits["credits"])
        concurrent = status["generating_tasks"]
        maximum = int(
            status["generation_limits"].get(
                _CREATIVE_STUDIO_I2V_SUB_APP,
                0,
            )
        )
        blockers: list[str] = []
        if not status["i2v_ready"]:
            blockers.append("permission_missing")
        if not credits["is_unlimited"] and balance < duration:
            blockers.append("insufficient_credits")
        if maximum <= 0 or concurrent >= maximum:
            blockers.append("concurrency_limit")
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "browser_session": True,
            "mode": "first_last_frame" if last_frame else "first_frame",
            "model": "dreamina_seedance_2",
            "model_id": _CREATIVE_STUDIO_I2V_MODEL_ID,
            "sub_app": _CREATIVE_STUDIO_I2V_SUB_APP,
            "prompt": normalized_prompt,
            "duration": duration,
            "first_frame_url": first_frame,
            "last_frame_url": last_frame,
            "reference_count": 2 if last_frame else 1,
            "estimated_credits": duration,
            "ready": not blockers,
            "blockers": blockers,
            "credits": credits,
            "concurrency": {
                "active": concurrent,
                "maximum": maximum,
                "available": max(0, maximum - concurrent),
            },
            "permission": status["permissions"].get(
                _CREATIVE_STUDIO_I2V_SUB_APP,
                {},
            ),
        }

    def prepare_creative_studio_r2v(
        self,
        prompt: str,
        *,
        reference_vids: Sequence[str],
        duration: int = 5,
    ) -> dict[str, Any]:
        """校验 R2V 已有 Studio 视频参考及会话状态，不提交生成任务。"""
        normalized_prompt = self._creative_studio_prompt(prompt)
        self._creative_studio_generation_options(
            duration=duration,
            enhance_prompt=False,
        )
        if isinstance(reference_vids, (str, bytes)) or not isinstance(
            reference_vids,
            Sequence,
        ):
            raise TikTokInputError("reference_vids must be a sequence")
        normalized_vids = [
            self._creative_studio_asset_id(vid, name="reference_vid")
            for vid in reference_vids
        ]
        if not 1 <= len(normalized_vids) <= _CREATIVE_STUDIO_R2V_MAX_VIDEOS:
            raise TikTokInputError("reference_vids must contain between 1 and 3 videos")
        if len(set(normalized_vids)) != len(normalized_vids):
            raise TikTokInputError("reference_vids must not contain duplicates")

        references = [
            self.get_creative_studio_video_info(vid)
            for vid in normalized_vids
        ]
        durations = [float(reference["duration"]) for reference in references]
        if any(
            item < _CREATIVE_STUDIO_R2V_MIN_VIDEO_DURATION
            for item in durations
        ):
            raise TikTokInputError(
                "each reference video must be at least 2 seconds long"
            )
        total_duration = math.fsum(durations)
        if total_duration >= _CREATIVE_STUDIO_R2V_MAX_VIDEO_DURATION_SUM:
            raise TikTokInputError(
                "reference video durations must total less than 15.2 seconds"
            )

        status = self.get_creative_studio_status()
        credits = status["credits"]
        balance = int(credits["credits"])
        concurrent = status["generating_tasks"]
        maximum = int(
            status["generation_limits"].get(
                _CREATIVE_STUDIO_R2V_SUB_APP,
                0,
            )
        )
        permission = status["permissions"].get(
            _CREATIVE_STUDIO_R2V_SUB_APP,
            {},
        )
        blockers: list[str] = []
        if permission.get("entry_pass") is not True:
            blockers.append("r2v_entry_pass_missing")
        if not credits["is_unlimited"] and balance < duration:
            blockers.append("insufficient_credits")
        if maximum <= 0 or concurrent >= maximum:
            blockers.append("concurrency_limit")
        # 已恢复的是静态合同，提交和本机视频上传仍须有真实会话证据。
        blockers.append("r2v_submission_not_verified")
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "browser_session": True,
            "mode": "reference_video",
            "model": "dreamina_seedance_2",
            "model_id": _CREATIVE_STUDIO_R2V_MODEL_ID,
            "sub_app": _CREATIVE_STUDIO_R2V_SUB_APP,
            "prompt": normalized_prompt,
            "duration": duration,
            "references": [
                {
                    "vid": reference["vid"],
                    "duration": reference["duration"],
                    "poster_url": reference["poster_url"],
                    "video_url": reference["video_url"],
                }
                for reference in references
            ],
            "reference_count": len(references),
            "reference_duration_sum": total_duration,
            "reference_duration_exclusive_maximum": (
                _CREATIVE_STUDIO_R2V_MAX_VIDEO_DURATION_SUM
            ),
            "estimated_credits": duration,
            "estimated_credits_evidence": "t2v_i2v_duration_rate_only",
            "ready": False,
            "blockers": blockers,
            "credits": credits,
            "concurrency": {
                "active": concurrent,
                "maximum": maximum,
                "available": max(0, maximum - concurrent),
            },
            "permission": permission,
            "submission_verified": False,
        }

    def get_creative_studio_credit_ledger(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """查询 Symphony 积分流水。"""
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 100
        ):
            raise TikTokInputError("limit must be between 1 and 100")
        entries = [("pageSize", str(limit))]
        normalized_cursor = None
        if cursor is not None:
            normalized_cursor = str(cursor).strip()
            if (
                not normalized_cursor
                or len(normalized_cursor) > 1024
                or any(
                    character in normalized_cursor
                    for character in "\r\n\0"
                )
            ):
                raise TikTokInputError("cursor is invalid")
            entries.append(("cursor", normalized_cursor))
        payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_LEDGER_PATH,
            entries,
            _CREATIVE_STUDIO_REFERER,
        )
        ledger_entries = payload.get("entries")
        has_more = payload.get("has_more")
        next_cursor = payload.get("next_cursor")
        if (
            not isinstance(ledger_entries, list)
            or len(ledger_entries) > limit
            or not all(isinstance(item, Mapping) for item in ledger_entries)
            or not isinstance(has_more, bool)
            or not isinstance(next_cursor, str)
            or (has_more and not next_cursor)
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio credit ledger response is invalid"
            )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_LEDGER_PATH,
            "browser_session": True,
            "cursor": normalized_cursor,
            "limit": limit,
            "entries": ledger_entries,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    def get_creative_studio_history(
        self,
        *,
        offset: int = 0,
        limit: int = 30,
    ) -> dict[str, Any]:
        """查询 Seedance 历史任务，支持按 offset 恢复。"""
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or not 0 <= offset <= 100000
        ):
            raise TikTokInputError("offset must be between 0 and 100000")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 100
        ):
            raise TikTokInputError("limit must be between 1 and 100")
        payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_HISTORY_PATH,
            [("offset", str(offset)), ("limit", str(limit))],
            _CREATIVE_STUDIO_REFERER,
        )
        normalized = self._creative_studio_history_payload(
            payload,
            expected_offset=offset,
            expected_limit=limit,
        )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_HISTORY_PATH,
            "browser_session": True,
            **normalized,
        }

    def get_creative_studio_task_detail(self, draft_id: str) -> dict[str, Any]:
        """按 draft_id 查询可恢复的 Seedance 历史详情。"""
        normalized_draft_id = self._creative_studio_decimal_id(
            draft_id,
            name="draft_id",
        )
        payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_TASK_DETAIL_PATH,
            [("draftId", normalized_draft_id)],
            _CREATIVE_STUDIO_REFERER,
        )
        draft = self._creative_studio_draft_payload(
            payload,
            expected_draft_id=normalized_draft_id,
        )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_TASK_DETAIL_PATH,
            "browser_session": True,
            **draft,
        }

    def get_creative_studio_video_info(self, vid: str) -> dict[str, Any]:
        """查询 Seedance 成品视频地址、尺寸和码率。"""
        normalized_vid = self._creative_studio_asset_id(vid, name="vid")
        payload = self._creative_browser_fetch(
            _CREATIVE_STUDIO_VIDEO_INFO_PATH,
            [("vid", normalized_vid)],
            _CREATIVE_STUDIO_REFERER,
        )
        video = self._creative_studio_video_payload(
            payload,
            expected_vid=normalized_vid,
        )
        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_VIDEO_INFO_PATH,
            "browser_session": True,
            **video,
        }

    def download_creative_studio_video(
        self,
        vid: str,
        *,
        output_path: str | Path,
        definition: str | None = None,
    ) -> dict[str, Any]:
        """下载 Seedance 成品的指定清晰度，不覆盖已有文件。"""
        output = self._creative_studio_download_output_path(output_path)
        video = self.get_creative_studio_video_info(vid)
        variant = self._creative_studio_download_variant(video, definition)
        variant_format = str(variant.get("format") or "").strip().lower()
        if variant_format != "mp4":
            raise TikTokResponseError(
                "TikTok Creative Studio video variant is not an MP4 file"
            )

        request = Request(
            str(variant["url"]),
            headers={
                "Accept": "video/*,application/octet-stream;q=0.9,*/*;q=0.8",
                "Referer": _CREATIVE_STUDIO_REFERER,
                "User-Agent": self.user_agent,
            },
        )
        temporary: Path | None = None
        bytes_written = 0
        try:
            with urlopen(request, timeout=self.timeout) as response:
                self._creative_studio_download_response(response)
                prefix = response.read(16)
                if (
                    not isinstance(prefix, bytes)
                    or len(prefix) < 16
                    or prefix[4:8] != b"ftyp"
                ):
                    raise TikTokResponseError(
                        "TikTok Creative Studio download is not an MP4 file"
                    )

                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{output.name}.",
                    suffix=".part",
                    dir=output.parent,
                )
                temporary = Path(temporary_name)
                with os.fdopen(descriptor, "wb") as target:
                    target.write(prefix)
                    bytes_written = len(prefix)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        if not isinstance(chunk, bytes):
                            raise TikTokResponseError(
                                "TikTok Creative Studio download body is invalid"
                            )
                        target.write(chunk)
                        bytes_written += len(chunk)

                expected_size = self._creative_studio_download_content_length(
                    response
                )
                if expected_size is not None and bytes_written != expected_size:
                    raise TikTokResponseError(
                        "TikTok Creative Studio download size does not match Content-Length"
                    )

            try:
                os.link(temporary, output)
            except FileExistsError as exc:
                raise TikTokInputError(
                    f"output file already exists: {output}"
                ) from exc
            temporary.unlink()
            temporary = None
        except (HTTPError, URLError, OSError) as exc:
            raise TikTokResponseError(
                f"TikTok Creative Studio video download failed: {exc}"
            ) from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

        return {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web+python_http",
            "vid": video["vid"],
            "definition": self._creative_studio_variant_definition(variant),
            "format": variant_format,
            "width": variant["width"],
            "height": variant["height"],
            "output_path": str(output),
            "bytes": bytes_written,
        }

    def get_one_creator_filters(self) -> dict[str, Any]:
        """查询 TikTok One 达人广场的可用筛选项。"""
        payload = self._creative_browser_fetch(
            _TIKTOK_ONE_FILTERS_PATH,
            [],
            _TIKTOK_ONE_REFERER,
        )
        languages = payload.get("languages")
        regions = payload.get("allDataVDCRegions")
        default_region = payload.get("defaultDataVDCRegion")
        if (
            not isinstance(languages, list)
            or not languages
            or not all(isinstance(item, str) and item for item in languages)
            or not isinstance(regions, list)
            or not regions
            or not isinstance(default_region, int)
            or isinstance(default_region, bool)
        ):
            raise TikTokResponseError(
                "TikTok One creator filters response is invalid"
            )
        fields = {
            name: payload[name]
            for name in (
                "audienceEngagedFilterGroup",
                "audienceReachedFilterGroup",
                "audienceRegionIndustryList",
                "commercialReadinessOptions",
                "defaultRegion",
                "defaultRegionLabelInfoList",
                "followerRegions",
                "personaList",
                "recommendationTypeOptions",
                "regionPriceSegment",
                "regionToSubRegionList",
                "storeRegions",
                "vdcDefaultRegionList",
            )
            if name in payload
        }
        return {
            "source": "tiktok_one",
            "transport": "browser_web",
            "endpoint": _TIKTOK_ONE_FILTERS_PATH,
            "browser_session": True,
            "data_vdc_regions": regions,
            "default_data_vdc_region": default_region,
            "languages": languages,
            "filters": fields,
        }

    def get_one_creator_suggestions(
        self,
        keyword: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        """查询 TikTok One 达人搜索联想词。"""
        query = self._one_keyword(keyword, required=True)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 0 <= limit <= 100
        ):
            raise TikTokInputError("limit must be between 0 and 100")
        if limit == 0:
            words: list[str] = []
        else:
            payload = self._creative_browser_fetch(
                _TIKTOK_ONE_SUGGEST_PATH,
                [("query", query)],
                _TIKTOK_ONE_REFERER,
            )
            raw_words = payload.get("suggestedWords")
            if (
                not isinstance(raw_words, list)
                or not all(isinstance(item, str) and item for item in raw_words)
            ):
                raise TikTokResponseError(
                    "TikTok One creator suggestions response is invalid"
                )
            words = list(dict.fromkeys(raw_words))[:limit]
        return {
            "source": "tiktok_one",
            "transport": "browser_web",
            "endpoint": _TIKTOK_ONE_SUGGEST_PATH,
            "browser_session": True,
            "keyword": query,
            "available": len(words),
            "suggestions": words,
        }

    def search_one_creators(
        self,
        keyword: str = "",
        *,
        countries: str | Sequence[str] = (),
        languages: str | Sequence[str] = (),
        min_followers: int | None = None,
        max_followers: int | None = None,
        min_median_views: int | None = None,
        max_median_views: int | None = None,
        min_engagement_rate: float | None = None,
        max_engagement_rate: float | None = None,
        sort: str = "relevance",
        sort_direction: str = "descending",
        page: int = 1,
        limit: int = 24,
    ) -> dict[str, Any]:
        """搜索 TikTok One 达人，按固定上游页长自动翻页并去重。"""
        query = self._one_keyword(keyword)
        country_codes = self._creative_top_ads_values(
            countries,
            maximum_items=50,
            label="countries",
            validator=lambda value: re.fullmatch(r"[A-Z]{2}", value) is not None,
            transform=lambda value: value.upper(),
        )
        language_codes = self._creative_top_ads_values(
            languages,
            maximum_items=20,
            label="languages",
            validator=lambda value: (
                re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z]{2,8})?", value)
                is not None
            ),
        )
        integer_filters = {
            "minFansCnt": self._one_integer_filter(
                min_followers, "min_followers"
            ),
            "maxFansCnt": self._one_integer_filter(
                max_followers, "max_followers"
            ),
            "minMedianViews": self._one_integer_filter(
                min_median_views, "min_median_views"
            ),
            "maxMedianViews": self._one_integer_filter(
                max_median_views, "max_median_views"
            ),
        }
        engagement_filters = {
            "minEngagementRate": self._one_rate_filter(
                min_engagement_rate, "min_engagement_rate"
            ),
            "maxEngagementRate": self._one_rate_filter(
                max_engagement_rate, "max_engagement_rate"
            ),
        }
        for minimum, maximum, label in (
            (min_followers, max_followers, "followers"),
            (min_median_views, max_median_views, "median views"),
            (
                min_engagement_rate,
                max_engagement_rate,
                "engagement rate",
            ),
        ):
            if minimum is not None and maximum is not None and minimum > maximum:
                raise TikTokInputError(f"minimum {label} exceeds maximum")
        sort_name = str(sort).strip().lower().replace("-", "_")
        if sort_name not in _TIKTOK_ONE_SORT_FIELDS:
            raise TikTokInputError(
                "sort must be relevance, followers, average_views, engagement, "
                "median_views, price, recent_video_count, submission_rate, "
                "audience_relevance, or creator_value"
            )
        direction = str(sort_direction).strip().lower()
        if direction not in {"ascending", "descending"}:
            raise TikTokInputError(
                "sort_direction must be ascending or descending"
            )
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= 1000
        ):
            raise TikTokInputError("page must be between 1 and 1000")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 0 <= limit <= 200
        ):
            raise TikTokInputError("limit must be between 0 and 200")

        creators: list[dict[str, Any]] = []
        seen: set[str] = set()
        current_page = page
        pages_fetched = 0
        total_count = 0
        upstream_has_more = False
        while len(creators) < limit and current_page <= 1000:
            entries = [
                ("page", str(current_page)),
                ("limit", str(_TIKTOK_ONE_PAGE_SIZE)),
                ("query", query),
                ("sortField", str(_TIKTOK_ONE_SORT_FIELDS[sort_name])),
                ("sortType", "2" if direction == "descending" else "1"),
            ]
            if country_codes:
                entries.append(("countryCodeList", ",".join(country_codes)))
            if language_codes:
                entries.append(("languageList", ",".join(language_codes)))
            for name, value in {**integer_filters, **engagement_filters}.items():
                if value is not None:
                    entries.append((name, value))
            payload = self._creative_browser_fetch(
                _TIKTOK_ONE_SEARCH_PATH,
                entries,
                _TIKTOK_ONE_REFERER,
            )
            raw_creators = payload.get("creators")
            pagination = payload.get("pagination")
            if (
                not isinstance(raw_creators, list)
                or len(raw_creators) > _TIKTOK_ONE_PAGE_SIZE
                or not isinstance(pagination, Mapping)
            ):
                raise TikTokResponseError(
                    "TikTok One creator search response is invalid"
                )
            response_page = _integer(pagination.get("page"))
            response_limit = _integer(pagination.get("limit"))
            page_total = _integer(pagination.get("totalCount"))
            upstream_has_more = pagination.get("hasMore")
            if (
                response_page != current_page
                or response_limit != _TIKTOK_ONE_PAGE_SIZE
                or page_total < (current_page - 1) * _TIKTOK_ONE_PAGE_SIZE
                or not isinstance(upstream_has_more, bool)
            ):
                raise TikTokResponseError(
                    "TikTok One creator pagination response is invalid"
                )
            pages_fetched += 1
            total_count = max(total_count, page_total)
            for index, raw_creator in enumerate(raw_creators):
                creator = self._normalize_one_creator(raw_creator, index)
                creator_id = creator["creator_id"]
                if creator_id in seen:
                    continue
                seen.add(creator_id)
                creators.append(creator)
                if len(creators) >= limit:
                    break
            if not upstream_has_more:
                break
            current_page += 1
        return {
            "source": "tiktok_one",
            "transport": "browser_web",
            "endpoint": _TIKTOK_ONE_SEARCH_PATH,
            "browser_session": True,
            "keyword": query,
            "countries": country_codes,
            "languages": language_codes,
            "filters": {
                "min_followers": min_followers,
                "max_followers": max_followers,
                "min_median_views": min_median_views,
                "max_median_views": max_median_views,
                "min_engagement_rate": min_engagement_rate,
                "max_engagement_rate": max_engagement_rate,
            },
            "sort": sort_name,
            "sort_direction": direction,
            "start_page": page,
            "pages_fetched": pages_fetched,
            "upstream_page_size": _TIKTOK_ONE_PAGE_SIZE,
            "requested_limit": limit,
            "available": len(creators),
            "total_count": total_count,
            "has_more": upstream_has_more,
            "creators": creators,
        }

    def create_creative_studio_video(
        self,
        prompt: str,
        *,
        duration: int = 5,
        enhance_prompt: bool = False,
        wait: bool = False,
        wait_timeout: float = 900,
        poll_interval: float = 5,
    ) -> dict[str, Any]:
        """使用 Dreamina Seedance 2.0 创建文生视频任务。"""
        preflight = self.prepare_creative_studio_video(
            prompt,
            duration=duration,
            enhance_prompt=enhance_prompt,
        )
        return self._create_creative_studio_video_from_preflight(
            preflight,
            duration=duration,
            enhance_prompt=enhance_prompt,
            wait=wait,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )

    def create_creative_studio_i2v(
        self,
        prompt: str,
        *,
        first_frame_url: str,
        last_frame_url: str | None = None,
        duration: int = 5,
        wait: bool = False,
        wait_timeout: float = 900,
        poll_interval: float = 5,
    ) -> dict[str, Any]:
        """使用 Seedance 2.0 和一张或两张参考帧创建视频任务。"""
        preflight = self.prepare_creative_studio_i2v(
            prompt,
            first_frame_url=first_frame_url,
            last_frame_url=last_frame_url,
            duration=duration,
        )
        self._creative_studio_wait_options(
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )
        if not preflight["ready"]:
            raise TikTokResponseError(
                "Seedance I2V preflight blocked: "
                + ", ".join(preflight["blockers"])
            )
        entries = [
            ("prompt", preflight["prompt"]),
            ("duration", str(duration)),
            ("firstFrameUrl", preflight["first_frame_url"]),
        ]
        if preflight["last_frame_url"]:
            entries.append(
                ("lastFrameUrl", preflight["last_frame_url"])
            )
        task = self._creative_studio_task_payload(
            self._creative_browser_fetch(
                _CREATIVE_STUDIO_I2V_GENERATE_PATH,
                entries,
                _CREATIVE_STUDIO_REFERER,
            )
        )
        if wait and task["status"] == "processing":
            task = self._wait_creative_studio_task(
                task["task_id"],
                wait_timeout=wait_timeout,
                poll_interval=poll_interval,
                initial_task=task,
            )
        outputs = self._creative_studio_task_outputs(task)
        if wait and task["status"] == "succeeded" and not outputs:
            raise TikTokResponseError(
                "Seedance I2V task succeeded without a retrievable video output"
            )
        result = {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_I2V_GENERATE_PATH,
            "browser_session": True,
            "mode": preflight["mode"],
            "model": "dreamina_seedance_2",
            "model_id": _CREATIVE_STUDIO_I2V_MODEL_ID,
            "duration": duration,
            "references": {
                "first_frame_url": preflight["first_frame_url"],
                "last_frame_url": preflight["last_frame_url"],
                "count": preflight["reference_count"],
            },
            "preflight": {
                "ready": True,
                "estimated_credits": preflight["estimated_credits"],
                "concurrency": preflight["concurrency"],
                "permission": preflight["permission"],
            },
            **task,
            "submitted": True,
            "waited": wait,
            "finished": task["status"] in {"succeeded", "failed"},
            "output_available": bool(outputs),
            "outputs": outputs,
        }
        if task["status"] == "processing":
            result["resume_command"] = (
                "python -m reverse tiktok creative-studio-task "
                f"{task['task_id']} --wait --wait-timeout 3600"
            )
        return result

    def _create_creative_studio_video_from_preflight(
        self,
        preflight: Mapping[str, Any],
        *,
        duration: int,
        enhance_prompt: bool,
        wait: bool,
        wait_timeout: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        """复用已完成的预检提交任务，避免工作流重复读取四次状态。"""
        self._creative_studio_wait_options(
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )
        if not preflight["ready"]:
            raise TikTokResponseError(
                "Seedance preflight blocked: "
                + ", ".join(preflight["blockers"])
            )
        normalized_prompt = preflight["prompt"]
        credits_before = preflight["credits"]
        entries = [
            ("prompt", normalized_prompt),
            ("duration", str(duration)),
            ("enhancePrompt", "1" if enhance_prompt else "0"),
        ]
        task = self._creative_studio_task_payload(
            self._creative_browser_fetch(
                _CREATIVE_STUDIO_GENERATE_PATH,
                entries,
                _CREATIVE_STUDIO_REFERER,
            )
        )
        if wait and task["status"] == "processing":
            task = self._wait_creative_studio_task(
                task["task_id"],
                wait_timeout=wait_timeout,
                poll_interval=poll_interval,
                initial_task=task,
            )
        outputs = self._creative_studio_task_outputs(task)
        if wait and task["status"] == "succeeded" and not outputs:
            raise TikTokResponseError(
                "Seedance task succeeded without a retrievable video output"
            )
        credits_after = self._creative_studio_credits_payload(
            self._creative_browser_fetch(
                _CREATIVE_STUDIO_CREDITS_PATH,
                [],
                _CREATIVE_STUDIO_REFERER,
            )
        )
        before_value = int(credits_before["credits"])
        after_value = int(credits_after["credits"])
        result = {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_GENERATE_PATH,
            "browser_session": True,
            "mode": "text",
            "model": "dreamina_seedance_2",
            "model_id": _CREATIVE_STUDIO_MODEL_ID,
            "duration": duration,
            "enhance_prompt": enhance_prompt,
            "preflight": {
                "ready": True,
                "estimated_credits": preflight["estimated_credits"],
                "concurrency": preflight["concurrency"],
                "permission": preflight["permission"],
            },
            **task,
            "submitted": True,
            "waited": wait,
            "finished": task["status"] in {"succeeded", "failed"},
            "output_available": bool(outputs),
            "outputs": outputs,
            "credits": {
                "before": credits_before,
                "after": credits_after,
                "consumed": max(0, before_value - after_value),
            },
        }
        if task["status"] == "processing":
            result["resume_command"] = (
                "python -m reverse tiktok creative-studio-task "
                f"{task['task_id']} --wait --wait-timeout 3600"
            )
        return result

    def get_creative_studio_task(
        self,
        task_id: str,
        *,
        wait: bool = False,
        wait_timeout: float = 900,
        poll_interval: float = 5,
    ) -> dict[str, Any]:
        """查询 Seedance 任务，可按需轮询到终态。"""
        normalized_task_id = self._creative_studio_task_id(task_id)
        self._creative_studio_wait_options(
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )
        try:
            task = self._creative_studio_task_payload(
                self._creative_browser_fetch(
                    _CREATIVE_STUDIO_TASK_PATH,
                    [("taskId", normalized_task_id)],
                    _CREATIVE_STUDIO_REFERER,
                ),
                expected_task_id=normalized_task_id,
            )
        except TikTokResponseError:
            task = self._creative_studio_failed_task_from_history(
                normalized_task_id
            )
            if task is None:
                raise
        if wait and task["status"] == "processing":
            task = self._wait_creative_studio_task(
                normalized_task_id,
                wait_timeout=wait_timeout,
                poll_interval=poll_interval,
                initial_task=task,
            )
        outputs = self._creative_studio_task_outputs(task)
        result = {
            "source": "tiktok_symphony_creative_studio",
            "transport": "browser_web",
            "endpoint": _CREATIVE_STUDIO_TASK_PATH,
            "browser_session": True,
            "model": "dreamina_seedance_2",
            "model_id": _CREATIVE_STUDIO_MODEL_ID,
            **task,
            "finished": task["status"] in {"succeeded", "failed"},
            "output_available": bool(outputs),
            "outputs": outputs,
        }
        if task["status"] == "processing":
            result["resume_command"] = (
                "python -m reverse tiktok creative-studio-task "
                f"{task['task_id']} --wait --wait-timeout 3600"
            )
        return result

    def _wait_creative_studio_task(
        self,
        task_id: str,
        *,
        wait_timeout: float,
        poll_interval: float,
        initial_task: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + wait_timeout
        last_task = (
            dict(initial_task)
            if isinstance(initial_task, Mapping)
            else None
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_task is None:
                    raise TikTokResponseError(
                        f"Seedance task {task_id} polling did not start"
                    )
                return {**last_task, "wait_timeout_reached": True}
            try:
                task = self._creative_studio_task_payload(
                    self._creative_browser_fetch(
                        _CREATIVE_STUDIO_TASK_PATH,
                        [("taskId", task_id)],
                        _CREATIVE_STUDIO_REFERER,
                    ),
                    expected_task_id=task_id,
                )
            except TikTokResponseError as exc:
                recovered = self._creative_studio_failed_task_from_history(
                    task_id
                )
                if recovered is not None:
                    return recovered
                if last_task is None:
                    raise
                return {
                    **last_task,
                    "wait_interrupted": True,
                    "wait_error": str(exc),
                }
            last_task = task
            if task["status"] != "processing":
                return task
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {**task, "wait_timeout_reached": True}
            time.sleep(min(poll_interval, remaining))

    def _creative_studio_failed_task_from_history(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        """任务查询异常时，从历史记录恢复已确认的失败终态。"""
        try:
            history = self.get_creative_studio_history(limit=30)
        except TikTokResponseError:
            return None
        drafts = [
            draft
            for draft in history["drafts"]
            if draft.get("task_id") == task_id
        ]
        if not drafts or not any(
            draft.get("status") == "failed" for draft in drafts
        ):
            return None
        return {
            "task_id": task_id,
            "status": "failed",
            "poll_after_ms": 0,
            "drafts": drafts,
            "recovered_from": _CREATIVE_STUDIO_HISTORY_PATH,
        }

    @classmethod
    def _creative_studio_task_outputs(
        cls,
        task: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """从终态任务中提取可直接使用的成品视频。"""
        outputs: list[dict[str, Any]] = []
        drafts = task.get("drafts")
        if not isinstance(drafts, list):
            return outputs
        for draft in drafts:
            if (
                not isinstance(draft, Mapping)
                or draft.get("status") != "succeeded"
            ):
                continue
            video = draft.get("video")
            if not isinstance(video, Mapping):
                continue
            normalized_video = cls._creative_studio_video_payload(
                video,
                expected_vid=str(draft.get("vid") or ""),
            )
            outputs.append(
                {
                    "draft_id": str(draft.get("draft_id") or ""),
                    **normalized_video,
                }
            )
        return outputs

    @staticmethod
    def _creative_studio_prompt(value: str) -> str:
        prompt = str(value).strip()
        if (
            not prompt
            or len(prompt) > 5000
            or any(character in prompt for character in "\r\n\0")
        ):
            raise TikTokInputError(
                "prompt must be 1..5000 characters without control line breaks"
            )
        return prompt

    @staticmethod
    def _creative_studio_image_mime(name: str, data: bytes) -> str:
        filename = str(name).strip()
        if (
            not filename
            or len(filename) > 255
            or any(character in filename for character in "/\\\r\n\0")
        ):
            raise TikTokInputError("reference image has an invalid file name")
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if (
            len(data) >= 12
            and data.startswith(b"RIFF")
            and data[8:12] == b"WEBP"
        ):
            return "image/webp"
        raise TikTokInputError(
            "reference image must be PNG, JPEG, or WebP"
        )

    @staticmethod
    def _creative_studio_image_url(value: str | None) -> str:
        url = str(value or "").strip()
        if not url or len(url) > 2048 or any(
            character in url for character in "\r\n\0"
        ):
            raise TikTokInputError("reference image URL is invalid")
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.startswith("/")
            or not (
                hostname.endswith(".ibyteimg.com")
                or hostname.endswith(".tiktokcdn.com")
            )
        ):
            raise TikTokInputError(
                "reference image URL must be a TikTok Creative Studio asset"
            )
        return url

    @staticmethod
    def _creative_studio_generation_options(
        *,
        duration: int,
        enhance_prompt: bool,
    ) -> None:
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or not 4 <= duration <= 15
        ):
            raise TikTokInputError("duration must be between 4 and 15 seconds")
        if not isinstance(enhance_prompt, bool):
            raise TikTokInputError("enhance_prompt must be a boolean")

    @staticmethod
    def _creative_studio_decimal_id(value: str, *, name: str) -> str:
        identifier = str(value).strip()
        if re.fullmatch(r"[1-9][0-9]{0,31}", identifier) is None:
            raise TikTokInputError(f"{name} must be a decimal identifier")
        return identifier

    @staticmethod
    def _creative_studio_asset_id(value: str, *, name: str) -> str:
        identifier = str(value).strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", identifier) is None:
            raise TikTokInputError(f"{name} must be a valid asset identifier")
        return identifier

    @staticmethod
    def _creative_studio_download_output_path(value: str | Path) -> Path:
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise TikTokInputError("output_path must be a file path")
        output = Path(value).expanduser()
        if not output.name or output.name in {".", ".."}:
            raise TikTokInputError("output_path must be a file path")
        if not output.parent.is_dir():
            raise TikTokInputError(
                f"output directory does not exist: {output.parent}"
            )
        if output.exists() or output.is_symlink():
            raise TikTokInputError(f"output file already exists: {output}")
        return output

    @staticmethod
    def _creative_studio_variant_definition(
        variant: Mapping[str, Any],
    ) -> str:
        value = variant.get("definition")
        definition = value.strip().lower() if isinstance(value, str) else ""
        if (
            not definition
            or len(definition) > 64
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", definition)
            is None
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio video definition is invalid"
            )
        return definition

    @classmethod
    def _creative_studio_download_variant(
        cls,
        video: Mapping[str, Any],
        definition: str | None,
    ) -> dict[str, Any]:
        variants = video.get("variants")
        if not isinstance(variants, list) or not variants:
            raise TikTokResponseError(
                "TikTok Creative Studio video variants are invalid"
            )
        normalized_variants = [
            dict(item) for item in variants if isinstance(item, Mapping)
        ]
        if len(normalized_variants) != len(variants):
            raise TikTokResponseError(
                "TikTok Creative Studio video variants are invalid"
            )
        if definition is None:
            default_url = video.get("video_url")
            candidates = [
                item
                for item in normalized_variants
                if item.get("url") == default_url
            ]
            if len(candidates) != 1:
                raise TikTokResponseError(
                    "TikTok Creative Studio default video variant is invalid"
                )
            return candidates[0]

        if not isinstance(definition, str):
            raise TikTokInputError("definition must be a normalized value like 720p")
        requested_definition = definition.strip().lower()
        if (
            not requested_definition
            or len(requested_definition) > 64
            or re.fullmatch(
                r"[a-z0-9][a-z0-9._-]{0,63}",
                requested_definition,
            )
            is None
        ):
            raise TikTokInputError("definition must be a normalized value like 720p")
        candidates = [
            item
            for item in normalized_variants
            if cls._creative_studio_variant_definition(item)
            == requested_definition
        ]
        if not candidates:
            raise TikTokInputError(
                f"definition is not available for this video: {requested_definition}"
            )
        if len(candidates) != 1:
            raise TikTokResponseError(
                "TikTok Creative Studio video definition is ambiguous"
            )
        return candidates[0]

    @staticmethod
    def _creative_studio_download_header(response: Any, name: str) -> str:
        headers = getattr(response, "headers", None)
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return ""
        value = getter(name)
        if value is None:
            value = getter(name.lower())
        return str(value).strip() if value is not None else ""

    @classmethod
    def _creative_studio_download_content_length(
        cls,
        response: Any,
    ) -> int | None:
        value = cls._creative_studio_download_header(
            response,
            "Content-Length",
        )
        if not value:
            return None
        if re.fullmatch(r"[1-9][0-9]{0,19}", value) is None:
            raise TikTokResponseError(
                "TikTok Creative Studio download Content-Length is invalid"
            )
        return int(value)

    @classmethod
    def _creative_studio_download_response(cls, response: Any) -> None:
        status = getattr(response, "status", None)
        if status is None:
            getcode = getattr(response, "getcode", None)
            status = getcode() if callable(getcode) else None
        if status not in (None, 200):
            raise TikTokResponseError(
                f"TikTok Creative Studio download returned HTTP {status}"
            )
        content_type = cls._creative_studio_download_header(
            response,
            "Content-Type",
        ).split(";", 1)[0].strip().lower()
        if content_type and not (
            content_type.startswith("video/")
            or content_type in {"application/octet-stream", "binary/octet-stream"}
        ):
            raise TikTokResponseError(
                f"TikTok Creative Studio download has invalid Content-Type: {content_type}"
            )

    @staticmethod
    def _creative_studio_task_id(value: str) -> str:
        return TikTokClient._creative_studio_decimal_id(
            value,
            name="task_id",
        )

    @staticmethod
    def _creative_studio_wait_options(
        *,
        wait_timeout: float,
        poll_interval: float,
    ) -> None:
        for name, value, minimum, maximum in (
            ("wait_timeout", wait_timeout, 1, 3600),
            ("poll_interval", poll_interval, 1, 60),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not minimum <= float(value) <= maximum
            ):
                raise TikTokInputError(
                    f"{name} must be between {minimum} and {maximum} seconds"
                )

    @staticmethod
    def _creative_studio_credits_payload(
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in ("credits", "bonus", "weekly_spent"):
            value = payload.get(name)
            if (
                not isinstance(value, str)
                or re.fullmatch(r"(?:0|[1-9][0-9]{0,31})", value) is None
            ):
                raise TikTokResponseError(
                    "TikTok Creative Studio credits response is invalid"
                )
            result[name] = value
        tier = payload.get("tier")
        unlimited = payload.get("is_unlimited")
        if (
            not isinstance(tier, int)
            or isinstance(tier, bool)
            or tier < 0
            or not isinstance(unlimited, bool)
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio credits response is invalid"
            )
        result["tier"] = tier
        result["is_unlimited"] = unlimited
        return result

    @classmethod
    def _creative_studio_video_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_vid: str = "",
    ) -> dict[str, Any]:
        vid = payload.get("vid")
        duration = payload.get("duration")
        poster_url = payload.get("poster_url")
        video_url = payload.get("video_url")
        variants = payload.get("variants")
        if (
            not isinstance(vid, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", vid) is None
            or (expected_vid and vid != expected_vid)
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or duration <= 0
            or not isinstance(poster_url, str)
            or not poster_url.startswith("https://")
            or not isinstance(video_url, str)
            or not video_url.startswith("https://")
            or not isinstance(variants, list)
            or not variants
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio video response is invalid"
            )
        for variant in variants:
            if (
                not isinstance(variant, Mapping)
                or not isinstance(variant.get("url"), str)
                or not variant["url"].startswith("https://")
                or not isinstance(variant.get("width"), int)
                or isinstance(variant.get("width"), bool)
                or variant["width"] <= 0
                or not isinstance(variant.get("height"), int)
                or isinstance(variant.get("height"), bool)
                or variant["height"] <= 0
            ):
                raise TikTokResponseError(
                    "TikTok Creative Studio video variant is invalid"
                )
        return {
            "vid": vid,
            "duration": duration,
            "poster_url": poster_url,
            "video_url": video_url,
            "variants": variants,
        }

    @classmethod
    def _creative_studio_draft_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_draft_id: str = "",
    ) -> dict[str, Any]:
        task_id = payload.get("task_id")
        draft_id = payload.get("draft_id")
        status = payload.get("status")
        draft_status = payload.get("draft_status")
        render_status = payload.get("render_status")
        vid = payload.get("vid")
        watermark_vid = payload.get("watermark_vid")
        if (
            not isinstance(task_id, str)
            or re.fullmatch(r"[1-9][0-9]{0,31}", task_id) is None
            or not isinstance(draft_id, str)
            or re.fullmatch(r"[1-9][0-9]{0,31}", draft_id) is None
            or (expected_draft_id and draft_id != expected_draft_id)
            or status not in {"processing", "succeeded", "failed"}
            or not isinstance(draft_status, int)
            or isinstance(draft_status, bool)
            or not isinstance(render_status, int)
            or isinstance(render_status, bool)
            or not isinstance(vid, str)
            or not isinstance(watermark_vid, str)
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio draft response is invalid"
            )
        result = dict(payload)
        video = payload.get("video")
        if video is not None:
            if not isinstance(video, Mapping):
                raise TikTokResponseError(
                    "TikTok Creative Studio draft video is invalid"
                )
            result["video"] = cls._creative_studio_video_payload(
                video,
                expected_vid=vid,
            )
        return result

    @classmethod
    def _creative_studio_history_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_offset: int,
        expected_limit: int,
    ) -> dict[str, Any]:
        offset = payload.get("offset")
        limit = payload.get("limit")
        total = payload.get("total")
        has_more = payload.get("has_more")
        next_offset = payload.get("next_offset")
        drafts = payload.get("drafts")
        if (
            offset != expected_offset
            or limit != expected_limit
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
            or not isinstance(has_more, bool)
            or not isinstance(next_offset, int)
            or isinstance(next_offset, bool)
            or next_offset < offset
            or not isinstance(drafts, list)
            or len(drafts) > limit
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio history response is invalid"
            )
        normalized_drafts = [
            cls._creative_studio_draft_payload(item)
            if isinstance(item, Mapping)
            else None
            for item in drafts
        ]
        if any(item is None for item in normalized_drafts):
            raise TikTokResponseError(
                "TikTok Creative Studio history draft is invalid"
            )
        return {
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": has_more,
            "next_offset": next_offset,
            "drafts": normalized_drafts,
        }

    @classmethod
    def _creative_studio_task_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_task_id: str = "",
    ) -> dict[str, Any]:
        task_id = str(payload.get("task_id", ""))
        if re.fullmatch(r"[1-9][0-9]{0,31}", task_id) is None:
            raise TikTokResponseError(
                "TikTok Creative Studio task response has an invalid task_id"
            )
        if expected_task_id and task_id != expected_task_id:
            raise TikTokResponseError(
                "TikTok Creative Studio task response has a mismatched task_id"
            )
        status = payload.get("status")
        poll_after_ms = payload.get("poll_after_ms")
        drafts = payload.get("drafts")
        if (
            status not in {"processing", "succeeded", "failed"}
            or not isinstance(poll_after_ms, int)
            or isinstance(poll_after_ms, bool)
            or poll_after_ms < 0
            or not isinstance(drafts, list)
            or not drafts
        ):
            raise TikTokResponseError(
                "TikTok Creative Studio task response is invalid"
            )
        for draft in drafts:
            if (
                not isinstance(draft, Mapping)
                or draft.get("task_id") != task_id
                or draft.get("status") not in {"processing", "succeeded", "failed"}
                or not isinstance(draft.get("draft_status"), int)
                or not isinstance(draft.get("render_status"), int)
            ):
                raise TikTokResponseError(
                    "TikTok Creative Studio draft response is invalid"
                )
        return {
            "task_id": task_id,
            "status": status,
            "poll_after_ms": poll_after_ms,
            "drafts": drafts,
        }

    def _creative_browser_fetch(
        self,
        path: str,
        entries: Sequence[tuple[str, str]],
        referer: str,
    ) -> Mapping[str, Any]:
        if self.creative_fetch is None:
            raise TikTokInputError(
                "TikTok commercial endpoints require the Chrome browser bridge"
            )
        payload = self.creative_fetch(path, entries, referer)
        if not isinstance(payload, Mapping):
            raise TikTokResponseError(
                "TikTok commercial browser response is not an object"
            )
        return payload

    @staticmethod
    def _ads_keyword_list(
        values: Sequence[str],
        *,
        maximum: int,
    ) -> list[str]:
        if isinstance(values, str):
            items = [values]
        elif isinstance(values, Sequence):
            items = list(values)
        else:
            raise TikTokInputError("keywords must be a sequence")
        if not 1 <= len(items) <= maximum:
            raise TikTokInputError(
                f"keywords must contain between 1 and {maximum} items"
            )
        normalized: list[str] = []
        seen: set[str] = set()
        for value in items:
            keyword = str(value).strip().lower()
            if (
                not keyword
                or len(keyword) > 80
                or any(character in keyword for character in "\r\n\0")
            ):
                raise TikTokInputError("keyword is invalid")
            if keyword in seen:
                raise TikTokInputError("keywords must not contain duplicates")
            seen.add(keyword)
            normalized.append(keyword)
        return normalized

    @staticmethod
    def _ads_keyword_country(value: str) -> tuple[str, int]:
        country = str(value).strip().upper()
        country_id = _ADS_KEYWORD_COUNTRY_IDS.get(country)
        if country_id is None:
            supported = ", ".join(sorted(_ADS_KEYWORD_COUNTRY_IDS))
            raise TikTokInputError(
                f"country is not supported; choose one of: {supported}"
            )
        return country, country_id

    @staticmethod
    def _ads_keyword_competitions(values: Sequence[str]) -> set[int]:
        if isinstance(values, str):
            items = [values]
        else:
            items = list(values)
        if not items:
            raise TikTokInputError("competitions must not be empty")
        if len(items) != len(set(items)):
            raise TikTokInputError("competitions must not contain duplicates")
        try:
            return {_ADS_KEYWORD_COMPETITION[item] for item in items}
        except KeyError as exc:
            raise TikTokInputError(
                "competitions must contain limited, medium, or high"
            ) from exc

    @staticmethod
    def _ads_keyword_time_range(
        start_time: int | None,
        end_time: int | None,
    ) -> tuple[int, int]:
        if start_time is None and end_time is None:
            china_tz = timezone(timedelta(hours=8))
            now = datetime.fromtimestamp(time.time(), tz=china_tz)
            end_boundary = datetime(now.year, now.month, 1, tzinfo=china_tz)
            start_year = end_boundary.year - 1
            start_boundary = datetime(
                start_year,
                end_boundary.month,
                1,
                tzinfo=china_tz,
            )
            return int(start_boundary.timestamp()), int(end_boundary.timestamp()) - 1
        if start_time is None or end_time is None:
            raise TikTokInputError(
                "start_time and end_time must be provided together"
            )
        if (
            not isinstance(start_time, int)
            or isinstance(start_time, bool)
            or not isinstance(end_time, int)
            or isinstance(end_time, bool)
            or start_time <= 0
            or end_time <= start_time
            or end_time - start_time > 370 * 24 * 60 * 60
            or end_time > 4_102_444_800
        ):
            raise TikTokInputError("keyword time range is invalid")
        return start_time, end_time

    @staticmethod
    def _ads_keyword_number(value: Any, name: str) -> int | float:
        if isinstance(value, bool):
            raise TikTokResponseError(
                f"TikTok Ads keyword response has invalid {name}"
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TikTokResponseError(
                f"TikTok Ads keyword response has invalid {name}"
            ) from exc
        if not math.isfinite(number) or number < 0:
            raise TikTokResponseError(
                f"TikTok Ads keyword response has invalid {name}"
            )
        return int(number) if number.is_integer() else number

    @classmethod
    def _ads_keyword_range(
        cls,
        value: Any,
        name: str,
        *,
        allow_none: bool = False,
        minimum_key: str = "volumeMin",
        maximum_key: str = "volumeMax",
    ) -> dict[str, int | float] | None:
        if value is None and allow_none:
            return None
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                f"TikTok Ads keyword response has invalid {name}"
            )
        minimum = cls._ads_keyword_number(value.get(minimum_key), f"{name}.min")
        maximum = cls._ads_keyword_number(value.get(maximum_key), f"{name}.max")
        if minimum > maximum:
            raise TikTokResponseError(
                f"TikTok Ads keyword response has invalid {name}"
            )
        return {"min": minimum, "max": maximum}

    @classmethod
    def _normalize_ads_keyword_idea(
        cls,
        value: Any,
        index: int,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                f"TikTok Ads keyword idea {index} is not an object"
            )
        keyword = value.get("keyword")
        competition = value.get("competition")
        brand_option = value.get("brandOption")
        source_type = value.get("sourceType")
        match_type = value.get("matchType")
        language = value.get("language")
        if (
            not isinstance(keyword, str)
            or not keyword.strip()
            or len(keyword) > 80
            or competition not in {1, 2, 3}
            or brand_option not in {0, 1, 2}
            or not isinstance(source_type, int)
            or isinstance(source_type, bool)
            or source_type < 0
            or not isinstance(match_type, int)
            or isinstance(match_type, bool)
            or match_type not in {1, 2, 3}
            or language != "en"
        ):
            raise TikTokResponseError(
                f"TikTok Ads keyword idea {index} is invalid"
            )
        changes: dict[str, float | None] = {}
        for source_name, target_name in (
            ("threeMonthChange", "three_month"),
            ("yoyChange", "year_over_year"),
        ):
            raw = value.get(source_name)
            if raw is None:
                changes[target_name] = None
                continue
            if (
                not isinstance(raw, (int, float))
                or isinstance(raw, bool)
                or not math.isfinite(float(raw))
            ):
                raise TikTokResponseError(
                    f"TikTok Ads keyword idea {index} has invalid {source_name}"
                )
            changes[target_name] = float(raw)
        country_id = value.get("countryId")
        if country_id is not None and (
            not isinstance(country_id, int)
            or isinstance(country_id, bool)
            or country_id <= 0
        ):
            raise TikTokResponseError(
                f"TikTok Ads keyword idea {index} has invalid countryId"
            )
        return {
            "keyword": keyword,
            "search_volume": cls._ads_keyword_range(
                value.get("searchVol"),
                f"idea[{index}].searchVol",
            ),
            "change": changes,
            "trend": value.get("trend"),
            "competition": {
                "id": competition,
                "level": {
                    1: "limited",
                    2: "medium",
                    3: "high",
                }[competition],
            },
            "estimated_cpc": cls._ads_keyword_range(
                value.get("estimatedCpc"),
                f"idea[{index}].estimatedCpc",
                minimum_key="estimatedCpcLow",
                maximum_key="estimatedCpcHigh",
            ),
            "brand_option": brand_option,
            "source_type": source_type,
            "match_type": match_type,
            "language": language,
            "country_id": country_id,
        }

    @staticmethod
    def _one_keyword(value: str, *, required: bool = False) -> str:
        keyword = str(value).strip()
        if (
            (required and not keyword)
            or len(keyword) > 256
            or any(character in keyword for character in "\r\n\0")
        ):
            raise TikTokInputError("keyword is invalid")
        return keyword

    @staticmethod
    def _one_integer_filter(value: int | None, name: str) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 1_000_000_000
        ):
            raise TikTokInputError(f"{name} must be between 0 and 1000000000")
        return str(value)

    @staticmethod
    def _one_rate_filter(value: float | None, name: str) -> str | None:
        if value is None:
            return None
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
        ):
            raise TikTokInputError(f"{name} must be between 0 and 1")
        return f"{float(value):.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _normalize_one_creator(value: Any, index: int) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                f"TikTok One creator {index} is not an object"
            )
        creator_id = str(value.get("creator_id") or "")
        tiktok_uid = str(value.get("tiktok_uid") or "")
        metrics = value.get("metrics")
        rates = value.get("rates")
        recent_videos = value.get("recent_videos")
        if (
            re.fullmatch(r"[1-9][0-9]{0,31}", creator_id) is None
            or re.fullmatch(r"[1-9][0-9]{0,31}", tiktok_uid) is None
            or not isinstance(value.get("handle"), str)
            or not value["handle"]
            or not isinstance(value.get("nickname"), str)
            or not value["nickname"]
            or not isinstance(value.get("bio"), str)
            or not isinstance(value.get("region"), str)
            or not isinstance(value.get("avatar_url"), str)
            or urlsplit(value["avatar_url"]).scheme != "https"
            or not isinstance(value.get("banned"), bool)
            or not isinstance(metrics, Mapping)
            or not isinstance(rates, Mapping)
            or not isinstance(recent_videos, list)
        ):
            raise TikTokResponseError(
                f"TikTok One creator {index} is invalid"
            )
        for name in ("followers", "median_views"):
            metric = metrics.get(name)
            if (
                not isinstance(metric, (int, float))
                or isinstance(metric, bool)
                or metric < 0
            ):
                raise TikTokResponseError(
                    f"TikTok One creator {index} metrics are invalid"
                )
        engagement = metrics.get("engagement_rate")
        if (
            not isinstance(engagement, (int, float))
            or isinstance(engagement, bool)
            or not 0 <= engagement <= 1
        ):
            raise TikTokResponseError(
                f"TikTok One creator {index} metrics are invalid"
            )
        normalized_rates: dict[str, Any] = {}
        for name, rate in rates.items():
            if (
                name not in {"recommended", "starting", "regional_starting"}
                or not isinstance(rate, Mapping)
                or re.fullmatch(
                    r"(?:0|[1-9][0-9]{0,31})",
                    str(rate.get("amount_100k") or ""),
                )
                is None
                or not isinstance(rate.get("currency"), str)
                or not re.fullmatch(r"[A-Z]{3}", rate["currency"])
            ):
                raise TikTokResponseError(
                    f"TikTok One creator {index} rate is invalid"
                )
            amount_100k = str(rate["amount_100k"])
            normalized_rates[name] = {
                "amount": int(amount_100k) / 100_000,
                "amount_100k": amount_100k,
                "currency": rate["currency"],
            }
        profile_url = (
            "https://www.tiktok.com/@"
            f"{quote(value['handle'], safe='')}"
        )
        normalized_recent_videos: list[dict[str, Any]] = []
        for video_index, video in enumerate(recent_videos):
            if not isinstance(video, Mapping):
                raise TikTokResponseError(
                    "TikTok One creator "
                    f"{index} recent video {video_index} is invalid"
                )
            video_id = str(video.get("id") or "")
            if re.fullmatch(r"[1-9][0-9]{0,31}", video_id) is None:
                raise TikTokResponseError(
                    "TikTok One creator "
                    f"{index} recent video {video_index} is invalid"
                )
            normalized_video = dict(video)
            normalized_video["url"] = f"{profile_url}/video/{video_id}"
            normalized_recent_videos.append(normalized_video)

        result = dict(value)
        result["profile_url"] = profile_url
        result["recent_videos"] = normalized_recent_videos
        result["rates"] = normalized_rates
        return result

    @staticmethod
    def _creative_top_ads_values(
        value: str | Sequence[Any],
        *,
        maximum_items: int,
        label: str,
        validator: Callable[[str], bool],
        transform: Callable[[str], str] = lambda value: value,
    ) -> list[str]:
        raw_values: list[Any] = (
            value.split(",")
            if isinstance(value, str)
            else list(value)
        )
        result: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            item = transform(str(raw_value).strip())
            if not item:
                continue
            if not validator(item) or item in seen:
                raise TikTokInputError(f"{label} is invalid")
            seen.add(item)
            result.append(item)
        if len(result) > maximum_items:
            raise TikTokInputError(
                f"{label} accepts at most {maximum_items} values"
            )
        return result

    @staticmethod
    def _creative_safe_decimal(value: str) -> bool:
        return (
            re.fullmatch(r"[1-9][0-9]{0,15}", value) is not None
            and int(value) <= 9_007_199_254_740_991
        )

    @staticmethod
    def _creative_top_ads_order(value: str) -> str:
        normalized = str(value).strip().lower().replace("-", "_")
        aliases = {
            "": "for_you",
            "recommended": "for_you",
            "for_you": "for_you",
            "views": "impression",
            "video_views": "impression",
            "impression": "impression",
            "ctr": "ctr",
            "click_rate": "ctr",
            "likes": "like",
            "like": "like",
        }
        if normalized not in aliases:
            raise TikTokInputError(
                "order must be for_you, impression, ctr, or like"
            )
        return aliases[normalized]

    @staticmethod
    def _creative_top_ads_performance_order(value: str) -> tuple[str, int]:
        normalized = str(value).strip().lower().replace("-", "_")
        aliases = {
            "": ("video_views", 1),
            "views": ("video_views", 1),
            "video_view": ("video_views", 1),
            "video_views": ("video_views", 1),
            "ctr": ("click_rate", 2),
            "click_rate": ("click_rate", 2),
            "engagement": ("engagement_rate", 3),
            "engagement_rate": ("engagement_rate", 3),
            "completion": ("six_second_view_rate", 4),
            "6s": ("six_second_view_rate", 4),
            "six_second_view_rate": ("six_second_view_rate", 4),
        }
        if normalized not in aliases:
            raise TikTokInputError(
                "order must be views, ctr, engagement, or completion"
            )
        return aliases[normalized]

    @staticmethod
    def _creative_top_ads_performance_ad_format(
        value: int | str | None,
    ) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise TikTokInputError("ad_format is invalid")
        normalized = str(value).strip()
        if (
            not normalized.isascii()
            or not normalized.isdecimal()
            or normalized != str(int(normalized))
            or int(normalized) not in {1, 2, 3, 4, 99, 100}
        ):
            raise TikTokInputError("ad_format is invalid")
        return int(normalized)

    @staticmethod
    def _creative_top_ads_performance_integer(
        value: Any,
        *,
        field: str,
    ) -> int:
        if isinstance(value, bool):
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        if isinstance(value, int):
            result = value
        elif isinstance(value, str) and re.fullmatch(
            r"(?:0|[1-9][0-9]*)", value
        ):
            result = int(value)
        else:
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        if result < 0 or result > (1 << 63) - 1:
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        return result

    @staticmethod
    def _creative_top_ads_performance_number(
        value: Any,
        *,
        field: str,
    ) -> float:
        if isinstance(value, bool):
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        if isinstance(value, str):
            if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None:
                raise TikTokResponseError(
                    f"TikTok Top Ads performance {field} is invalid"
                )
            result = float(value)
        elif isinstance(value, (int, float)):
            result = float(value)
        else:
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        if not math.isfinite(result) or not 0 <= result <= (1 << 53):
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        return result

    @staticmethod
    def _creative_top_ads_performance_asset(
        value: Any,
        *,
        field: str,
        allow_empty: bool = False,
    ) -> str:
        if not isinstance(value, str) or len(value) > 16_384:
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        if allow_empty and not value:
            return ""
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            ) from exc
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise TikTokResponseError(
                f"TikTok Top Ads performance {field} is invalid"
            )
        return value

    @staticmethod
    def _normalize_creative_top_ads_performance(
        value: Any,
        index: int,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                f"TikTok Top Ads performance item {index} is not an object"
            )
        material_id = str(value.get("materialID") or "")
        video_info = value.get("videoInfo")
        if (
            re.fullmatch(r"[1-9][0-9]{0,31}", material_id) is None
            or not isinstance(video_info, Mapping)
        ):
            raise TikTokResponseError(
                f"TikTok Top Ads performance item {index} is invalid"
            )
        video_urls = video_info.get("video_url")
        if not isinstance(video_urls, Mapping):
            raise TikTokResponseError(
                f"TikTok Top Ads performance item {index} media is invalid"
            )
        media_url = TikTokClient._creative_top_ads_performance_asset(
            video_urls.get("720p"),
            field=f"item {index} video_url",
        )
        cover_url = TikTokClient._creative_top_ads_performance_asset(
            video_info.get("cover"),
            field=f"item {index} cover",
        )
        avif_cover_url = TikTokClient._creative_top_ads_performance_asset(
            video_info.get("coverAvif", ""),
            field=f"item {index} coverAvif",
            allow_empty=True,
        )
        raw_selling_points = value.get("sellingPointList")
        if (
            not isinstance(raw_selling_points, list)
            or len(raw_selling_points) > 100
        ):
            raise TikTokResponseError(
                f"TikTok Top Ads performance item {index} selling points are invalid"
            )
        selling_points: list[str] = []
        for point in raw_selling_points:
            if (
                not isinstance(point, str)
                or not point
                or point != point.strip()
                or len(point) > 1024
                or any(ord(character) < 32 or ord(character) == 127 for character in point)
                or point in selling_points
            ):
                raise TikTokResponseError(
                    f"TikTok Top Ads performance item {index} selling points are invalid"
                )
            selling_points.append(point)
        video: dict[str, Any] = {
            "media_url": media_url,
            "media_quality": "720p",
            "cover_url": cover_url,
            "preferred_cover": avif_cover_url or cover_url,
        }
        if avif_cover_url:
            video["avif_cover_url"] = avif_cover_url
        return {
            "id": material_id,
            "source_url": _CREATIVE_TOP_ADS_PERFORMANCE_REFERER,
            "selling_points": selling_points,
            "metrics": {
                "video_views": TikTokClient._creative_top_ads_performance_integer(
                    value.get("videoView"),
                    field=f"item {index} videoView",
                ),
                "click_rate": TikTokClient._creative_top_ads_performance_number(
                    value.get("clickRate"),
                    field=f"item {index} clickRate",
                ),
                "ctr_rank": TikTokClient._creative_top_ads_performance_number(
                    value.get("ctrRank"),
                    field=f"item {index} ctrRank",
                ),
                "engagement_rate": TikTokClient._creative_top_ads_performance_number(
                    value.get("engagementRate"),
                    field=f"item {index} engagementRate",
                ),
                "six_second_view_rank": TikTokClient._creative_top_ads_performance_number(
                    value.get("videoView6sRank"),
                    field=f"item {index} videoView6sRank",
                ),
            },
            "video": video,
        }

    @staticmethod
    def _creative_top_ads_material_id(value: str) -> str:
        material_id = str(value).strip()
        if re.fullmatch(r"[1-9][0-9]{0,31}", material_id) is None:
            raise TikTokInputError("material_id must be a decimal identifier")
        return material_id

    @staticmethod
    def _creative_top_ads_metrics(value: Sequence[str]) -> list[str]:
        if isinstance(value, (str, bytes, bytearray)):
            raw_metrics = [str(value)]
        else:
            raw_metrics = list(value)
        metrics: list[str] = []
        for raw_metric in raw_metrics:
            metric = str(raw_metric).strip().lower()
            if metric not in _CREATIVE_TOP_ADS_KEYFRAME_METRICS:
                raise TikTokInputError("keyframe metric is invalid")
            if metric not in metrics:
                metrics.append(metric)
        if not metrics or len(metrics) > len(_CREATIVE_TOP_ADS_KEYFRAME_METRICS):
            raise TikTokInputError("at least one keyframe metric is required")
        return metrics

    @staticmethod
    def _creative_top_ads_industry_id(value: Any) -> str:
        match = re.fullmatch(r"label_([1-9][0-9]{0,31})", str(value or ""))
        if match is None:
            raise TikTokResponseError(
                "TikTok Top Ads detail has an invalid industry key"
            )
        return match.group(1)

    @staticmethod
    def _normalize_creative_top_ad(
        value: Any,
        index: int,
        *,
        country: str,
        time_range: int,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                f"TikTok Top Ads item {index} is not an object"
            )
        material_id = str(value.get("id") or "")
        video_info = value.get("videoInfo")
        if (
            not material_id.isascii()
            or not material_id.isdecimal()
            or not isinstance(video_info, Mapping)
        ):
            raise TikTokResponseError(
                f"TikTok Top Ads item {index} is invalid"
            )
        video_urls = video_info.get("videoUrl")
        if (
            not isinstance(video_urls, Mapping)
            or not video_urls
            or not all(
                isinstance(name, str) and isinstance(url, str) and url
                for name, url in video_urls.items()
            )
            or not isinstance(video_info.get("cover"), str)
        ):
            raise TikTokResponseError(
                f"TikTok Top Ads item {index} media is invalid"
            )
        quality, media_url = max(
            video_urls.items(),
            key=lambda item: _integer(re.sub(r"\D", "", item[0])),
        )
        video = {
            "id": str(video_info.get("vid") or ""),
            "media_url": media_url,
            "media_quality": quality,
            "cover_url": video_info["cover"],
            "duration": video_info.get("duration"),
            "width": video_info.get("width"),
            "height": video_info.get("height"),
            "variants": dict(video_urls),
        }
        source_key = value.get("sourceKey")
        if isinstance(source_key, bool) or not isinstance(source_key, (int, str)):
            source_key = None
        return {
            "id": material_id,
            "creative_center_url": TikTokClient._creative_top_ads_detail_url(
                material_id,
                country=country,
                time_range=time_range,
            ),
            "title": str(value.get("adTitle") or ""),
            "brand_name": str(value.get("brandName") or ""),
            "industry_key": str(value.get("industryKey") or ""),
            "objective_key": str(value.get("objectiveKey") or ""),
            "landing_page": str(value.get("landingPage") or ""),
            "countries": list(value.get("countryCode") or []),
            "source_name": str(value.get("source") or ""),
            "source_key": source_key,
            "keywords": value.get("keywordList"),
            "pattern_labels": value.get("patternLabel"),
            "objectives": value.get("objectives"),
            "highlight_text": str(value.get("highlightText") or ""),
            "has_summary": value.get("hasSummary") is True,
            "metrics": {
                "cost_tier": value.get("cost"),
                "ctr": value.get("ctr"),
                "likes": value.get("like"),
                "comments": value.get("comment"),
                "shares": value.get("share"),
            },
            "video": video,
        }

    @staticmethod
    def _creative_top_ads_detail_url(
        material_id: str,
        *,
        country: str,
        time_range: int,
    ) -> str:
        query = urlencode(
            [("countryCode", country), ("period", str(time_range))],
            quote_via=quote,
            safe="",
        )
        return (
            f"{_CREATIVE_CENTER_BASE_URL}/business/creativecenter/topads/"
            f"{material_id}/pc/en?{query}"
        )

    @staticmethod
    def _creative_trending_video_detail_input_id(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise TikTokInputError("item_id must be a positive decimal identifier")
        identifier = str(value)
        if re.fullmatch(r"[1-9][0-9]{0,31}", identifier) is None:
            raise TikTokInputError("item_id must be a positive decimal identifier")
        return identifier

    @staticmethod
    def _creative_trending_video_detail_identifier(
        value: Any,
        *,
        field: str,
    ) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a positive decimal"
            )
        identifier = str(value)
        if re.fullmatch(r"[1-9][0-9]{0,31}", identifier) is None:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a positive decimal"
            )
        return identifier

    @staticmethod
    def _creative_trending_video_detail_nonnegative_integer(
        value: Any,
        *,
        field: str,
    ) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a non-negative integer"
            )
        if isinstance(value, int):
            result = value
        elif isinstance(value, str) and re.fullmatch(
            r"(?:0|[1-9][0-9]*)", value
        ):
            result = int(value)
        else:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a non-negative integer"
            )
        if result > (1 << 63) - 1:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a non-negative integer"
            )
        return result

    @staticmethod
    def _creative_trending_video_detail_nonnegative_number(
        value: Any,
        *,
        field: str,
    ) -> float:
        if value is None:
            return 0.0
        if isinstance(value, bool):
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a non-negative number"
            )
        if isinstance(value, str):
            if value != value.strip() or not value:
                raise TikTokResponseError(
                    f"TikTok Creative Center video detail {field} is not a non-negative number"
                )
            try:
                result = float(value)
            except ValueError as exc:
                raise TikTokResponseError(
                    f"TikTok Creative Center video detail {field} is not a non-negative number"
                ) from exc
        elif isinstance(value, (int, float)):
            result = float(value)
        else:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a non-negative number"
            )
        if not math.isfinite(result) or result < 0:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a non-negative number"
            )
        return result

    @staticmethod
    def _creative_trending_video_detail_text(
        value: Any,
        *,
        field: str,
        maximum_length: int,
        allow_text_whitespace: bool = False,
    ) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is invalid"
            )
        text = value.strip()
        if len(text) > maximum_length:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is too long"
            )
        for character in text:
            if unicodedata.category(character) != "Cc":
                continue
            if allow_text_whitespace and character in "\n\r\t":
                continue
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} contains a control character"
            )
        return text

    @staticmethod
    def _creative_trending_video_detail_handle(value: Any, *, field: str) -> str:
        handle = TikTokClient._creative_trending_video_detail_text(
            value,
            field=field,
            maximum_length=24,
        )
        if not handle:
            return ""
        if len(handle.encode("utf-8")) > 24 or re.fullmatch(
            r"[A-Za-z0-9._]+", handle
        ) is None:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a valid TikTok handle"
            )
        return handle

    @staticmethod
    def _creative_trending_video_detail_asset_url(
        value: Any,
        *,
        field: str,
    ) -> str:
        if value is None:
            return ""
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 4096
            or any(character in value for character in "\r\n\0")
        ):
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a valid URL"
            )
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} is not a valid URL"
            ) from exc
        hostname = (parsed.hostname or "").lower()
        allowed = any(
            hostname == suffix or hostname.endswith("." + suffix)
            for suffix in _CREATIVE_TRENDING_VIDEO_DETAIL_CDN_SUFFIXES
        )
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.fragment
            or not allowed
        ):
            raise TikTokResponseError(
                f"TikTok Creative Center video detail {field} must use an allowed TikTok CDN HTTPS URL"
            )
        return value

    @staticmethod
    def _creative_trending_video_detail_object(
        parent: Mapping[str, Any],
        name: str,
    ) -> Mapping[str, Any]:
        value = parent.get(name)
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                "TikTok Creative Center video detail entityInfo has no " + name
            )
        return value

    @staticmethod
    def _creative_trending_video_detail_covers(value: Any) -> list[dict[str, str]]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 20:
            raise TikTokResponseError(
                "TikTok Creative Center video detail coverURLList is invalid"
            )
        covers: list[dict[str, str]] = []
        for index, raw_cover in enumerate(value):
            if not isinstance(raw_cover, Mapping):
                raise TikTokResponseError(
                    f"TikTok Creative Center video detail cover {index} is not an object"
                )
            covers.append(
                {
                    "format": TikTokClient._creative_trending_video_detail_text(
                        raw_cover.get("format"),
                        field=f"entityInfo.itemInfo.coverURLList[{index}].format",
                        maximum_length=32,
                    ),
                    "url": TikTokClient._creative_trending_video_detail_asset_url(
                        raw_cover.get("imageUrl"),
                        field=(
                            "entityInfo.itemInfo.coverURLList["
                            f"{index}].imageUrl"
                        ),
                    ),
                }
            )
        return covers

    @staticmethod
    def _creative_trending_video_detail_comments(
        value: Any,
    ) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 100:
            raise TikTokResponseError(
                "TikTok Creative Center video detail commentInfos is invalid"
            )
        comments: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw_comment in enumerate(value):
            if not isinstance(raw_comment, Mapping):
                raise TikTokResponseError(
                    f"TikTok Creative Center video detail comment {index} is not an object"
                )
            comment_id = TikTokClient._creative_trending_video_detail_identifier(
                raw_comment.get("objectID"),
                field=f"entityInfo.commentInfos[{index}].objectID",
            )
            if comment_id in seen_ids:
                continue
            seen_ids.add(comment_id)
            comments.append(
                {
                    "id": comment_id,
                    "text": TikTokClient._creative_trending_video_detail_text(
                        raw_comment.get("text"),
                        field=f"entityInfo.commentInfos[{index}].text",
                        maximum_length=4096,
                        allow_text_whitespace=True,
                    ),
                    "created_at": TikTokClient._creative_trending_video_detail_nonnegative_integer(
                        raw_comment.get("createTime"),
                        field=f"entityInfo.commentInfos[{index}].createTime",
                    ),
                    "like_count": TikTokClient._creative_trending_video_detail_nonnegative_integer(
                        raw_comment.get("likeCnt"),
                        field=f"entityInfo.commentInfos[{index}].likeCnt",
                    ),
                    "user": {
                        "id": TikTokClient._creative_trending_video_detail_identifier(
                            raw_comment.get("userID"),
                            field=f"entityInfo.commentInfos[{index}].userID",
                        ),
                        "name": TikTokClient._creative_trending_video_detail_text(
                            raw_comment.get("userName"),
                            field=f"entityInfo.commentInfos[{index}].userName",
                            maximum_length=256,
                        ),
                        "avatar_url": TikTokClient._creative_trending_video_detail_asset_url(
                            raw_comment.get("userAvatarLink"),
                            field=(
                                "entityInfo.commentInfos["
                                f"{index}].userAvatarLink"
                            ),
                        ),
                    },
                }
            )
        return comments

    @staticmethod
    def _creative_trending_video_detail_metrics(
        value: Mapping[str, Any],
    ) -> dict[str, int | float]:
        integer_fields = {
            "video_views": "videoViews",
            "video_views_lifetime": "videoViewsLifeTime",
            "organic_video_views": "organicVideoViews",
            "organic_video_views_lifetime": "organicVideoViewsLifeTime",
        }
        number_fields = {
            "engagement_rate": "engagementRate",
            "engagement_rate_lifetime": "engagementRateLifeTime",
            "six_second_vtr": "sixSecondsVTR",
            "six_second_vtr_lifetime": "sixSecondsVTRLifeTime",
        }
        metrics: dict[str, int | float] = {}
        for output_name, upstream_name in integer_fields.items():
            metrics[output_name] = (
                TikTokClient._creative_trending_video_detail_nonnegative_integer(
                    value.get(upstream_name),
                    field=f"entityInfo.itemMetrics.{upstream_name}",
                )
            )
        for output_name, upstream_name in number_fields.items():
            metrics[output_name] = (
                TikTokClient._creative_trending_video_detail_nonnegative_number(
                    value.get(upstream_name),
                    field=f"entityInfo.itemMetrics.{upstream_name}",
                )
            )
        return metrics

    @staticmethod
    def _normalize_creative_trending_video_items(
        raw_items: Any,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_items, list):
            raise TikTokResponseError(
                "TikTok Creative Center video response does not contain entityInfos"
            )
        videos: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise TikTokResponseError(
                    f"TikTok Creative Center video item {index} is not an object"
                )
            item_info = raw_item.get("itemInfo")
            if not isinstance(item_info, Mapping):
                raise TikTokResponseError(
                    f"TikTok Creative Center video item {index} has no itemInfo"
                )
            identifier = str(item_info.get("itemID") or "").strip()
            if not identifier:
                raise TikTokResponseError(
                    f"TikTok Creative Center video item {index} has no itemID"
                )
            if identifier in seen_ids:
                continue
            seen_ids.add(identifier)
            author_info = raw_item.get("itemAuthorInfo")
            if not isinstance(author_info, Mapping):
                author_info = {}
            author_metrics = raw_item.get("itemAuthorMetrics")
            if not isinstance(author_metrics, Mapping):
                author_metrics = {}
            item_metrics = raw_item.get("itemMetrics")
            if not isinstance(item_metrics, Mapping):
                item_metrics = {}
            handle = str(author_info.get("handlerName") or "").strip()
            public_url = (
                f"https://www.tiktok.com/@{quote(handle, safe='')}"
                f"/video/{identifier}"
                if handle
                else ""
            )
            videos.append(
                {
                    "rank": len(videos) + 1,
                    "id": identifier,
                    "title": str(item_info.get("title") or "").strip(),
                    "url": public_url,
                    "cover_url": str(item_info.get("coverURL") or "").strip(),
                    "media_url": str(item_info.get("videoURL") or "").strip(),
                    "created_at": str(item_info.get("createTime") or "").strip(),
                    "content_type": max(0, _integer(item_info.get("contentType"))),
                    "author": {
                        "id": str(item_info.get("authorID") or "").strip(),
                        "creator_id": str(
                            item_info.get("creatorID") or ""
                        ).strip(),
                        "handle": handle,
                        "nickname": str(
                            author_info.get("nickName") or ""
                        ).strip(),
                        "avatar_url": str(
                            author_info.get("avatarURI") or ""
                        ).strip(),
                        "bio": str(author_info.get("bio") or "").strip(),
                        "followers": max(
                            0, _integer(author_metrics.get("followers"))
                        ),
                    },
                    "metrics": {
                        "video_views": max(
                            0, _integer(item_metrics.get("videoViews"))
                        ),
                        "organic_video_views": max(
                            0, _integer(item_metrics.get("organicVideoViews"))
                        ),
                        "engagement_rate": item_metrics.get("engagementRate"),
                        "six_second_vtr": item_metrics.get("sixSecondsVTR"),
                    },
                }
            )
            if len(videos) >= limit:
                break
        return videos

    @staticmethod
    def _creative_content_labels(
        value: str | Sequence[int | str] | None,
    ) -> list[str]:
        if value is None:
            return []
        raw_labels: Sequence[Any]
        if isinstance(value, str):
            if not value.strip():
                return []
            raw_labels = value.split(",")
        elif isinstance(value, Sequence) and not isinstance(
            value, (bytes, bytearray)
        ):
            raw_labels = value
        else:
            raise TikTokInputError(
                "content_label_ids must contain positive decimal ids"
            )
        labels: list[str] = []
        seen: set[str] = set()
        for raw_label in raw_labels:
            label = str(raw_label).strip()
            if re.fullmatch(r"[1-9][0-9]*", label) is None:
                raise TikTokInputError(
                    "content_label_ids must contain positive decimal ids"
                )
            label = str(int(label))
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
            if len(labels) > 20:
                raise TikTokInputError(
                    "content_label_ids accepts at most 20 ids"
                )
        return labels

    @staticmethod
    def _creative_trending_hashtag_inputs(
        *,
        country: str,
        time_range: int,
        industry_id: int | str | None,
        page: int,
        limit: int,
    ) -> tuple[str, int, int | None, int, int]:
        normalized_country = str(country).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", normalized_country) is None:
            raise TikTokInputError("country must be a two-letter ASCII country code")
        if time_range not in (7, 30, 90):
            raise TikTokInputError("time_range must be 7, 30, or 90")
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or not 1 <= page <= 1000
        ):
            raise TikTokInputError("page must be between 1 and 1000")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 100
        ):
            raise TikTokInputError("limit must be between 1 and 100")

        normalized_industry_id: int | None = None
        if industry_id is not None and str(industry_id).strip():
            try:
                normalized_industry_id = int(industry_id)
            except (TypeError, ValueError) as exc:
                raise TikTokInputError(
                    "industry_id must be a positive decimal integer"
                ) from exc
            if normalized_industry_id <= 0:
                raise TikTokInputError(
                    "industry_id must be a positive decimal integer"
                )
        return (
            normalized_country,
            time_range,
            normalized_industry_id,
            page,
            limit,
        )

    @staticmethod
    def _creative_center_origin(country: str) -> str:
        if country == "US":
            return "https://ads.us.tiktok.com"
        if country in _CREATIVE_CENTER_EU_COUNTRIES:
            return "https://ads-useast2a.tiktok.com"
        return _CREATIVE_CENTER_BASE_URL

    def _creative_center_get(
        self,
        base_url: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": _CREATIVE_CENTER_BASE_URL,
            "Referer": _CREATIVE_TRENDING_VIDEOS_REFERER,
        }
        last_error: TikTokResponseError | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_request_slot()
            try:
                response = self.session.get(
                    base_url + path,
                    headers=headers,
                    params=dict(params or {}),
                    timeout=self.timeout,
                )
            except requests.RequestsError as exc:
                last_error = TikTokResponseError(
                    f"TikTok Creative Center video request failed: {exc}"
                )
            else:
                if response.status_code == 200:
                    try:
                        decoded = response.json()
                    except (requests.exceptions.JSONDecodeError, ValueError) as exc:
                        raise TikTokResponseError(
                            "TikTok Creative Center video response is not valid JSON"
                        ) from exc
                    if not isinstance(decoded, dict):
                        raise TikTokResponseError(
                            "TikTok Creative Center video response is not an object"
                        )
                    base_response = decoded.get("BaseResp")
                    if isinstance(base_response, Mapping):
                        status = _integer(base_response.get("StatusCode"))
                        if status:
                            message = str(
                                base_response.get("StatusMessage")
                                or "unknown error"
                            )
                            raise TikTokResponseError(
                                "TikTok Creative Center API status "
                                f"{status}: {message}"
                            )
                    return decoded
                last_error = TikTokResponseError(
                    "TikTok Creative Center returned HTTP "
                    f"{response.status_code} for {path}"
                )
                if response.status_code != 429 and response.status_code < 500:
                    raise last_error
            if attempt >= self.retries:
                break
            time.sleep(0.4 * (2**attempt))
        raise last_error or TikTokResponseError(
            "TikTok Creative Center video request failed"
        )

    def get_tag(self, tag_name: str) -> dict[str, Any]:
        name = self._tag_name(tag_name)
        referer = f"https://www.tiktok.com/tag/{quote(name, safe='')}"
        self._ensure_ms_token()
        payload = self._signed_get(
            "/api/challenge/detail/",
            self._common_params() + [("challengeName", name)],
            referer=referer,
        )
        return self._normalize_tag(payload, expected_name=name)

    def get_tag_videos(
        self,
        tag_id: str,
        *,
        limit: int | None = 30,
        page_size: int = 30,
    ) -> dict[str, Any]:
        identifier = self._numeric_id(tag_id, "tag id")
        result = self._collect_video_list(
            path="/api/challenge/item_list/",
            id_param="challengeID",
            id_value=identifier,
            id_field="tag_id",
            label="tag video",
            referer="https://www.tiktok.com/tag/_",
            limit=limit,
            page_size=page_size,
            maximum_page_size=30,
        )
        return result

    def get_music(self, music_id: str) -> dict[str, Any]:
        identifier = self._numeric_id(music_id, "music id")
        referer = f"https://www.tiktok.com/music/-{identifier}"
        self._ensure_ms_token()
        payload = self._signed_get(
            "/api/music/detail/",
            self._common_params() + [("musicId", identifier)],
            referer=referer,
        )
        return self._normalize_music(payload, expected_id=identifier)

    def get_music_videos(
        self,
        music_id: str,
        *,
        limit: int | None = 30,
        page_size: int = 30,
    ) -> dict[str, Any]:
        identifier = self._numeric_id(music_id, "music id")
        return self._collect_video_list(
            path="/api/music/item_list/",
            id_param="musicID",
            id_value=identifier,
            id_field="music_id",
            label="music video",
            referer=f"https://www.tiktok.com/music/-{identifier}",
            limit=limit,
            page_size=page_size,
            maximum_page_size=30,
        )

    def get_comments(
        self,
        video_url_or_id: str,
        *,
        include_replies: bool = False,
        reply_limit: int | None = None,
        reply_page_size: int = 20,
        limit: int | None = None,
        page_size: int = 20,
    ) -> dict[str, Any]:
        if limit is not None and limit < 0:
            raise TikTokInputError("limit must be non-negative")
        if reply_limit is not None and reply_limit < 0:
            raise TikTokInputError("reply_limit must be non-negative")
        video_id, referer = self._resolve_video(video_url_or_id)
        comments: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        cursor = "0"
        has_more = True
        seen_cursors: set[str] = set()

        while has_more and (limit is None or len(comments) < limit):
            self._ensure_ms_token()
            if cursor in seen_cursors:
                raise TikTokResponseError(f"comment pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            params = self._common_params() + [
                ("aweme_id", video_id),
                ("count", str(min(max(page_size, 1), 50))),
                ("cursor", cursor),
                ("current_region", self.region),
            ]
            payload = self._signed_get("/api/comment/list/", params, referer=referer)
            items = payload.get("comments") or []
            if not isinstance(items, list):
                raise TikTokResponseError("comment response comments is not a list")
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                comment_id = str(item.get("cid") or item.get("id") or "")
                if not comment_id or comment_id in seen_ids:
                    continue
                seen_ids.add(comment_id)
                normalized = self._normalize_comment(item)
                if include_replies and normalized["reply_count"]:
                    normalized["replies"] = self.get_comment_replies(
                        video_id,
                        comment_id,
                        limit=reply_limit,
                        page_size=reply_page_size,
                        referer=referer,
                    )["replies"]
                comments.append(normalized)
                if limit is not None and len(comments) >= limit:
                    break
            has_more = _boolean(payload.get("has_more", payload.get("hasMore", False)))
            next_cursor = str(payload.get("cursor", ""))
            if not has_more:
                cursor = next_cursor or cursor
                break
            if not next_cursor or next_cursor == cursor:
                raise TikTokResponseError("comment response did not advance its cursor")
            cursor = next_cursor

        return {
            "video_id": video_id,
            "total": len(comments),
            "cursor": cursor,
            "has_more": has_more,
            "comments": comments,
        }

    def get_comment_replies(
        self,
        video_id: str,
        comment_id: str,
        *,
        limit: int | None = None,
        page_size: int = 20,
        referer: str | None = None,
    ) -> dict[str, Any]:
        if limit is not None and limit < 0:
            raise TikTokInputError("limit must be non-negative")
        replies: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        cursor = "0"
        has_more = True
        seen_cursors: set[str] = set()
        resolved_referer = referer or f"https://www.tiktok.com/@_/video/{video_id}"

        while has_more and (limit is None or len(replies) < limit):
            self._ensure_ms_token()
            if cursor in seen_cursors:
                raise TikTokResponseError(f"reply pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            params = self._common_params() + [
                ("item_id", str(video_id)),
                ("comment_id", str(comment_id)),
                ("count", str(min(max(page_size, 20), 50))),
                ("cursor", cursor),
            ]
            payload = self._signed_get(
                "/api/comment/list/reply/",
                params,
                referer=resolved_referer,
            )
            items = payload.get("comments") or []
            if not isinstance(items, list):
                raise TikTokResponseError("reply response comments is not a list")
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                reply_id = str(item.get("cid") or item.get("id") or "")
                if not reply_id or reply_id in seen_ids:
                    continue
                seen_ids.add(reply_id)
                replies.append(self._normalize_comment(item))
                if limit is not None and len(replies) >= limit:
                    break
            has_more = _boolean(payload.get("has_more", payload.get("hasMore", False)))
            next_cursor = str(payload.get("cursor", ""))
            if not has_more:
                cursor = next_cursor or cursor
                break
            if not next_cursor or next_cursor == cursor:
                raise TikTokResponseError("reply response did not advance its cursor")
            cursor = next_cursor

        return {
            "video_id": str(video_id),
            "comment_id": str(comment_id),
            "total": len(replies),
            "cursor": cursor,
            "has_more": has_more,
            "replies": replies,
        }

    @staticmethod
    def _search_input(
        keyword: str,
        *,
        limit: int,
        offset: int,
        search_id: str,
    ) -> tuple[str, str, str]:
        if not isinstance(keyword, str) or not keyword.strip():
            raise TikTokInputError("keyword must not be empty")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 0
        ):
            raise TikTokInputError("limit must be non-negative")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
        ):
            raise TikTokInputError("offset must be non-negative")
        if not isinstance(search_id, str):
            raise TikTokInputError("search_id must be a string")
        return keyword.strip(), str(offset), search_id.strip()

    @staticmethod
    def _search_referer(query: str, *, category: str = "") -> str:
        path = f"/search/{category}" if category else "/search"
        return f"https://www.tiktok.com{path}?q={quote(query, safe='')}"

    @staticmethod
    def _empty_search_result(
        query: str,
        cursor: str,
        search_id: str,
        result_field: str,
        *,
        offset: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "keyword": query,
            "total": 0,
            "cursor": cursor,
            "search_id": search_id,
            "rid": "",
            "has_more": False,
            result_field: [],
        }
        if offset is not None:
            result["offset"] = offset
        return result

    def _collect_search_results(
        self,
        *,
        query: str,
        cursor: str,
        search_id: str,
        limit: int,
        page_size: int,
        path: str,
        referer: str,
        label: str,
        result_field: str,
        item_keys: tuple[str, ...],
        params_builder: Callable[
            [str, str, str, int],
            list[tuple[str, str]],
        ],
        normalizer: Callable[
            [Any, int],
            tuple[str, dict[str, Any]] | None,
        ],
        require_search_id: bool = False,
    ) -> dict[str, Any]:
        if limit == 0:
            return self._empty_search_result(
                query,
                cursor,
                search_id,
                result_field,
            )

        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        rid = ""
        has_more = True
        pages_without_new_results = 0

        while has_more and len(results) < limit:
            if cursor in seen_cursors:
                raise TikTokResponseError(
                    f"{label} pagination repeated cursor {cursor}"
                )
            seen_cursors.add(cursor)
            count = min(page_size, limit - len(results))
            payload = self._signed_get(
                path,
                self._common_params()
                + params_builder(query, cursor, search_id, count),
                referer=referer,
            )
            raw_items: Any = None
            found_items = False
            for key in item_keys:
                if key in payload:
                    raw_items = payload[key]
                    found_items = True
                    break
            if not found_items:
                raise TikTokResponseError(
                    f"{label} response does not contain {item_keys[0]}"
                )
            if not isinstance(raw_items, list):
                raise TikTokResponseError(
                    f"{label} response {item_keys[0]} is not a list"
                )

            before = len(results)
            for index, value in enumerate(raw_items):
                normalized = normalizer(value, index)
                if normalized is None:
                    continue
                identifier, item = normalized
                if identifier in seen_ids:
                    continue
                seen_ids.add(identifier)
                results.append(item)
                if len(results) >= limit:
                    break

            has_more = self._has_more(payload)
            if len(results) == before:
                pages_without_new_results += 1
            else:
                pages_without_new_results = 0
            if has_more and pages_without_new_results >= 3:
                raise TikTokResponseError(
                    f"{label} pagination produced three pages without new results"
                )

            next_cursor = self._response_token(
                payload.get("cursor"),
                f"{label} cursor",
            )
            page_search_id, page_rid = self._search_tokens(payload)
            if page_search_id:
                search_id = page_search_id
            if page_rid:
                rid = page_rid
            if not has_more:
                cursor = next_cursor or cursor
                break
            if not next_cursor or next_cursor == cursor:
                raise TikTokResponseError(
                    f"{label} response did not advance its cursor"
                )
            if require_search_id and not search_id:
                raise TikTokResponseError(
                    f"{label} response did not contain search_id or trace id"
                )
            cursor = next_cursor

        return {
            "keyword": query,
            "total": len(results),
            "cursor": cursor,
            "search_id": search_id,
            "rid": rid,
            "has_more": has_more,
            result_field: results,
        }

    @staticmethod
    def _user_search_params(
        query: str,
        cursor: str,
        search_id: str,
        _count: int,
    ) -> list[tuple[str, str]]:
        params = [
            ("cursor", cursor),
            ("from_page", "search"),
            ("keyword", query),
            ("web_search_code", _SEARCH_WEB_CODE),
        ]
        if search_id:
            params.append(("search_id", search_id))
        return params

    @staticmethod
    def _music_search_params(
        query: str,
        cursor: str,
        search_id: str,
        count: int,
    ) -> list[tuple[str, str]]:
        return [
            ("count", str(count)),
            ("cursor", cursor),
            ("from_page", "search"),
            ("keyword", query),
            ("offset", cursor),
            ("search_id", search_id),
            ("web_search_code", _SEARCH_WEB_CODE),
        ]

    def _live_search_params(
        self,
        query: str,
        cursor: str,
        search_id: str,
        count: int,
    ) -> list[tuple[str, str]]:
        return [
            ("client_ab_versions", self.client_ab_versions),
            ("count", str(count)),
            ("cursor", cursor),
            ("is_non_personalized_search", "0"),
            ("keyword", query),
            ("offset", cursor),
            ("search_id", search_id),
            ("web_search_code", _SEARCH_WEB_CODE),
        ]

    def _photo_search_params(
        self,
        query: str,
        cursor: str,
        search_id: str,
        count: int,
    ) -> list[tuple[str, str]]:
        return [
            ("client_ab_versions", self.client_ab_versions),
            ("count", str(count)),
            ("cursor", cursor),
            ("is_non_personalized_search", "0"),
            ("keyword", query),
            ("offset", cursor),
            ("search_id", search_id),
            ("web_search_code", _SEARCH_WEB_CODE),
        ]

    @staticmethod
    def _searched_user_object(item: Mapping[str, Any]) -> Mapping[str, Any]:
        value = _first_value(item, "userInfo", "user_info", "user")
        return value if isinstance(value, Mapping) else item

    @classmethod
    def _searched_user_id(cls, item: Mapping[str, Any]) -> str:
        user = cls._searched_user_object(item)
        return str(
            _first_value(
                user,
                "secUid",
                "sec_uid",
                "id",
                "uid",
                "userId",
                "user_id",
            )
            or ""
        )

    @classmethod
    def _normalize_searched_user(
        cls,
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        user = cls._searched_user_object(item)
        stats_value = _first_value(item, "stats", "statsV2", "stats_v2")
        if not isinstance(stats_value, Mapping):
            stats_value = _first_value(user, "stats", "statsV2", "stats_v2")
        stats = stats_value if isinstance(stats_value, Mapping) else {}
        verified = _boolean(
            _first_value(user, "verified", "isVerified", "is_verified")
        )
        if not verified:
            verified = bool(
                str(
                    _first_value(
                        user,
                        "customVerify",
                        "custom_verify",
                        "enterpriseVerifyReason",
                        "enterprise_verify_reason",
                    )
                    or ""
                )
            )

        def stat(*keys: str) -> int:
            value = _first_value(stats, *keys)
            if value is None:
                value = _first_value(user, *keys)
            return _integer(value)

        unique_id = str(
            _first_value(user, "uniqueId", "unique_id") or ""
        )
        return {
            "id": str(
                _first_value(user, "id", "uid", "userId", "user_id") or ""
            ),
            "sec_uid": str(
                _first_value(user, "secUid", "sec_uid") or ""
            ),
            "unique_id": unique_id,
            "profile_url": (
                f"https://www.tiktok.com/@{quote(unique_id, safe='')}"
                if unique_id
                else ""
            ),
            "profile_url_available": bool(unique_id),
            "nickname": str(user.get("nickname") or ""),
            "signature": str(user.get("signature") or ""),
            "verified": verified,
            "avatar": _first_url(
                _first_value(
                    user,
                    "avatarLarger",
                    "avatar_larger",
                    "avatarMedium",
                    "avatar_medium",
                    "avatarThumb",
                    "avatar_thumb",
                )
            ),
            "stats": {
                "followers": stat("followerCount", "follower_count"),
                "following": stat("followingCount", "following_count"),
                "likes": stat(
                    "heartCount",
                    "heart_count",
                    "diggCount",
                    "digg_count",
                ),
                "videos": stat("videoCount", "video_count"),
            },
        }

    @classmethod
    def _normalize_user_search_item(
        cls,
        value: Any,
        _index: int,
    ) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(value, Mapping):
            return None
        identifier = cls._searched_user_id(value)
        if not identifier:
            return None
        return identifier, cls._normalize_searched_user(value)

    @classmethod
    def _normalize_music_search_item(
        cls,
        value: Any,
        _index: int,
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError("music search result is not an object")
        music = _first_value(value, "musicInfo", "music_info")
        if not isinstance(music, Mapping):
            raise TikTokResponseError(
                "music search result does not contain music_info"
            )
        identifier = str(
            _first_value(music, "idStr", "id_str", "id", "mid") or ""
        )
        if not cls._positive_numeric_id(identifier):
            raise TikTokResponseError(
                "music search result has an invalid music id"
            )
        normalized = cls._normalize_music(
            {"music_info": music},
            expected_id=identifier,
        )
        return identifier, normalized

    @classmethod
    def _normalize_live_search_item(
        cls,
        value: Any,
        _index: int,
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError("live search result is not an object")
        info = _first_value(value, "live_info", "liveInfo")
        if not isinstance(info, Mapping):
            raise TikTokResponseError(
                "live search result does not contain live_info"
            )
        raw_room = cls._object_json(
            _first_value(info, "raw_data", "rawData", "rawdata")
        )
        if raw_room is None:
            raise TikTokResponseError(
                "live search result raw_data is not a JSON object"
            )
        room = cls._normalize_search_room(raw_room)
        identifier = str(room["id"])
        if not cls._positive_numeric_id(identifier):
            raise TikTokResponseError(
                "live search result has an invalid room id"
            )
        room_info = _first_value(info, "room_info", "roomInfo")
        if room_info is not None and not isinstance(room_info, Mapping):
            raise TikTokResponseError(
                "live search result room_info is not an object"
            )
        room_info = room_info if isinstance(room_info, Mapping) else {}
        room["has_commerce_goods"] = _boolean(
            _first_value(
                room_info,
                "hasCommerceGoods",
                "has_commerce_goods",
            )
        )
        room["is_battle"] = _boolean(
            _first_value(room_info, "isBattle", "is_battle")
        )
        return identifier, room

    @classmethod
    def _normalize_photo_search_item(
        cls,
        value: Any,
        index: int,
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                f"photo search item {index} is not an object"
            )
        nested = value.get("item")
        item = nested if isinstance(nested, Mapping) else value
        identifier = str(item.get("id") or item.get("aweme_id") or "")
        if not cls._positive_numeric_id(identifier):
            raise TikTokResponseError(
                f"photo search item {index} has an invalid photo id"
            )
        return identifier, cls._normalize_photo_post(item)

    @classmethod
    def _normalize_general_search_page(
        cls,
        query: str,
        limit: int,
        start_cursor: str,
        start_search_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise TikTokResponseError(
                "general search response data is not a list"
            )
        results: list[dict[str, Any]] = []
        for value in raw_items[:limit]:
            if not isinstance(value, Mapping):
                raise TikTokResponseError(
                    "general search result is not an object"
                )
            results.append(cls._normalize_general_search_card(value))

        has_more = cls._has_more(payload)
        cursor = cls._response_token(
            payload.get("cursor"),
            "general search cursor",
        ) or start_cursor
        search_id, rid = cls._search_tokens(payload)
        search_id = search_id or start_search_id
        if has_more and cursor == start_cursor:
            raise TikTokResponseError(
                "general search response did not advance its cursor"
            )
        if has_more and not search_id:
            raise TikTokResponseError(
                "general search response did not contain search_id or trace id"
            )
        return {
            "keyword": query,
            "total": len(results),
            "offset": start_cursor,
            "cursor": cursor,
            "search_id": search_id,
            "rid": rid,
            "has_more": has_more,
            "results": results,
        }

    @classmethod
    def _normalize_general_search_card(
        cls,
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        type_token = cls._response_token(
            item.get("type"),
            "general search result type",
        )
        try:
            type_code = int(type_token)
        except (TypeError, ValueError) as exc:
            raise TikTokResponseError(
                "general search result has an invalid type"
            ) from exc
        if type_code < 0:
            raise TikTokResponseError(
                "general search result has an invalid type"
            )
        type_names = {
            1: "video",
            4: "user",
            20: "user_live",
            61: "live",
            62: "single_live",
        }
        card: dict[str, Any] = {
            "type": type_names.get(type_code, "unknown"),
            "type_code": type_code,
        }
        common = item.get("common")
        if isinstance(common, Mapping):
            card["document_id"] = str(
                _first_value(common, "doc_id_str", "docId") or ""
            )
        if "view_more" in item:
            card["view_more"] = _boolean(item["view_more"])

        if type_code == 1:
            video = item.get("item")
            identifier = (
                str(_first_value(video, "id", "aweme_id") or "")
                if isinstance(video, Mapping)
                else ""
            )
            if not isinstance(video, Mapping) or not cls._positive_numeric_id(
                identifier
            ):
                raise TikTokResponseError(
                    "general search video result does not contain a valid item"
                )
            card["video"] = cls._normalize_video(video)
        elif type_code == 4:
            raw_users = item.get("user_list")
            if not isinstance(raw_users, list):
                raise TikTokResponseError(
                    "general search user result user_list is not a list"
                )
            users: list[dict[str, Any]] = []
            seen: set[str] = set()
            for value in raw_users:
                if not isinstance(value, Mapping):
                    raise TikTokResponseError(
                        "general search user result contains a non-object user"
                    )
                identifier = cls._searched_user_id(value)
                if not identifier:
                    raise TikTokResponseError(
                        "general search user result contains a user without an id"
                    )
                if identifier in seen:
                    continue
                seen.add(identifier)
                users.append(cls._normalize_searched_user(value))
            card["users"] = users
        elif type_code == 20:
            user_live = item.get("user_live")
            if not isinstance(user_live, Mapping):
                raise TikTokResponseError(
                    "general search user_live result is not an object"
                )
            user_info = user_live.get("user_info")
            if (
                not isinstance(user_info, Mapping)
                or not cls._searched_user_id(user_info)
            ):
                raise TikTokResponseError(
                    "general search user_live result does not contain a valid user"
                )
            card["user"] = cls._normalize_searched_user(user_info)
            room = cls._room_from_live_info(user_live.get("live_info"))
            if room is not None:
                card["room"] = room
        elif type_code == 61:
            collection = item.get("live_collection")
            raw_rooms = (
                collection.get("live_list")
                if isinstance(collection, Mapping)
                else None
            )
            if not isinstance(raw_rooms, list):
                raise TikTokResponseError(
                    "general search live result live_list is not a list"
                )
            rooms: list[dict[str, Any]] = []
            for value in raw_rooms:
                if not isinstance(value, Mapping):
                    raise TikTokResponseError(
                        "general search live result contains a non-object room"
                    )
                rooms.append(cls._normalize_search_room(value))
            card["rooms"] = rooms
        elif type_code == 62:
            single_live = item.get("single_live")
            aweme_info = (
                _first_value(single_live, "aweme_info", "awemeInfo")
                if isinstance(single_live, Mapping)
                else None
            )
            if not isinstance(aweme_info, Mapping):
                raise TikTokResponseError(
                    "general search single_live result does not contain aweme_info"
                )
            room = cls._object_json(
                _first_value(aweme_info, "rawdata", "raw_data")
            )
            if room is None:
                raise TikTokResponseError(
                    "general search single_live result has invalid rawdata"
                )
            card["room"] = cls._normalize_search_room(room)
        return card

    @staticmethod
    def _object_json(value: Any) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            return value
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, Mapping) else None

    @classmethod
    def _room_from_live_info(
        cls,
        value: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        room = cls._object_json(
            _first_value(value, "raw_data", "rawdata")
        )
        if room is None:
            candidate = _first_value(value, "room", "room_info")
            room = candidate if isinstance(candidate, Mapping) else None
        return cls._normalize_search_room(room) if room is not None else None

    @staticmethod
    def _normalize_search_room(
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        nested = _first_value(value, "data", "room")
        room = nested if isinstance(nested, Mapping) else value
        owner_value = _first_value(room, "owner", "user")
        owner = owner_value if isinstance(owner_value, Mapping) else {}
        stats_value = room.get("stats")
        stats = stats_value if isinstance(stats_value, Mapping) else {}
        return {
            "id": str(
                _first_value(room, "id_str", "id", "room_id") or ""
            ),
            "title": str(room.get("title") or ""),
            "status": _integer(room.get("status")),
            "start_time": _integer(
                _first_value(room, "start_time", "startTime")
            ),
            "viewer_count": _integer(
                _first_value(
                    room,
                    "user_count",
                    "viewer_count",
                    "total_user",
                )
            ),
            "stats": {
                "comments": _integer(
                    _first_value(stats, "comment_count", "commentCount")
                ),
                "shares": _integer(
                    _first_value(stats, "share_count", "shareCount")
                ),
            },
            "owner": {
                "id": str(
                    _first_value(owner, "id_str", "id", "uid") or ""
                ),
                "sec_uid": str(
                    _first_value(owner, "sec_uid", "secUid") or ""
                ),
                "unique_id": str(
                    _first_value(
                        owner,
                        "unique_id",
                        "uniqueId",
                        "display_id",
                        "displayId",
                    )
                    or ""
                ),
                "nickname": str(owner.get("nickname") or ""),
                "verified": _boolean(owner.get("verified")),
            },
        }

    @classmethod
    def _normalize_photo_post(
        cls,
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        identifier = str(item.get("id") or item.get("aweme_id") or "")
        image_post_value = _first_value(item, "imagePost", "image_post")
        if not isinstance(image_post_value, Mapping):
            raise TikTokResponseError(
                "photo post does not contain imagePost"
            )
        raw_images = _first_value(
            image_post_value,
            "images",
            "image_list",
        )
        if not isinstance(raw_images, list):
            raise TikTokResponseError("photo post images is not a list")
        if not raw_images:
            raise TikTokResponseError("photo post images is empty")
        images = [
            {
                "index": index,
                **cls._normalize_photo_image(value),
            }
            for index, value in enumerate(raw_images)
        ]
        cover_value = image_post_value.get("cover")
        cover = (
            cls._normalize_photo_image(cover_value)
            if cover_value is not None
            else None
        )
        share_cover_value = _first_value(
            image_post_value,
            "shareCover",
            "share_cover",
        )
        share_cover = (
            cls._normalize_photo_image(share_cover_value)
            if share_cover_value is not None
            else None
        )
        author_value = item.get("author")
        author = author_value if isinstance(author_value, Mapping) else {}
        stats_value = _first_value(item, "statsV2", "stats")
        stats = stats_value if isinstance(stats_value, Mapping) else {}
        username = str(
            _first_value(author, "uniqueId", "unique_id") or ""
        )
        description = str(
            _first_value(item, "desc", "description") or ""
        )
        image_title = str(image_post_value.get("title") or "")
        return {
            "id": identifier,
            "url": (
                f"https://www.tiktok.com/@{username or '_'}/photo/"
                f"{identifier}"
            ),
            "title": image_title or description,
            "description": description,
            "create_time": _integer(
                _first_value(item, "createTime", "create_time")
            ),
            "author": {
                "id": str(_first_value(author, "id", "uid") or ""),
                "sec_uid": str(
                    _first_value(author, "secUid", "sec_uid") or ""
                ),
                "unique_id": username,
                "nickname": str(author.get("nickname") or ""),
                "verified": _boolean(author.get("verified")),
            },
            "stats": {
                "likes": _integer(
                    _first_value(stats, "diggCount", "digg_count")
                ),
                "plays": _integer(
                    _first_value(stats, "playCount", "play_count")
                ),
                "comments": _integer(
                    _first_value(stats, "commentCount", "comment_count")
                ),
                "shares": _integer(
                    _first_value(stats, "shareCount", "share_count")
                ),
                "collects": _integer(
                    _first_value(stats, "collectCount", "collect_count")
                ),
            },
            "image_post": {
                "title": image_title,
                "image_count": len(images),
                "cover": cover,
                "share_cover": share_cover,
                "images": images,
            },
        }

    @classmethod
    def _normalize_photo_image(
        cls,
        value: Any,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TikTokResponseError(
                "image resource is not an object"
            )
        urls = cls._photo_image_urls(
            _first_value(value, "imageURL", "image_url")
        )
        if not urls:
            urls = cls._photo_image_urls(value)
        if not urls:
            raise TikTokResponseError(
                "image resource does not contain a URL"
            )
        width = _integer(
            _first_value(value, "imageWidth", "image_width", "width")
        )
        height = _integer(
            _first_value(value, "imageHeight", "image_height", "height")
        )
        if width < 0 or height < 0:
            raise TikTokResponseError(
                "image resource has invalid dimensions"
            )
        return {
            "url": urls[0],
            "urls": urls,
            "width": width,
            "height": height,
        }

    @staticmethod
    def _photo_image_urls(value: Any) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        def collect(candidate: Any) -> None:
            if isinstance(candidate, str):
                url = candidate.strip()
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
                return
            if isinstance(candidate, Sequence) and not isinstance(
                candidate,
                (str, bytes, bytearray),
            ):
                for item in candidate:
                    collect(item)
                return
            if isinstance(candidate, Mapping):
                for key in (
                    "urlList",
                    "UrlList",
                    "url_list",
                    "url",
                    "imageURL",
                    "image_url",
                ):
                    if key in candidate:
                        collect(candidate[key])

        collect(value)
        return urls

    @classmethod
    def _normalize_search_suggestions(
        cls,
        query: str,
        limit: int,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw_suggestions = payload.get("sug_list")
        if not isinstance(raw_suggestions, list):
            raise TikTokResponseError(
                "search suggest response sug_list is not a list"
            )
        suggestions: list[dict[str, Any]] = []
        for index, value in enumerate(raw_suggestions[:limit]):
            if not isinstance(value, Mapping):
                raise TikTokResponseError(
                    f"search suggest result {index} is not an object"
                )
            content = str(value.get("content") or "").strip()
            if not content:
                raise TikTokResponseError(
                    "search suggest result has empty content"
                )
            word_record = value.get("word_record")
            if not isinstance(word_record, Mapping):
                raise TikTokResponseError(
                    "search suggest result word_record is not an object"
                )
            position_token = cls._response_token(
                word_record.get("words_position"),
                "search suggest position",
            )
            try:
                position = int(position_token)
            except (TypeError, ValueError) as exc:
                raise TikTokResponseError(
                    "search suggest result has an invalid position"
                ) from exc
            if position < 0:
                raise TikTokResponseError(
                    "search suggest result has an invalid position"
                )
            group_id = cls._response_token(
                word_record.get("group_id"),
                "search suggest group id",
            )
            if not cls._positive_numeric_id(group_id):
                raise TikTokResponseError(
                    "search suggest result has an invalid group id"
                )
            extra_value = value.get("extra_info")
            extra = (
                extra_value
                if isinstance(extra_value, Mapping)
                else {}
            )
            suggestions.append(
                {
                    "text": content,
                    "type": str(value.get("sug_type") or ""),
                    "position": position,
                    "group_id": group_id,
                    "language": str(
                        word_record.get("words_lang")
                        or extra.get("lang")
                        or ""
                    ),
                    "user": cls._normalize_suggestion_user(extra),
                }
            )
        query_record = payload.get("words_query_record")
        query_record = (
            query_record if isinstance(query_record, Mapping) else {}
        )
        query_id = cls._response_token(
            query_record.get("query_id"),
            "search suggest query id",
        )
        search_id, rid = cls._search_tokens(payload)
        return {
            "keyword": query,
            "total": len(suggestions),
            "query_id": query_id,
            "rid": rid or search_id,
            "suggestions": suggestions,
        }

    @classmethod
    def _normalize_suggestion_user(
        cls,
        extra: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        user_id = str(extra.get("sug_user_id") or "")
        if not user_id:
            return None
        if not cls._positive_numeric_id(user_id):
            raise TikTokResponseError(
                "search suggest rich user has an invalid id"
            )
        sec_uid = str(extra.get("sug_sec_user_id") or "").strip()
        unique_id = str(
            _first_value(extra, "unique_id", "sug_uniq_id") or ""
        ).strip()
        if not sec_uid or not unique_id:
            raise TikTokResponseError(
                "search suggest rich user is missing identity fields"
            )
        return {
            "id": user_id,
            "sec_uid": sec_uid,
            "unique_id": unique_id,
            "nickname": str(
                _first_value(
                    extra,
                    "nickname",
                    "rich_sug_nickname",
                )
                or ""
            ),
            "verified": _boolean(extra.get("is_verified")),
            "avatar": _first_url(extra.get("rich_sug_avatar_uri")),
        }

    @staticmethod
    def _normalize_trending_search_words(
        requested_count: int,
        region: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw_words = payload.get("trending_search_words")
        if not isinstance(raw_words, list):
            raise TikTokResponseError(
                "trending search words response does not contain a word list"
            )
        if len(raw_words) > requested_count:
            raise TikTokResponseError(
                "trending search words response exceeds the requested count"
            )
        words: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, value in enumerate(raw_words):
            if not isinstance(value, Mapping):
                raise TikTokResponseError(
                    f"trending search words item {index} is not an object"
                )
            word = str(
                _first_value(
                    value,
                    "trendingSearchWord",
                    "trending_search_word",
                )
                or ""
            ).strip()
            if not word:
                raise TikTokResponseError(
                    f"trending search words item {index} has an empty word"
                )
            if word in seen:
                continue
            seen.add(word)
            words.append(
                {
                    "rank": len(words) + 1,
                    "word": word,
                    "type": str(
                        _first_value(
                            value,
                            "trendingSearchWordType",
                            "trending_search_word_type",
                        )
                        or ""
                    ),
                }
            )
        return {
            "source": "tiktok_web",
            "transport": "web_api",
            "endpoint": _TRENDING_SEARCH_WORDS_PATH,
            "region": region,
            "total": len(words),
            "words": words,
        }

    @staticmethod
    def _positive_numeric_id(value: str) -> bool:
        return bool(
            _ASCII_NUMERIC_ID_RE.fullmatch(value)
            and any(character != "0" for character in value)
        )

    def _collect_video_list(
        self,
        *,
        path: str,
        id_param: str,
        id_value: str,
        id_field: str,
        label: str,
        referer: str,
        limit: int | None,
        page_size: int,
        maximum_page_size: int,
    ) -> dict[str, Any]:
        self._validate_limit(limit)
        if limit == 0:
            return {
                id_field: id_value,
                "total": 0,
                "cursor": "0",
                "has_more": False,
                "videos": [],
            }

        videos: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor = "0"
        has_more = True
        while has_more and (limit is None or len(videos) < limit):
            if cursor in seen_cursors:
                raise TikTokResponseError(f"{label} pagination repeated cursor {cursor}")
            seen_cursors.add(cursor)
            self._ensure_ms_token()
            count = self._request_count_for_limit(
                page_size, maximum_page_size, limit, len(videos)
            )
            payload = self._signed_get(
                path,
                self._common_params()
                + [(id_param, id_value), ("count", str(count)), ("cursor", cursor)],
                referer=referer,
            )
            items = self._video_items(payload, label)
            self._append_videos(videos, seen_ids, items, limit)
            has_more = self._has_more(payload)
            next_cursor = self._response_token(payload.get("cursor"), f"{label} cursor")
            if not has_more:
                cursor = next_cursor or cursor
                break
            if not next_cursor or next_cursor == cursor:
                raise TikTokResponseError(f"{label} response did not advance its cursor")
            cursor = next_cursor

        return {
            id_field: id_value,
            "total": len(videos),
            "cursor": cursor,
            "has_more": has_more,
            "videos": videos,
        }

    @staticmethod
    def _video_items(payload: Mapping[str, Any], label: str) -> list[Any]:
        items = payload.get("itemList", payload.get("item_list", []))
        if not isinstance(items, list):
            raise TikTokResponseError(f"{label} response item list is not a list")
        return items

    def _append_videos(
        self,
        destination: list[dict[str, Any]],
        seen_ids: set[str],
        items: list[Any],
        limit: int | None,
    ) -> None:
        for value in items:
            if not isinstance(value, Mapping):
                continue
            item = value.get("item") if isinstance(value.get("item"), Mapping) else value
            video_id = str(item.get("id") or item.get("aweme_id") or "")
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            destination.append(self._normalize_video(item))
            if limit is not None and len(destination) >= limit:
                break

    @staticmethod
    def _has_more(payload: Mapping[str, Any]) -> bool:
        return _boolean(payload.get("hasMore", payload.get("has_more", False)))

    @staticmethod
    def _response_token(value: Any, label: str) -> str:
        if value is None:
            return ""
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise TikTokResponseError(f"{label} is not a scalar token")
        return str(value)

    @classmethod
    def _search_tokens(cls, payload: Mapping[str, Any]) -> tuple[str, str]:
        extra = payload.get("extra") if isinstance(payload.get("extra"), Mapping) else {}
        log_pb = payload.get("log_pb") if isinstance(payload.get("log_pb"), Mapping) else {}
        explicit = cls._response_token(payload.get("search_id"), "search_id")
        logid = cls._response_token(extra.get("logid"), "extra.logid")
        impr_id = cls._response_token(log_pb.get("impr_id"), "log_pb.impr_id")
        if logid and impr_id and logid != impr_id:
            raise TikTokResponseError("search response contains conflicting log identifiers")
        rid = cls._response_token(payload.get("rid"), "rid")
        return explicit or logid or impr_id or rid, rid

    @staticmethod
    def _request_count_for_limit(
        page_size: int,
        maximum: int,
        limit: int | None,
        collected: int,
    ) -> int:
        count = min(max(page_size, 1), maximum)
        if limit is not None:
            count = min(count, limit - collected)
        return count

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and limit < 0:
            raise TikTokInputError("limit must be non-negative")

    @staticmethod
    def _numeric_id(value: str, label: str) -> str:
        identifier = str(value).strip()
        if not _ASCII_NUMERIC_ID_RE.fullmatch(identifier) or not any(
            char != "0" for char in identifier
        ):
            raise TikTokInputError(f"{label} must be a positive numeric string")
        return identifier

    @staticmethod
    def _tag_name(value: str) -> str:
        name = str(value).strip().removeprefix("#").strip()
        if not name:
            raise TikTokInputError("tag name must not be empty")
        if "/" in name or "?" in name or "#" in name:
            raise TikTokInputError("tag name must not contain URL separators")
        return name

    def _public_get(
        self,
        path: str,
        params: list[tuple[str, str]],
        *,
        referer: str,
    ) -> dict[str, Any]:
        raw_query = urlencode(
            sorted(params, key=lambda item: item[0]),
            doseq=True,
            quote_via=quote,
            safe="",
        )
        url = f"https://www.tiktok.com{path}?{raw_query}"
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_request_slot()
            try:
                response = self.session.get(
                    url,
                    headers={"Referer": referer},
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.RequestsError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.4 * (2**attempt))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_error = TikTokResponseError(
                    f"TikTok returned HTTP {response.status_code} for {path}"
                )
                if attempt >= self.retries:
                    raise last_error
                delay = (
                    self._retry_delay(response, attempt)
                    if response.status_code == 429
                    else 0.4 * (2**attempt)
                )
                time.sleep(delay)
                continue
            if response.status_code != 200:
                raise TikTokResponseError(
                    f"TikTok returned HTTP {response.status_code} for {path}"
                )
            try:
                payload = response.json()
            except (requests.exceptions.JSONDecodeError, ValueError) as exc:
                raise TikTokResponseError(
                    f"TikTok returned a non-JSON response for {path}"
                ) from exc
            if not isinstance(payload, dict):
                raise TikTokResponseError(
                    f"TikTok returned a non-object JSON response for {path}"
                )
            if not _status_ok(payload):
                status = payload.get(
                    "statusCode",
                    payload.get("status_code"),
                )
                message = payload.get(
                    "statusMsg",
                    payload.get("status_msg", ""),
                )
                raise TikTokResponseError(
                    f"TikTok API status {status}: {message}"
                )
            return payload
        if isinstance(last_error, TikTokResponseError):
            raise last_error
        raise TikTokResponseError(
            f"request failed for {path}: {last_error}"
        ) from last_error

    def _signed_get(
        self,
        path: str,
        params: list[tuple[str, str]],
        *,
        referer: str,
    ) -> dict[str, Any]:
        self._ensure_ms_token()
        params = sorted(params, key=lambda item: item[0])
        raw_query = urlencode(params, doseq=True, quote_via=quote, safe="")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            # 签名前预留请求启动时机，避免签名材料过期。
            self._wait_for_request_slot()
            counters = {
                "txr": 24 + self._request_count,
                "tfr": 0,
                "ixr": 28 + self._request_count,
                "ifr": 0,
                "dynosaurIxr": 4,
            }
            signed = self.signer.sign(
                raw_query,
                user_agent=self.user_agent,
                ms_token=self.ms_token,
                counters=counters,
            )
            url = f"https://www.tiktok.com{path}?{signed['query']}"
            try:
                response = self.session.get(
                    url,
                    headers={"Referer": referer},
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.RequestsError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.4 * (2**attempt))
                continue
            self._request_count += 1
            self._refresh_ms_token(response)
            if urlsplit(str(response.url)).query != signed["query"]:
                raise TikTokResponseError("HTTP transport changed the signed query bytes")
            if response.status_code == 429 or response.status_code >= 500:
                last_error = TikTokResponseError(
                    f"TikTok returned HTTP {response.status_code} for {path}"
                )
                if attempt >= self.retries:
                    raise last_error
                delay = (
                    self._retry_delay(response, attempt)
                    if response.status_code == 429
                    else 0.4 * (2**attempt)
                )
                time.sleep(delay)
                continue
            if response.status_code != 200:
                raise TikTokResponseError(
                    f"TikTok returned HTTP {response.status_code} for {path}"
                )
            try:
                payload = response.json()
            except (requests.exceptions.JSONDecodeError, ValueError) as exc:
                raise TikTokResponseError(
                    f"TikTok returned a non-JSON response for {path}"
                ) from exc
            if not isinstance(payload, dict):
                raise TikTokResponseError(f"TikTok returned a non-object JSON response for {path}")
            if not _status_ok(payload):
                status = payload.get("statusCode", payload.get("status_code"))
                message = payload.get("statusMsg", payload.get("status_msg", ""))
                raise TikTokResponseError(f"TikTok API status {status}: {message}")
            return payload
        if isinstance(last_error, TikTokResponseError):
            raise last_error
        raise TikTokResponseError(f"request failed for {path}: {last_error}") from last_error

    def _common_params(self) -> list[tuple[str, str]]:
        params = [
            ("WebIdLastTime", str(self.web_id_last_time)),
            ("aid", "1988"),
            ("app_language", self.language),
            ("app_name", "tiktok_web"),
            ("browser_language", self._browser_language()),
            ("browser_name", "Mozilla"),
            ("browser_online", "true"),
            ("browser_platform", "MacIntel"),
            ("browser_version", self.user_agent.removeprefix("Mozilla/")),
            ("channel", "tiktok_web"),
            ("cookie_enabled", "true"),
            ("data_collection_enabled", "false"),
            ("device_id", self.device_id),
            ("device_platform", "web_pc"),
            ("focus_state", "true"),
            ("history_len", "2"),
            ("is_fullscreen", "false"),
            ("is_page_visible", "true"),
            ("language", self.language),
            ("odinId", self.odin_id),
            ("os", "mac"),
            ("priority_region", ""),
            ("referer", self.root_referer),
            ("region", self.region),
            ("root_referer", self.root_referer),
            ("screen_height", "900"),
            ("screen_width", "1440"),
            ("tz_name", "Asia/Shanghai"),
            ("user_is_login", "false"),
            ("webcast_language", self.language),
        ]
        if self.client_ab_versions:
            params.append(("clientABVersions", self.client_ab_versions))
        return params

    def _post_params(self, sec_uid: str, cursor: str, count: int) -> list[tuple[str, str]]:
        return self._common_params() + [
            ("count", str(count)),
            ("coverFormat", "2"),
            ("cursor", cursor),
            ("enable_cache", "false"),
            ("from_page", "user"),
            ("needPinnedItemIds", "true"),
            ("post_item_list_request_type", "0"),
            ("secUid", sec_uid),
            ("video_encoding", "dash"),
        ]

    def _refresh_ms_token(self, response: requests.Response) -> None:
        token = (
            response.headers.get("x-ms-token")
            or self._response_cookie(response, "msToken")
            or _cookie_value(self.session, "msToken", domain="tiktok.com")
            or _cookie_value(self.session, "msToken")
        )
        if token:
            self._set_ms_token(token)

    def _ensure_ms_token(self) -> None:
        if self._ms_token_ready:
            return
        self._ensure_identity()
        headers = {
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": "https://www.tiktok.com",
            "Referer": "https://www.tiktok.com/",
        }
        initial_token = self.ms_token
        if not initial_token:
            self._wait_for_request_slot()
            timestamp_ms = int(time.time() * 1000)
            initial_body = json.dumps(
                {
                    "magic": 538969122,
                    "version": 1,
                    "dataType": 8,
                    "strData": "",
                    "tspFromClient": timestamp_ms,
                },
                separators=(",", ":"),
            )
            try:
                response = self.session.post(
                    _MS_TOKEN_URL,
                    params={"msToken": ""},
                    headers=headers,
                    data=initial_body,
                    timeout=self.timeout,
                )
            except requests.RequestsError as exc:
                raise TikTokResponseError(f"msToken request failed: {exc}") from exc
            if response.status_code != 200:
                raise TikTokResponseError(
                    f"msToken request returned HTTP {response.status_code}"
                )
            initial_token = self._response_cookie(response, "msToken")
            if not initial_token:
                raise TikTokResponseError("msToken response did not contain a token")

        # 遥测报告需要签名，因此在生成时间戳前预留请求启动时机。
        self._wait_for_request_slot()
        timestamp_ms = int(time.time() * 1000)
        telemetry = build_telemetry(
            device_id=self.device_id,
            user_agent=self.user_agent,
            timestamp_ms=timestamp_ms,
            language=self._browser_language(),
        )
        report_body = json.dumps(
            {
                "magic": 538969122,
                "version": 1,
                "dataType": 8,
                "strData": self.signer.encode_telemetry(telemetry),
                "tspFromClient": timestamp_ms,
            },
            separators=(",", ":"),
        )
        signed = self.signer.sign(
            "",
            user_agent=self.user_agent,
            ms_token=initial_token,
            body=report_body,
        )
        try:
            response = self.session.post(
                f"{_MS_TOKEN_URL}?{signed['query']}",
                headers={**headers, "Cookie": f"msToken={initial_token}"},
                data=report_body,
                timeout=self.timeout,
            )
        except requests.RequestsError as exc:
            raise TikTokResponseError(f"msToken telemetry request failed: {exc}") from exc
        if response.status_code != 200:
            raise TikTokResponseError(
                f"msToken telemetry request returned HTTP {response.status_code}"
            )
        token = self._response_cookie(response, "msToken")
        if not token:
            raise TikTokResponseError("msToken telemetry response did not contain a token")
        self._set_ms_token(token)
        self._ms_token_ready = True

    def _ensure_identity(self) -> None:
        if self.device_id and self.odin_id and self.web_id_last_time:
            return
        response, data = self._get_hydration("https://www.tiktok.com/", "identity")
        default_scope = data.get("__DEFAULT_SCOPE__", {})
        if not isinstance(default_scope, Mapping):
            raise TikTokResponseError("identity HTML default scope is not an object")
        self._apply_app_context(default_scope.get("webapp.app-context"))
        self._refresh_ms_token(response)

    def _get_hydration(
        self,
        url: str,
        purpose: str,
    ) -> tuple[requests.Response, dict[str, Any]]:
        last_error: TikTokResponseError | None = None
        last_cause: Exception | None = None
        for attempt in range(self.retries + 1):
            retryable = True
            last_cause = None
            self._wait_for_request_slot()
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestsError as exc:
                last_error = TikTokResponseError(f"{purpose} request failed: {exc}")
                last_cause = exc
            else:
                if response.status_code != 200:
                    last_error = TikTokResponseError(
                        f"{purpose} request returned HTTP {response.status_code}: "
                        f"{response.url}"
                    )
                    retryable = response.status_code == 429 or response.status_code >= 500
                else:
                    try:
                        return response, self._universal_data(response.text)
                    except TikTokResponseError as exc:
                        # 200 状态的验证或边缘响应可能会短暂缺少 hydration 脚本。
                        last_error = exc
                        if "WAF challenge" in str(exc):
                            retryable = False
            if attempt >= self.retries or not retryable:
                break
            time.sleep(0.4 * (2**attempt))
        if last_error is None:
            raise TikTokResponseError(f"{purpose} hydration request failed")
        if last_cause is not None:
            raise last_error from last_cause
        raise last_error

    def _set_ms_token(self, token: str) -> None:
        self.ms_token = token
        self.session.cookies.set("msToken", token, domain=".tiktok.com", path="/")

    def _wait_for_request_slot(self) -> None:
        with self._request_slot_lock:
            now = time.monotonic()
            if self._last_request_started_at is not None and self.request_interval > 0:
                next_start = self._last_request_started_at + self.request_interval
                while now < next_start:
                    time.sleep(next_start - now)
                    now = time.monotonic()
            self._last_request_started_at = now

    @staticmethod
    def _response_cookie(response: requests.Response, name: str) -> str | None:
        try:
            value = response.cookies.get(name)
        except (AttributeError, KeyError, TypeError, ValueError):
            value = None
        if value:
            return str(value)
        match = re.search(
            rf"(?:^|,\s*){re.escape(name)}=([^;]+)",
            response.headers.get("set-cookie", ""),
        )
        return match.group(1) if match else None

    def _apply_app_context(self, value: Any) -> None:
        if not isinstance(value, Mapping):
            raise TikTokResponseError("profile HTML does not contain app context")
        device_id = str(value.get("wid") or "")
        odin_id = str(value.get("odinId") or "")
        created_time = _integer(value.get("webIdCreatedTime"))
        if not device_id or not odin_id or not created_time:
            raise TikTokResponseError("profile app context is missing device identifiers")
        self.device_id = device_id
        self.odin_id = odin_id
        self.web_id_last_time = created_time
        self.region = str(value.get("region") or self.region)
        self.language = str(value.get("language") or self.language)
        ab_test = value.get("abTestVersion")
        if isinstance(ab_test, Mapping):
            self.client_ab_versions = str(ab_test.get("versionName") or "")

    def _browser_language(self) -> str:
        if self.language.startswith("zh"):
            return "zh-CN"
        if self.language == "en":
            return "en-US"
        return self.language

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        try:
            return min(max(float(value or 0), 0.5), 10)
        except ValueError:
            return min(0.5 * (2**attempt), 10)

    @staticmethod
    def _universal_data(html: str) -> dict[str, Any]:
        if (
            "SlardarWAF" in html
            or "_wafchallengeid" in html
            or 'id="wci"' in html
        ):
            raise TikTokResponseError(
                "TikTok Web visitor bootstrap returned a WAF challenge"
            )
        parser = _UniversalDataParser()
        parser.feed(html)
        if not parser.value:
            raise TikTokResponseError("HTML does not contain universal hydration data")
        try:
            payload = json.loads(parser.value)
        except json.JSONDecodeError as exc:
            raise TikTokResponseError("universal hydration data is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TikTokResponseError("universal hydration data is not an object")
        return payload

    @staticmethod
    def _validate_tiktok_url(value: str) -> str:
        text = value.strip()
        if not text.startswith(("http://", "https://")):
            text = "https://" + text
        parsed = urlsplit(text)
        if not parsed.hostname or not _TIKTOK_HOST_RE.search(parsed.hostname):
            raise TikTokInputError("URL host must be tiktok.com")
        return text

    def _resolve_video(self, value: str) -> tuple[str, str]:
        text = value.strip()
        if _ASCII_NUMERIC_ID_RE.fullmatch(text):
            return text, f"https://www.tiktok.com/@_/video/{text}"
        url = self._validate_tiktok_url(text)
        match = _VIDEO_RE.search(urlsplit(url).path)
        if match:
            return match.group(1), url
        self._wait_for_request_slot()
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestsError as exc:
            raise TikTokResponseError(f"video redirect request failed: {exc}") from exc
        if response.status_code >= 400:
            raise TikTokResponseError(
                f"video redirect returned HTTP {response.status_code}: {response.url}"
            )
        match = _VIDEO_RE.search(urlsplit(response.url).path)
        if not match:
            raise TikTokInputError("video URL does not contain a numeric video id")
        self._refresh_ms_token(response)
        return match.group(1), response.url

    @staticmethod
    def _normalize_video(item: Mapping[str, Any]) -> dict[str, Any]:
        author = item.get("author") if isinstance(item.get("author"), Mapping) else {}
        video = item.get("video") if isinstance(item.get("video"), Mapping) else {}
        stats = item.get("statsV2") or item.get("stats") or {}
        if not isinstance(stats, Mapping):
            stats = {}
        video_id = str(item.get("id") or item.get("aweme_id") or "")
        username = str(author.get("uniqueId") or author.get("unique_id") or "")
        description = str(item.get("desc") or item.get("description") or "")
        seo = item.get("seoInfos") if isinstance(item.get("seoInfos"), Mapping) else {}
        title = str(seo.get("seoTitle") or description)
        bitrate_urls: list[str] = []
        bitrate_info = video.get("bitrateInfo", video.get("bit_rate", []))
        if isinstance(bitrate_info, list):
            for entry in bitrate_info:
                result = _first_url(entry)
                if result and result not in bitrate_urls:
                    bitrate_urls.append(result)
        normalized: dict[str, Any] = {
            "id": video_id,
            "url": f"https://www.tiktok.com/@{username or '_'}/video/{video_id}",
            "title": title,
            "description": description,
            "language": str(
                item.get("textLanguage", item.get("text_language", "")) or ""
            ),
            "create_time": _integer(item.get("createTime", item.get("create_time"))),
            "author": {
                "id": str(author.get("id") or author.get("uid") or ""),
                "sec_uid": str(author.get("secUid") or author.get("sec_uid") or ""),
                "unique_id": username,
                "nickname": str(author.get("nickname") or ""),
                "verified": _boolean(author.get("verified", False)),
            },
            "stats": {
                "likes": _integer(stats.get("diggCount", stats.get("digg_count"))),
                "plays": _integer(stats.get("playCount", stats.get("play_count"))),
                "comments": _integer(stats.get("commentCount", stats.get("comment_count"))),
                "shares": _integer(stats.get("shareCount", stats.get("share_count"))),
                "collects": _integer(stats.get("collectCount", stats.get("collect_count"))),
            },
            "media": {
                "cover": _first_url(video.get("cover")),
                "origin_cover": _first_url(video.get("originCover", video.get("origin_cover"))),
                "dynamic_cover": _first_url(video.get("dynamicCover", video.get("dynamic_cover"))),
                "play_url": _first_url(video.get("playAddr", video.get("play_addr"))),
                "download_url": _first_url(video.get("downloadAddr", video.get("download_addr"))),
                "bitrate_urls": bitrate_urls,
                "duration": _integer(video.get("duration")),
                "width": _integer(video.get("width")),
                "height": _integer(video.get("height")),
            },
        }
        tags = TikTokClient._normalize_video_tags(item)
        if tags:
            normalized["tags"] = tags
        music = TikTokClient._normalize_video_music(item)
        if music:
            normalized["music"] = music
        return normalized

    @staticmethod
    def _normalize_video_tags(item: Mapping[str, Any]) -> list[dict[str, str]]:
        """归一化视频携带的挑战标签，供 tag-videos 扩展。"""
        candidates: list[Any] = []

        def append_candidates(value: Any) -> None:
            if isinstance(value, Mapping):
                candidates.append(value)
            elif isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                candidates.extend(value)

        for key in ("challenges", "challengeInfo", "challenge_info"):
            value = item.get(key)
            if isinstance(value, Mapping):
                nested = value.get("challenges") or value.get("challenge")
                if isinstance(nested, Mapping) or (
                    isinstance(nested, Sequence)
                    and not isinstance(nested, (str, bytes, bytearray))
                ):
                    append_candidates(nested)
                else:
                    append_candidates(value)
            else:
                append_candidates(value)

        tags: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for value in candidates:
            if not isinstance(value, Mapping):
                continue
            challenge = value.get("challenge")
            if not isinstance(challenge, Mapping):
                challenge = value
            identifier = str(
                challenge.get("id")
                or challenge.get("cid")
                or challenge.get("challengeId")
                or challenge.get("challenge_id")
                or challenge.get("idStr")
                or challenge.get("id_str")
                or ""
            ).strip()
            if (
                not _ASCII_NUMERIC_ID_RE.fullmatch(identifier)
                or not any(char != "0" for char in identifier)
                or identifier in seen_ids
            ):
                continue
            name = str(
                challenge.get("title")
                or challenge.get("chaName")
                or challenge.get("cha_name")
                or challenge.get("name")
                or challenge.get("challengeName")
                or challenge.get("challenge_name")
                or ""
            ).strip()
            name = name.removeprefix("#").strip()
            if not name:
                continue
            seen_ids.add(identifier)
            tags.append(
                {
                    "id": identifier,
                    "name": name,
                    "url": f"https://www.tiktok.com/tag/{quote(name, safe='')}",
                }
            )
        return tags

    @staticmethod
    def _normalize_video_music(item: Mapping[str, Any]) -> dict[str, Any] | None:
        """归一化视频携带的音乐身份，供 music-videos 扩展。"""
        music = item.get("music")
        if not isinstance(music, Mapping):
            return None
        identifier = str(
            music.get("idStr")
            or music.get("id_str")
            or music.get("id")
            or music.get("mid")
            or ""
        ).strip()
        if not _ASCII_NUMERIC_ID_RE.fullmatch(identifier) or not any(
            char != "0" for char in identifier
        ):
            return None

        normalized: dict[str, Any] = {
            "id": identifier,
            "url": f"https://www.tiktok.com/music/-{identifier}",
        }
        title = str(
            music.get("title")
            or music.get("name")
            or music.get("musicName")
            or music.get("music_name")
            or ""
        ).strip()
        if title:
            normalized["title"] = title
        author_value = (
            music.get("authorName")
            or music.get("author_name")
            or music.get("ownerNickname")
            or music.get("owner_nickname")
            or music.get("ownerHandle")
            or music.get("owner_handle")
            or music.get("author")
        )
        if isinstance(author_value, Mapping):
            author_name = str(
                author_value.get("nickname")
                or author_value.get("name")
                or author_value.get("uniqueId")
                or author_value.get("unique_id")
                or ""
            ).strip()
        else:
            author_name = str(author_value or "").strip()
        if author_name:
            normalized["author_name"] = author_name
        for key in ("original", "isOriginal", "is_original", "isOriginalSound"):
            if key in music and music[key] is not None:
                normalized["original"] = _boolean(music[key])
                break
        return normalized

    @staticmethod
    def _normalize_tag(
        payload: Mapping[str, Any],
        *,
        expected_name: str,
    ) -> dict[str, Any]:
        info = payload.get("challengeInfo", payload.get("challenge_info", {}))
        if not isinstance(info, Mapping):
            raise TikTokResponseError("tag response challengeInfo is not an object")
        challenge = info.get("challenge")
        if not isinstance(challenge, Mapping):
            raise TikTokResponseError("tag response does not contain challenge details")
        identifier = str(challenge.get("id") or challenge.get("id_str") or "")
        name = str(challenge.get("title") or challenge.get("name") or "")
        if not _ASCII_NUMERIC_ID_RE.fullmatch(identifier) or not any(
            char != "0" for char in identifier
        ):
            raise TikTokResponseError("tag response has an invalid tag id")
        if not name:
            raise TikTokResponseError("tag response has an empty tag name")
        if name.casefold() != expected_name.casefold():
            raise TikTokResponseError(
                f"tag response name mismatch: expected {expected_name}, got {name}"
            )
        stats = info.get("stats")
        if not isinstance(stats, Mapping):
            stats = challenge.get("stats", {})
        if not isinstance(stats, Mapping):
            stats = {}
        return {
            "id": identifier,
            "name": name,
            "description": str(challenge.get("desc") or challenge.get("description") or ""),
            "split_name": str(challenge.get("splitTitle") or challenge.get("split_title") or ""),
            "is_commerce": _boolean(
                challenge.get("isCommerce", challenge.get("is_commerce", False))
            ),
            "url": f"https://www.tiktok.com/tag/{quote(expected_name, safe='')}",
            "profile_image": _first_url(
                challenge.get(
                    "profileMedium",
                    challenge.get("profile_medium", challenge.get("profileThumb")),
                )
            ),
            "cover_image": _first_url(
                challenge.get(
                    "coverMedium",
                    challenge.get("cover_medium", challenge.get("coverThumb")),
                )
            ),
            "stats": {
                "videos": _integer(stats.get("videoCount", stats.get("video_count"))),
                "views": _integer(stats.get("viewCount", stats.get("view_count"))),
            },
        }

    @staticmethod
    def _normalize_music(
        payload: Mapping[str, Any],
        *,
        expected_id: str,
    ) -> dict[str, Any]:
        info = payload.get("musicInfo", payload.get("music_info", {}))
        if not isinstance(info, Mapping):
            info = {}
        music = info.get("music")
        if not isinstance(music, Mapping) and _first_value(
            info,
            "idStr",
            "id_str",
            "id",
            "mid",
        ):
            music = info
        if not isinstance(music, Mapping):
            music = payload.get("music")
        if not isinstance(music, Mapping):
            raise TikTokResponseError("music response does not contain music details")
        identifier = str(
            _first_value(music, "idStr", "id_str", "id", "mid") or ""
        )
        if not _ASCII_NUMERIC_ID_RE.fullmatch(identifier) or not any(
            char != "0" for char in identifier
        ):
            raise TikTokResponseError("music response has an invalid music id")
        if identifier != expected_id:
            raise TikTokResponseError(
                f"music response ID mismatch: expected {expected_id}, got {identifier}"
            )
        author_value = _first_value(
            info,
            "author",
            "ownerNickname",
            "owner_nickname",
            "ownerHandle",
            "owner_handle",
        )
        if author_value is None:
            author_value = _first_value(
                music,
                "author",
                "ownerNickname",
                "owner_nickname",
                "ownerHandle",
                "owner_handle",
            )
        author = author_value if isinstance(author_value, Mapping) else {}
        stats = info.get("stats")
        if not isinstance(stats, Mapping):
            stats = payload.get("stats", {})
        if not isinstance(stats, Mapping):
            stats = {}
        author_name = str(
            music.get("authorName")
            or music.get("author_name")
            or music.get("ownerNickname")
            or music.get("owner_nickname")
            or music.get("ownerHandle")
            or music.get("owner_handle")
            or author.get("nickname")
            or (author_value if isinstance(author_value, str) else "")
        )
        video_count = _first_value(stats, "videoCount", "video_count")
        if video_count is None:
            video_count = _first_value(music, "userCount", "user_count")
        author_unique_id = str(
            _first_value(author, "uniqueId", "unique_id")
            or _first_value(music, "ownerHandle", "owner_handle")
            or ""
        )
        author_nickname = str(
            author.get("nickname")
            or _first_value(music, "ownerNickname", "owner_nickname")
            or ""
        )
        return {
            "id": identifier,
            "title": str(music.get("title") or ""),
            "author_name": author_name,
            "duration": _integer(
                _first_value(
                    music,
                    "duration",
                    "videoDuration",
                    "video_duration",
                )
            ),
            "original": _boolean(
                _first_value(
                    music,
                    "original",
                    "isOriginal",
                    "is_original",
                    "isOriginalSound",
                    "is_original_sound",
                )
            ),
            "url": f"https://www.tiktok.com/music/-{identifier}",
            "play_url": _first_url(music.get("playUrl", music.get("play_url"))),
            "covers": {
                "large": _first_url(music.get("coverLarge", music.get("cover_large"))),
                "medium": _first_url(music.get("coverMedium", music.get("cover_medium"))),
                "thumb": _first_url(music.get("coverThumb", music.get("cover_thumb"))),
            },
            "author": {
                "id": str(author.get("id") or author.get("uid") or ""),
                "sec_uid": str(author.get("secUid") or author.get("sec_uid") or ""),
                "unique_id": author_unique_id,
                "nickname": author_nickname,
            },
            "stats": {
                "videos": _integer(video_count),
            },
        }

    @staticmethod
    def _normalize_comment(item: Mapping[str, Any]) -> dict[str, Any]:
        user = item.get("user") if isinstance(item.get("user"), Mapping) else {}
        return {
            "id": str(item.get("cid") or item.get("id") or ""),
            "text": str(item.get("text") or ""),
            "create_time": _integer(item.get("create_time", item.get("createTime"))),
            "likes": _integer(item.get("digg_count", item.get("diggCount"))),
            "reply_count": _integer(
                item.get("reply_comment_total", item.get("replyCommentTotal"))
            ),
            "parent_id": str(item.get("reply_id") or item.get("replyId") or ""),
            "user": {
                "id": str(user.get("uid") or user.get("id") or ""),
                "sec_uid": str(user.get("sec_uid") or user.get("secUid") or ""),
                "unique_id": str(user.get("unique_id") or user.get("uniqueId") or ""),
                "nickname": str(user.get("nickname") or ""),
                "avatar": _first_url(user.get("avatar_thumb", user.get("avatarThumb"))),
            },
        }


def iter_video_ids(videos: Mapping[str, Any]) -> Iterator[str]:
    for video in videos.get("videos", []):
        if isinstance(video, Mapping) and video.get("id"):
            yield str(video["id"])
