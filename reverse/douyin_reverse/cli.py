from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..browser_progress import stderr_progress
from ..browser_session import BrowserSessionError, call_daemon, start_daemon
from .client import DouyinClient
from .errors import DouyinError, DouyinResponseError


_BROWSER_COMMANDS = frozenset(
    {
        "user-posts",
        "comments",
        "comment-replies",
        "search-videos",
        "keyword-trend",
    }
)


def _request_interval(value: str) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("请求间隔必须是秒数") from exc
    if not math.isfinite(interval) or not 0 <= interval <= 10:
        raise argparse.ArgumentTypeError("请求间隔必须在 0 到 10 秒之间")
    return interval


def _add_browser_paging(
    parser: argparse.ArgumentParser,
    *,
    page_size: int,
) -> None:
    parser.add_argument("--limit", type=int, default=20, help="最多返回条目数")
    parser.add_argument("--after", default="0", help="非负十进制分页游标")
    parser.add_argument(
        "--page-size",
        type=int,
        default=page_size,
        help="每次浏览器请求的条目数",
    )
    parser.add_argument(
        "--request-interval",
        type=_request_interval,
        default=3.0,
        help="同一抖音浏览器请求的最小启动间隔秒数（0..10）",
    )


def _browser_fetch(
    request_interval: float,
    *,
    platform: str = "douyin",
) -> Callable[
    [str, Sequence[tuple[str, str]], str],
    Mapping[str, Any],
]:
    started = False
    report_progress = stderr_progress()

    def fetch(
        path: str,
        entries: Sequence[tuple[str, str]],
        referer: str,
    ) -> Mapping[str, Any]:
        nonlocal started
        request = {
            "op": "request",
            "platform": platform,
            "path": path,
            "entries": [list(entry) for entry in entries],
            "referer": referer,
            "method": "GET",
            "request_interval_ms": round(request_interval * 1000),
        }
        result: Any = None
        for attempt in range(2):
            try:
                if not started:
                    start_daemon()
                    started = True
                result = asyncio.run(
                    call_daemon(request, progress=report_progress)
                )
                break
            except BrowserSessionError as exc:
                if attempt == 0 and exc.code == "daemon_unavailable":
                    started = False
                    continue
                raise DouyinResponseError(
                    f"抖音浏览器会话请求失败 ({exc.code}): {exc}"
                ) from exc
        if not isinstance(result, Mapping):
            raise DouyinResponseError("抖音浏览器会话响应不是对象")
        return result

    return fetch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Douyin 匿名移动分享页与公开资料客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument(
        "--proxy",
        default=os.environ.get("DOUYIN_PROXY") or os.environ.get("REVERSE_PROXY"),
        help="HTTP/SOCKS 代理；默认依次读取 DOUYIN_PROXY、REVERSE_PROXY",
    )
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    resolve = commands.add_parser("resolve", help="解析 aweme id、URL 或短链接")
    resolve.add_argument("aweme_reference")

    aweme = commands.add_parser("aweme", help="查询单个公开视频或图文")
    aweme.add_argument("aweme_reference")

    video = commands.add_parser("video", help="aweme 命令的别名")
    video.add_argument("aweme_reference")

    profile = commands.add_parser("profile", help="按 sec_uid 查询公开资料")
    profile.add_argument("user_reference")

    author = commands.add_parser(
        "author", help="查询 aweme 作者的公开资料"
    )
    author.add_argument("aweme_reference")

    batch_awemes = commands.add_parser(
        "batch-awemes", help="批量查询最多 20 个公开 aweme"
    )
    batch_awemes.add_argument("aweme_references", nargs="+")

    batch_profiles = commands.add_parser(
        "batch-profiles", help="批量查询最多 20 个公开资料"
    )
    batch_profiles.add_argument("user_references", nargs="+")

    stats = commands.add_parser("stats", help="查询单个 aweme 的公开统计")
    stats.add_argument("aweme_reference")

    batch_stats = commands.add_parser(
        "batch-stats", help="批量查询最多 20 个 aweme 的公开统计"
    )
    batch_stats.add_argument("aweme_references", nargs="+")

    extract_aweme = commands.add_parser(
        "extract-aweme-ids", help="从复制文本中提取全部 aweme id"
    )
    extract_aweme.add_argument("text")

    extract_users = commands.add_parser(
        "extract-sec-uids", help="从复制文本中提取全部 sec_uid"
    )
    extract_users.add_argument("text")

    user_posts = commands.add_parser(
        "user-posts",
        help="通过 Chrome 登录态查询用户作品列表",
    )
    user_posts.add_argument("user_reference")
    _add_browser_paging(user_posts, page_size=18)

    comments = commands.add_parser(
        "comments",
        help="通过 Chrome 登录态查询作品一级评论",
    )
    comments.add_argument("aweme_reference")
    _add_browser_paging(comments, page_size=20)
    comments.add_argument(
        "--include-replies",
        action="store_true",
        help="自动查询每条一级评论的二级回复",
    )
    comments.add_argument(
        "--reply-limit",
        type=int,
        default=200,
        help="每条一级评论最多查询的回复数（0..200）",
    )
    comments.add_argument(
        "--reply-page-size",
        type=int,
        default=20,
        help="回复每页条目数（1..50）",
    )

    comment_replies = commands.add_parser(
        "comment-replies",
        help="通过 Chrome 登录态查询指定评论的二级回复",
    )
    comment_replies.add_argument("aweme_reference")
    comment_replies.add_argument("comment_id")
    _add_browser_paging(comment_replies, page_size=20)

    search_videos = commands.add_parser(
        "search-videos",
        help="通过 Chrome 登录态搜索抖音视频",
    )
    search_videos.add_argument("keyword")
    _add_browser_paging(search_videos, page_size=10)
    search_videos.add_argument(
        "--sort-type",
        type=int,
        choices=(0, 1, 2),
        default=0,
        help="排序方式：0 综合、1 最多点赞、2 最新发布",
    )
    search_videos.add_argument(
        "--publish-time",
        type=int,
        choices=(0, 1, 7, 30, 180),
        default=0,
        help="发布时间筛选天数；0 表示不限",
    )

    keyword_trend = commands.add_parser(
        "keyword-trend",
        help="通过 Chrome 创作者中心查询关键词趋势",
    )
    keyword_trend.add_argument("keywords", nargs="+", help="最多五个关键词")
    keyword_trend.add_argument(
        "--start-date",
        required=True,
        help="开始日期，格式 YYYYMMDD",
    )
    keyword_trend.add_argument(
        "--end-date",
        required=True,
        help="结束日期，格式 YYYYMMDD",
    )
    keyword_trend.add_argument(
        "--region",
        action="append",
        default=[],
        help="地区名称，可重复传入",
    )
    keyword_trend.add_argument(
        "--app-name",
        choices=("aweme", "toutiao"),
        default="aweme",
        help="指数数据源",
    )
    keyword_trend.add_argument(
        "--request-interval",
        type=_request_interval,
        default=3.0,
        help="同一抖音浏览器请求的最小启动间隔秒数（0..10）",
    )

    hot = commands.add_parser("hot", help="查询公开热搜榜")
    hot.add_argument("--limit", type=int, default=50)
    return parser


def _client(args: argparse.Namespace) -> DouyinClient:
    options: dict[str, Any] = {
        "timeout": args.timeout,
        "retries": args.retries,
        "proxy": args.proxy,
    }
    if args.command in _BROWSER_COMMANDS:
        if args.command == "keyword-trend":
            options["index_fetch"] = _browser_fetch(
                args.request_interval,
                platform="douyin_index",
            )
        else:
            options["web_fetch"] = _browser_fetch(args.request_interval)
    return DouyinClient(
        **options,
    )


def _dispatch(client: DouyinClient, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "resolve":
        return client.resolve_aweme_reference(args.aweme_reference)
    if args.command in {"aweme", "video"}:
        return client.get_aweme(args.aweme_reference)
    if args.command == "profile":
        return client.get_profile(args.user_reference)
    if args.command == "author":
        return client.get_author_profile(args.aweme_reference)
    if args.command == "batch-awemes":
        return client.get_awemes(args.aweme_references)
    if args.command == "batch-profiles":
        return client.get_profiles(args.user_references)
    if args.command == "stats":
        return client.get_aweme_statistics(args.aweme_reference)
    if args.command == "batch-stats":
        return client.get_aweme_statistics_batch(args.aweme_references)
    if args.command == "extract-aweme-ids":
        return client.extract_aweme_ids(args.text)
    if args.command == "extract-sec-uids":
        return client.extract_sec_uids(args.text)
    if args.command == "user-posts":
        return client.get_user_posts(
            args.user_reference,
            limit=args.limit,
            cursor=args.after,
            page_size=args.page_size,
        )
    if args.command == "comments":
        return client.get_comments(
            args.aweme_reference,
            limit=args.limit,
            cursor=args.after,
            page_size=args.page_size,
            include_replies=args.include_replies,
            reply_limit=args.reply_limit,
            reply_page_size=args.reply_page_size,
        )
    if args.command == "comment-replies":
        return client.get_comment_replies(
            args.aweme_reference,
            args.comment_id,
            limit=args.limit,
            cursor=args.after,
            page_size=args.page_size,
        )
    if args.command == "search-videos":
        return client.search_videos(
            args.keyword,
            limit=args.limit,
            cursor=args.after,
            page_size=args.page_size,
            sort_type=args.sort_type,
            publish_time=args.publish_time,
        )
    if args.command == "keyword-trend":
        return client.get_keyword_trend(
            args.keywords,
            start_date=args.start_date,
            end_date=args.end_date,
            regions=args.region,
            app_name=args.app_name,
        )
    return client.get_hot_searches(limit=args.limit)


def _run(args: argparse.Namespace) -> dict[str, Any]:
    return _dispatch(_client(args), args)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except DouyinError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
