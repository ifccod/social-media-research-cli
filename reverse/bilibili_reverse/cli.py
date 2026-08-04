from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import BilibiliClient
from .errors import BilibiliError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bilibili 匿名公开数据客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    video = commands.add_parser("video", help="查询单个公开视频")
    video.add_argument("video_url_or_id")

    parts = commands.add_parser("parts", help="查询视频分 P")
    parts.add_argument("video_url_or_id")

    playurl = commands.add_parser("playurl", help="查询匿名视频流")
    playurl.add_argument("video_url_or_id")
    playurl.add_argument("--cid")
    playurl.add_argument("--quality", type=int, default=80)
    playurl.add_argument(
        "--wbi",
        action="store_true",
        help="优先尝试 WBI playurl API，再回退到稳定的 legacy API",
    )

    subtitles = commands.add_parser("subtitles", help="查询视频字幕元数据")
    subtitles.add_argument("video_url_or_id")
    subtitles.add_argument("--cid")

    danmaku = commands.add_parser("danmaku", help="查询实时弹幕 XML")
    danmaku.add_argument("cid")

    user = commands.add_parser("user", help="查询匿名用户资料")
    user.add_argument("user_id")

    videos = commands.add_parser("user-videos", help="查询用户公开投稿")
    videos.add_argument("user_id")
    videos.add_argument("--limit", type=int)
    videos.add_argument("--page-size", type=int, default=20)
    videos.add_argument(
        "--order", choices=("pubdate", "click", "stow"), default="pubdate"
    )

    comments = commands.add_parser("comments", help="查询视频评论")
    comments.add_argument("video_url_or_id")
    comments.add_argument("--limit", type=int, default=20)
    comments.add_argument("--page-size", type=int, default=20)
    comments.add_argument("--include-replies", action="store_true")
    comments.add_argument("--reply-limit", type=int, default=20)

    replies = commands.add_parser("replies", help="查询一条根评论下的回复")
    replies.add_argument("aid")
    replies.add_argument("root_id")
    replies.add_argument("--limit", type=int, default=20)
    replies.add_argument("--page-size", type=int, default=20)

    search = commands.add_parser("search", help="搜索 Bilibili 公开内容")
    search.add_argument("keyword")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--page-size", type=int, default=20)

    popular = commands.add_parser("popular", help="查询综合热门视频")
    popular.add_argument("--limit", type=int, default=20)

    hot = commands.add_parser("hot-search", help="查询热搜词")
    hot.add_argument("--limit", type=int, default=20)

    feed = commands.add_parser("home-feed", help="查询匿名 App 首页 feed")
    feed.add_argument("--limit", type=int, default=20)

    app_popular = commands.add_parser("app-popular", help="查询匿名 App 热门 feed")
    app_popular.add_argument("--limit", type=int, default=20)

    app_video = commands.add_parser(
        "app-video-detail",
        help="查询 Android App 视频详情",
    )
    app_video.add_argument("video_url_or_id", help="BV、av 或官方视频链接")

    app_comments = commands.add_parser(
        "app-comments",
        help="查询 Android App 视频根评论",
    )
    app_comments.add_argument("video_url_or_id", help="BV、av 或官方视频链接")
    app_comments.add_argument("--limit", type=int, default=20, help="最多返回条数")
    app_comments.add_argument("--page-size", type=int, default=20, help="单页请求条数")
    app_comments.add_argument(
        "--order",
        choices=("hot", "time", "new", "latest", "3", "2"),
        default="hot",
        help="评论排序：hot/3 为热门，time/new/latest/2 为最新",
    )
    app_comments.add_argument("--offset", type=int, default=0, help="起始整数游标")

    app_replies = commands.add_parser(
        "app-comment-replies",
        help="查询 Android App 根评论下的回复",
    )
    app_replies.add_argument("video_url_or_id", help="BV、av 或官方视频链接")
    app_replies.add_argument(
        "--root-id",
        "--cid",
        dest="root_id",
        required=True,
        help="根评论 ID；--cid 保留旧命令兼容",
    )
    app_replies.add_argument("--limit", type=int, default=20, help="最多返回条数")
    app_replies.add_argument("--page-size", type=int, default=20, help="单页请求条数")
    app_replies.add_argument("--offset", type=int, default=0, help="起始整数游标")
    app_replies.add_argument(
        "--pagination-token",
        help="继续分页的不透明 Base64 token",
    )

    app_search = commands.add_parser(
        "app-search-type",
        help="按类型调用 Android App 搜索",
    )
    app_search.add_argument("keyword", help="搜索关键词")
    app_search.add_argument(
        "--category",
        choices=("video", "user", "live", "article", "bangumi", "pgc"),
        default="video",
        help="结果类型",
    )
    app_search.add_argument(
        "--order",
        type=int,
        choices=range(5),
        default=0,
        help="App 搜索排序编号",
    )
    app_search.add_argument("--limit", type=int, default=20, help="最多返回条数")
    app_search.add_argument("--page-size", type=int, default=20, help="单页请求条数")
    app_search.add_argument(
        "--pagination-token",
        default="",
        help="继续分页的不透明 token",
    )

    app_cinema = commands.add_parser(
        "app-cinema-tab",
        help="查询 Android App 影视页签",
    )
    app_cinema.add_argument(
        "--pagination-token",
        default="",
        help="继续分页的不透明 cursor",
    )

    app_bangumi = commands.add_parser(
        "app-bangumi-tab",
        help="查询 Android App 番剧页签",
    )
    app_bangumi.add_argument(
        "--pagination-token",
        default="",
        help="继续分页的不透明 cursor",
    )

    relation = commands.add_parser("relation-stats", help="查询公开关注数和粉丝数")
    relation.add_argument("user_id")

    folders = commands.add_parser("favorite-folders", help="查询公开收藏夹")
    folders.add_argument("user_id")

    collection = commands.add_parser("collection", help="查询公开收藏夹中的视频")
    collection.add_argument("folder_id")
    collection.add_argument("--page", type=int, default=1)
    collection.add_argument("--page-size", type=int, default=20)

    live = commands.add_parser("live-room", help="查询单个直播间")
    live.add_argument("room_id")
    live.add_argument("--streams", action="store_true")

    commands.add_parser("live-areas", help="查询全部直播分区")

    live_list = commands.add_parser("live-list", help="查询指定直播分区的主播")
    live_list.add_argument("area_id")
    live_list.add_argument("--parent-area-id", default="0")
    live_list.add_argument("--page", type=int, default=1)
    live_list.add_argument("--page-size", type=int, default=30)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any] | list[dict[str, Any]]:
    client = BilibiliClient(timeout=args.timeout)
    if args.command == "video":
        return client.get_video(args.video_url_or_id)
    if args.command == "parts":
        return client.get_video_parts(args.video_url_or_id)
    if args.command == "playurl":
        return client.get_video_playurl(
            args.video_url_or_id,
            cid=args.cid,
            quality=args.quality,
            prefer_wbi=args.wbi,
        )
    if args.command == "subtitles":
        return client.get_subtitles(args.video_url_or_id, cid=args.cid)
    if args.command == "danmaku":
        return client.get_video_danmaku(args.cid)
    if args.command == "user":
        return client.get_user_profile(args.user_id)
    if args.command == "user-videos":
        return client.get_user_videos(
            args.user_id, limit=args.limit, page_size=args.page_size, order=args.order
        )
    if args.command == "comments":
        return client.get_comments(
            args.video_url_or_id,
            limit=args.limit,
            page_size=args.page_size,
            include_replies=args.include_replies,
            reply_limit=args.reply_limit,
        )
    if args.command == "replies":
        return client.get_comment_replies(
            args.aid, args.root_id, limit=args.limit, page_size=args.page_size
        )
    if args.command == "search":
        return client.search(args.keyword, limit=args.limit, page_size=args.page_size)
    if args.command == "popular":
        return client.get_popular(limit=args.limit)
    if args.command == "hot-search":
        return client.get_hot_search(limit=args.limit)
    if args.command == "home-feed":
        return client.get_home_feed(limit=args.limit)
    if args.command == "app-popular":
        return client.get_app_popular(limit=args.limit)
    if args.command == "app-video-detail":
        return client.get_app_video_detail(args.video_url_or_id)
    if args.command == "app-comments":
        return client.get_app_comments(
            args.video_url_or_id,
            limit=args.limit,
            page_size=args.page_size,
            order=args.order,
            offset=args.offset,
        )
    if args.command == "app-comment-replies":
        return client.get_app_comment_replies(
            args.video_url_or_id,
            args.root_id,
            limit=args.limit,
            page_size=args.page_size,
            offset=args.offset,
            pagination_token=args.pagination_token,
        )
    if args.command == "app-search-type":
        return client.search_app_by_type(
            args.keyword,
            category=args.category,
            order=args.order,
            limit=args.limit,
            page_size=args.page_size,
            pagination_token=args.pagination_token,
        )
    if args.command == "app-cinema-tab":
        return client.get_app_cinema_tab(
            pagination_token=args.pagination_token,
        )
    if args.command == "app-bangumi-tab":
        return client.get_app_bangumi_tab(
            pagination_token=args.pagination_token,
        )
    if args.command == "relation-stats":
        return client.get_relation_stats(args.user_id)
    if args.command == "favorite-folders":
        return client.get_favorite_folders(args.user_id)
    if args.command == "collection":
        return client.get_collection_videos(
            args.folder_id, page=args.page, page_size=args.page_size
        )
    if args.command == "live-areas":
        return client.get_live_areas()
    if args.command == "live-list":
        return client.get_live_streamers(
            args.area_id,
            parent_area_id=args.parent_area_id,
            page=args.page,
            page_size=args.page_size,
        )
    if args.streams:
        return client.get_live_streams(args.room_id)
    return client.get_live_room(args.room_id)


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except BilibiliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
