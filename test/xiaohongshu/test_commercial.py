from __future__ import annotations

import unittest

from reverse.xiaohongshu_reverse import cli
from reverse.xiaohongshu_reverse.client import XiaohongshuClient
from reverse.xiaohongshu_reverse.errors import XiaohongshuInputError


class XiaohongshuPgyCommercialTest(unittest.TestCase):
    def test_pgy_commercial_commands_keep_observed_fixed_page_sizes(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return {"code": 0, "data": [{"name": "fixture"}]}

        client = XiaohongshuClient(pgy_fetch=fetch)
        note = client.get_pgy_good_notes("美妆个护")
        live = client.get_pgy_good_lives("潮流运动")
        bloggers = client.get_pgy_top_bloggers(rank_type=6)
        classes = client.get_pgy_good_case_classes()
        industries = client.get_pgy_industries()

        self.assertEqual((note["page"], note["page_size"]), (1, 6))
        self.assertEqual((live["page"], live["page_size"]), (1, 6))
        self.assertEqual((bloggers["page"], bloggers["page_size"]), (1, 3))
        self.assertEqual(classes["operation"], "good_case_classes")
        self.assertEqual(industries["operation"], "industries")
        self.assertEqual(
            [(path, entries) for path, entries, _referer in calls],
            [
                (
                    "/bridge/v1/xiaohongshu-pgy/good-notes",
                    [("category", "美妆个护")],
                ),
                (
                    "/bridge/v1/xiaohongshu-pgy/good-lives",
                    [("category", "潮流运动")],
                ),
                (
                    "/bridge/v1/xiaohongshu-pgy/top-bloggers",
                    [("rank_type", "6")],
                ),
                (
                    "/bridge/v1/xiaohongshu-pgy/good-case-classes",
                    [],
                ),
                (
                    "/bridge/v1/xiaohongshu-pgy/industries",
                    [],
                ),
            ],
        )
        self.assertTrue(
            all(
                referer == "https://pgy.xiaohongshu.com/"
                for _path, _entries, referer in calls
            )
        )

    def test_pgy_inputs_match_extension_contract(self) -> None:
        client = XiaohongshuClient(pgy_fetch=lambda *_args: {"code": 0})
        for category in ("", " 美妆", "x" * 65):
            with self.subTest(category=category), self.assertRaises(
                XiaohongshuInputError
            ):
                client.get_pgy_good_notes(category)
        for rank_type in (-1, 10000, True):
            with self.subTest(rank_type=rank_type), self.assertRaises(
                XiaohongshuInputError
            ):
                client.get_pgy_top_bloggers(rank_type=rank_type)

    def test_pgy_cli_uses_named_category_and_rank_options(self) -> None:
        note = cli._parser().parse_args(
            ["pgy-good-notes", "--category", "美妆个护"]
        )
        bloggers = cli._parser().parse_args(
            ["pgy-top-bloggers", "--rank-type", "7"]
        )

        self.assertEqual(note.category, "美妆个护")
        self.assertEqual(bloggers.rank_type, 7)
        self.assertEqual(note.request_interval, 3.0)


if __name__ == "__main__":
    unittest.main()
