from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reverse.xiaohongshu_reverse import cli
from reverse.xiaohongshu_reverse.client import (
    CREATOR_PUBLISH_NOTE_PATH,
    CREATOR_REFERER,
    CREATOR_UPLOAD_IMAGE_PATH,
    CREATOR_UPLOAD_VIDEO_PATH,
    VIDEO_CHUNK_BYTES,
    XiaohongshuClient,
)
from reverse.xiaohongshu_reverse.errors import XiaohongshuInputError


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00"
NOTE_ID = "0123456789abcdef01234567"
VIDEO_UPLOAD_ID = "fixture-upload-id"


def _png(directory: Path, name: str = "pic.png") -> Path:
    path = directory / name
    path.write_bytes(PNG_BYTES)
    return path


def _mp4(directory: Path, name: str = "clip.mp4", size: int = 32) -> Path:
    path = directory / name
    header = b"\x00\x00\x00\x18ftypmp42"
    path.write_bytes(header + b"\x00" * max(0, size - len(header)))
    return path


class XiaohongshuPublishClientTests(unittest.TestCase):
    def test_parser_exposes_publish_note(self) -> None:
        parser = cli._parser()
        args = parser.parse_args(
            [
                "publish-note",
                "--title",
                "标题",
                "--content",
                "正文",
                "--images",
                "a.png",
            ]
        )
        self.assertEqual(args.command, "publish-note")
        self.assertEqual(args.title, "标题")
        self.assertEqual(args.content, "正文")
        self.assertEqual(args.images, [Path("a.png")])
        help_text = parser.format_help()
        self.assertIn("publish-note", help_text)
        self.assertIn("Chrome 创作者页临时传输", help_text)
        self.assertIn("https://creator.xiaohongshu.com/publish/publish", help_text)
        publish_parser = next(
            action.choices["publish-note"]
            for action in parser._actions
            if isinstance(getattr(action, "choices", None), dict)
            and "publish-note" in action.choices
        )
        command_help = publish_parser.format_help()
        self.assertIn("Chrome 创作者页临时传输", command_help)
        self.assertIn("https://creator.xiaohongshu.com/publish/publish", command_help)
        self.assertIn("--title", command_help)
        self.assertIn("--content", command_help)
        self.assertIn("--images", command_help)
        self.assertIn("--video", command_help)
        self.assertIn("--cover", command_help)
        self.assertIn("图文或视频", command_help)
        self.assertIn("Chrome 创作者页临时传输", command_help)

    def test_publish_note_uploads_then_publishes_with_bridge_entries(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            if path == CREATOR_UPLOAD_IMAGE_PATH:
                return {
                    "file_id": "fixture-file-id",
                    "width": 8,
                    "height": 6,
                }
            return {
                "success": True,
                "result": 0,
                "data": {"id": NOTE_ID},
            }

        with tempfile.TemporaryDirectory() as raw:
            media = _png(Path(raw))
            result = XiaohongshuClient(creator_fetch=fetch).publish_note(
                "标题",
                "正文\n第二行",
                images=[media],
            )

        self.assertEqual(result["kind"], "xiaohongshu_note")
        self.assertEqual(result["id"], NOTE_ID)
        self.assertEqual(result["file_ids"], ["spectrum/fixture-file-id"])
        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], CREATOR_UPLOAD_IMAGE_PATH)
        self.assertEqual(calls[0][2], CREATOR_REFERER)
        self.assertEqual(
            dict(calls[0][1]),
            {
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(PNG_BYTES).decode("ascii"),
            },
        )
        self.assertEqual(calls[1][0], CREATOR_PUBLISH_NOTE_PATH)
        self.assertEqual(
            dict(calls[1][1]),
            {
                "title": "标题",
                "content": "正文\n第二行",
                "file_ids": "spectrum/fixture-file-id",
            },
        )

    def test_publish_note_reads_note_id_from_alternate_fields(self) -> None:
        def fetch(path, entries, referer):
            if path == CREATOR_UPLOAD_IMAGE_PATH:
                return {"file_id": "spectrum/already-prefixed"}
            return {"success": True, "note_id": NOTE_ID}

        with tempfile.TemporaryDirectory() as raw:
            result = XiaohongshuClient(creator_fetch=fetch).publish_note(
                "标题",
                "正文",
                images=[_png(Path(raw))],
            )
        self.assertEqual(result["id"], NOTE_ID)
        self.assertEqual(result["file_ids"], ["spectrum/already-prefixed"])

    def test_publish_note_allows_success_without_id(self) -> None:
        def fetch(path, entries, referer):
            if path == CREATOR_UPLOAD_IMAGE_PATH:
                return {"file_id": "fixture-file-id"}
            return {"success": True, "result": 0}

        with tempfile.TemporaryDirectory() as raw:
            result = XiaohongshuClient(creator_fetch=fetch).publish_note(
                "标题",
                "正文",
                images=[_png(Path(raw))],
            )
        self.assertIsNone(result["id"])
        self.assertTrue(result["success"])

    def test_publish_note_rejects_long_title_and_missing_images(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            raise AssertionError("must not call browser")

        client = XiaohongshuClient(creator_fetch=fetch)
        with self.assertRaises(XiaohongshuInputError):
            client.publish_note("一二三四五六七八九十一二三四五六七八九十一", "正文", images=["a.png"])
        with self.assertRaises(XiaohongshuInputError):
            client.publish_note("标题", "正文", images=[])
        with self.assertRaises(XiaohongshuInputError):
            client.publish_note("标题", "正文", images=["a.png"] * 10)
        with self.assertRaises(XiaohongshuInputError):
            client.publish_note("标题", "正文", images=["a.png"], video="a.mp4")
        self.assertEqual(calls, [])

    def test_parser_images_and_video_are_exclusive(self) -> None:
        parser = cli._parser()
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
        with patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "publish-note",
                    "--title",
                    "标题",
                    "--content",
                    "正文",
                ]
            )
        args = parser.parse_args(
            [
                "publish-note",
                "--title",
                "标题",
                "--content",
                "正文",
                "--video",
                "a.mp4",
                "--cover",
                "cover.jpg",
            ]
        )
        self.assertEqual(args.video, Path("a.mp4"))
        self.assertEqual(args.cover, Path("cover.jpg"))
        self.assertIsNone(args.images)

    def test_publish_note_video_uploads_chunks_then_cover_then_publishes(self) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, list(entries), referer))
            values = dict(entries)
            if path == CREATOR_UPLOAD_VIDEO_PATH and values.get("command") == "begin":
                return {"upload_id": VIDEO_UPLOAD_ID}
            if path == CREATOR_UPLOAD_VIDEO_PATH and values.get("command") == "finish":
                return {"file_id": "video-file-id", "width": 1280, "height": 720}
            if path == CREATOR_UPLOAD_IMAGE_PATH:
                return {"file_id": "cover-file-id", "width": 8, "height": 6}
            return {
                "success": True,
                "result": 0,
                "data": {"id": NOTE_ID},
            }

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            video = _mp4(directory, size=VIDEO_CHUNK_BYTES + 10)
            cover = _png(directory, "cover.png")
            data = video.read_bytes()
            result = XiaohongshuClient(creator_fetch=fetch).publish_note(
                "标题",
                "正文",
                video=video,
                cover=cover,
            )

        self.assertEqual(result["kind"], "xiaohongshu_note")
        self.assertEqual(result["id"], NOTE_ID)
        self.assertEqual(result["video_file_id"], "spectrum/video-file-id")
        self.assertEqual(result["cover_file_id"], "spectrum/cover-file-id")
        self.assertEqual(
            result["file_ids"],
            ["spectrum/video-file-id", "spectrum/cover-file-id"],
        )
        self.assertEqual(len(calls), 6)
        self.assertEqual(calls[0][0], CREATOR_UPLOAD_VIDEO_PATH)
        self.assertEqual(
            dict(calls[0][1]),
            {
                "command": "begin",
                "mimeType": "video/mp4",
                "total_bytes": str(len(data)),
            },
        )
        self.assertEqual(dict(calls[1][1])["command"], "chunk")
        self.assertEqual(dict(calls[1][1])["upload_id"], VIDEO_UPLOAD_ID)
        self.assertEqual(dict(calls[1][1])["segment_index"], "0")
        self.assertEqual(
            dict(calls[1][1])["dataBase64"],
            base64.b64encode(data[:VIDEO_CHUNK_BYTES]).decode("ascii"),
        )
        self.assertEqual(dict(calls[2][1])["command"], "chunk")
        self.assertEqual(dict(calls[2][1])["segment_index"], "1")
        self.assertEqual(
            dict(calls[2][1])["dataBase64"],
            base64.b64encode(data[VIDEO_CHUNK_BYTES:]).decode("ascii"),
        )
        self.assertEqual(
            dict(calls[3][1]),
            {"command": "finish", "upload_id": VIDEO_UPLOAD_ID},
        )
        self.assertEqual(calls[4][0], CREATOR_UPLOAD_IMAGE_PATH)
        self.assertEqual(
            dict(calls[4][1]),
            {
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(PNG_BYTES).decode("ascii"),
            },
        )
        self.assertEqual(calls[5][0], CREATOR_PUBLISH_NOTE_PATH)
        self.assertEqual(
            dict(calls[5][1]),
            {
                "title": "标题",
                "content": "正文",
                "video_file_id": "spectrum/video-file-id",
                "cover_file_id": "spectrum/cover-file-id",
                "width": "1280",
                "height": "720",
            },
        )
        self.assertEqual(calls[0][2], CREATOR_REFERER)

    @patch("reverse.xiaohongshu_reverse.client.shutil.which", return_value=None)
    def test_video_without_cover_requires_ffmpeg(self, _which) -> None:
        calls: list[tuple] = []

        def fetch(path, entries, referer):
            calls.append((path, entries, referer))
            raise AssertionError("must not call browser")

        with tempfile.TemporaryDirectory() as raw:
            video = _mp4(Path(raw))
            with self.assertRaises(XiaohongshuInputError) as caught:
                XiaohongshuClient(creator_fetch=fetch).publish_note(
                    "标题",
                    "正文",
                    video=video,
                )
        self.assertIn("ffmpeg", str(caught.exception))
        self.assertIn("--cover", str(caught.exception))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
