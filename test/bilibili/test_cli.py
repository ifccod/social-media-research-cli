from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch

from reverse.bilibili_reverse import cli


class BilibiliCLITests(unittest.TestCase):
    def test_parser_exposes_six_migrated_app_commands(self) -> None:
        parser = cli._parser()
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        self.assertEqual(
            {
                "app-video-detail",
                "app-comments",
                "app-comment-replies",
                "app-search-type",
                "app-cinema-tab",
                "app-bangumi-tab",
            }
            - set(subparsers.choices),
            set(),
        )
        self.assertEqual(len(subparsers.choices), 26)

    def test_comment_replies_keeps_cid_alias(self) -> None:
        args = cli._parser().parse_args(
            [
                "app-comment-replies",
                "av2",
                "--cid",
                "495059",
                "--limit",
                "2",
                "--page-size",
                "2",
            ]
        )

        self.assertEqual(args.root_id, "495059")
        self.assertEqual(args.limit, 2)
        self.assertEqual(args.page_size, 2)
        self.assertEqual(
            cli._parser()
            .parse_args(["app-comments", "av2", "--order", "latest"])
            .order,
            "latest",
        )

    @patch("reverse.bilibili_reverse.cli.BilibiliClient")
    def test_six_app_commands_dispatch_all_options(
        self,
        client_type: MagicMock,
    ) -> None:
        client = client_type.return_value
        cases = (
            (
                ["app-video-detail", "BV1xx411c7mD"],
                "get_app_video_detail",
                ("BV1xx411c7mD",),
                {},
            ),
            (
                [
                    "app-comments",
                    "av2",
                    "--limit",
                    "3",
                    "--page-size",
                    "2",
                    "--order",
                    "time",
                    "--offset",
                    "7",
                ],
                "get_app_comments",
                ("av2",),
                {"limit": 3, "page_size": 2, "order": "time", "offset": 7},
            ),
            (
                [
                    "app-comment-replies",
                    "av2",
                    "--root-id",
                    "495059",
                    "--limit",
                    "3",
                    "--page-size",
                    "2",
                    "--pagination-token",
                    "CAI=",
                ],
                "get_app_comment_replies",
                ("av2", "495059"),
                {
                    "limit": 3,
                    "page_size": 2,
                    "offset": 0,
                    "pagination_token": "CAI=",
                },
            ),
            (
                [
                    "app-search-type",
                    "python",
                    "--category",
                    "user",
                    "--order",
                    "4",
                    "--limit",
                    "3",
                    "--page-size",
                    "2",
                    "--pagination-token",
                    "opaque",
                ],
                "search_app_by_type",
                ("python",),
                {
                    "category": "user",
                    "order": 4,
                    "limit": 3,
                    "page_size": 2,
                    "pagination_token": "opaque",
                },
            ),
            (
                ["app-cinema-tab", "--pagination-token", "8"],
                "get_app_cinema_tab",
                (),
                {"pagination_token": "8"},
            ),
            (
                ["app-bangumi-tab", "--pagination-token", "16"],
                "get_app_bangumi_tab",
                (),
                {"pagination_token": "16"},
            ),
        )

        for argv, method_name, positional, keyword in cases:
            with self.subTest(command=argv[0]):
                method = getattr(client, method_name)
                method.reset_mock()
                method.return_value = {"command": argv[0]}

                result = cli._run(cli._parser().parse_args(argv))

                self.assertEqual(result, {"command": argv[0]})
                method.assert_called_once_with(*positional, **keyword)


if __name__ == "__main__":
    unittest.main()
