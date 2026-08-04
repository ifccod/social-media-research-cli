from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import KuaishouClient
from .errors import KuaishouError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kuaishou 匿名公开分享与 Web 热榜客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时 HTTP 失败重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    post = commands.add_parser("post", help="解析单个公开分享或帖子")
    post.add_argument("reference", help="photo id、分享 URL、短链接或分享文本")

    resolve = commands.add_parser("resolve", help="跟随公开分享链并提取 id")
    resolve.add_argument("reference")

    author = commands.add_parser("author", help="读取公开帖子分享中的作者")
    author.add_argument("reference")

    hot_list = commands.add_parser(
        "hot-list",
        help="读取 Kuaishou Web 匿名实时热榜",
    )
    hot_list.add_argument("--limit", type=int, default=50, help="返回 0..50 条")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = KuaishouClient(timeout=args.timeout, retries=args.retries)
    if args.command == "post":
        return client.get_post(args.reference)
    if args.command == "resolve":
        return client.resolve_share(args.reference)
    if args.command == "author":
        return client.get_author(args.reference)
    return client.get_hot_list(limit=args.limit)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except KuaishouError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
