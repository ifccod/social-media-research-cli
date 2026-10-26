from __future__ import annotations

import io
import unittest
from unittest.mock import AsyncMock, patch

from reverse.xiaohongshu_reverse import cli
from reverse.xiaohongshu_reverse.client import XiaohongshuClient
from reverse.xiaohongshu_reverse.errors import XiaohongshuInputError, XiaohongshuResponseError


NOTE_ID = "64c13017000000000103cde1"
SECOND_NOTE_ID = "65c13017000000000103cde2"
USER_ID = "5cbc3d1c0000000011035f05"
NOTE_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}"


def note_item(
    note_id: str,
    *,
    title: str = "测试笔记",
    note_type: str = "normal",
) -> dict[str, object]:
    return {
        "modelType": "note",
        "noteCard": {
            "noteId": note_id,
            "displayTitle": title,
            "type": note_type,
            "user": {
                "userId": USER_ID,
                "nickname": "测试作者",
            },
            "cover": {
                "urlDefault": "http://sns-webpic-qc.xhscdn.com/cover.webp"
            },
        },
    }


class XiaohongshuEngageTest(unittest.TestCase):
    def test_parser_exposes_like_comment_view_and_home_feed(self) -> None:
        parser = cli._parser()
        like = parser.parse_args(
            ["like", NOTE_ID, "--xsec-token", "TOKEN=", "--xsec-source", "pc_feed"]
        )
        comment = parser.parse_args(
            ["comment", NOTE_URL, "--content", "hello\nworld", "--xsec-token", "TOKEN="]
        )
        view = parser.parse_args(["view", NOTE_ID, "--xsec-token", "TOKEN="])
        home = parser.parse_args(
            ["home-feed", "--num", "8", "--cursor-score", "1.25"]
        )

        self.assertEqual(like.command, "like")
        self.assertEqual(like.note_url_or_id, NOTE_ID)
        self.assertEqual(comment.command, "comment")
        self.assertEqual(comment.content, "hello\nworld")
        self.assertEqual(view.command, "view")
        self.assertEqual(home.command, "home-feed")
        self.assertEqual(home.num, 8)
        self.assertEqual(home.cursor_score, "1.25")

        help_text = parser.format_help()
        for name in ("like", "comment", "view", "home-feed"):
            self.assertIn(name, help_text)
        choices = next(
            action.choices
            for action in parser._actions
            if isinstance(getattr(action, "choices", None), dict)
            and "like" in action.choices
        )
        for name in ("like", "comment", "view", "home-feed"):
            command_help = choices[name].format_help()
            self.assertIn("Chrome 登录态临时传输", command_help)
        publish_help = choices["publish-note"].format_help()
        self.assertIn("--images", publish_help)
        self.assertIn("--video", publish_help)
        with patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "publish-note",
                    "--title",
                    "标题",
                    "--content",
                    "正文",
                    "--images",
                    "a.png",
                    "--video",
                    "a.mp4",
                ]
            )

    def test_like_comment_view_and_home_feed_send_bridge_entries(self) -> None:
        calls: list[tuple[str, list[tuple[str, str]], str]] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == "/api/sns/web/v1/note/like":
                return {"success": True, "code": 0}
            if path == "/api/sns/web/v1/comment/post":
                return {
                    "success": True,
                    "data": {"comment": {"id": "comment-1", "content": "hello\nworld"}},
                }
            if path == "/api/sns/web/v1/feed":
                return {"success": True, "items": [note_item(NOTE_ID, note_type="video")]}
            return {
                "success": True,
                "items": [
                    note_item(NOTE_ID),
                    {"modelType": "live_v2"},
                    note_item(NOTE_ID, title="重复"),
                    note_item(SECOND_NOTE_ID, title="第二条", note_type="video"),
                ],
                "cursor_score": "2.5",
                "has_more": True,
            }

        client = XiaohongshuClient(browser_fetch=fetch)
        liked = client.like_note(NOTE_ID, xsec_token="TOKEN=")
        commented = client.comment_note(NOTE_ID, "hello\nworld")
        viewed = client.view_note(NOTE_ID, xsec_token="TOKEN=", xsec_source="pc_feed")
        feed = client.get_home_feed(num=8, cursor_score="1.25")

        self.assertEqual(liked["kind"], "note_like")
        self.assertEqual(liked["note_id"], NOTE_ID)
        self.assertTrue(liked["success"])
        self.assertEqual(commented["kind"], "note_comment")
        self.assertEqual(commented["content"], "hello\nworld")
        self.assertEqual(commented["comment_id"], "comment-1")
        self.assertEqual(viewed["kind"], "note_view")
        self.assertEqual(viewed["note_id"], NOTE_ID)
        self.assertEqual(viewed["title"], "测试笔记")
        self.assertEqual(viewed["type"], "video")
        self.assertEqual(
            viewed["cover"],
            "https://sns-webpic-qc.xhscdn.com/cover.webp",
        )
        self.assertEqual(feed["kind"], "home_feed")
        self.assertEqual(
            [item["note_id"] for item in feed["items"]],
            [NOTE_ID, SECOND_NOTE_ID],
        )
        self.assertEqual(feed["items"][1]["type"], "video")
        self.assertEqual(feed["cursor_score"], "2.5")
        self.assertTrue(feed["has_more"])
        self.assertEqual(
            calls,
            [
                (
                    "/api/sns/web/v1/note/like",
                    [
                        ("note_id", NOTE_ID),
                        ("xsec_token", "TOKEN="),
                        ("xsec_source", "pc_feed"),
                    ],
                    NOTE_URL,
                ),
                (
                    "/api/sns/web/v1/comment/post",
                    [("note_id", NOTE_ID), ("content", "hello\nworld")],
                    NOTE_URL,
                ),
                (
                    "/api/sns/web/v1/feed",
                    [
                        ("note_id", NOTE_ID),
                        ("image_formats", "jpg,webp,avif"),
                        ("xsec_token", "TOKEN="),
                        ("xsec_source", "pc_feed"),
                    ],
                    NOTE_URL,
                ),
                (
                    "/api/sns/web/v1/homefeed",
                    [("num", "8"), ("cursor_score", "1.25")],
                    "https://www.xiaohongshu.com/explore",
                ),
            ],
        )

    def test_comment_and_home_feed_reject_invalid_inputs_before_browser_fetch(
        self,
    ) -> None:
        calls: list[object] = []
        client = XiaohongshuClient(
            browser_fetch=lambda *args: calls.append(args) or {}
        )
        cases = (
            lambda: client.like_note(NOTE_ID),
            lambda: client.view_note(NOTE_ID),
            lambda: client.comment_note(NOTE_ID, ""),
            lambda: client.comment_note(NOTE_ID, "   "),
            lambda: client.comment_note(NOTE_ID, "x" * 1001),
            lambda: client.comment_note(NOTE_ID, "hello\rworld"),
            lambda: client.get_home_feed(num=0),
            lambda: client.get_home_feed(num=41),
            lambda: client.get_home_feed(num=True),
        )
        for call in cases:
            with self.subTest(call=call), self.assertRaises(XiaohongshuInputError):
                call()
        self.assertEqual(calls, [])

    def test_view_rejects_empty_feed_items(self) -> None:
        with self.assertRaises(XiaohongshuResponseError):
            XiaohongshuClient(
                browser_fetch=lambda *_args: {"success": True, "items": []}
            ).view_note(NOTE_ID, xsec_token="TOKEN=")

    def test_browser_fetch_posts_engage_paths(self) -> None:
        call_daemon = AsyncMock(
            side_effect=[{"success": True}] * 4
        )
        paths = (
            "/api/sns/web/v1/note/like",
            "/api/sns/web/v1/comment/post",
            "/api/sns/web/v1/feed",
            "/api/sns/web/v1/homefeed",
        )
        with (
            patch.object(cli, "start_daemon") as start_daemon,
            patch.object(cli, "call_daemon", call_daemon),
        ):
            fetch = cli._browser_fetch(1.5)
            for path in paths:
                fetch(path, [("note_id", NOTE_ID)], NOTE_URL)

        self.assertEqual(start_daemon.call_count, 1)
        methods = [call.args[0]["method"] for call in call_daemon.await_args_list]
        self.assertEqual(methods, ["POST", "POST", "POST", "POST"])
        self.assertEqual(
            [call.args[0]["platform"] for call in call_daemon.await_args_list],
            ["xiaohongshu"] * 4,
        )
        self.assertEqual(call_daemon.await_args_list[0].args[0]["path"], paths[0])
        self.assertEqual(
            call_daemon.await_args_list[0].args[0]["request_interval_ms"],
            1500,
        )


if __name__ == "__main__":
    unittest.main()
