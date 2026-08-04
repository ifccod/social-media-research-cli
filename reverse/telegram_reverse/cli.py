from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import TelegramClient
from .errors import TelegramError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram 公开频道匿名客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    channel = commands.add_parser("channel", help="查询公开频道元数据")
    channel.add_argument("channel")

    channels = commands.add_parser("channels", help="查询多个公开频道")
    channels.add_argument("channels", nargs="+")

    posts = commands.add_parser("posts", help="按从新到旧查询公开帖子")
    posts.add_argument("channel")
    posts.add_argument("--before", help="返回早于此帖子 ID 的帖子")
    posts.add_argument("--limit", type=int, default=20)

    search = commands.add_parser("search", help="搜索频道近期公开帖子")
    search.add_argument("channel")
    search.add_argument("query")
    search.add_argument("--before", help="返回早于此帖子 ID 的匹配帖子")
    search.add_argument("--limit", type=int, default=20)

    post = commands.add_parser("post", help="查询一条公开帖子")
    post.add_argument("post_ref", help="channel/post_id 或 t.me 帖子 URL")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = TelegramClient(timeout=args.timeout, retries=args.retries)
    if args.command == "channel":
        return client.get_channel(args.channel)
    if args.command == "channels":
        return client.get_channels(args.channels)
    if args.command == "posts":
        return client.get_posts(args.channel, before=args.before, limit=args.limit)
    if args.command == "search":
        return client.search(args.channel, args.query, before=args.before, limit=args.limit)
    return client.get_post(args.post_ref)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except TelegramError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
