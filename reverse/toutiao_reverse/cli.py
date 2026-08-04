from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import ToutiaoClient
from .errors import ToutiaoError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="今日头条公开 HTTP 匿名客户端")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("-o", "--output")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("content", "article", "video"):
        command = sub.add_parser(name)
        command.add_argument("reference")

    comments = sub.add_parser("comments")
    comments.add_argument("reference")
    comments.add_argument("--offset", type=int, default=0)
    comments.add_argument("--count", type=int, default=20)

    search = sub.add_parser("search")
    search.add_argument("keyword")
    search.add_argument("--limit", type=int, default=20)

    hot = sub.add_parser("hot")
    hot.add_argument("--limit", type=int)

    profile = sub.add_parser("profile")
    profile.add_argument("reference")
    profile.add_argument("--skip-user-id", action="store_true")

    user_id = sub.add_parser("user-id")
    user_id.add_argument("reference")

    user_info = sub.add_parser("user-info")
    user_info.add_argument("user_id")

    reference = sub.add_parser("reference")
    reference.add_argument("kind", choices=("content", "user"))
    reference.add_argument("value")

    parse = sub.add_parser("parse")
    parse.add_argument("kind", choices=("info", "vod", "comments", "search", "hot", "profile"))
    parse.add_argument("file", type=Path)
    parse.add_argument("--id")
    parse.add_argument("--query", default="")
    parse.add_argument("--token", default="fixture-token-1234")
    return parser


def _read(path: Path, *, json_value: bool) -> Any:
    source = path.read_text(encoding="utf-8")
    return json.loads(source) if json_value else source


def _run(args: argparse.Namespace, client: ToutiaoClient) -> Any:
    if args.command == "content":
        return client.get_content_info(args.reference)
    if args.command == "article":
        return client.get_article_info(args.reference)
    if args.command == "video":
        return client.get_video_info(args.reference)
    if args.command == "comments":
        return client.get_comments(args.reference, offset=args.offset, count=args.count)
    if args.command == "search":
        return client.search(args.keyword, limit=args.limit)
    if args.command == "hot":
        return client.get_hot_board(limit=args.limit)
    if args.command == "profile":
        return client.get_user_profile(args.reference, resolve_id=not args.skip_user_id)
    if args.command == "user-id":
        return {"user_id": client.get_user_id(args.reference)}
    if args.command == "user-info":
        return client.get_user_info(args.user_id)
    if args.command == "reference":
        if args.kind == "content":
            return {"id": client.resolve_content_id(args.value)}
        return client.parse_user_reference(args.value)
    if args.command == "parse":
        if args.kind == "info":
            return client.parse_info_payload(_read(args.file, json_value=True), expected_id=args.id)
        if args.kind == "vod":
            return client.parse_vod_payload(_read(args.file, json_value=True), expected_video_id=args.id)
        if args.kind == "comments":
            return client.parse_comments_payload(_read(args.file, json_value=True), content_id=args.id or "0")
        if args.kind == "search":
            return client.parse_search_html(_read(args.file, json_value=False), query=args.query)
        if args.kind == "hot":
            return client.parse_hot_board_payload(_read(args.file, json_value=True))
        return client.parse_profile_html(
            _read(args.file, json_value=False),
            token=args.token,
        )
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args, ToutiaoClient(timeout=args.timeout, retries=args.retries))
    except (ToutiaoError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0
