from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import XiguaClient
from .errors import XiguaError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="西瓜视频移动端公开数据匿名客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    video = commands.add_parser("video", help="查询规范化的公开视频信息")
    video.add_argument("reference", help="视频 ID 或西瓜视频公开 URL")

    raw = commands.add_parser("video-raw", help="查询已校验的原始视频数据对象")
    raw.add_argument("reference")

    play = commands.add_parser("play", help="提取并在本地解密公开播放 URL")
    play.add_argument("reference")

    comments = commands.add_parser("comments", help="查询公开视频评论")
    comments.add_argument("reference")
    comments.add_argument("--offset", type=int, default=0)
    comments.add_argument("--count", type=int, default=20)

    user = commands.add_parser("user", help="查询公开用户资料")
    user.add_argument("reference", help="用户 ID 或西瓜视频公开用户 URL")

    posts = commands.add_parser("user-posts", help="查询用户的公开视频")
    posts.add_argument("reference")
    posts.add_argument("--offset", type=int, default=0)
    posts.add_argument("--max-behot-time")
    posts.add_argument("--count", type=int, default=20)

    search = commands.add_parser("search", help="搜索公开视频")
    search.add_argument("keyword")
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--order", dest="order_type", choices=("publish_time", "play_count"))
    search.add_argument("--min-duration", type=int)
    search.add_argument("--max-duration", type=int)
    search.add_argument("--limit", type=int, default=20)

    hot = commands.add_parser("hot", help="查询热门搜索和推荐")
    hot.add_argument("--limit", type=int, default=20)

    reference = commands.add_parser("reference", help="在本地校验并提取 ID")
    reference.add_argument("kind", choices=("video", "user"))
    reference.add_argument("value")

    parse = commands.add_parser("parse", help="离线解析已保存的公开响应")
    parse.add_argument(
        "kind",
        choices=("video", "video-raw", "play", "play-data", "comments", "user", "posts", "search", "hot"),
    )
    parse.add_argument("path", type=Path)
    parse.add_argument("--id")
    parse.add_argument("--query", default="fixture")
    parse.add_argument("--offset", type=int, default=0)
    parse.add_argument("--limit", type=int, default=20)
    return parser


def _parse_file(args: argparse.Namespace) -> Any:
    source = args.path.read_text(encoding="utf-8")
    if args.kind == "play":
        return XiguaClient.parse_play_page(source, expected_id=args.id)
    payload = json.loads(source)
    if args.kind == "play-data":
        return XiguaClient.parse_play_data_payload(payload, expected_id=args.id)
    if args.kind == "video":
        return XiguaClient.parse_video_payload(payload, expected_id=args.id)
    if args.kind == "video-raw":
        return XiguaClient.parse_video_data_payload(payload, expected_id=args.id)
    if args.kind == "comments":
        return XiguaClient.parse_comments_payload(payload, video_id=args.id or "")
    if args.kind == "user":
        return XiguaClient.parse_user_payload(payload, expected_id=args.id)
    if args.kind == "posts":
        return XiguaClient.parse_posts_payload(
            payload,
            user_id=args.id or "",
            offset=args.offset,
        )
    if args.kind == "search":
        return XiguaClient.parse_search_payload(
            payload,
            query=args.query,
            offset=args.offset,
            limit=args.limit,
        )
    return XiguaClient.parse_hot_payload(payload, limit=args.limit)


def _run(args: argparse.Namespace) -> Any:
    if args.command == "parse":
        return _parse_file(args)
    if args.command == "reference":
        if args.kind == "video":
            return {"kind": "video", "id": XiguaClient.resolve_video_id(args.value)}
        return {"kind": "user", "id": XiguaClient.resolve_user_id(args.value)}

    client = XiguaClient(timeout=args.timeout, retries=args.retries)
    if args.command == "video":
        return client.get_video_info(args.reference)
    if args.command == "video-raw":
        return client.get_video_data(args.reference)
    if args.command == "play":
        return client.get_video_play_url(args.reference)
    if args.command == "comments":
        return client.get_comments(args.reference, offset=args.offset, count=args.count)
    if args.command == "user":
        return client.get_user(args.reference)
    if args.command == "user-posts":
        return client.get_user_posts(
            args.reference,
            offset=args.offset,
            max_behot_time=args.max_behot_time,
            count=args.count,
        )
    if args.command == "search":
        return client.search(
            args.keyword,
            offset=args.offset,
            order_type=args.order_type,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            limit=args.limit,
        )
    return client.get_hot_recommendations(limit=args.limit)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except (XiguaError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
