from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..browser_progress import stderr_progress
from ..browser_session import (
    INTERACTIVE_LOGIN_ERRORS,
    BrowserSessionError,
    authorize_browser_session,
    call_daemon,
    start_daemon,
)
from .client import TikTokClient
from .errors import TikTokError, TikTokResponseError


_COMMERCIAL_PLATFORMS = {
    "creative-top-ads": "tiktok_creative_topads",
    "creative-top-ads-performance": "tiktok_creative_topads",
    "creative-top-ads-filters": "tiktok_creative_topads",
    "creative-top-ads-suggest": "tiktok_creative_topads",
    "creative-top-ads-detail": "tiktok_creative_topads",
    "creative-top-ads-keyframes": "tiktok_creative_topads",
    "creative-trending-videos-full": "tiktok_creative",
    "creative-trending-hashtags-full": "tiktok_creative",
    "creative-hashtag-detail": "tiktok_creative",
    "ads-keyword-ideas": "tiktok_ads_manager",
    "ads-keyword-summary": "tiktok_ads_manager",
    "creative-studio-credits": "tiktok_creative_studio",
    "creative-studio-permissions": "tiktok_creative_studio",
    "creative-studio-limits": "tiktok_creative_studio",
    "creative-studio-status": "tiktok_creative_studio",
    "creative-studio-models": "tiktok_creative_studio",
    "creative-studio-prepare": "tiktok_creative_studio",
    "creative-studio-prepare-i2v": "tiktok_creative_studio",
    "creative-studio-prepare-r2v": "tiktok_creative_studio",
    "creative-studio-ledger": "tiktok_creative_studio",
    "creative-studio-history": "tiktok_creative_studio",
    "creative-studio-task-detail": "tiktok_creative_studio",
    "creative-studio-video-info": "tiktok_creative_studio",
    "creative-studio-download": "tiktok_creative_studio",
    "creative-studio-upload-image": "tiktok_creative_studio",
    "creative-studio-generate": "tiktok_creative_studio",
    "creative-studio-generate-i2v": "tiktok_creative_studio",
    "creative-studio-task": "tiktok_creative_studio",
    "one-creator-filters": "tiktok_one",
    "one-creator-suggest": "tiktok_one",
    "one-creator-search": "tiktok_one",
}

_COMMERCIAL_OPERATION_LABELS = {
    "/api/v4/i18n/search_ads/search_keyword/mget_keyword_ideas/": "关键词机会",
    "/CreativeOne/KnowledgeAPI/GetHashtagList": "热门标签完整分页",
    "/CreativeOne/TopAds/SearchMaterial": "Top Ads 表现素材",
    "/creative_radar_api/v1/top_ads/v2/list": "Top Ads 素材",
    "/CreativeOne/MatchMaking/QueryPartnerCreatorSquare": "达人匹配",
    "/CreativeOne/SymphonyPlatform/QueryCreditAccount": "积分余额",
    "/creative_bff_i18n/api/cue/get_miniapp_permission_with_allowlist": (
        "模型权限"
    ),
    "/creative_bff_i18n/api/cue/generating-task-count": "运行中任务数",
    "/creative_bff_i18n/api/cue/get_generate_max_count": "并发上限",
    "/creative_bff_i18n/api/cue/t2v/create_generate_task": "提交视频生成任务",
    "/creative_bff_i18n/api/cue/upload/local-image": "上传视频参考图",
    "/creative_bff_i18n/api/cue/i2v/create_generate_task": "提交参考图视频任务",
    "/creative_bff_i18n/api/cue/generate-task/check": "等待视频生成结果",
    "/creative_bff_i18n/api/cue/video_info": "读取成品视频",
}


def _creative_fetch(
    platform: str,
    request_interval: float,
    *,
    interactive_login: bool | None = None,
    login_timeout: float = 300,
) -> Callable[
    [str, Sequence[tuple[str, str]], str],
    Mapping[str, Any],
]:
    started = False
    recovered_platforms: set[str] = set()
    reported_ready_platforms: set[str] = set()
    operation_counts: dict[str, int] = {}
    report_progress = stderr_progress()
    allow_interactive_login = (
        sys.stderr.isatty()
        if interactive_login is None
        else interactive_login
    )

    def request_platform(path: str) -> str:
        if path.startswith("/api/v4/i18n/search_ads/"):
            return "tiktok_ads_manager"
        if path.startswith("/creative_radar_api/"):
            return "tiktok_creative_topads"
        if path.startswith("/CreativeOne/MatchMaking/"):
            return "tiktok_one"
        if (
            path.startswith("/CreativeOne/SymphonyPlatform/")
            or path.startswith("/creative_bff_i18n/api/cue/")
        ):
            return "tiktok_creative_studio"
        return platform

    def fetch(
        path: str,
        entries: Sequence[tuple[str, str]],
        referer: str,
    ) -> Mapping[str, Any]:
        nonlocal started
        request = {
            "op": "request",
            "platform": request_platform(path),
            "path": path,
            "entries": [list(entry) for entry in entries],
            "referer": referer,
            "request_interval_ms": round(request_interval * 1000),
        }
        operation_label = _COMMERCIAL_OPERATION_LABELS.get(path)
        if operation_label:
            operation_counts[path] = operation_counts.get(path, 0) + 1
            if path == "/creative_bff_i18n/api/cue/generate-task/check":
                operation_label = (
                    f"{operation_label}（第 {operation_counts[path]} 次）"
                )

        def contextual_progress(event: dict[str, Any]) -> None:
            target_platform = str(event.get("platform") or request["platform"])
            if (
                event.get("stage") == "session"
                and target_platform in reported_ready_platforms
            ):
                return
            contextual = dict(event)
            if operation_label and event.get("stage") in {"request", "complete"}:
                contextual["message"] = (
                    f"{str(event.get('message') or '').rstrip('：:')}"
                    f"：{operation_label}"
                )
            report_progress(contextual)
            if event.get("stage") == "complete":
                reported_ready_platforms.add(target_platform)

        result: Any = None
        daemon_restarted = False
        while True:
            try:
                if not started:
                    start_daemon()
                    started = True
                result = asyncio.run(
                    call_daemon(request, progress=contextual_progress)
                )
                break
            except BrowserSessionError as exc:
                if not daemon_restarted and exc.code == "daemon_unavailable":
                    started = False
                    daemon_restarted = True
                    continue
                target_platform = request["platform"]
                if (
                    allow_interactive_login
                    and exc.code in INTERACTIVE_LOGIN_ERRORS
                    and target_platform not in recovered_platforms
                ):
                    try:
                        authorize_browser_session(
                            target_platform,
                            url=referer,
                            timeout=login_timeout,
                            open_browser=(
                                target_platform == "tiktok_ads_manager"
                                or exc.code in {
                                    "extension_disconnected",
                                    "tab_unavailable",
                                }
                            ),
                            progress=report_progress,
                        )
                    except BrowserSessionError as login_exc:
                        if (
                            target_platform == "tiktok_ads_manager"
                            and login_exc.code == "runtime_unavailable"
                        ):
                            raise TikTokResponseError(
                                "TikTok Ads Manager Keyword Planner 请求上下文不可用 "
                                f"({login_exc.code}): {login_exc}"
                            ) from login_exc
                        raise TikTokResponseError(
                            "TikTok 商业接口页面会话交接失败 "
                            f"({login_exc.code}): {login_exc}"
                        ) from login_exc
                    recovered_platforms.add(target_platform)
                    started = True
                    continue
                raise TikTokResponseError(
                    f"TikTok 商业接口浏览器会话请求失败 ({exc.code}): {exc}"
                ) from exc
        if not isinstance(result, Mapping):
            raise TikTokResponseError("TikTok 商业接口浏览器会话响应不是对象")
        return result

    return fetch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TikTok 资料、视频、搜索、标签、音乐与评论查询客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=3.0,
        help="目标请求的最小启动间隔秒数（0..10，默认值: 3.0）",
    )
    parser.add_argument(
        "--no-browser-login",
        action="store_true",
        help="浏览器会话缺失时直接报错，不进入交互式登录流程",
    )
    parser.add_argument(
        "--browser-login-timeout",
        type=float,
        default=300,
        help="交互式浏览器登录的最长等待秒数（默认值: 300）",
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="json_output",
        type=Path,
        help="将 JSON 写入此文件（置于子命令前）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    videos = subparsers.add_parser("videos", help="查询资料页的全部公开视频")
    videos.add_argument("profile_url")
    videos.add_argument("--limit", type=int)
    videos.add_argument("--page-size", type=int, default=16)

    video = subparsers.add_parser("video", help="查询一个视频")
    video.add_argument("video_url_or_id")

    search = subparsers.add_parser("search-videos", help="搜索公开视频")
    search.add_argument("keyword")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--page-size", type=int, default=20)

    search_general = subparsers.add_parser(
        "search-general",
        help="查询一页综合搜索卡片",
    )
    search_general.add_argument("keyword", help="搜索关键词")
    search_general.add_argument(
        "--limit",
        type=int,
        default=12,
        help="本页最多返回的卡片数（默认值: 12）",
    )
    search_general.add_argument(
        "--offset",
        type=int,
        default=0,
        help="起始游标（默认值: 0）",
    )
    search_general.add_argument(
        "--search-id",
        default="",
        help="续页搜索会话标识",
    )

    search_users = subparsers.add_parser(
        "search-users",
        help="分页搜索公开用户",
    )
    search_users.add_argument("keyword", help="搜索关键词")
    search_users.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最多返回的用户数（默认值: 20）",
    )
    search_users.add_argument(
        "--offset",
        type=int,
        default=0,
        help="起始游标（默认值: 0）",
    )
    search_users.add_argument(
        "--search-id",
        default="",
        help="续页搜索会话标识",
    )

    search_music = subparsers.add_parser(
        "search-music",
        help="分页搜索公开音乐",
    )
    search_music.add_argument("keyword", help="搜索关键词")
    search_music.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最多返回的音乐数（默认值: 20）",
    )
    search_music.add_argument(
        "--offset",
        type=int,
        default=0,
        help="起始游标（默认值: 0）",
    )
    search_music.add_argument(
        "--search-id",
        default="",
        help="续页搜索会话标识",
    )

    search_live = subparsers.add_parser(
        "search-live",
        help="分页搜索公开直播间",
    )
    search_live.add_argument("keyword", help="搜索关键词")
    search_live.add_argument(
        "--limit",
        type=int,
        default=12,
        help="最多返回的直播间数（默认值: 12）",
    )
    search_live.add_argument(
        "--offset",
        type=int,
        default=0,
        help="起始游标（默认值: 0）",
    )
    search_live.add_argument(
        "--search-id",
        default="",
        help="续页搜索会话标识",
    )

    search_photo = subparsers.add_parser(
        "search-photo",
        help="分页搜索公开图文",
    )
    search_photo.add_argument("keyword", help="搜索关键词")
    search_photo.add_argument(
        "--limit",
        type=int,
        default=12,
        help="最多返回的图文数（默认值: 12）",
    )
    search_photo.add_argument(
        "--offset",
        type=int,
        default=0,
        help="起始游标（默认值: 0）",
    )
    search_photo.add_argument(
        "--search-id",
        default="",
        help="续页搜索会话标识",
    )

    search_suggest = subparsers.add_parser(
        "search-suggest",
        help="查询公开搜索联想词",
    )
    search_suggest.add_argument("keyword", help="搜索关键词")
    search_suggest.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最多返回的联想词数（默认值: 20）",
    )

    trending_searchwords = subparsers.add_parser(
        "trending-searchwords",
        help="查询 Explore 热门搜索词",
    )
    trending_searchwords.add_argument(
        "--region",
        "--country",
        dest="region",
        default="US",
        help="两位国家或地区代码（默认值: US）",
    )
    trending_searchwords.add_argument(
        "--limit",
        type=int,
        default=15,
        help="最多返回的热门词数（1..50，默认值: 15）",
    )

    creative_hashtags = subparsers.add_parser(
        "creative-trending-hashtags",
        help="查询 TikTok Creative Center 热门标签",
    )
    creative_hashtags.add_argument("--country", default="US")
    creative_hashtags.add_argument("--time-range", type=int, default=7)
    creative_hashtags.add_argument("--industry-id")
    creative_hashtags.add_argument("--page", type=int, default=1)
    creative_hashtags.add_argument("--limit", type=int, default=20)

    creative_hashtags_full = subparsers.add_parser(
        "creative-trending-hashtags-full",
        help="通过 Chrome 分页查询 TikTok Creative Center 热门标签",
    )
    creative_hashtags_full.add_argument("--country", default="US")
    creative_hashtags_full.add_argument("--time-range", type=int, default=7)
    creative_hashtags_full.add_argument("--industry-id")
    creative_hashtags_full.add_argument("--page", type=int, default=1)
    creative_hashtags_full.add_argument("--limit", type=int, default=20)

    creative_hashtag_detail = subparsers.add_parser(
        "creative-hashtag-detail",
        help="通过 Chrome 查询热门标签受众、地域 TGI 和代表视频",
    )
    creative_hashtag_detail.add_argument("hashtag_id")
    creative_hashtag_detail.add_argument("--country", default="US")
    creative_hashtag_detail.add_argument(
        "--time-range",
        type=int,
        choices=(7, 30, 90),
        default=7,
    )

    creative_videos = subparsers.add_parser(
        "creative-trending-videos",
        help="查询 TikTok Creative Center 热门视频预览",
    )
    creative_videos.add_argument("--country", default="US")
    creative_videos.add_argument("--time-range", type=int, default=30)
    creative_videos.add_argument(
        "--metric",
        choices=("views", "engagement", "completion"),
        default="views",
    )
    creative_videos.add_argument("--content-label-ids", default="")
    creative_videos.add_argument("--page", type=int, default=1)
    creative_videos.add_argument("--limit", type=int, default=20)

    creative_videos_full = subparsers.add_parser(
        "creative-trending-videos-full",
        help="通过 Chrome 分页查询 TikTok Creative Center 热门视频",
    )
    creative_videos_full.add_argument("--country", default="US")
    creative_videos_full.add_argument("--time-range", type=int, default=30)
    creative_videos_full.add_argument(
        "--metric",
        choices=("views", "engagement", "completion"),
        default="views",
    )
    creative_videos_full.add_argument("--content-label-ids", default="")
    creative_videos_full.add_argument("--page", type=int, default=1)
    creative_videos_full.add_argument("--limit", type=int, default=20)

    creative_video_detail = subparsers.add_parser(
        "creative-trending-video-detail",
        help="查询 TikTok Creative Center 热门视频的公开详情和评论",
    )
    creative_video_detail.add_argument("item_id")
    creative_video_detail.add_argument("--country", default="US")
    creative_video_detail.add_argument(
        "--time-range",
        type=int,
        choices=(7, 30),
        default=30,
    )

    subparsers.add_parser(
        "creative-top-ads-filters",
        help="通过 Chrome 查询 TikTok Top Ads 筛选目录",
    )

    top_ads_suggest = subparsers.add_parser(
        "creative-top-ads-suggest",
        help="通过 Chrome 查询 TikTok Top Ads 热门词和相关搜索词",
    )
    top_ads_suggest.add_argument("keyword", nargs="?", default="")
    top_ads_suggest.add_argument("--country", default="US")
    top_ads_suggest.add_argument("--limit", type=int, default=20)

    top_ads = subparsers.add_parser(
        "creative-top-ads",
        help="通过 Chrome 搜索 TikTok Top Ads 素材",
    )
    top_ads.add_argument("search_word", nargs="?", default="")
    top_ads.add_argument(
        "--country",
        action="append",
        default=[],
        help="两位国家代码，可重复传入",
    )
    top_ads.add_argument(
        "--time-range",
        type=int,
        choices=(7, 30, 180),
        default=30,
    )
    top_ads.add_argument(
        "--industry-label-ids",
        default="",
        help="逗号分隔的行业标签 ID",
    )
    top_ads.add_argument(
        "--objectives",
        default="",
        help="逗号分隔的广告目标 ID",
    )
    top_ads.add_argument(
        "--ad-format",
        choices=("spark", "non_spark"),
    )
    top_ads.add_argument(
        "--duration",
        choices=("0-15", "15-30", "30-60", "60-999"),
    )
    top_ads.add_argument(
        "--like-range",
        choices=("0-100", "100-1000", "1000-10000", "10000-999999999"),
    )
    top_ads.add_argument(
        "--pattern-label-ids",
        default="",
        help="逗号分隔的创意模式标签 ID",
    )
    top_ads.add_argument(
        "--language",
        action="append",
        default=[],
        help="广告语言，可重复传入",
    )
    top_ads.add_argument(
        "--order",
        choices=("for_you", "impression", "ctr", "like"),
        default="for_you",
    )
    top_ads.add_argument("--page", type=int, default=1)
    top_ads.add_argument("--limit", type=int, default=20)

    top_ads_performance = subparsers.add_parser(
        "creative-top-ads-performance",
        help="通过 Chrome 读取 Top Ads Library 的数值表现素材",
    )
    top_ads_performance.add_argument("search_word", nargs="?", default="")
    top_ads_performance.add_argument(
        "--country",
        action="append",
        default=[],
        help="两位国家代码，可重复传入",
    )
    top_ads_performance.add_argument(
        "--time-range",
        type=int,
        choices=(7, 30, 180),
        default=30,
    )
    top_ads_performance.add_argument(
        "--industry-label-ids",
        default="",
        help="逗号分隔的行业标签 ID",
    )
    top_ads_performance.add_argument(
        "--objectives",
        default="",
        help="逗号分隔的广告目标 ID",
    )
    top_ads_performance.add_argument(
        "--ad-format",
        type=int,
        choices=(1, 2, 3, 4, 99, 100),
        help="Library 广告形式 ID",
    )
    top_ads_performance.add_argument(
        "--like-count-filter",
        type=int,
        choices=(1, 2, 3, 4, 5),
        help="Library 点赞档位 ID",
    )
    top_ads_performance.add_argument(
        "--order",
        choices=("views", "ctr", "engagement", "completion"),
        default="views",
    )
    top_ads_performance.add_argument("--page", type=int, default=1)
    top_ads_performance.add_argument("--limit", type=int, default=20)

    top_ads_detail = subparsers.add_parser(
        "creative-top-ads-detail",
        help="组合查询 Top Ads 详情、逐秒曲线、CTR 分位和相关推荐",
    )
    top_ads_detail.add_argument("material_id")
    top_ads_detail.add_argument("--country", default="US")
    top_ads_detail.add_argument(
        "--time-range",
        type=int,
        choices=(7, 30, 180),
        default=180,
    )
    top_ads_detail.add_argument(
        "--metric",
        action="append",
        choices=(
            "retain_ctr",
            "retain_cvr",
            "click_cnt",
            "convert_cnt",
            "play_retain_cnt",
        ),
        default=[],
    )
    top_ads_detail.add_argument(
        "--no-recommendations",
        action="store_true",
        help="跳过相关推荐",
    )
    top_ads_detail.add_argument(
        "--no-ai-analysis",
        action="store_true",
        help="跳过账号可见的 AI Detail Analysis",
    )

    top_ads_keyframes = subparsers.add_parser(
        "creative-top-ads-keyframes",
        help="查询 Top Ads 素材逐秒留存、点击或转化曲线",
    )
    top_ads_keyframes.add_argument("material_id")
    top_ads_keyframes.add_argument(
        "--metric",
        action="append",
        choices=(
            "retain_ctr",
            "retain_cvr",
            "click_cnt",
            "convert_cnt",
            "play_retain_cnt",
        ),
        default=[],
    )

    keyword_ideas = subparsers.add_parser(
        "ads-keyword-ideas",
        help="通过 Chrome 查询 Search Ads 关键词搜索量、CPC 和竞争度",
    )
    keyword_ideas.add_argument("keyword", nargs="+", help="种子词，最多 10 个")
    keyword_ideas.add_argument(
        "--country",
        choices=(
            "AE",
            "AU",
            "BR",
            "CA",
            "DE",
            "ES",
            "FR",
            "GB",
            "ID",
            "IT",
            "MX",
            "MY",
            "PH",
            "SA",
            "TH",
            "US",
            "VN",
        ),
        default="US",
    )
    keyword_ideas.add_argument("--language", choices=("en",), default="en")
    keyword_ideas.add_argument(
        "--brand",
        choices=("all", "branded", "non_branded"),
        default="all",
    )
    keyword_ideas.add_argument(
        "--competition",
        action="append",
        choices=("limited", "medium", "high"),
        default=[],
        help="本地筛选竞争度，可重复传入",
    )
    keyword_ideas.add_argument(
        "--sort",
        choices=(
            "default",
            "volume",
            "three_month",
            "yoy",
            "cpc",
            "source",
            "competition",
        ),
        default="default",
    )
    keyword_ideas.add_argument(
        "--order",
        choices=("default", "descending", "ascending"),
        default="default",
    )
    keyword_ideas.add_argument("--limit", type=int, default=50)

    keyword_summary = subparsers.add_parser(
        "ads-keyword-summary",
        help="通过 Chrome 汇总 Search Ads 关键词包的搜索量与预算",
    )
    keyword_summary.add_argument("word", nargs="+")
    keyword_summary.add_argument(
        "--country",
        choices=tuple(
            sorted(
                {
                    "AE",
                    "AU",
                    "BR",
                    "CA",
                    "DE",
                    "ES",
                    "FR",
                    "GB",
                    "ID",
                    "IT",
                    "MX",
                    "MY",
                    "PH",
                    "SA",
                    "TH",
                    "US",
                    "VN",
                }
            )
        ),
        default="US",
    )
    keyword_summary.add_argument(
        "--match-type",
        choices=("exact", "phrase", "broad"),
        default="broad",
    )
    keyword_summary.add_argument("--source-type", type=int, default=1)

    subparsers.add_parser(
        "creative-studio-credits",
        help="通过 Chrome 查询 Symphony Creative Studio 周额度",
    )
    subparsers.add_parser(
        "creative-studio-permissions",
        help="通过 Chrome 查询 Seedance 模型入口权限",
    )
    subparsers.add_parser(
        "creative-studio-limits",
        help="通过 Chrome 查询 Seedance 当前任务数与并发上限",
    )
    subparsers.add_parser(
        "creative-studio-status",
        help="通过 Chrome 汇总 Seedance 权限、积分和并发状态",
    )
    subparsers.add_parser(
        "creative-studio-models",
        help="列出已确认的 Seedance 模型、输入限制和命令覆盖状态",
    )

    studio_prepare = subparsers.add_parser(
        "creative-studio-prepare",
        help="校验 Seedance T2V 权限、积分、并发和输入，不提交任务",
    )
    studio_prepare.add_argument("prompt")
    studio_prepare.add_argument(
        "--duration",
        type=int,
        choices=tuple(range(4, 16)),
        default=5,
        help="视频时长秒数（4..15）",
    )
    studio_prepare.add_argument(
        "--enhance-prompt",
        action="store_true",
        help="预检页面侧提示词增强配置",
    )

    studio_prepare_i2v = subparsers.add_parser(
        "creative-studio-prepare-i2v",
        help="校验 Seedance I2V 首尾帧、权限、积分和并发，不提交任务",
    )
    studio_prepare_i2v.add_argument("prompt")
    studio_prepare_i2v.add_argument("--first-frame-url", required=True)
    studio_prepare_i2v.add_argument("--last-frame-url")
    studio_prepare_i2v.add_argument(
        "--duration",
        type=int,
        choices=tuple(range(4, 16)),
        default=5,
        help="视频时长秒数（4..15）",
    )

    studio_prepare_r2v = subparsers.add_parser(
        "creative-studio-prepare-r2v",
        help="校验 Seedance R2V 已有视频参考与会话，不提交任务",
    )
    studio_prepare_r2v.add_argument("prompt")
    studio_prepare_r2v.add_argument(
        "--reference-vid",
        action="append",
        required=True,
        help="已有 Creative Studio 视频的 vid，可重复传入（1..3 个）",
    )
    studio_prepare_r2v.add_argument(
        "--duration",
        type=int,
        choices=tuple(range(4, 16)),
        default=5,
        help="视频时长秒数（4..15）",
    )

    studio_ledger = subparsers.add_parser(
        "creative-studio-ledger",
        help="通过 Chrome 查询 Symphony 积分流水",
    )
    studio_ledger.add_argument("--cursor")
    studio_ledger.add_argument("--limit", type=int, default=20)

    studio_history = subparsers.add_parser(
        "creative-studio-history",
        help="通过 Chrome 查询可恢复的 Seedance 历史任务",
    )
    studio_history.add_argument("--offset", type=int, default=0)
    studio_history.add_argument("--limit", type=int, default=30)

    studio_detail = subparsers.add_parser(
        "creative-studio-task-detail",
        help="通过 Chrome 按 draft_id 查询 Seedance 历史详情",
    )
    studio_detail.add_argument("draft_id")

    studio_video = subparsers.add_parser(
        "creative-studio-video-info",
        help="通过 Chrome 查询 Seedance 成品视频地址和媒体信息",
    )
    studio_video.add_argument("vid")

    studio_download = subparsers.add_parser(
        "creative-studio-download",
        help="下载 Seedance 成品视频的指定清晰度",
    )
    studio_download.add_argument("vid")
    studio_download.add_argument(
        "--definition",
        help="精确匹配的清晰度，如 720p；省略时使用 video_url 默认变体",
    )
    studio_download.add_argument(
        "--output",
        dest="download_output",
        type=Path,
        required=True,
        help="下载文件路径；已有文件不会覆盖",
    )

    studio_upload = subparsers.add_parser(
        "creative-studio-upload-image",
        help="通过 Chrome 上传一张 Seedance 本机参考图",
    )
    studio_upload.add_argument("image_path")

    studio_generate = subparsers.add_parser(
        "creative-studio-generate",
        help="通过 Chrome 使用 Dreamina Seedance 2.0 创建文生视频",
    )
    studio_generate.add_argument("prompt")
    studio_generate.add_argument(
        "--duration",
        type=int,
        choices=tuple(range(4, 16)),
        default=5,
        help="视频时长秒数（4..15）",
    )
    studio_generate.add_argument(
        "--enhance-prompt",
        action="store_true",
        help="启用页面侧提示词增强",
    )
    studio_generate.add_argument(
        "--wait",
        action="store_true",
        help="轮询到生成成功或失败",
    )
    studio_generate.add_argument("--wait-timeout", type=float, default=900)
    studio_generate.add_argument("--poll-interval", type=float, default=5)

    studio_generate_i2v = subparsers.add_parser(
        "creative-studio-generate-i2v",
        help="通过 Chrome 使用 Seedance 2.0 和首帧或首尾帧创建视频",
    )
    studio_generate_i2v.add_argument("prompt")
    studio_generate_i2v.add_argument("--first-frame-url", required=True)
    studio_generate_i2v.add_argument("--last-frame-url")
    studio_generate_i2v.add_argument(
        "--duration",
        type=int,
        choices=tuple(range(4, 16)),
        default=5,
        help="视频时长秒数（4..15）",
    )
    studio_generate_i2v.add_argument(
        "--wait",
        action="store_true",
        help="轮询到生成成功或失败",
    )
    studio_generate_i2v.add_argument(
        "--wait-timeout",
        type=float,
        default=900,
    )
    studio_generate_i2v.add_argument(
        "--poll-interval",
        type=float,
        default=5,
    )

    studio_task = subparsers.add_parser(
        "creative-studio-task",
        help="通过 Chrome 查询 Seedance 视频生成任务",
    )
    studio_task.add_argument("task_id")
    studio_task.add_argument(
        "--wait",
        action="store_true",
        help="轮询到生成成功或失败",
    )
    studio_task.add_argument("--wait-timeout", type=float, default=900)
    studio_task.add_argument("--poll-interval", type=float, default=5)

    subparsers.add_parser(
        "one-creator-filters",
        help="通过 Chrome 查询 TikTok One 达人筛选目录",
    )

    one_suggest = subparsers.add_parser(
        "one-creator-suggest",
        help="通过 Chrome 查询 TikTok One 达人搜索联想词",
    )
    one_suggest.add_argument("keyword")
    one_suggest.add_argument("--limit", type=int, default=20)

    one_search = subparsers.add_parser(
        "one-creator-search",
        help="通过 Chrome 搜索 TikTok One 达人",
    )
    one_search.add_argument("keyword", nargs="?", default="")
    one_search.add_argument(
        "--country",
        action="append",
        default=[],
        help="创作者所在国家代码，可重复传入",
    )
    one_search.add_argument(
        "--language",
        action="append",
        default=[],
        help="创作者内容语言，可重复传入",
    )
    one_search.add_argument("--min-followers", type=int)
    one_search.add_argument("--max-followers", type=int)
    one_search.add_argument("--min-median-views", type=int)
    one_search.add_argument("--max-median-views", type=int)
    one_search.add_argument("--min-engagement-rate", type=float)
    one_search.add_argument("--max-engagement-rate", type=float)
    one_search.add_argument(
        "--sort",
        choices=(
            "relevance",
            "followers",
            "average_views",
            "engagement",
            "median_views",
            "price",
            "recent_video_count",
            "submission_rate",
            "audience_relevance",
            "creator_value",
        ),
        default="relevance",
    )
    one_search.add_argument(
        "--sort-direction",
        choices=("descending", "ascending"),
        default="descending",
    )
    one_search.add_argument("--page", type=int, default=1)
    one_search.add_argument("--limit", type=int, default=24)

    tag = subparsers.add_parser("tag", help="查询公开标签元数据")
    tag.add_argument("tag_name")

    tag_videos = subparsers.add_parser("tag-videos", help="按标签 ID 查询视频")
    tag_videos.add_argument("tag_id")
    tag_videos.add_argument("--limit", type=int, default=30)
    tag_videos.add_argument("--page-size", type=int, default=30)

    music = subparsers.add_parser("music", help="查询公开音乐元数据")
    music.add_argument("music_id")

    music_videos = subparsers.add_parser(
        "music-videos", help="按音乐 ID 查询视频"
    )
    music_videos.add_argument("music_id")
    music_videos.add_argument("--limit", type=int, default=30)
    music_videos.add_argument("--page-size", type=int, default=30)

    comments = subparsers.add_parser("comments", help="查询一个视频的评论")
    comments.add_argument("video_url_or_id")
    comments.add_argument(
        "--include-replies",
        action="store_true",
        help="查询已有回复的评论",
    )
    comments.add_argument(
        "--reply-limit",
        type=int,
        help="每条一级评论最多收集的回复数",
    )
    comments.add_argument(
        "--reply-page-size",
        type=int,
        default=20,
        help="每次 API 调用请求的回复数（限制为 20..50）",
    )
    comments.add_argument("--limit", type=int)
    comments.add_argument("--page-size", type=int, default=20)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {
        "timeout": args.timeout,
        "request_interval": args.request_interval,
    }
    commercial_platform = _COMMERCIAL_PLATFORMS.get(args.command)
    if commercial_platform:
        interactive_login = False if args.no_browser_login else None
        options["creative_fetch"] = _creative_fetch(
            commercial_platform,
            args.request_interval,
            interactive_login=interactive_login,
            login_timeout=args.browser_login_timeout,
        )
    client = TikTokClient(**options)
    if args.command == "videos":
        return client.get_user_videos(
            args.profile_url,
            limit=args.limit,
            page_size=args.page_size,
        )
    if args.command == "video":
        return client.get_video(args.video_url_or_id)
    if args.command == "search-videos":
        return client.search_videos(
            args.keyword,
            limit=args.limit,
            page_size=args.page_size,
        )
    if args.command == "search-general":
        return client.search_general(
            args.keyword,
            limit=args.limit,
            offset=args.offset,
            search_id=args.search_id,
        )
    if args.command == "search-users":
        return client.search_users(
            args.keyword,
            limit=args.limit,
            offset=args.offset,
            search_id=args.search_id,
        )
    if args.command == "search-music":
        return client.search_music(
            args.keyword,
            limit=args.limit,
            offset=args.offset,
            search_id=args.search_id,
        )
    if args.command == "search-live":
        return client.search_live(
            args.keyword,
            limit=args.limit,
            offset=args.offset,
            search_id=args.search_id,
        )
    if args.command == "search-photo":
        return client.search_photos(
            args.keyword,
            limit=args.limit,
            offset=args.offset,
            search_id=args.search_id,
        )
    if args.command == "search-suggest":
        return client.search_suggestions(
            args.keyword,
            limit=args.limit,
        )
    if args.command == "trending-searchwords":
        return client.get_trending_search_words(
            region=args.region,
            limit=args.limit,
        )
    if args.command == "creative-trending-hashtags":
        return client.get_creative_trending_hashtags(
            country=args.country,
            time_range=args.time_range,
            industry_id=args.industry_id,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "creative-trending-hashtags-full":
        return client.get_creative_trending_hashtags_full(
            country=args.country,
            time_range=args.time_range,
            industry_id=args.industry_id,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "creative-trending-videos":
        return client.get_creative_trending_videos(
            country=args.country,
            time_range=args.time_range,
            metric=args.metric,
            content_label_ids=args.content_label_ids,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "creative-trending-videos-full":
        return client.get_creative_trending_videos_full(
            country=args.country,
            time_range=args.time_range,
            metric=args.metric,
            content_label_ids=args.content_label_ids,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "creative-trending-video-detail":
        return client.get_creative_trending_video_detail(
            args.item_id,
            country=args.country,
            time_range=args.time_range,
        )
    if args.command == "creative-hashtag-detail":
        return client.get_creative_hashtag_detail(
            args.hashtag_id,
            country=args.country,
            time_range=args.time_range,
        )
    if args.command == "creative-top-ads-filters":
        return client.get_creative_top_ads_filters()
    if args.command == "creative-top-ads-suggest":
        return client.get_creative_top_ads_suggestions(
            args.keyword,
            country=args.country,
            limit=args.limit,
        )
    if args.command == "creative-top-ads":
        return client.get_creative_top_ads(
            args.search_word,
            countries=args.country,
            time_range=args.time_range,
            industry_label_ids=args.industry_label_ids,
            objectives=args.objectives,
            ad_format=args.ad_format,
            duration=args.duration,
            like_range=args.like_range,
            pattern_label_ids=args.pattern_label_ids,
            languages=args.language,
            order=args.order,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "creative-top-ads-performance":
        return client.get_creative_top_ads_performance(
            args.search_word,
            countries=args.country,
            time_range=args.time_range,
            industry_label_ids=args.industry_label_ids,
            objectives=args.objectives,
            ad_format=args.ad_format,
            like_count_filter=args.like_count_filter,
            order=args.order,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "creative-top-ads-detail":
        return client.get_creative_top_ads_detail(
            args.material_id,
            country=args.country,
            time_range=args.time_range,
            metrics=args.metric or ("retain_ctr", "play_retain_cnt"),
            include_recommendations=not args.no_recommendations,
            include_ai_analysis=not args.no_ai_analysis,
        )
    if args.command == "creative-top-ads-keyframes":
        return client.get_creative_top_ads_keyframes(
            args.material_id,
            metrics=args.metric or ("retain_ctr",),
        )
    if args.command == "ads-keyword-ideas":
        return client.get_ads_keyword_ideas(
            args.keyword,
            country=args.country,
            language=args.language,
            brand=args.brand,
            competitions=args.competition or ("limited", "medium", "high"),
            sort=args.sort,
            order=args.order,
            limit=args.limit,
        )
    if args.command == "ads-keyword-summary":
        return client.get_ads_keyword_summary(
            args.word,
            country=args.country,
            match_type=args.match_type,
            source_type=args.source_type,
        )
    if args.command == "creative-studio-credits":
        return client.get_creative_studio_credits()
    if args.command == "creative-studio-permissions":
        return client.get_creative_studio_permissions()
    if args.command == "creative-studio-limits":
        return client.get_creative_studio_generation_limits()
    if args.command == "creative-studio-status":
        return client.get_creative_studio_status()
    if args.command == "creative-studio-models":
        return client.get_creative_studio_models()
    if args.command == "creative-studio-prepare":
        return client.prepare_creative_studio_video(
            args.prompt,
            duration=args.duration,
            enhance_prompt=args.enhance_prompt,
        )
    if args.command == "creative-studio-prepare-i2v":
        return client.prepare_creative_studio_i2v(
            args.prompt,
            first_frame_url=args.first_frame_url,
            last_frame_url=args.last_frame_url,
            duration=args.duration,
        )
    if args.command == "creative-studio-prepare-r2v":
        return client.prepare_creative_studio_r2v(
            args.prompt,
            reference_vids=args.reference_vid,
            duration=args.duration,
        )
    if args.command == "creative-studio-ledger":
        return client.get_creative_studio_credit_ledger(
            cursor=args.cursor,
            limit=args.limit,
        )
    if args.command == "creative-studio-history":
        return client.get_creative_studio_history(
            offset=args.offset,
            limit=args.limit,
        )
    if args.command == "creative-studio-task-detail":
        return client.get_creative_studio_task_detail(args.draft_id)
    if args.command == "creative-studio-video-info":
        return client.get_creative_studio_video_info(args.vid)
    if args.command == "creative-studio-download":
        return client.download_creative_studio_video(
            args.vid,
            definition=args.definition,
            output_path=args.download_output,
        )
    if args.command == "creative-studio-upload-image":
        return client.upload_creative_studio_image(args.image_path)
    if args.command == "creative-studio-generate":
        return client.create_creative_studio_video(
            args.prompt,
            duration=args.duration,
            enhance_prompt=args.enhance_prompt,
            wait=args.wait,
            wait_timeout=args.wait_timeout,
            poll_interval=args.poll_interval,
        )
    if args.command == "creative-studio-generate-i2v":
        return client.create_creative_studio_i2v(
            args.prompt,
            first_frame_url=args.first_frame_url,
            last_frame_url=args.last_frame_url,
            duration=args.duration,
            wait=args.wait,
            wait_timeout=args.wait_timeout,
            poll_interval=args.poll_interval,
        )
    if args.command == "creative-studio-task":
        return client.get_creative_studio_task(
            args.task_id,
            wait=args.wait,
            wait_timeout=args.wait_timeout,
            poll_interval=args.poll_interval,
        )
    if args.command == "one-creator-filters":
        return client.get_one_creator_filters()
    if args.command == "one-creator-suggest":
        return client.get_one_creator_suggestions(
            args.keyword,
            limit=args.limit,
        )
    if args.command == "one-creator-search":
        return client.search_one_creators(
            args.keyword,
            countries=args.country,
            languages=args.language,
            min_followers=args.min_followers,
            max_followers=args.max_followers,
            min_median_views=args.min_median_views,
            max_median_views=args.max_median_views,
            min_engagement_rate=args.min_engagement_rate,
            max_engagement_rate=args.max_engagement_rate,
            sort=args.sort,
            sort_direction=args.sort_direction,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "tag":
        return client.get_tag(args.tag_name)
    if args.command == "tag-videos":
        return client.get_tag_videos(
            args.tag_id,
            limit=args.limit,
            page_size=args.page_size,
        )
    if args.command == "music":
        return client.get_music(args.music_id)
    if args.command == "music-videos":
        return client.get_music_videos(
            args.music_id,
            limit=args.limit,
            page_size=args.page_size,
        )
    if args.command == "comments":
        return client.get_comments(
            args.video_url_or_id,
            include_replies=args.include_replies,
            reply_limit=args.reply_limit,
            reply_page_size=args.reply_page_size,
            limit=args.limit,
            page_size=args.page_size,
        )
    raise AssertionError(f"unsupported command: {args.command}")


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except TikTokError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
