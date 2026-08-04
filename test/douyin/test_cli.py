from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from reverse.browser_session import BrowserSessionError
from reverse.douyin_reverse import cli
from reverse.douyin_reverse.errors import DouyinResponseError


class DouyinCliTest(unittest.TestCase):
    def test_browser_command_defaults_match_the_migrated_contract(self) -> None:
        cases = (
            (
                ["user-posts", "SEC_UID"],
                {
                    "command": "user-posts",
                    "limit": 20,
                    "after": "0",
                    "page_size": 18,
                    "request_interval": 3.0,
                },
            ),
            (
                ["comments", "7372484719365098803"],
                {
                    "command": "comments",
                    "limit": 20,
                    "after": "0",
                    "page_size": 20,
                    "request_interval": 3.0,
                    "include_replies": False,
                    "reply_limit": 200,
                    "reply_page_size": 20,
                },
            ),
            (
                [
                    "comment-replies",
                    "7372484719365098803",
                    "7372484719365098811",
                ],
                {
                    "command": "comment-replies",
                    "limit": 20,
                    "after": "0",
                    "page_size": 20,
                    "request_interval": 3.0,
                },
            ),
            (
                ["search-videos", "关键词"],
                {
                    "command": "search-videos",
                    "limit": 20,
                    "after": "0",
                    "page_size": 10,
                    "request_interval": 3.0,
                    "sort_type": 0,
                    "publish_time": 0,
                },
            ),
        )
        for arguments, expected in cases:
            with self.subTest(command=arguments[0]):
                parsed = cli._parser().parse_args(arguments)
                for field, value in expected.items():
                    self.assertEqual(getattr(parsed, field), value)

    def test_browser_commands_parse_and_dispatch_every_option(self) -> None:
        cases = (
            (
                [
                    "user-posts",
                    "SEC_UID",
                    "--limit",
                    "7",
                    "--after",
                    "18",
                    "--page-size",
                    "6",
                    "--request-interval",
                    "2.5",
                ],
                "get_user_posts",
                ("SEC_UID",),
                {"limit": 7, "cursor": "18", "page_size": 6},
            ),
            (
                [
                    "comments",
                    "7372484719365098803",
                    "--limit",
                    "9",
                    "--after",
                    "20",
                    "--page-size",
                    "8",
                    "--request-interval",
                    "4",
                    "--include-replies",
                    "--reply-limit",
                    "11",
                    "--reply-page-size",
                    "5",
                ],
                "get_comments",
                ("7372484719365098803",),
                {
                    "limit": 9,
                    "cursor": "20",
                    "page_size": 8,
                    "include_replies": True,
                    "reply_limit": 11,
                    "reply_page_size": 5,
                },
            ),
            (
                [
                    "comment-replies",
                    "7372484719365098803",
                    "7372484719365098811",
                    "--limit",
                    "13",
                    "--after",
                    "40",
                    "--page-size",
                    "12",
                    "--request-interval",
                    "5",
                ],
                "get_comment_replies",
                ("7372484719365098803", "7372484719365098811"),
                {"limit": 13, "cursor": "40", "page_size": 12},
            ),
            (
                [
                    "search-videos",
                    "fixture query",
                    "--limit",
                    "15",
                    "--after",
                    "30",
                    "--page-size",
                    "10",
                    "--request-interval",
                    "1.25",
                    "--sort-type",
                    "2",
                    "--publish-time",
                    "30",
                ],
                "search_videos",
                ("fixture query",),
                {
                    "limit": 15,
                    "cursor": "30",
                    "page_size": 10,
                    "sort_type": 2,
                    "publish_time": 30,
                },
            ),
        )
        for arguments, method_name, positional, keyword in cases:
            with self.subTest(command=arguments[0]):
                client = Mock()
                operation = getattr(client, method_name)
                operation.return_value = {"kind": arguments[0]}
                parsed = cli._parser().parse_args(arguments)

                result = cli._dispatch(client, parsed)

                self.assertEqual(result, {"kind": arguments[0]})
                operation.assert_called_once_with(*positional, **keyword)

    def test_plain_http_command_constructs_plain_client(self) -> None:
        args = cli._parser().parse_args(["hot", "--limit", "1"])
        with patch("reverse.douyin_reverse.cli.DouyinClient") as client_type:
            client_type.return_value.get_hot_searches.return_value = {"kind": "hot"}
            result = cli._run(args)

        self.assertEqual(result, {"kind": "hot"})
        self.assertEqual(
            client_type.call_args.kwargs,
            {"timeout": 20, "retries": 2, "proxy": None},
        )

    def test_browser_client_receives_the_default_three_second_fetch(self) -> None:
        args = cli._parser().parse_args(
            ["comments", "7372484719365098803", "--limit", "0"]
        )
        browser_fetch = object()
        with (
            patch.object(cli, "_browser_fetch", return_value=browser_fetch) as factory,
            patch.object(cli, "DouyinClient") as client_type,
        ):
            cli._client(args)

        factory.assert_called_once_with(3.0)
        self.assertEqual(
            client_type.call_args.kwargs,
            {
                "timeout": 20,
                "retries": 2,
                "proxy": None,
                "web_fetch": browser_fetch,
            },
        )

    def test_browser_fetch_starts_once_and_builds_the_daemon_request(self) -> None:
        call_daemon = AsyncMock(return_value={"status_code": 0})
        with (
            patch.object(cli, "start_daemon") as start_daemon,
            patch.object(cli, "call_daemon", call_daemon),
        ):
            fetch = cli._browser_fetch(3.0)
            result = fetch(
                "/aweme/v1/web/comment/list/",
                [
                    ("aweme_id", "7372484719365098803"),
                    ("cursor", "0"),
                    ("count", "20"),
                ],
                "https://www.douyin.com/video/7372484719365098803",
            )
            fetch(
                "/aweme/v1/web/comment/list/reply/",
                [
                    ("item_id", "7372484719365098803"),
                    ("comment_id", "7372484719365098811"),
                ],
                "https://www.douyin.com/video/7372484719365098803",
            )

        self.assertEqual(result, {"status_code": 0})
        start_daemon.assert_called_once_with()
        self.assertEqual(call_daemon.await_count, 2)
        self.assertEqual(
            call_daemon.await_args_list[0].args[0],
            {
                "op": "request",
                "platform": "douyin",
                "path": "/aweme/v1/web/comment/list/",
                "entries": [
                    ["aweme_id", "7372484719365098803"],
                    ["cursor", "0"],
                    ["count", "20"],
                ],
                "referer": "https://www.douyin.com/video/7372484719365098803",
                "method": "GET",
                "request_interval_ms": 3000,
            },
        )

    def test_browser_fetch_restarts_the_daemon_only_once(self) -> None:
        call_daemon = AsyncMock(
            side_effect=[
                BrowserSessionError("daemon_unavailable"),
                {"status_code": 0},
            ]
        )
        with (
            patch.object(cli, "start_daemon") as start_daemon,
            patch.object(cli, "call_daemon", call_daemon),
        ):
            result = cli._browser_fetch(3.0)(
                "/aweme/v1/web/comment/list/",
                [("aweme_id", "7372484719365098803")],
                "https://www.douyin.com/video/7372484719365098803",
            )

        self.assertEqual(result, {"status_code": 0})
        self.assertEqual(start_daemon.call_count, 2)
        self.assertEqual(call_daemon.await_count, 2)

    def test_browser_fetch_does_not_loop_after_the_restart_fails(self) -> None:
        first = BrowserSessionError("daemon_unavailable")
        second = BrowserSessionError("daemon_unavailable", "第二次连接仍失败")
        call_daemon = AsyncMock(side_effect=[first, second])
        with (
            patch.object(cli, "start_daemon") as start_daemon,
            patch.object(cli, "call_daemon", call_daemon),
            self.assertRaisesRegex(
                DouyinResponseError,
                r"daemon_unavailable.*第二次连接仍失败",
            ) as raised,
        ):
            cli._browser_fetch(3.0)(
                "/aweme/v1/web/comment/list/",
                [("aweme_id", "7372484719365098803")],
                "https://www.douyin.com/video/7372484719365098803",
            )

        self.assertIs(raised.exception.__cause__, second)
        self.assertEqual(start_daemon.call_count, 2)
        self.assertEqual(call_daemon.await_count, 2)

    def test_browser_fetch_maps_session_errors_and_invalid_payloads(self) -> None:
        for code in ("not_logged_in", "verification_required", "rate_limited"):
            with self.subTest(code=code):
                cause = BrowserSessionError(code, f"{code} fixture")
                with (
                    patch.object(cli, "start_daemon"),
                    patch.object(cli, "call_daemon", AsyncMock(side_effect=cause)),
                    self.assertRaisesRegex(
                        DouyinResponseError,
                        code,
                    ) as raised,
                ):
                    cli._browser_fetch(3.0)(
                        "/aweme/v1/web/comment/list/",
                        [("aweme_id", "7372484719365098803")],
                        "https://www.douyin.com/video/7372484719365098803",
                    )
                self.assertIs(raised.exception.__cause__, cause)

        with (
            patch.object(cli, "start_daemon"),
            patch.object(cli, "call_daemon", AsyncMock(return_value=[])),
            self.assertRaisesRegex(DouyinResponseError, "响应不是对象"),
        ):
            cli._browser_fetch(3.0)(
                "/aweme/v1/web/comment/list/",
                [("aweme_id", "7372484719365098803")],
                "https://www.douyin.com/video/7372484719365098803",
            )


if __name__ == "__main__":
    unittest.main()
