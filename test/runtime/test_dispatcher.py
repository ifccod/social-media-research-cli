from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from reverse import PLATFORM_MODULES, normalize_platform
from reverse.__main__ import main


def _make_parser_with_subcommands():
    """构造仅供命令列表测试使用的临时解析器。"""
    import argparse

    parser = argparse.ArgumentParser(description="临时客户端")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("search", help="搜索公开帖子")
    commands.add_parser("post", help="查询一条帖子")
    return parser


class DispatcherTest(unittest.TestCase):
    def test_platform_registry_has_each_python_package(self) -> None:
        self.assertEqual(len(PLATFORM_MODULES), 26)
        self.assertEqual(normalize_platform("wechat-channels"), "wechat_channels")

    def test_unknown_platform_returns_usage_error(self) -> None:
        with redirect_stderr(StringIO()):
            self.assertEqual(main(["not-a-platform"]), 2)

    def test_dispatches_arguments_to_selected_cli(self) -> None:
        seen: list[str] = []

        def fake_main() -> int:
            seen.extend(sys.argv)
            return 17

        fake_cli = types.SimpleNamespace(main=fake_main)
        with patch("reverse.__main__.importlib.import_module", return_value=fake_cli) as loader:
            self.assertEqual(main(["reddit", "search", "python"]), 17)

        loader.assert_called_once_with("reverse.reddit_reverse.cli")
        self.assertEqual(seen, ["python -m reverse reddit", "search", "python"])

    def test_dispatches_session_commands_to_the_local_bridge(self) -> None:
        with patch("reverse.browser_session.main", return_value=23) as session:
            self.assertEqual(main(["session", "status", "--platform", "reddit"]), 23)
        session.assert_called_once_with(["status", "--platform", "reddit"])

    def test_package_directory_is_a_supported_python_entrypoint(self) -> None:
        root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "reverse"),
                "douyin",
                "hot",
                "--limit",
                "0",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["count"], 0)


class ListCommandTest(unittest.TestCase):
    def test_list_does_not_invoke_a_platform_cli_main(self) -> None:
        # list 只检查各平台的 cli._parser()，不能像真实命令那样调用 cli.main()。
        invocations: list[str] = []

        fake_cli = types.SimpleNamespace(
            main=lambda: invocations.append("main-called") or 99,
            _parser=lambda: _make_parser_with_subcommands(),
        )
        with patch("reverse.__main__.importlib.import_module", return_value=fake_cli):
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["list", "--platform", "reddit"]), 0)
        self.assertEqual(invocations, [])

    def test_list_json_covers_every_platform(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["list", "--json"]), 0)
        payload = json.loads(buffer.getvalue())
        names = [item["name"] for item in payload["platforms"]]
        self.assertEqual(names, list(PLATFORM_MODULES.keys()))
        for item in payload["platforms"]:
            self.assertIn("description", item)
            self.assertIsInstance(item["commands"], list)
            for command in item["commands"]:
                self.assertIn("name", command)
                self.assertIn("summary", command)

    def test_list_platform_filter_returns_only_that_platform(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["list", "--platform", "reddit"]), 0)
        output = buffer.getvalue()
        self.assertIn("[reddit]", output)
        # 筛选后的列表不得混入其他平台
        self.assertNotIn("[douyin]", output)
        self.assertIn("search", output)

    def test_list_unknown_platform_returns_error(self) -> None:
        with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
            self.assertEqual(main(["list", "--platform", "nope"]), 2)

    def test_describe_selects_one_command_from_the_same_catalog(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(
                main(["describe", "reddit", "search", "--format", "json"]),
                0,
            )
        payload = json.loads(buffer.getvalue())
        self.assertEqual([item["name"] for item in payload["platforms"]], ["reddit"])
        self.assertEqual(
            [item["name"] for item in payload["platforms"][0]["commands"]],
            ["search"],
        )


if __name__ == "__main__":
    unittest.main()
