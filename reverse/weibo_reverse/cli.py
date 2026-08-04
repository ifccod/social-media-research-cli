from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import WeiboClient
from .errors import WeiboError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微博移动网页 JSON 匿名客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("config", help="查询公开频道配置")

    channel = commands.add_parser("channel", help="查询已配置频道的信息流")
    channel.add_argument("channel_name", nargs="?", help="频道名或容器 ID")
    channel.add_argument("--page", type=int, default=1)
    channel.add_argument("--limit", type=int, default=20)

    trend = commands.add_parser("trend", help="直接查询频道容器")
    trend.add_argument("container_id")
    trend.add_argument("--page", type=int, default=1)
    trend.add_argument("--limit", type=int, default=20)

    user = commands.add_parser("user", help="查询公开用户资料")
    user.add_argument("uid_or_url")

    posts = commands.add_parser("user-posts", help="查询用户的公开帖子")
    posts.add_argument("uid_or_url")
    posts.add_argument("--page", type=int, default=1)
    posts.add_argument("--since-id")
    posts.add_argument("--limit", type=int, default=20)

    post = commands.add_parser("post", help="查询一条公开帖子")
    post.add_argument("post_id_or_url")

    comments = commands.add_parser("comments", help="查询公开帖子评论")
    comments.add_argument("post_id_or_url")
    comments.add_argument("--mid")
    comments.add_argument("--max-id")
    comments.add_argument("--max-id-type", type=int, choices=(0, 1), default=0)
    comments.add_argument("--limit", type=int, default=20)

    replies = commands.add_parser("replies", help="查询一级评论的回复")
    replies.add_argument("cid")
    replies.add_argument("--max-id", default="0")
    replies.add_argument("--max-id-type", type=int, choices=(0, 1), default=0)
    replies.add_argument("--limit", type=int, default=20)

    search = commands.add_parser("search", help="搜索微博公开内容")
    search.add_argument("keyword")
    search.add_argument("--page", type=int, default=1)
    search.add_argument(
        "--type",
        dest="search_type",
        choices=("1", "61", "3", "60", "64", "63", "21"),
        default="1",
    )
    search.add_argument("--time", dest="time_scope", choices=("hour", "day", "week", "month"))
    search.add_argument("--limit", type=int, default=20)

    commands.add_parser("hot", help="查询公开实时热搜榜")
    return parser


def _run(args: argparse.Namespace) -> Any:
    client = WeiboClient(timeout=args.timeout, retries=args.retries)
    if args.command == "config":
        return client.get_config()
    if args.command == "channel":
        return client.get_channel_feed(
            args.channel_name,
            page=args.page,
            limit=args.limit,
        )
    if args.command == "trend":
        return client.get_trend_top(args.container_id, page=args.page, limit=args.limit)
    if args.command == "user":
        return client.get_user(args.uid_or_url)
    if args.command == "user-posts":
        return client.get_user_posts(
            args.uid_or_url,
            page=args.page,
            since_id=args.since_id,
            limit=args.limit,
        )
    if args.command == "post":
        return client.get_post(args.post_id_or_url)
    if args.command == "comments":
        return client.get_comments(
            args.post_id_or_url,
            mid=args.mid,
            max_id=args.max_id,
            max_id_type=args.max_id_type,
            limit=args.limit,
        )
    if args.command == "replies":
        return client.get_comment_replies(
            args.cid,
            max_id=args.max_id,
            max_id_type=args.max_id_type,
            limit=args.limit,
        )
    if args.command == "search":
        return client.search(
            args.keyword,
            page=args.page,
            search_type=args.search_type,
            time_scope=args.time_scope,
            limit=args.limit,
        )
    return client.get_hot_search()


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except WeiboError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
