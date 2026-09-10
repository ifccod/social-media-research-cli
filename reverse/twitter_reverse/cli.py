from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

from ..browser_progress import stderr_progress
from ..browser_session import (
    INTERACTIVE_LOGIN_ERRORS,
    PLATFORM_LOGIN_URLS,
    BrowserSessionError,
    authorize_browser_session,
    call_daemon,
    start_daemon,
)
from .client import (
    TWITTER_FOLLOWERS_PATH,
    TWITTER_FOLLOWING_PATH,
    TWITTER_HOME_FEED_PATH,
    TWITTER_SEARCH_POSTS_PATH,
    TWITTER_USER_PATH,
    TWITTER_USER_TWEETS_PATH,
    TwitterClient,
    parse_tweet_id,
)
from .discover import (
    DEFAULT_CRITERIA,
    DEFAULT_CSV_NAME,
    DEFAULT_GEMINI_CONCURRENCY,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_STATE_NAME,
    run_discover,
)
from .errors import TwitterError, TwitterResponseError
from .labels import (
    DEFAULT_EXPAND_MAX_FOLLOWERS,
    DEFAULT_EXPAND_MIN_FOLLOWERS,
    DEFAULT_KOL_FOLLOWING_RATIO,
    DEFAULT_KOL_MIN_FOLLOWERS,
    DEFAULT_MUTUAL_MIN_COUNT,
    DEFAULT_MUTUAL_RATIO_MAX,
    DEFAULT_MUTUAL_RATIO_MIN,
)
from .signer import TwitterSyndicationSigner


_BROWSER_COMMANDS = frozenset(
    {
        "home-feed",
        "search-posts",
        "user",
        "user-tweets",
        "followers",
        "following",
        "discover",
    }
)
_BROWSER_ROUTES = {
    TWITTER_HOME_FEED_PATH: ("twitter_home", "https://x.com/home"),
    TWITTER_USER_PATH: ("twitter_home", "https://x.com/home"),
    TWITTER_USER_TWEETS_PATH: ("twitter_home", "https://x.com/home"),
    TWITTER_FOLLOWERS_PATH: ("twitter_home", "https://x.com/home"),
    TWITTER_FOLLOWING_PATH: ("twitter_home", "https://x.com/home"),
    TWITTER_SEARCH_POSTS_PATH: (
        "twitter_search",
        PLATFORM_LOGIN_URLS["twitter_search"],
    ),
}


def _request_interval(value: str) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("请求间隔必须是秒数") from exc
    if not math.isfinite(interval) or not 0 <= interval <= 10:
        raise argparse.ArgumentTypeError("请求间隔必须在 0 到 10 秒之间")
    return interval


def _browser_fetch(
    request_interval: float,
    *,
    allow_interactive_login: bool = False,
    login_timeout: float = 300,
) -> Callable[
    [str, Sequence[tuple[str, str]], str],
    Mapping[str, Any],
]:
    started = False
    recovered_platforms: set[str] = set()
    report_progress = stderr_progress()

    def fetch(
        path: str,
        entries: Sequence[tuple[str, str]],
        referer: str,
    ) -> Mapping[str, Any]:
        nonlocal started
        route = _BROWSER_ROUTES.get(path)
        if route is None:
            raise TwitterResponseError(
                f"未登记的 X 浏览器请求路径: {path}",
                code="invalid_request",
            )
        platform, login_url = route
        request = {
            "op": "request",
            "platform": platform,
            "path": path,
            "entries": [list(entry) for entry in entries],
            "referer": referer,
            "request_interval_ms": round(request_interval * 1000),
        }
        result: Any = None
        daemon_restarted = False
        while True:
            try:
                if not started:
                    start_daemon()
                    started = True
                result = asyncio.run(
                    call_daemon(request, progress=report_progress)
                )
                break
            except BrowserSessionError as exc:
                if not daemon_restarted and exc.code == "daemon_unavailable":
                    started = False
                    daemon_restarted = True
                    continue
                if (
                    allow_interactive_login
                    and exc.code in INTERACTIVE_LOGIN_ERRORS
                    and platform not in recovered_platforms
                ):
                    try:
                        authorize_browser_session(
                            platform,
                            url=login_url,
                            timeout=login_timeout,
                            open_browser=exc.code
                            in {
                                "extension_disconnected",
                                "tab_unavailable",
                            },
                            progress=report_progress,
                        )
                    except BrowserSessionError as login_exc:
                        raise TwitterResponseError(
                            f"X 浏览器会话请求失败 ({login_exc.code}): {login_exc}",
                            code=login_exc.code,
                        ) from login_exc
                    recovered_platforms.add(platform)
                    started = True
                    continue
                raise TwitterResponseError(
                    f"X 浏览器会话请求失败 ({exc.code}): {exc}",
                    code=exc.code,
                ) from exc
        if not isinstance(result, Mapping):
            raise TwitterResponseError("X 浏览器会话响应不是对象")
        return result

    return fetch


def _add_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "screen_name",
        nargs="?",
        help="用户名；缺省或 me 表示当前登录用户",
    )
    parser.add_argument(
        "--user-id",
        dest="user_id",
        help="用户 rest_id，与 screen_name 互斥",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="X/Twitter Syndication、网页趋势与 Chrome 登录态用户图客户端"
    )
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--lang", default="en", help="Syndication 语言标签")
    parser.add_argument(
        "--request-interval",
        type=_request_interval,
        default=3.0,
        help="同一 X 浏览器请求的最小启动间隔秒数（0..10）",
    )
    parser.add_argument(
        "--no-browser-login",
        action="store_true",
        help="浏览器会话缺失时直接报错，不进入交互式登录流程",
    )
    parser.add_argument(
        "--browser-login-timeout",
        type=float,
        default=300,
        help="交互式浏览器登录的最长等待秒数（默认值: 300）",
    )
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    tweet = commands.add_parser("tweet", help="查询并规范化一条公开帖子")
    tweet.add_argument("tweet_url_or_id")

    raw = commands.add_parser("raw", help="查询原始 Syndication JSON")
    raw.add_argument("tweet_url_or_id")

    token = commands.add_parser("token", help="在本地计算 Syndication 令牌")
    token.add_argument("tweet_url_or_id")

    trending = commands.add_parser(
        "trending",
        help="读取 X 支持地区的当前趋势",
    )
    trending.add_argument(
        "location",
        nargs="?",
        default="United States",
        help="国家、城市、国家代码或数字 WOEID",
    )
    trending.add_argument("--limit", type=int, default=20)

    locations = commands.add_parser(
        "trend-locations",
        help="列出 X 趋势接口支持的地区",
    )
    locations.add_argument("--country", default="")
    locations.add_argument("--limit", type=int)

    home = commands.add_parser(
        "home-feed",
        help="通过 Chrome 登录态读取 X For You 推荐流",
    )
    home.add_argument("--limit", type=int, default=20)
    home.add_argument("--cursor")

    search = commands.add_parser(
        "search-posts",
        help="通过 Chrome 登录态主动搜索 X 帖子",
    )
    search.add_argument("query")
    search.add_argument(
        "--product",
        choices=("top", "latest"),
        default="top",
    )
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--cursor")

    user = commands.add_parser(
        "user",
        help="通过 Chrome 登录态临时传输读取 X 用户资料",
    )
    _add_identity_args(user)

    tweets = commands.add_parser(
        "user-tweets",
        help="通过 Chrome 登录态临时传输读取用户推文",
    )
    _add_identity_args(tweets)
    tweets.add_argument("--limit", type=int, default=10)
    tweets.add_argument("--cursor")

    followers = commands.add_parser(
        "followers",
        help="通过 Chrome 登录态临时传输读取粉丝列表",
    )
    _add_identity_args(followers)
    followers.add_argument("--limit", type=int, default=20)
    followers.add_argument("--cursor")

    following = commands.add_parser(
        "following",
        help="通过 Chrome 登录态临时传输读取关注列表",
    )
    _add_identity_args(following)
    following.add_argument("--limit", type=int, default=20)
    following.add_argument("--cursor")

    discover = commands.add_parser(
        "discover",
        help="通过 Chrome 登录态临时传输扫描蓝 V 关系图，只出冷启动榜单、不自动关注",
    )
    discover.set_defaults(_command_level="workflow")
    discover.add_argument(
        "--seed",
        action="append",
        choices=("following", "followers"),
        help="种子列表，仅 following 或 followers，可重复传入；未传则两者都用",
    )
    discover.add_argument(
        "--max-seed-pages",
        "--pages",
        dest="max_seed_pages",
        type=int,
        default=20,
        help="每个种子列表翻几页（following / followers）；同一 --state 续跑不会重拉已翻过的页",
    )
    discover.add_argument(
        "--max-candidates",
        type=int,
        default=99999,
        help="本轮最多新处理的候选账号数；--state 里已终态的账号会跳过且不占用",
    )
    discover.add_argument(
        "--max-llm-calls",
        type=int,
        default=99999,
        help="本轮最多新的 Gemini HTTP 次数；已写入 --state 的判定不会重打。默认 40，只够扫自己的关注前两页；要扩散必须显式加大",
    )
    discover.add_argument(
        "--max-seconds",
        type=float,
        default=36000,
        help="本批最长运行秒数",
    )
    discover.add_argument(
        "--max-expand-users",
        type=int,
        default=99999,
        help="最多扩散的互关枢纽账号数（mutual_blue 且粉丝 50 到 10000）；默认 5",
    )
    discover.add_argument(
        "--max-expand-pages",
        "--expand-pages",
        dest="max_expand_pages",
        type=int,
        default=100,
        help="每个扩散枢纽每种关系列表翻几页",
    )
    discover.add_argument(
        "--expand-min-followers",
        type=int,
        default=DEFAULT_EXPAND_MIN_FOLLOWERS,
        help="扩散枢纽粉丝数下限，默认 50",
    )
    discover.add_argument(
        "--expand-max-followers",
        type=int,
        default=DEFAULT_EXPAND_MAX_FOLLOWERS,
        help="扩散枢纽粉丝数上限",
    )
    discover.add_argument(
        "--daily-budget",
        type=int,
        default=90,
        help="今日建议关注人数，合法范围 80 到 100",
    )
    discover.add_argument(
        "--batch-size",
        type=int,
        default=30,
        help="早中晚每班建议关注人数",
    )
    discover.add_argument(
        "--user-tweets-limit",
        type=int,
        default=10,
        help="简介不足时拉取的推文条数",
    )
    discover.add_argument(
        "--kol-min-followers",
        type=int,
        default=DEFAULT_KOL_MIN_FOLLOWERS,
        help="大 V 粉丝数阈值",
    )
    discover.add_argument(
        "--kol-following-ratio",
        type=float,
        default=DEFAULT_KOL_FOLLOWING_RATIO,
        help="大 V 关注数相对粉丝数的上限比例",
    )
    discover.add_argument(
        "--mutual-ratio-min",
        type=float,
        default=DEFAULT_MUTUAL_RATIO_MIN,
        help="互关蓝 V 关注/粉丝比例下限",
    )
    discover.add_argument(
        "--mutual-ratio-max",
        type=float,
        default=DEFAULT_MUTUAL_RATIO_MAX,
        help="互关蓝 V 关注/粉丝比例上限",
    )
    discover.add_argument(
        "--mutual-min-count",
        type=int,
        default=DEFAULT_MUTUAL_MIN_COUNT,
        help="互关蓝 V 粉丝和关注数下限，默认 50",
    )
    discover.add_argument(
        "--no-include-untagged",
        action="store_true",
        help="全量榜丢掉 tag=none 的匹配账号；默认写入",
    )
    discover.add_argument(
        "--state",
        type=Path,
        default=Path.cwd() / DEFAULT_STATE_NAME,
        help="JSONL 断点文件，默认当前目录 twitter-discover-state.jsonl",
    )
    discover.add_argument(
        "--markdown",
        type=Path,
        help="可选，将人读榜单写入此 Markdown 文件",
    )
    discover.add_argument(
        "--csv",
        nargs="?",
        const=Path.cwd() / DEFAULT_CSV_NAME,
        type=Path,
        default=None,
        help=(
            "把榜单写成 CSV：主页链接、我是否关注、标签、粉丝数、关注数、AI 判断总结；"
            "省略路径则写入当前目录 twitter-discover.csv"
        ),
    )
    discover.add_argument(
        "--criteria",
        default=DEFAULT_CRITERIA,
        help="交给 Gemini 的相关性说明，不要在 Python 里拆成词表",
    )
    discover.add_argument(
        "--gemini-base-url",
        help=(
            "Gemini Responses 中转根路径，或环境变量 GEMINI_BASE_URL；"
            "必须指向 Responses 兼容中转，不要填 https://generativelanguage.googleapis.com"
        ),
    )
    discover.add_argument(
        "--gemini-api-key",
        help="Gemini 中转 Bearer 密钥，或环境变量 GEMINI_API_KEY",
    )
    discover.add_argument(
        "--gemini-model",
        default=DEFAULT_GEMINI_MODEL,
        help="Gemini 模型名",
    )
    discover.add_argument(
        "--gemini-timeout",
        type=float,
        default=120,
        help="仅 Gemini HTTP 超时秒数；high 推理建议 120，不复用 --timeout",
    )
    discover.add_argument(
        "--gemini-concurrency",
        type=int,
        default=DEFAULT_GEMINI_CONCURRENCY,
        help="Gemini 判定并发数，默认 1：拿完主页立刻判定，等判定结束再翻下一页 X；1 到 32",
    )
    discover.add_argument(
        "--dry-run",
        action="store_true",
        help="只做种子、硬过滤和数值标签，不调用 Gemini、不拉推文",
    )
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {
        "timeout": args.timeout,
        "retries": args.retries,
    }
    if args.command in _BROWSER_COMMANDS:
        options["browser_fetch"] = _browser_fetch(
            args.request_interval,
            allow_interactive_login=(
                not args.no_browser_login and sys.stderr.isatty()
            ),
            login_timeout=args.browser_login_timeout,
        )
    client = TwitterClient(**options)
    if args.command == "home-feed":
        return client.get_home_feed(
            limit=args.limit,
            cursor=args.cursor,
        )
    if args.command == "search-posts":
        return client.search_posts(
            args.query,
            product=args.product,
            limit=args.limit,
            cursor=args.cursor,
        )
    if args.command == "user":
        return client.get_user(
            screen_name=args.screen_name,
            user_id=args.user_id,
        )
    if args.command == "user-tweets":
        return client.get_user_tweets(
            screen_name=args.screen_name,
            user_id=args.user_id,
            limit=args.limit,
            cursor=args.cursor,
        )
    if args.command == "followers":
        return client.get_followers(
            screen_name=args.screen_name,
            user_id=args.user_id,
            limit=args.limit,
            cursor=args.cursor,
        )
    if args.command == "following":
        return client.get_following(
            screen_name=args.screen_name,
            user_id=args.user_id,
            limit=args.limit,
            cursor=args.cursor,
        )
    if args.command == "discover":
        return run_discover(
            client,
            seeds=args.seed,
            max_seed_pages=args.max_seed_pages,
            max_candidates=args.max_candidates,
            max_llm_calls=args.max_llm_calls,
            max_seconds=args.max_seconds,
            max_expand_users=args.max_expand_users,
            max_expand_pages=args.max_expand_pages,
            expand_min_followers=args.expand_min_followers,
            expand_max_followers=args.expand_max_followers,
            daily_budget=args.daily_budget,
            batch_size=args.batch_size,
            user_tweets_limit=args.user_tweets_limit,
            kol_min_followers=args.kol_min_followers,
            kol_following_ratio=args.kol_following_ratio,
            mutual_ratio_min=args.mutual_ratio_min,
            mutual_ratio_max=args.mutual_ratio_max,
            mutual_min_count=args.mutual_min_count,
            include_untagged=not args.no_include_untagged,
            state_path=args.state,
            markdown_path=args.markdown,
            csv_path=args.csv,
            criteria=args.criteria,
            gemini_base_url=args.gemini_base_url or os.environ.get("GEMINI_BASE_URL", ""),
            gemini_api_key=args.gemini_api_key or os.environ.get("GEMINI_API_KEY", ""),
            gemini_model=args.gemini_model,
            gemini_timeout=args.gemini_timeout,
            gemini_concurrency=args.gemini_concurrency,
            dry_run=args.dry_run,
        )
    if args.command == "trending":
        return client.get_trending(args.location, limit=args.limit)
    if args.command == "trend-locations":
        return client.get_trend_locations(
            country=args.country,
            limit=args.limit,
        )

    identifier = parse_tweet_id(args.tweet_url_or_id)
    if args.command == "token":
        return TwitterSyndicationSigner.sign(identifier)
    if args.command == "raw":
        return client.get_tweet_raw(identifier, language=args.lang)
    return client.get_tweet(identifier, language=args.lang)


def _dotenv_paths() -> tuple[Path, ...]:
    repo = Path(__file__).resolve().parents[2]
    cwd = Path.cwd()
    paths: list[Path] = []
    for candidate in (repo / ".env", cwd / ".env"):
        resolved = candidate.resolve()
        if resolved not in paths:
            paths.append(resolved)
    return tuple(paths)


def _apply_dotenv(path: Path, environ: MutableMapping[str, str]) -> None:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    if text.startswith("\ufeff"):
        text = text[1:]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        environ[key] = value


def _load_project_dotenv(environ: MutableMapping[str, str] | None = None) -> None:
    target = os.environ if environ is None else environ
    for path in _dotenv_paths():
        _apply_dotenv(path, target)


def main() -> int:
    _load_project_dotenv()
    args = _parser().parse_args()
    try:
        result = _run(args)
    except TwitterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0
