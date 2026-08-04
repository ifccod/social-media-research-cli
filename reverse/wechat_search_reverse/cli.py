from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .client import WeChatSearchClient
from .errors import WeChatSearchError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="搜狗公开微信索引匿名 HTTP 客户端"
    )
    parser.add_argument("--timeout", type=float, default=30, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("articles", "搜索已收录的微信公众号文章"),
        ("accounts", "搜索公开公众号索引"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("keyword")
        command.add_argument("--page", type=int, default=1)
        command.add_argument("--limit", type=int, default=10)

    resolve = commands.add_parser(
        "resolve", help="将搜狗临时结果解码为微信文章 URL"
    )
    resolve.add_argument("sogou_url")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = WeChatSearchClient(timeout=args.timeout, retries=args.retries)
    if args.command == "articles":
        return client.search_articles(args.keyword, page=args.page, limit=args.limit)
    if args.command == "accounts":
        return client.search_accounts(args.keyword, page=args.page, limit=args.limit)
    return {"article_url": client.resolve_article_url(args.sogou_url)}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except WeChatSearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
