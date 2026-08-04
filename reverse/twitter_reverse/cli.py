from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..browser_progress import stderr_progress
from ..browser_session import BrowserSessionError, call_daemon, start_daemon
from .client import (
    TWITTER_HOME_FEED_PATH,
    TwitterClient,
    parse_tweet_id,
)
from .errors import TwitterError, TwitterResponseError
from .signer import TwitterSyndicationSigner


_BROWSER_COMMANDS = frozenset({"home-feed", "search-posts"})


def _request_interval(value: str) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("请求间隔必须是秒数") from exc
    if not math.isfinite(interval) or not 0 <= interval <= 10:
        raise argparse.ArgumentTypeError("请求间隔必须在 0 到 10 秒之间")
    return interval


def _browser_fetch(
    request_interval: float,
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
            "platform": (
                "twitter_home"
                if path == TWITTER_HOME_FEED_PATH
                else "twitter_search"
            ),
            "path": path,
            "entries": [list(entry) for entry in entries],
            "referer": referer,
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
                raise TwitterResponseError(
                    f"X 浏览器会话请求失败 ({exc.code}): {exc}"
                ) from exc
        if not isinstance(result, Mapping):
            raise TwitterResponseError("X 浏览器会话响应不是对象")
        return result

    return fetch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="X/Twitter Syndication 与网页趋势匿名客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--lang", default="en", help="Syndication 语言标签")
    parser.add_argument(
        "--request-interval",
        type=_request_interval,
        default=3.0,
        help="同一 X 浏览器请求的最小启动间隔秒数（0..10）",
    )
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    tweet = commands.add_parser("tweet", help="查询并规范化一条公开帖子")
    tweet.add_argument("tweet_url_or_id")

    raw = commands.add_parser("raw", help="查询原始 Syndication JSON")
    raw.add_argument("tweet_url_or_id")

    token = commands.add_parser("token", help="在本地计算 Syndication 令牌")
    token.add_argument("tweet_url_or_id")

    trending = commands.add_parser(
        "trending",
        help="读取 X 支持地区的当前趋势",
    )
    trending.add_argument(
        "location",
        nargs="?",
        default="United States",
        help="国家、城市、国家代码或数字 WOEID",
    )
    trending.add_argument("--limit", type=int, default=20)

    locations = commands.add_parser(
        "trend-locations",
        help="列出 X 趋势接口支持的地区",
    )
    locations.add_argument("--country", default="")
    locations.add_argument("--limit", type=int)

    home = commands.add_parser(
        "home-feed",
        help="通过 Chrome 登录态读取 X For You 推荐流",
    )
    home.add_argument("--limit", type=int, default=20)
    home.add_argument("--cursor")

    search = commands.add_parser(
        "search-posts",
        help="通过 Chrome 登录态主动搜索 X 帖子",
    )
    search.add_argument("query")
    search.add_argument(
        "--product",
        choices=("top", "latest"),
        default="top",
    )
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--cursor")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {
        "timeout": args.timeout,
        "retries": args.retries,
    }
    if args.command in _BROWSER_COMMANDS:
        options["browser_fetch"] = _browser_fetch(args.request_interval)
    client = TwitterClient(**options)
    if args.command == "home-feed":
        return client.get_home_feed(
            limit=args.limit,
            cursor=args.cursor,
        )
    if args.command == "search-posts":
        return client.search_posts(
            args.query,
            product=args.product,
            limit=args.limit,
            cursor=args.cursor,
        )
    if args.command == "trending":
        return client.get_trending(args.location, limit=args.limit)
    if args.command == "trend-locations":
        return client.get_trend_locations(
            country=args.country,
            limit=args.limit,
        )

    identifier = parse_tweet_id(args.tweet_url_or_id)
    if args.command == "token":
        return TwitterSyndicationSigner.sign(identifier)
    if args.command == "raw":
        return client.get_tweet_raw(identifier, language=args.lang)
    return client.get_tweet(identifier, language=args.lang)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except TwitterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
