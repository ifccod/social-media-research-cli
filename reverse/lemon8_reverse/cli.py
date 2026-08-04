from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import Lemon8Client
from .errors import Lemon8Error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lemon8 匿名公开页面客户端")
    parser.add_argument("--region", default="us", help="两字母回退地区")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    post = commands.add_parser("post", help="查询单个公开帖子")
    post.add_argument("reference", help="帖子 ID、长 URL、短链接或分享文本")

    profile = commands.add_parser("profile", help="查询单个公开用户资料")
    profile.add_argument("reference", help="作者 handle、用户 ID、URL 或短链接")

    reference = commands.add_parser("reference", help="不发起 HTTP 请求，仅归一化引用")
    reference.add_argument("kind", choices=("post", "user"))
    reference.add_argument("value")

    parse_html = commands.add_parser("parse-html", help="解析已保存的 Lemon8 HTML 响应")
    parse_html.add_argument("kind", choices=("post", "profile", "open-graph", "hydration"))
    parse_html.add_argument("path", type=Path)
    parse_html.add_argument("--page-url", default="https://www.lemon8-app.com/")
    parse_html.add_argument("--expected-id")
    parse_html.add_argument("--expected-author")
    return parser


def _run(args: argparse.Namespace) -> Any:
    client = Lemon8Client(
        region=args.region,
        timeout=args.timeout,
        retries=args.retries,
    )
    if args.command == "post":
        return client.get_post(args.reference)
    if args.command == "profile":
        return client.get_user_profile(args.reference)
    if args.command == "reference":
        if args.kind == "post":
            return client.parse_post_reference(args.value, region=args.region)
        return client.parse_user_reference(args.value, region=args.region)

    source = args.path.read_text(encoding="utf-8")
    if args.kind == "post":
        return client.parse_post_html(
            source,
            expected_id=args.expected_id,
            page_url=args.page_url,
        )
    if args.kind == "profile":
        return client.parse_profile_html(
            source,
            expected_user_id=args.expected_id,
            expected_author=args.expected_author,
            page_url=args.page_url,
        )
    if args.kind == "open-graph":
        return client.extract_open_graph(source, page_url=args.page_url)
    return client.extract_hydration_json(source)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except (Lemon8Error, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
