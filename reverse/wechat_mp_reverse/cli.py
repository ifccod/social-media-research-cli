from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import WeChatMPClient
from .errors import WeChatMPError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信公众号文章匿名客户端")
    parser.add_argument("--timeout", type=float, default=30, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("article", "获取并解析一篇公开文章"),
        ("account", "从公开文章提取账号元数据"),
        ("extensions", "获取公开标签和文章扩展数据"),
        ("related", "获取相邻文章和推荐文章"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("url")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = WeChatMPClient(timeout=args.timeout, retries=args.retries)
    if args.command == "article":
        return client.get_article(args.url)
    if args.command == "account":
        return client.get_account_from_article(args.url)
    if args.command == "extensions":
        return client.get_article_extensions(args.url)
    return client.get_related_articles(args.url)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except WeChatMPError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
