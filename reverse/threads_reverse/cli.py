from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import ThreadsClient
from .errors import ThreadsError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Threads 公开 SSR 与嵌入页匿名客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument(
        "--retries", type=int, default=2, help="瞬时 HTTP 失败的重试次数"
    )
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="读取一份公开资料")
    profile.add_argument("reference", help="用户名、@用户名或资料 URL")

    post = commands.add_parser("post", help="读取一条公开帖子及其媒体")
    post.add_argument("reference", help="短码、数字 ID、帖子 URL 或分享文本")

    resolve = commands.add_parser("resolve", help="规范化公开帖子引用")
    resolve.add_argument("reference")

    encode = commands.add_parser("encode", help="将数字媒体 ID 转为短码")
    encode.add_argument("media_id")

    decode = commands.add_parser("decode", help="将短码转为数字媒体 ID")
    decode.add_argument("shortcode")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = ThreadsClient(timeout=args.timeout, retries=args.retries)
    if args.command == "profile":
        return client.get_profile(args.reference)
    if args.command == "post":
        return client.get_post(args.reference)
    if args.command == "resolve":
        return client.resolve_post_reference(args.reference)
    if args.command == "encode":
        return {
            "media_id": str(args.media_id),
            "shortcode": client.media_id_to_shortcode(args.media_id),
        }
    return {
        "shortcode": str(args.shortcode),
        "media_id": client.shortcode_to_media_id(args.shortcode),
    }


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except ThreadsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
