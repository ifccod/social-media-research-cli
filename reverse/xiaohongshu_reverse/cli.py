from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..browser_progress import stderr_progress
from ..browser_session import BrowserSessionError, call_daemon, start_daemon
from .client import XiaohongshuClient
from .errors import XiaohongshuError, XiaohongshuResponseError

_CREATOR_COMMANDS = frozenset({"publish-note"})
_PGY_COMMANDS = frozenset(
    {
        "pgy-good-case-classes",
        "pgy-good-notes",
        "pgy-good-lives",
        "pgy-top-bloggers",
        "pgy-industries",
    }
)
_SEARCH_COMMANDS = frozenset(
    {
        "search-notes",
        "search-users",
        "search-suggest",
        "search-filters",
        "hot-list",
        "user-posts",
        "note-comments",
        "note-related-searches",
        "like",
        "comment",
        "view",
        "home-feed",
    }
)
_SEARCH_POST_PATHS = frozenset(
    {
        "/api/sns/web/v2/search/notes",
        "/api/sns/web/v1/search/usersearch",
        "/api/sns/web/v2/widgets",
        "/api/sns/web/v1/note/like",
        "/api/sns/web/v1/comment/post",
        "/api/sns/web/v1/feed",
        "/api/sns/web/v1/homefeed",
    }
)


def _request_interval(value: str) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("请求间隔必须是秒数") from exc
    if not math.isfinite(interval) or not 0 <= interval <= 10:
        raise argparse.ArgumentTypeError("请求间隔必须在 0 到 10 秒之间")
    return interval


_BROWSER_SCOPE_LABELS = {
    "xiaohongshu": "小红书",
    "xiaohongshu_pgy": "小红书蒲公英",
    "xiaohongshu_creator": "小红书创作者页",
}


def _request_method(platform: str, path: str) -> str:
    if platform == "xiaohongshu_creator" or (
        platform == "xiaohongshu" and path in _SEARCH_POST_PATHS
    ):
        return "POST"
    return "GET"


def _browser_fetch(
    request_interval: float,
    platform: str = "xiaohongshu",
) -> Callable[
    [str, Sequence[tuple[str, str]], str],
    Mapping[str, Any],
]:
    label = _BROWSER_SCOPE_LABELS[platform]
    started = False
    report_progress = stderr_progress()

    def fetch(
        path: str,
        entries: Sequence[tuple[str, str]],
        referer: str,
    ) -> Mapping[str, Any]:
        nonlocal started
        request = {
            "op": "request",
            "platform": platform,
            "path": path,
            "entries": [list(entry) for entry in entries],
            "referer": referer,
            "method": _request_method(platform, path),
            "request_interval_ms": round(request_interval * 1000),
        }
        result: Any = None
        for attempt in range(2):
            try:
                if not started:
                    start_daemon()
                    started = True
                result = asyncio.run(
                    call_daemon(request, progress=report_progress)
                )
                break
            except BrowserSessionError as exc:
                if attempt == 0 and exc.code == "daemon_unavailable":
                    started = False
                    continue
                raise XiaohongshuResponseError(
                    f"{label}浏览器会话请求失败 ({exc.code}): {exc}"
                ) from exc
        if not isinstance(result, Mapping):
            raise XiaohongshuResponseError(f"{label}浏览器会话响应不是对象")
        return result

    return fetch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="小红书公开页面与 Chrome 登录态数据客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument(
        "--request-interval",
        type=_request_interval,
        default=3.0,
        help="同一小红书浏览器请求的最小启动间隔秒数（0..10）",
    )
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    note = commands.add_parser("note", help="查询并规范化一篇公开笔记")
    note.add_argument("note_url_or_id", help="笔记 ID、直达 URL、分享文本或 xhslink URL")
    note.add_argument("--xsec-token", help="覆盖 xsec_token 查询值")
    note.add_argument("--xsec-source", help="覆盖 xsec_source 查询值")

    resolve = commands.add_parser("resolve", help="解析笔记 ID、URL 或短链接")
    resolve.add_argument("note_url_or_id", help="笔记 ID、直达 URL、分享文本或 xhslink URL")
    resolve.add_argument("--xsec-token", help="覆盖 xsec_token 查询值")
    resolve.add_argument("--xsec-source", help="覆盖 xsec_source 查询值")

    profile = commands.add_parser("profile", help="查询公开资料 SSR 页面")
    profile.add_argument("profile_url_or_user_id", help="用户 ID 或公开资料 URL")
    profile.add_argument("--xsec-token", help="可选的资料页 xsec_token")
    profile.add_argument("--xsec-source", help="可选的资料页 xsec_source")

    search_notes = commands.add_parser(
        "search-notes",
        help="通过 Chrome 登录态搜索笔记",
    )
    search_notes.add_argument("keyword", help="搜索关键词")
    search_notes.add_argument("--limit", type=int, default=20, help="最多返回条目数")
    search_notes.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="每次请求的条目数（固定为 20）",
    )
    search_notes.add_argument("--page", type=int, default=1, help="起始页码")
    search_notes.add_argument(
        "--search-id",
        help="复用搜索分页 ID；省略时自动生成",
    )
    search_notes.add_argument(
        "--sort",
        "--order",
        choices=(
            "general",
            "popularity_descending",
            "time_descending",
            "comment_descending",
            "collect_descending",
        ),
        default="general",
        help="搜索排序方式",
    )
    search_notes.add_argument(
        "--note-type",
        choices=("all", "video", "image"),
        default="all",
        help="笔记类型",
    )

    search_users = commands.add_parser(
        "search-users",
        help="通过 Chrome 登录态搜索用户",
    )
    search_users.add_argument("keyword", help="搜索关键词")
    search_users.add_argument("--limit", type=int, default=20, help="最多返回条目数")
    search_users.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="每次请求的条目数（1..50）",
    )
    search_users.add_argument("--page", type=int, default=1, help="起始页码")
    search_users.add_argument(
        "--search-id",
        help="复用搜索分页 ID；省略时自动生成",
    )

    search_suggest = commands.add_parser(
        "search-suggest",
        help="查询搜索联想词",
    )
    search_suggest.add_argument(
        "keyword",
        nargs="?",
        default="",
        help="搜索关键词；省略时读取默认建议",
    )
    search_suggest.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最多返回条目数",
    )

    search_filters = commands.add_parser(
        "search-filters",
        help="查询关键词可用的排序、类型、时间、范围和地域筛选器",
    )
    search_filters.add_argument("keyword", help="搜索关键词")
    search_filters.add_argument(
        "--search-id",
        help="复用搜索分页 ID；省略时自动生成",
    )

    hot_list = commands.add_parser(
        "hot-list",
        help="查询搜索热榜",
    )
    hot_list.add_argument("--limit", type=int, default=20, help="最多返回条目数")

    user_posts = commands.add_parser(
        "user-posts",
        help="通过 Chrome 登录态查询作者作品历史",
    )
    user_posts.add_argument(
        "profile_url_or_user_id",
        help="用户 ID 或资料页 URL；带 xsec_token 的 URL 可直接定位页面上下文",
    )
    user_posts.add_argument("--limit", type=int, default=30, help="最多返回条目数")
    user_posts.add_argument(
        "--cursor",
        default="",
        help="继续分页的 cursor",
    )
    user_posts.add_argument(
        "--page-size",
        type=int,
        default=30,
        help="每次请求的条目数（1..100）",
    )
    user_posts.add_argument("--xsec-token", help="覆盖资料页 xsec_token")
    user_posts.add_argument("--xsec-source", help="覆盖资料页 xsec_source")

    note_comments = commands.add_parser(
        "note-comments",
        help="通过 Chrome 登录态查询笔记评论与购买疑问",
    )
    note_comments.add_argument(
        "note_url_or_id",
        help="笔记 ID 或笔记 URL；带 xsec_token 的 URL 可直接定位页面上下文",
    )
    note_comments.add_argument("--limit", type=int, default=50, help="最多返回一级评论数")
    note_comments.add_argument("--cursor", default="", help="继续分页的 cursor")
    note_comments.add_argument(
        "--include-replies",
        action="store_true",
        help="补齐每条一级评论的楼中楼回复",
    )
    note_comments.add_argument(
        "--reply-limit",
        type=int,
        default=100,
        help="每条一级评论最多返回的回复数",
    )
    note_comments.add_argument(
        "--reply-page-size",
        type=int,
        default=20,
        help="回复每次请求的条目数（1..100）",
    )
    note_comments.add_argument("--xsec-token", help="覆盖笔记页 xsec_token")
    note_comments.add_argument("--xsec-source", help="覆盖笔记页 xsec_source")

    note_related = commands.add_parser(
        "note-related-searches",
        help="读取笔记“猜你想搜”，从素材反查关联搜索词",
    )
    note_related.add_argument(
        "note_url_or_id",
        help="笔记 ID 或笔记 URL；带 xsec_token 的 URL 可直接定位页面上下文",
    )
    note_related.add_argument("--xsec-token", help="覆盖笔记页 xsec_token")
    note_related.add_argument("--xsec-source", help="覆盖笔记页 xsec_source")

    like = commands.add_parser(
        "like",
        help=(
            "通过 Chrome 登录态临时传输点赞笔记；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页"
        ),
        description=(
            "通过 Chrome 登录态临时传输点赞笔记；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页；"
            "由页面 webpack 包装函数代签，不是创作者发布页"
        ),
    )
    like.add_argument(
        "note_url_or_id",
        help="笔记 ID 或笔记 URL；带 xsec_token 的 URL 可直接定位页面上下文",
    )
    like.add_argument("--xsec-token", help="覆盖笔记页 xsec_token")
    like.add_argument("--xsec-source", help="覆盖笔记页 xsec_source")

    comment = commands.add_parser(
        "comment",
        help=(
            "通过 Chrome 登录态临时传输发表主评；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页"
        ),
        description=(
            "通过 Chrome 登录态临时传输发表主评；"
            "正文非空，最多 1000 字，允许换行；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页；"
            "由页面 webpack 包装函数代签，不是创作者发布页"
        ),
    )
    comment.add_argument(
        "note_url_or_id",
        help="笔记 ID 或笔记 URL；带 xsec_token 的 URL 可直接定位页面上下文",
    )
    comment.add_argument(
        "--content",
        required=True,
        help="评论正文，必填，不超过 1000 字，允许换行",
    )
    comment.add_argument("--xsec-token", help="覆盖笔记页 xsec_token")

    view = commands.add_parser(
        "view",
        help=(
            "通过 Chrome 登录态临时传输浏览一篇笔记；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页"
        ),
        description=(
            "通过 Chrome 登录态临时传输浏览一篇笔记（登录态 feed）；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页；"
            "公开 note 命令不能代替此登录态浏览"
        ),
    )
    view.add_argument(
        "note_url_or_id",
        help="笔记 ID 或笔记 URL；带 xsec_token 的 URL 可直接定位页面上下文",
    )
    view.add_argument("--xsec-token", help="覆盖笔记页 xsec_token")

    home_feed = commands.add_parser(
        "home-feed",
        help=(
            "通过 Chrome 登录态临时传输读取推荐流；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页"
        ),
        description=(
            "通过 Chrome 登录态临时传输读取推荐流（登录态 homefeed）；"
            "需要已打开 www.xiaohongshu.com 探索或笔记页"
        ),
    )
    home_feed.add_argument(
        "--num",
        type=int,
        default=20,
        help="返回条数（1..40）",
    )
    home_feed.add_argument(
        "--cursor-score",
        default="",
        help="继续分页的 cursor_score",
    )

    commands.add_parser(
        "pgy-good-case-classes",
        help="查询蒲公英优质案例分类",
    )
    good_notes = commands.add_parser(
        "pgy-good-notes",
        help="查询蒲公英首页优质笔记案例",
    )
    good_notes.add_argument("--category", required=True, help="二级行业分类")
    good_lives = commands.add_parser(
        "pgy-good-lives",
        help="查询蒲公英首页优质直播案例",
    )
    good_lives.add_argument("--category", required=True, help="二级行业分类")
    top_bloggers = commands.add_parser(
        "pgy-top-bloggers",
        help="查询蒲公英首页达人榜",
    )
    top_bloggers.add_argument("--rank-type", type=int, default=6)
    commands.add_parser(
        "pgy-industries",
        help="查询蒲公英首页行业商业数据",
    )
    publish_note = commands.add_parser(
        "publish-note",
        help=(
            "通过 Chrome 创作者页临时传输发布图文或视频笔记；"
            "需要已打开 https://creator.xiaohongshu.com/publish/publish "
            "或 https://creator.xiaohongshu.com/new/note-manager"
        ),
        description=(
            "通过 Chrome 创作者页临时传输发布图文或视频笔记；"
            "图文用 --images，视频用 --video，二者必须二选一；"
            "需要已打开 https://creator.xiaohongshu.com/publish/publish "
            "或 https://creator.xiaohongshu.com/new/note-manager；"
            "扩展需覆盖 creator 主机"
        ),
    )
    publish_note.add_argument("--title", required=True, help="笔记标题，必填，不超过 20 字")
    publish_note.add_argument(
        "--content",
        required=True,
        help="笔记正文，必填，不超过 1000 字",
    )
    media = publish_note.add_mutually_exclusive_group(required=True)
    media.add_argument(
        "--images",
        action="append",
        type=Path,
        help="本地图片路径，可重复，最多 9 张，仅 jpeg/png/webp；与 --video 互斥",
    )
    media.add_argument(
        "--video",
        type=Path,
        help="本地视频路径，mp4 或 mov，单文件不超过 64000000 字节；与 --images 互斥",
    )
    publish_note.add_argument(
        "--cover",
        type=Path,
        help="视频封面，仅 --video 可用，jpeg/png/webp；省略时用 ffmpeg 抽首帧",
    )
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {
        "timeout": args.timeout,
        "retries": args.retries,
    }
    if args.command in _PGY_COMMANDS:
        options["pgy_fetch"] = _browser_fetch(
            args.request_interval, "xiaohongshu_pgy"
        )
    if args.command in _SEARCH_COMMANDS:
        options["browser_fetch"] = _browser_fetch(args.request_interval)
    if args.command in _CREATOR_COMMANDS:
        options["creator_fetch"] = _browser_fetch(
            args.request_interval, "xiaohongshu_creator"
        )
    client = XiaohongshuClient(**options)
    if args.command == "resolve":
        return client.resolve_note_reference(
            args.note_url_or_id,
            xsec_token=args.xsec_token,
            xsec_source=args.xsec_source,
        )
    if args.command == "note":
        return client.get_note(
            args.note_url_or_id,
            xsec_token=args.xsec_token,
            xsec_source=args.xsec_source,
        )
    if args.command == "search-notes":
        return client.search_notes(
            args.keyword,
            limit=args.limit,
            page_size=args.page_size,
            page=args.page,
            search_id=args.search_id,
            sort=args.sort,
            note_type=args.note_type,
        )
    if args.command == "search-users":
        return client.search_users(
            args.keyword,
            limit=args.limit,
            page_size=args.page_size,
            page=args.page,
            search_id=args.search_id,
        )
    if args.command == "search-suggest":
        return client.search_suggest(args.keyword, limit=args.limit)
    if args.command == "search-filters":
        return client.get_search_filters(
            args.keyword,
            search_id=args.search_id,
        )
    if args.command == "hot-list":
        return client.get_hot_list(limit=args.limit)
    if args.command == "user-posts":
        return client.get_user_posts(
            args.profile_url_or_user_id,
            limit=args.limit,
            cursor=args.cursor,
            page_size=args.page_size,
            xsec_token=args.xsec_token,
            xsec_source=args.xsec_source,
        )
    if args.command == "note-comments":
        return client.get_note_comments(
            args.note_url_or_id,
            limit=args.limit,
            cursor=args.cursor,
            include_replies=args.include_replies,
            reply_limit=args.reply_limit,
            reply_page_size=args.reply_page_size,
            xsec_token=args.xsec_token,
            xsec_source=args.xsec_source,
        )
    if args.command == "note-related-searches":
        return client.get_note_related_searches(
            args.note_url_or_id,
            xsec_token=args.xsec_token,
            xsec_source=args.xsec_source,
        )
    if args.command == "like":
        return client.like_note(
            args.note_url_or_id,
            xsec_token=args.xsec_token,
            xsec_source=args.xsec_source,
        )
    if args.command == "comment":
        return client.comment_note(
            args.note_url_or_id,
            args.content,
            xsec_token=args.xsec_token,
        )
    if args.command == "view":
        return client.view_note(
            args.note_url_or_id,
            xsec_token=args.xsec_token,
        )
    if args.command == "home-feed":
        return client.get_home_feed(
            num=args.num,
            cursor_score=args.cursor_score,
        )
    if args.command == "pgy-good-case-classes":
        return client.get_pgy_good_case_classes()
    if args.command == "pgy-good-notes":
        return client.get_pgy_good_notes(args.category)
    if args.command == "pgy-good-lives":
        return client.get_pgy_good_lives(args.category)
    if args.command == "pgy-top-bloggers":
        return client.get_pgy_top_bloggers(rank_type=args.rank_type)
    if args.command == "pgy-industries":
        return client.get_pgy_industries()
    if args.command == "publish-note":
        return client.publish_note(
            args.title,
            args.content,
            images=args.images,
            video=args.video,
            cover=args.cover,
        )
    return client.get_profile(
        args.profile_url_or_user_id,
        xsec_token=args.xsec_token,
        xsec_source=args.xsec_source,
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _run(args)
    except XiaohongshuError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
