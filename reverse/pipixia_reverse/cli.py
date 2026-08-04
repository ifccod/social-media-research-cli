from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import PiPiXiaClient
from .errors import PiPiXiaError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PiPiXia 匿名公开 App JSON 客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    post = commands.add_parser("post", help="查询单个公开帖子及媒体 URL")
    post.add_argument("reference", help="帖子 id、item URL、短链接或分享文本")
    post.add_argument("--cell-type", type=int, default=1)

    comments = commands.add_parser("comments", help="查询公开帖子评论")
    comments.add_argument("reference")
    comments.add_argument("--offset", default="0")
    comments.add_argument("--count", type=int, default=20)
    comments.add_argument("--cell-type", type=int, default=1)

    user = commands.add_parser("user", help="查询公开用户资料")
    user.add_argument("reference", help="用户 id 或公开用户 URL")

    followers = commands.add_parser("followers", help="查询公开粉丝页")
    followers.add_argument("reference")
    followers.add_argument("--cursor", default="0")
    followers.add_argument("--limit", type=int, default=20)

    following = commands.add_parser("following", help="查询公开关注页")
    following.add_argument("reference")
    following.add_argument("--cursor", default="0")
    following.add_argument("--limit", type=int, default=20)

    hot = commands.add_parser("hot", help="查询公开热搜词")
    hot.add_argument("--limit", type=int, default=20)

    hashtag = commands.add_parser("hashtag", help="查询公开 hashtag 元数据")
    hashtag.add_argument("reference", help="hashtag id 或公开 hashtag URL")

    short_url = commands.add_parser("short-url", help="生成 PiPiXia 短链接")
    short_url.add_argument("original_url", help="待缩短的 HTTP(S) URL")

    resolve = commands.add_parser("resolve", help="从短分享链接解析帖子 id")
    resolve.add_argument("reference")

    reference = commands.add_parser("reference", help="在本地校验并提取 id")
    reference.add_argument("kind", choices=("post", "user", "hashtag"))
    reference.add_argument("value")

    parse = commands.add_parser("parse", help="解析已保存的公开 JSON 响应")
    parse.add_argument(
        "kind",
        choices=(
            "post",
            "comments",
            "user",
            "followers",
            "following",
            "hot",
            "hashtag",
            "short-url",
        ),
    )
    parse.add_argument("path", type=Path)
    parse.add_argument("--id")
    parse.add_argument("--limit", type=int, default=20)
    return parser


def _parse_file(args: argparse.Namespace) -> Any:
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    if args.kind == "post":
        return PiPiXiaClient.parse_post_payload(payload, expected_id=args.id)
    if args.kind == "comments":
        return PiPiXiaClient.parse_comments_payload(payload, cell_id=args.id or "")
    if args.kind == "user":
        return PiPiXiaClient.parse_user_payload(payload, expected_id=args.id)
    if args.kind in {"followers", "following"}:
        return PiPiXiaClient.parse_user_list_payload(
            payload,
            user_id=args.id or "",
            kind=args.kind,
            limit=args.limit,
        )
    if args.kind == "hot":
        return PiPiXiaClient.parse_hot_payload(payload, limit=args.limit)
    if args.kind == "short-url":
        return PiPiXiaClient.parse_short_url_payload(
            payload,
            original_url=args.id or "",
        )
    return PiPiXiaClient.parse_hashtag_payload(payload, expected_id=args.id)


def _run(args: argparse.Namespace) -> Any:
    if args.command == "parse":
        return _parse_file(args)
    if args.command == "reference":
        resolver = {
            "post": PiPiXiaClient.resolve_cell_id,
            "user": PiPiXiaClient.resolve_user_id,
            "hashtag": PiPiXiaClient.resolve_hashtag_id,
        }[args.kind]
        return {"kind": args.kind, "id": resolver(args.value)}

    client = PiPiXiaClient(timeout=args.timeout, retries=args.retries)
    if args.command == "post":
        return client.get_post(args.reference, cell_type=args.cell_type)
    if args.command == "comments":
        return client.get_comments(
            args.reference,
            offset=args.offset,
            count=args.count,
            cell_type=args.cell_type,
        )
    if args.command == "user":
        return client.get_user(args.reference)
    if args.command == "followers":
        return client.get_followers(args.reference, cursor=args.cursor, limit=args.limit)
    if args.command == "following":
        return client.get_following(args.reference, cursor=args.cursor, limit=args.limit)
    if args.command == "hot":
        return client.get_hot_search_words(limit=args.limit)
    if args.command == "hashtag":
        return client.get_hashtag(args.reference)
    if args.command == "short-url":
        return client.get_short_url(args.original_url)
    return client.resolve_share(args.reference)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except (PiPiXiaError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
