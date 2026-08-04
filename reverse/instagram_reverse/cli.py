from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import InstagramClient
from .errors import InstagramError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Instagram 匿名公开数据客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="429、5xx 和传输错误的重试次数",
    )
    parser.add_argument(
        "--initialize-session",
        action="store_true",
        help="查询前通过一次 HTTP 请求初始化匿名 Cookie",
    )
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="查询单个公开资料")
    profile.add_argument("username_or_url")

    page = commands.add_parser(
        "profile-page", help="查询公开资料及首屏帖子"
    )
    page.add_argument("username_or_url")
    page.add_argument("--limit", type=int, default=12)

    posts = commands.add_parser("posts", help="查询公开帖子首屏")
    posts.add_argument("username_or_url")
    posts.add_argument("--limit", type=int, default=12)

    post = commands.add_parser(
        "post", help="按 shortcode 或 URL 查询单个公开帖子"
    )
    post.add_argument("shortcode_or_url")

    to_id = commands.add_parser(
        "shortcode-to-id", help="在本地将 shortcode 转为 media id"
    )
    to_id.add_argument("shortcode_or_url")

    to_code = commands.add_parser(
        "id-to-shortcode", help="在本地将 media id 转为 shortcode"
    )
    to_code.add_argument("media_id")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = InstagramClient(timeout=args.timeout, retries=args.retries)
    if args.initialize_session and args.command in {"profile", "profile-page", "posts", "post"}:
        client.initialize_session()
    if args.command == "profile":
        return client.get_user_profile(args.username_or_url)
    if args.command == "profile-page":
        return client.get_profile_page(args.username_or_url, limit=args.limit)
    if args.command == "posts":
        return client.get_user_posts(args.username_or_url, limit=args.limit)
    if args.command == "post":
        return client.get_post(args.shortcode_or_url)
    if args.command == "shortcode-to-id":
        shortcode = client.resolve_shortcode(args.shortcode_or_url)
        return {"shortcode": shortcode, "media_id": client.shortcode_to_media_id(shortcode)}
    shortcode = client.media_id_to_shortcode(args.media_id)
    return {"media_id": str(int(args.media_id)), "shortcode": shortcode}


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except InstagramError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
