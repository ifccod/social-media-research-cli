from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import WeChatChannelsClient
from .errors import WeChatChannelsError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="微信视频号公开分享匿名客户端"
    )
    parser.add_argument("--timeout", type=float, default=30, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)
    feed = commands.add_parser("feed", help="获取一个公开分享 URL 或短 URI")
    feed.add_argument("reference")
    export = commands.add_parser("export", help="按临时导出 ID 获取内容")
    export.add_argument("export_id")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = WeChatChannelsClient(timeout=args.timeout, retries=args.retries)
    if args.command == "feed":
        return client.get_feed(args.reference)
    return client.get_feed_by_export_id(args.export_id)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except WeChatChannelsError as exc:
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
