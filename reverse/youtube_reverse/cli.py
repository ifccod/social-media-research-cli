from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import YouTubeClient
from .errors import YouTubeError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube 公开视频匿名客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--language", default="en", help="YouTube 响应语言")
    parser.add_argument("--region", default="US", help="YouTube 响应地区")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    video = commands.add_parser("video", help="查询规范化的公开视频数据")
    video.add_argument("video_url_or_id")
    video.add_argument("--no-innertube-fallback", action="store_true")

    oembed = commands.add_parser("oembed", help="查询公开 oEmbed 元数据")
    oembed.add_argument("video_url_or_id")

    captions = commands.add_parser("captions", help="查询公开字幕轨道元数据")
    captions.add_argument("video_url_or_id")
    captions.add_argument("--no-innertube-fallback", action="store_true")

    player = commands.add_parser("player", help="查询原始播放器响应和配置")
    player.add_argument("video_url_or_id")
    player.add_argument(
        "--innertube",
        action="store_true",
        help="强制使用公开 Innertube 播放器 API",
    )
    player.add_argument("--no-innertube-fallback", action="store_true")

    search = commands.add_parser("search", help="搜索 YouTube 公开内容")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--continuation")

    comments = commands.add_parser("comments", help="查询公开视频评论")
    comments.add_argument("video_url_or_id")
    comments.add_argument("--limit", type=int, default=20)
    comments.add_argument("--continuation")

    channel_videos = commands.add_parser(
        "channel-videos", help="查询公开频道发布的视频"
    )
    channel_videos.add_argument("channel_reference")
    channel_videos.add_argument("--limit", type=int, default=20)
    channel_videos.add_argument("--continuation")

    search_suggest = commands.add_parser(
        "search-suggest", help="查询 YouTube 搜索建议"
    )
    search_suggest.add_argument("query")
    search_suggest.add_argument("--limit", type=int, default=10)

    trending = commands.add_parser(
        "trending",
        help="查询当前 YouTube 官方音乐榜或电影预告榜",
    )
    trending.add_argument("section", nargs="?", default="music")
    trending.add_argument("--limit", type=int, default=30)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = YouTubeClient(
        timeout=args.timeout,
        retries=args.retries,
        language=args.language,
        region=args.region,
    )
    if args.command == "oembed":
        return client.get_oembed(args.video_url_or_id)
    if args.command == "video":
        return client.get_video(
            args.video_url_or_id,
            innertube_fallback=not args.no_innertube_fallback,
        )
    if args.command == "captions":
        return client.get_caption_tracks(
            args.video_url_or_id,
            innertube_fallback=not args.no_innertube_fallback,
        )
    if args.command == "search":
        return client.search(
            args.query,
            limit=args.limit,
            continuation=args.continuation,
        )
    if args.command == "comments":
        return client.get_comments(
            args.video_url_or_id,
            limit=args.limit,
            continuation=args.continuation,
        )
    if args.command == "channel-videos":
        return client.get_channel_videos(
            args.channel_reference,
            limit=args.limit,
            continuation=args.continuation,
        )
    if args.command == "search-suggest":
        return client.get_search_suggestions(args.query, limit=args.limit)
    if args.command == "trending":
        return client.get_trending_videos(args.section, limit=args.limit)
    if args.innertube:
        return client.get_innertube_player(args.video_url_or_id)
    return client.get_player_response(
        args.video_url_or_id,
        innertube_fallback=not args.no_innertube_fallback,
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except YouTubeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
