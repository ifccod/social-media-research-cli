from __future__ import annotations

import csv
import inspect
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from reverse.twitter_reverse import cli
from reverse.twitter_reverse.errors import TwitterResponseError
from reverse.twitter_reverse.follow_batch import run_follow_batch


class FakeFollowClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, str | None]] = []

    def follow(
        self,
        screen_name: str | None = None,
        user_id: str | None = None,
    ) -> object:
        self.calls.append({"screen_name": screen_name, "user_id": user_id})
        if not self.outcomes:
            raise AssertionError("unexpected follow")
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok(user_id: str = "1", screen_name: str = "alice", *, already: bool = False) -> dict:
    return {
        "kind": "twitter_follow",
        "following": True,
        "user_id": user_id,
        "screen_name": screen_name,
        "already_following": already,
    }


class TwitterFollowBatchTests(unittest.TestCase):
    def test_parser_exposes_follow_batch_without_workflow_level(self) -> None:
        parser = cli._parser()
        args = parser.parse_args(["follow-batch", "--file", "names.txt"])
        self.assertNotEqual(getattr(args, "_command_level", None), "workflow")
        self.assertIn("follow-batch", cli._BROWSER_COMMANDS)
        self.assertIn("follow", cli._BROWSER_COMMANDS)
        self.assertIn("schedule-tweet", cli._BROWSER_COMMANDS)
        self.assertEqual(args.cooldown, 1800)
        self.assertEqual(args.interval, 18)
        self.assertEqual(args.window_seconds, 900)
        self.assertEqual(args.window_limit, 50)
        self.assertEqual(args.daily_limit, 400)
        self.assertTrue(str(args.state).endswith("twitter-follow-state.jsonl"))
        with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["follow-batch"])
        with patch("sys.stderr", StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                ["follow-batch", "--file", "a.txt", "--csv", "b.csv"]
            )

    def test_file_follows_in_order_and_skips_comments(self) -> None:
        client = FakeFollowClient(
            [
                _ok("12345", "n1"),
                _ok("2", "alice"),
                _ok("3", "bob"),
            ]
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            names = root / "names.txt"
            names.write_text("# heading\n12345\n@alice\n\nbob\n", encoding="utf-8")
            result = run_follow_batch(
                client,
                file_path=names,
                state_path=root / "state.jsonl",
                sleep=lambda _seconds: self.fail("should not sleep"),
            )
        self.assertEqual(
            client.calls,
            [
                {"screen_name": None, "user_id": "12345"},
                {"screen_name": "alice", "user_id": None},
                {"screen_name": "bob", "user_id": None},
            ],
        )
        self.assertEqual(result["kind"], "twitter_follow_batch")
        self.assertEqual(result["attempted"], 3)
        self.assertEqual(result["followed"], 3)
        self.assertEqual(result["skipped"], 0)
        self.assertIsNone(result["stopped_reason"])

    def test_csv_skips_already_following_yes(self) -> None:
        client = FakeFollowClient([_ok("2", "bob"), _ok("3", "carol")])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            csv_path = root / "discover.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["主页链接", "我是否关注", "标签", "粉丝数", "关注数", "AI判断总结"]
                )
                writer.writerow(
                    ["https://x.com/alice", "是", "mutual_blue", 1, 1, ""]
                )
                writer.writerow(["https://x.com/bob", "否", "kol", 2, 2, ""])
                writer.writerow(["https://twitter.com/carol", "", "tag", 3, 3, ""])
            result = run_follow_batch(
                client,
                csv_path=csv_path,
                state_path=root / "state.jsonl",
                sleep=lambda _seconds: self.fail("should not sleep"),
            )
        self.assertEqual(
            client.calls,
            [
                {"screen_name": "bob", "user_id": None},
                {"screen_name": "carol", "user_id": None},
            ],
        )
        self.assertEqual(result["followed"], 2)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["attempted"], 2)

    def test_rate_limited_sleeps_cooldown_then_retries_same_user(self) -> None:
        client = FakeFollowClient(
            [
                TwitterResponseError("slow", code="rate_limited"),
                _ok("12345", "alice"),
            ]
        )
        slept: list[float] = []
        logged = StringIO()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            names = root / "names.txt"
            names.write_text("12345\n", encoding="utf-8")
            result = run_follow_batch(
                client,
                file_path=names,
                state_path=root / "state.jsonl",
                cooldown=7,
                sleep=slept.append,
                log=logged,
            )
        self.assertEqual(slept, [7])
        self.assertIn(
            "[限流] user_id=12345 rate_limited，休息 7 秒后重试同一条",
            logged.getvalue(),
        )
        self.assertIn("[限流] 冷却结束，继续 user_id=12345", logged.getvalue())
        self.assertEqual(
            client.calls,
            [
                {"screen_name": None, "user_id": "12345"},
                {"screen_name": None, "user_id": "12345"},
            ],
        )
        self.assertEqual(result["followed"], 1)
        self.assertEqual(result["attempted"], 2)
        self.assertEqual(result["cooldown"], 1)
        self.assertIsNone(result["stopped_reason"])

    def test_interval_sleeps_between_follows_not_after_cooldown(self) -> None:
        client = FakeFollowClient(
            [
                _ok("1", "a"),
                TwitterResponseError("slow", code="rate_limited"),
                _ok("2", "b"),
            ]
        )
        slept: list[float] = []
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            names = root / "names.txt"
            names.write_text("1\n2\n", encoding="utf-8")
            result = run_follow_batch(
                client,
                file_path=names,
                state_path=root / "state.jsonl",
                interval=9,
                cooldown=7,
                sleep=slept.append,
            )
        self.assertEqual(slept, [9, 7])
        self.assertEqual(result["followed"], 2)
        self.assertEqual(result["cooldown"], 1)

    def test_daily_limit_stops_without_calling_more(self) -> None:
        client = FakeFollowClient([_ok("1", "a"), _ok("2", "b")])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            names = root / "names.txt"
            names.write_text("1\n2\n", encoding="utf-8")
            result = run_follow_batch(
                client,
                file_path=names,
                state_path=root / "state.jsonl",
                daily_limit=1,
                window_limit=0,
                sleep=lambda _seconds: self.fail("should not sleep"),
            )
        self.assertEqual(result["followed"], 1)
        self.assertEqual(result["stopped_reason"], "daily_limit")
        self.assertEqual(len(client.calls), 1)

    def test_window_limit_sleeps_then_continues(self) -> None:
        client = FakeFollowClient([_ok("1", "a"), _ok("2", "b")])
        clock = [1000.0]
        slept: list[float] = []

        def fake_now() -> float:
            return clock[0]

        def fake_sleep(seconds: float) -> None:
            slept.append(seconds)
            clock[0] += seconds

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            names = root / "names.txt"
            names.write_text("1\n2\n", encoding="utf-8")
            result = run_follow_batch(
                client,
                file_path=names,
                state_path=root / "state.jsonl",
                interval=0,
                window_seconds=10,
                window_limit=1,
                daily_limit=0,
                sleep=fake_sleep,
                now=fake_now,
            )
        self.assertEqual(slept, [10])
        self.assertEqual(result["followed"], 2)
        self.assertIsNone(result["stopped_reason"])

    def test_state_resume_does_not_repeat_followed(self) -> None:
        client = FakeFollowClient([_ok("2", "alice")])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            names = root / "names.txt"
            names.write_text("12345\n@alice\n", encoding="utf-8")
            state = root / "state.jsonl"
            state.write_text(
                json.dumps(
                    {
                        "type": "followed",
                        "user_id": "12345",
                        "screen_name": "n1",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_follow_batch(
                client,
                file_path=names,
                state_path=state,
                sleep=lambda _seconds: self.fail("should not sleep"),
            )
        self.assertEqual(
            client.calls,
            [{"screen_name": "alice", "user_id": None}],
        )
        self.assertEqual(result["followed"], 1)
        self.assertEqual(result["attempted"], 1)

    def test_forbidden_skips_and_session_errors_stop_batch(self) -> None:
        client = FakeFollowClient(
            [
                TwitterResponseError("blocked", code="forbidden"),
                TwitterResponseError("login", code="not_logged_in"),
            ]
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            names = root / "names.txt"
            names.write_text("alice\nbob\ncarol\n", encoding="utf-8")
            result = run_follow_batch(
                client,
                file_path=names,
                state_path=root / "state.jsonl",
                sleep=lambda _seconds: self.fail("should not sleep"),
            )
        self.assertEqual(
            [item["screen_name"] for item in client.calls],
            ["alice", "bob"],
        )
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["followed"], 0)
        self.assertEqual(result["stopped_reason"], "not_logged_in")
        self.assertEqual(result["attempted"], 2)

    def test_module_does_not_import_or_call_discover(self) -> None:
        from reverse.twitter_reverse import follow_batch

        source = inspect.getsource(follow_batch)
        self.assertNotIn("run_discover", source)
        self.assertNotIn("discover import", source)
        self.assertNotIn(".discover", source)
        self.assertNotIn("reverse.twitter_reverse.discover", source)


if __name__ == "__main__":
    unittest.main()
