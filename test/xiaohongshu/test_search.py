from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from reverse.xiaohongshu_reverse import cli
from reverse.xiaohongshu_reverse.client import XiaohongshuClient
from reverse.xiaohongshu_reverse.errors import XiaohongshuInputError, XiaohongshuResponseError


NOTE_ID = "64c13017000000000103cde1"
SECOND_NOTE_ID = "65c13017000000000103cde2"
USER_ID = "5cbc3d1c0000000011035f05"
SECOND_USER_ID = "6cbc3d1c0000000011035f06"
SEARCH_ID = "search_fixture_123"


def note_item(
    note_id: str,
    *,
    user_id: str = USER_ID,
    title: str = "测试笔记",
) -> dict[str, object]:
    return {
        "modelType": "note",
        "noteCard": {
            "noteId": note_id,
            "displayTitle": title,
            "type": "normal",
            "user": {
                "userId": user_id,
                "nickname": "测试作者",
                "avatarUrl": "http://sns-avatar-qc.xhscdn.com/avatar.jpg",
            },
            "cover": {
                "urlDefault": "http://sns-webpic-qc.xhscdn.com/cover.webp"
            },
            "interactInfo": {
                "likedCount": "1.2万",
                "collectedCount": "34",
                "commentCount": 5,
                "shareCount": "6",
            },
        },
    }


class XiaohongshuSearchTest(unittest.TestCase):
    def test_search_notes_paginates_deduplicates_and_skips_auxiliary_cards(
        self,
    ) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []
        pages = [
            {
                "status": 200,
                "data": {
                    "success": True,
                    "data": {
                        "items": [
                            note_item(NOTE_ID),
                            {"modelType": "hot_query", "title": "辅助卡片"},
                        ],
                        "hasMore": True,
                    },
                },
            },
            {
                "success": True,
                "items": [
                    note_item(NOTE_ID, title="重复笔记"),
                    note_item(SECOND_NOTE_ID, user_id=SECOND_USER_ID),
                ],
                "has_more": False,
            },
        ]

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return pages.pop(0)

        result = XiaohongshuClient(browser_fetch=fetch).search_notes(
            " 商业内容 ",
            limit=3,
            page_size=20,
            page=1,
            search_id=SEARCH_ID,
            sort="time_descending",
            note_type="video",
        )

        self.assertEqual(result["keyword"], "商业内容")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["next_page"], 3)
        self.assertFalse(result["has_more"])
        self.assertEqual(
            [item["note_id"] for item in result["items"]],
            [NOTE_ID, SECOND_NOTE_ID],
        )
        first = result["items"][0]
        self.assertEqual(first["like_count"], 12_000)
        self.assertEqual(
            first["cover"],
            "https://sns-webpic-qc.xhscdn.com/cover.webp",
        )
        self.assertEqual(
            calls,
            [
                (
                    "/api/sns/web/v2/search/notes",
                    [
                        ("keyword", "商业内容"),
                        ("page", "1"),
                        ("page_size", "20"),
                        ("search_id", SEARCH_ID),
                        ("sort", "time_descending"),
                        ("note_type", "1"),
                    ],
                    "https://www.xiaohongshu.com/search_result",
                ),
                (
                    "/api/sns/web/v2/search/notes",
                    [
                        ("keyword", "商业内容"),
                        ("page", "2"),
                        ("page_size", "20"),
                        ("search_id", SEARCH_ID),
                        ("sort", "time_descending"),
                        ("note_type", "1"),
                    ],
                    "https://www.xiaohongshu.com/search_result",
                ),
            ],
        )

    def test_search_users_normalizes_wire_styles_and_deduplicates(self) -> None:
        calls: list[list[tuple[str, str]]] = []
        pages = [
            {
                "data": {
                    "users": [
                        {
                            "id": USER_ID,
                            "name": "Camel 用户",
                            "image": "http://sns-avatar-qc.xhscdn.com/user.jpg",
                            "fans": "1.2K",
                            "noteCount": 23,
                            "redId": "camel-red-id",
                            "subTitle": "商业博主",
                        }
                    ],
                    "hasMore": "1",
                }
            },
            {
                "users": [
                    {"user_id": USER_ID, "nickname": "重复用户"},
                    {
                        "user_id": SECOND_USER_ID,
                        "nickname": "第二用户",
                        "fans_count": "34",
                        "note_count": "5",
                    },
                ],
                "has_more": 0,
            },
        ]

        def fetch(_path, entries, _referer):
            calls.append(list(entries))
            return pages.pop(0)

        result = XiaohongshuClient(browser_fetch=fetch).search_users(
            "达人",
            limit=3,
            page_size=2,
            search_id=SEARCH_ID,
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["followers"], 1_200)
        self.assertEqual(result["items"][0]["description"], "商业博主")
        self.assertEqual(
            result["items"][0]["avatar"],
            "https://sns-avatar-qc.xhscdn.com/user.jpg",
        )
        self.assertEqual(calls[1][1], ("page", "2"))

    def test_suggestions_and_hot_list_are_normalized_and_deduplicated(
        self,
    ) -> None:
        payloads = {
            "/api/sns/web/v1/search/recommend": {
                "success": True,
                "data": {
                    "sugItems": [
                        "露营",
                        {"text": "露营装备", "displayType": "normal"},
                        "露营",
                    ]
                },
            },
            "/api/sns/web/v1/search/trending/query": {
                "success": True,
                "queries": [
                    {
                        "title": "展示标题",
                        "searchWord": "实际搜索词",
                        "displayType": "hot",
                        "link": (
                            "http://www.xiaohongshu.com/search_result"
                            "?keyword=fixture"
                        ),
                    },
                    {"title": "第二条", "searchWord": "第二条"},
                ],
            },
        }

        def fetch(path, _entries, _referer):
            return payloads[path]

        client = XiaohongshuClient(browser_fetch=fetch)
        suggestions = client.search_suggest("露营", limit=20)
        hot = client.get_hot_list(limit=20)

        self.assertEqual(
            [item["text"] for item in suggestions["items"]],
            ["露营", "露营装备"],
        )
        self.assertEqual(hot["items"][0]["rank"], 1)
        self.assertEqual(hot["items"][1]["rank"], 2)
        self.assertEqual(hot["items"][0]["search_word"], "实际搜索词")
        self.assertEqual(
            hot["items"][0]["url"],
            "https://www.xiaohongshu.com/search_result?keyword=fixture",
        )

    def test_search_rejects_invalid_inputs_before_browser_fetch(self) -> None:
        calls: list[object] = []
        client = XiaohongshuClient(
            browser_fetch=lambda *args: calls.append(args) or {}
        )
        cases = (
            lambda: client.search_notes(""),
            lambda: client.search_notes("x", limit=True),
            lambda: client.search_notes("x", limit=201),
            lambda: client.search_notes("x", page_size=21),
            lambda: client.search_notes("x", page_size=5),
            lambda: client.search_users("x", page_size=51),
            lambda: client.search_users("x", page=0),
            lambda: client.search_users("x", search_id="short"),
            lambda: client.search_notes("x", sort="unknown"),
            lambda: client.search_notes("x", note_type="audio"),
            lambda: client.search_suggest("x\nbad"),
        )
        for call in cases:
            with self.subTest(call=call), self.assertRaises(
                XiaohongshuInputError
            ):
                call()
        self.assertEqual(calls, [])

    def test_search_rejects_malformed_business_and_item_payloads(self) -> None:
        payloads = (
            {"success": False, "message": "登录态失效"},
            {"success": "yes", "items": []},
            {"code": 3, "msg": "频率过高"},
            {"code": float("nan"), "items": []},
            {"items": {}, "has_more": False},
            {
                "items": [{"modelType": "future_fixture_card"}],
                "has_more": False,
            },
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(
                XiaohongshuResponseError
            ):
                XiaohongshuClient(
                    browser_fetch=lambda *_args, value=payload: value
                ).search_notes(
                    "fixture",
                    search_id=SEARCH_ID,
                )

    def test_zero_limit_keeps_resume_shape_without_browser_connection(
        self,
    ) -> None:
        result = XiaohongshuClient().search_notes(
            "fixture",
            limit=0,
            page=3,
            search_id=SEARCH_ID,
        )
        suggestions = XiaohongshuClient().search_suggest(limit=0)

        self.assertEqual(result["items"], [])
        self.assertEqual(result["next_page"], 3)
        self.assertFalse(result["has_more"])
        self.assertEqual(suggestions["items"], [])

    def test_generated_search_id_matches_web_search_session_shape(self) -> None:
        search_id = XiaohongshuClient._search_id(None)

        self.assertRegex(search_id, r"^[0-9a-z]{20,32}$")

    def test_cli_declares_search_arguments_and_bridge_methods(self) -> None:
        notes = cli._parser().parse_args(
            [
                "search-notes",
                "AI 视频",
                "--limit",
                "40",
                "--page-size",
                "20",
                "--page",
                "2",
                "--search-id",
                SEARCH_ID,
                "--sort",
                "popularity_descending",
                "--note-type",
                "video",
            ]
        )
        suggest = cli._parser().parse_args(["search-suggest"])

        self.assertEqual(notes.command, "search-notes")
        self.assertEqual(notes.sort, "popularity_descending")
        self.assertEqual(notes.note_type, "video")
        self.assertEqual(suggest.keyword, "")

        call_daemon = AsyncMock(
            side_effect=[
                {"items": [], "has_more": False},
                {"queries": []},
            ]
        )
        with (
            patch.object(cli, "start_daemon") as start_daemon,
            patch.object(cli, "call_daemon", call_daemon),
        ):
            fetch = cli._browser_fetch(1.5)
            fetch(
                "/api/sns/web/v2/search/notes",
                [
                    ("keyword", "fixture"),
                    ("page", "1"),
                    ("page_size", "20"),
                    ("search_id", SEARCH_ID),
                ],
                "https://www.xiaohongshu.com/search_result",
            )
            fetch(
                "/api/sns/web/v1/search/trending/query",
                [],
                "https://www.xiaohongshu.com/search_result",
            )

        self.assertEqual(start_daemon.call_count, 1)
        first = call_daemon.await_args_list[0].args[0]
        second = call_daemon.await_args_list[1].args[0]
        self.assertEqual(first["platform"], "xiaohongshu")
        self.assertEqual(first["method"], "POST")
        self.assertEqual(second["method"], "GET")
        self.assertEqual(first["request_interval_ms"], 1500)


if __name__ == "__main__":
    unittest.main()
