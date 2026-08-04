from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .client import RedditClient
from .errors import RedditError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reddit 公开 JSON 匿名客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument(
        "--proxy",
        default=os.environ.get("REDDIT_OPPORTUNITY_PROXY"),
        help="HTTP/SOCKS 代理；默认读取 REDDIT_OPPORTUNITY_PROXY",
    )
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    subreddit = commands.add_parser("subreddit", help="查询公开版块信息流")
    subreddit.add_argument("subreddit")
    subreddit.add_argument("--sort", choices=("hot", "new", "top", "rising", "controversial"), default="hot")
    subreddit.add_argument("--time", dest="time_filter", choices=("hour", "day", "week", "month", "year", "all"), default="all")
    subreddit.add_argument("--limit", type=int, default=25)
    subreddit.add_argument("--after")

    batch_info = commands.add_parser(
        "batch-info", help="单次查询最多 30 条公开帖子或评论"
    )
    batch_info.add_argument(
        "fullnames", nargs="+", help="t3_/t1_ 完整名称，以空格或逗号分隔"
    )

    post = commands.add_parser("post", help="查询一条公开帖子及其评论")
    post.add_argument("post_url_or_id")
    post.add_argument("--comment-limit", type=int, default=100)
    post.add_argument("--depth", type=int)
    post.add_argument("--sort", choices=("confidence", "top", "new", "controversial", "old", "qa"), default="confidence")

    more_comments = commands.add_parser(
        "more-comments", help="通过 morechildren 展开公开评论"
    )
    more_comments.add_argument("post_url_or_id")
    more_comments.add_argument(
        "comment_ids", nargs="+", help="评论 ID 或 t1_ 完整名称"
    )
    more_comments.add_argument(
        "--sort",
        choices=("confidence", "top", "new", "controversial", "old", "qa"),
        default="confidence",
    )

    user = commands.add_parser("user", help="查询公开用户资料")
    user.add_argument("username_or_url")

    trophies = commands.add_parser(
        "user-trophies", help="查询用户的公开奖杯"
    )
    trophies.add_argument("username_or_url")

    submitted = commands.add_parser("user-posts", help="查询用户公开发布的帖子")
    submitted.add_argument("username_or_url")
    submitted.add_argument("--limit", type=int, default=25)
    submitted.add_argument("--after")

    comments = commands.add_parser("user-comments", help="查询用户的公开评论")
    comments.add_argument("username")
    comments.add_argument(
        "--sort", choices=("hot", "new", "top", "controversial"), default="new"
    )
    comments.add_argument(
        "--time",
        dest="time_filter",
        choices=("hour", "day", "week", "month", "year", "all"),
        default="all",
    )
    comments.add_argument("--limit", type=int, default=25)
    comments.add_argument("--after")

    subreddit_info = commands.add_parser(
        "subreddit-info", help="查询公开版块元数据"
    )
    subreddit_info.add_argument("subreddit")

    subreddit_rules = commands.add_parser(
        "subreddit-rules", help="查询公开版块规则"
    )
    subreddit_rules.add_argument("subreddit")

    subreddit_settings = commands.add_parser(
        "subreddit-settings", help="查询公开版块设置"
    )
    subreddit_settings.add_argument("subreddit_fullname")

    typeahead = commands.add_parser(
        "typeahead", help="查询公开用户和版块建议"
    )
    typeahead.add_argument("query")
    typeahead.add_argument("--limit", type=int, default=10)
    typeahead.add_argument(
        "--safe-search", choices=("unset", "strict"), default="unset"
    )
    typeahead.add_argument("--allow-nsfw", action="store_true")

    search = commands.add_parser("search", help="搜索 Reddit 公开帖子")
    search.add_argument("query")
    search.add_argument("--subreddit")
    search.add_argument("--sort", choices=("relevance", "hot", "top", "new", "comments"), default="relevance")
    search.add_argument("--time", dest="time_filter", choices=("hour", "day", "week", "month", "year", "all"), default="all")
    search.add_argument("--limit", type=int, default=25)
    search.add_argument("--after")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = RedditClient(timeout=args.timeout, retries=args.retries, proxy=args.proxy)
    if args.command == "subreddit":
        return client.get_subreddit(
            args.subreddit,
            sort=args.sort,
            time_filter=args.time_filter,
            limit=args.limit,
            after=args.after,
        )
    if args.command == "batch-info":
        return client.get_batch_info(args.fullnames)
    if args.command == "post":
        return client.get_post(
            args.post_url_or_id,
            comment_limit=args.comment_limit,
            depth=args.depth,
            sort=args.sort,
        )
    if args.command == "more-comments":
        return client.get_more_comments(
            args.post_url_or_id,
            args.comment_ids,
            sort=args.sort,
        )
    if args.command == "user":
        return client.get_user(args.username_or_url)
    if args.command == "user-trophies":
        return client.get_user_trophies(args.username_or_url)
    if args.command == "user-posts":
        return client.get_user_posts(
            args.username_or_url, limit=args.limit, after=args.after
        )
    if args.command == "user-comments":
        return client.get_user_comments(
            args.username,
            sort=args.sort,
            time_filter=args.time_filter,
            limit=args.limit,
            after=args.after,
        )
    if args.command == "subreddit-info":
        return client.get_subreddit_info(args.subreddit)
    if args.command == "subreddit-rules":
        return client.get_subreddit_rules(args.subreddit)
    if args.command == "subreddit-settings":
        return client.get_subreddit_settings(args.subreddit_fullname)
    if args.command == "typeahead":
        return client.typeahead(
            args.query,
            limit=args.limit,
            safe_search=args.safe_search,
            allow_nsfw=args.allow_nsfw,
        )
    if args.command == "search":
        return client.search(
            args.query,
            subreddit=args.subreddit,
            sort=args.sort,
            time_filter=args.time_filter,
            limit=args.limit,
            after=args.after,
        )
    raise RuntimeError(f"unsupported Reddit command: {args.command}")


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except RedditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
