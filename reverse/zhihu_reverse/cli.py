from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import ZhihuClient
from .errors import ZhihuError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="知乎公开 JSON 匿名客户端")
    parser.add_argument("--timeout", type=float, default=20, help="HTTP 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="瞬时请求失败的重试次数")
    parser.add_argument("--output", "-o", type=Path, help="将 JSON 写入此文件")
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text, argument in (
        ("question", "获取一个公开问题", "question"),
        ("answer", "获取一个公开回答", "answer"),
        ("article", "获取一篇公开专栏文章", "article"),
        ("pin", "获取一个公开想法", "pin"),
        ("user", "获取一份公开用户资料", "user"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(argument)

    column = commands.add_parser("column", help="获取专栏中的公开文章")
    column.add_argument("column")
    _add_window(column, default_limit=10)

    hot = commands.add_parser("hot", help="获取公开热榜")
    hot.add_argument("--limit", type=int, default=50)

    hot_recommend = commands.add_parser(
        "hot-recommend", help="获取匿名首页推荐流"
    )
    hot_recommend.add_argument("--offset", type=int, default=0)
    hot_recommend.add_argument(
        "--page", "--page-number", dest="page_number", type=int, default=1
    )
    hot_recommend.add_argument("--session-token", default="")

    answers = commands.add_parser("question-answers", help="获取问题的回答")
    answers.add_argument("question")
    _add_window(answers, default_limit=5)
    answers.add_argument(
        "--order", choices=("default", "created", "updated"), default="default"
    )

    user_answers = commands.add_parser("user-answers", help="获取用户的回答")
    user_answers.add_argument("user")
    _add_window(user_answers)

    user_articles = commands.add_parser("user-articles", help="获取用户的文章")
    user_articles.add_argument("user")
    _add_window(user_articles)
    user_articles.add_argument("--sort", choices=("created", "updated"), default="created")

    for name, help_text in (
        ("user-followers", "获取用户的公开关注者"),
        ("user-followees", "获取公开用户关注的账号"),
        ("user-pins", "获取用户的公开想法"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("user")
        _add_window(command)

    comments = commands.add_parser("comments", help="获取回答的一级评论")
    comments.add_argument("answer")
    _add_comments_options(comments)

    replies = commands.add_parser("comment-replies", help="获取一条评论的回复")
    replies.add_argument("comment")
    _add_comments_options(replies)

    pin_comments = commands.add_parser("pin-comments", help="获取想法的一级评论")
    pin_comments.add_argument("pin")
    _add_comments_options(pin_comments)

    search = commands.add_parser("search", help="搜索知乎公开内容")
    search.add_argument("query")
    _add_window(search)
    search.add_argument("--vertical", choices=("answer", "article", "zvideo"), default="")
    search.add_argument("--sort", choices=("upvoted_count", "created_time"), default="")
    search.add_argument(
        "--time",
        dest="time_interval",
        choices=("a_day", "a_week", "a_month", "three_months", "half_a_year", "a_year"),
        default="",
    )
    return parser


def _add_window(parser: argparse.ArgumentParser, *, default_limit: int = 20) -> None:
    parser.add_argument("--limit", type=int, default=default_limit)
    parser.add_argument("--offset", type=int, default=0)


def _add_comments_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--order-by", choices=("score", "ts"), default="score")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", default="")


def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = ZhihuClient(timeout=args.timeout, retries=args.retries)
    if args.command == "question":
        return client.get_question(args.question)
    if args.command == "answer":
        return client.get_answer(args.answer)
    if args.command == "article":
        return client.get_article(args.article)
    if args.command == "pin":
        return client.get_pin(args.pin)
    if args.command == "user":
        return client.get_user(args.user)
    if args.command == "column":
        return client.get_column_articles(args.column, limit=args.limit, offset=args.offset)
    if args.command == "hot":
        return client.get_hot_list(limit=args.limit)
    if args.command == "hot-recommend":
        return client.get_hot_recommend(
            offset=args.offset,
            page_number=args.page_number,
            session_token=args.session_token,
        )
    if args.command == "question-answers":
        return client.get_question_answers(
            args.question, limit=args.limit, offset=args.offset, order=args.order
        )
    if args.command == "user-answers":
        return client.get_user_answers(args.user, limit=args.limit, offset=args.offset)
    if args.command == "user-articles":
        return client.get_user_articles(
            args.user,
            limit=args.limit,
            offset=args.offset,
            sort=args.sort,
        )
    if args.command == "user-followers":
        return client.get_user_followers(
            args.user, limit=args.limit, offset=args.offset
        )
    if args.command == "user-followees":
        return client.get_user_followees(
            args.user, limit=args.limit, offset=args.offset
        )
    if args.command == "user-pins":
        return client.get_user_pins(args.user, limit=args.limit, offset=args.offset)
    if args.command == "comments":
        return client.get_comments(
            args.answer,
            order_by=args.order_by,
            limit=args.limit,
            offset=args.offset,
        )
    if args.command == "comment-replies":
        return client.get_comment_replies(
            args.comment,
            order_by=args.order_by,
            limit=args.limit,
            offset=args.offset,
        )
    if args.command == "pin-comments":
        return client.get_pin_comments(
            args.pin,
            order_by=args.order_by,
            limit=args.limit,
            offset=args.offset,
        )
    return client.search(
        args.query,
        limit=args.limit,
        offset=args.offset,
        vertical=args.vertical,
        sort=args.sort,
        time_interval=args.time_interval,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
    except ZhihuError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
