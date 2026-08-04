from __future__ import annotations

import unittest

from reverse.xiaohongshu_reverse import cli
from reverse.xiaohongshu_reverse.client import XiaohongshuClient


NOTE_ID = "64c13017000000000103cde1"
ROOT_COMMENT_ID = "65c13017000000000103cde2"
REPLY_COMMENT_ID = "66c13017000000000103cde3"
SECOND_REPLY_ID = "67c13017000000000103cde4"
USER_ID = "5cbc3d1c0000000011035f05"
SEARCH_ID = "search_fixture_123"
XSEC_TOKEN = "fixture_xsec_token"


def note_item(note_id: str) -> dict[str, object]:
    return {
        "note_id": note_id,
        "display_title": "测试笔记",
        "type": "normal",
        "user": {
            "user_id": USER_ID,
            "nickname": "测试作者",
        },
        "interact_info": {
            "liked_count": "123",
        },
    }


def comment_item(
    comment_id: str,
    content: str,
    *,
    sub_comments: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": comment_id,
        "content": content,
        "like_count": "12",
        "create_time": 1_720_000_000_000,
        "ip_location": "上海",
        "user_info": {
            "user_id": USER_ID,
            "nickname": "评论用户",
        },
        "sub_comment_count": 2 if sub_comments else 0,
        "sub_comment_cursor": "reply_cursor" if sub_comments else "",
        "sub_comment_has_more": bool(sub_comments),
        "sub_comments": sub_comments or [],
    }


class XiaohongshuContentInsightsTest(unittest.TestCase):
    def test_user_posts_uses_profile_context_and_cursor_pagination(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []
        pages = [
            {
                "code": 0,
                "data": {
                    "notes": [note_item(NOTE_ID)],
                    "cursor": "next_cursor",
                },
            },
            {
                "code": 0,
                "data": {
                    "notes": [],
                    "cursor": "",
                },
            },
        ]

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return pages.pop(0)

        result = XiaohongshuClient(browser_fetch=fetch).get_user_posts(
            f"https://www.xiaohongshu.com/user/profile/{USER_ID}"
            f"?xsec_token={XSEC_TOKEN}&xsec_source=pc_profile",
            limit=2,
            page_size=1,
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["note_id"], NOTE_ID)
        self.assertFalse(result["has_more"])
        self.assertEqual(calls[0][0], "/api/sns/web/v1/user_posted")
        self.assertEqual(calls[1][1][1], ("cursor", "next_cursor"))
        self.assertIn(f"xsec_token={XSEC_TOKEN}", calls[0][2])

    def test_note_comments_normalizes_pain_points_and_completes_replies(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []
        first_reply = comment_item(REPLY_COMMENT_ID, "已有回复")
        payloads = {
            "/api/sns/web/v2/comment/page": {
                "code": 0,
                "data": {
                    "comments": [
                        comment_item(
                            ROOT_COMMENT_ID,
                            "尺码偏小吗？",
                            sub_comments=[first_reply],
                        )
                    ],
                    "cursor": "",
                    "has_more": False,
                },
            },
            "/api/sns/web/v2/comment/sub/page": {
                "code": 0,
                "data": {
                    "comments": [
                        first_reply,
                        comment_item(SECOND_REPLY_ID, "建议拍大一码"),
                    ],
                    "cursor": "",
                    "has_more": False,
                },
            },
        }

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            return payloads[path]

        result = XiaohongshuClient(browser_fetch=fetch).get_note_comments(
            f"https://www.xiaohongshu.com/explore/{NOTE_ID}"
            f"?xsec_token={XSEC_TOKEN}&xsec_source=pc_feed",
            include_replies=True,
            reply_limit=10,
        )

        self.assertEqual(result["count"], 1)
        comment = result["items"][0]
        self.assertEqual(comment["content"], "尺码偏小吗？")
        self.assertEqual(comment["ip_location"], "上海")
        self.assertEqual(comment["reply_count"], 2)
        self.assertEqual(
            [item["comment_id"] for item in comment["replies"]],
            [REPLY_COMMENT_ID, SECOND_REPLY_ID],
        )
        self.assertEqual(calls[1][0], "/api/sns/web/v2/comment/sub/page")
        self.assertIn(("root_comment_id", ROOT_COMMENT_ID), calls[1][1])

    def test_search_filters_and_note_related_searches_keep_business_fields(
        self,
    ) -> None:
        payloads = {
            "/api/sns/web/v1/search/filter": {
                "code": 0,
                "data": {
                    "filters": [
                        {
                            "id": "sort",
                            "name": "排序",
                            "options": [
                                {
                                    "id": "collect_descending",
                                    "name": "最多收藏",
                                }
                            ],
                        }
                    ]
                },
            },
            "/api/sns/web/v2/widgets": {
                "code": 0,
                "data": {
                    "widgets": [
                        {
                            "biz_type": "video_related_search",
                            "model": {
                                "title": "猜你想搜",
                                "sub_title": "露营桌椅推荐",
                                "link": (
                                    "https://www.xiaohongshu.com/search_result"
                                    "?keyword=%E9%9C%B2%E8%90%A5%E6%A1%8C%E6%A4%85"
                                ),
                                "biz_extra": {
                                    "word_request_id": "word_fixture_1"
                                },
                            },
                        },
                        {
                            "biz_type": "unrelated_widget",
                            "model": {"title": "忽略"},
                        },
                    ]
                },
            },
        }

        def fetch(path, _entries, _referer):
            return payloads[path]

        client = XiaohongshuClient(browser_fetch=fetch)
        filters = client.get_search_filters(
            "露营",
            search_id=SEARCH_ID,
        )
        related = client.get_note_related_searches(
            NOTE_ID,
            xsec_token=XSEC_TOKEN,
            xsec_source="pc_feed",
        )

        self.assertEqual(
            filters["items"][0]["options"][0]["id"],
            "collect_descending",
        )
        self.assertEqual(related["count"], 1)
        self.assertEqual(related["items"][0]["text"], "露营桌椅")
        self.assertEqual(
            related["items"][0]["word_request_id"],
            "word_fixture_1",
        )

    def test_cli_exposes_content_insight_commands_and_new_sort_orders(self) -> None:
        filters = cli._parser().parse_args(
            ["search-filters", "露营", "--search-id", SEARCH_ID]
        )
        notes = cli._parser().parse_args(
            ["search-notes", "露营", "--sort", "collect_descending"]
        )
        comments = cli._parser().parse_args(
            [
                "note-comments",
                NOTE_ID,
                "--include-replies",
                "--reply-limit",
                "50",
            ]
        )
        posts = cli._parser().parse_args(
            ["user-posts", USER_ID, "--page-size", "50"]
        )

        self.assertEqual(filters.command, "search-filters")
        self.assertEqual(notes.sort, "collect_descending")
        self.assertTrue(comments.include_replies)
        self.assertEqual(posts.page_size, 50)


if __name__ == "__main__":
    unittest.main()
