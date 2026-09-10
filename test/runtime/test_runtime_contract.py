from __future__ import annotations

import importlib
import json
import re
import tomllib
import unittest
from pathlib import Path

from reverse import PLATFORM_MODULES
from reverse.browser_session import PLATFORMS as BROWSER_PLATFORMS
from reverse.browser_session import PROTOCOL_VERSION
from reverse.browser_session import _rpc_timeout
from reverse.catalog import (
    interface_document,
    platform_catalog,
    render_markdown,
    render_skill,
)


ROOT = Path(__file__).resolve().parents[2]
REVERSE_DIR = ROOT / "reverse"
EXTENSION_DIR = ROOT / "browser_session_bridge"
EXPECTED_PLATFORMS = {
    "bilibili",
    "douyin",
    "facebook_ads",
    "instagram",
    "kuaishou",
    "lemon8",
    "linkedin",
    "microsoft_ads",
    "netease_music",
    "pinterest_ads",
    "pipixia",
    "reddit",
    "snapchat_ads",
    "telegram",
    "threads",
    "tiktok",
    "toutiao",
    "twitter",
    "wechat_channels",
    "wechat_mp",
    "wechat_search",
    "weibo",
    "xiaohongshu",
    "xigua",
    "youtube",
    "zhihu",
}
EXPECTED_BROWSER_PLATFORMS = {
    "bilibili",
    "douyin",
    "douyin_index",
    "linkedin",
    "reddit",
    "tiktok_ads_manager",
    "tiktok_creative",
    "tiktok_creative_studio",
    "tiktok_creative_topads",
    "tiktok_one",
    "twitter_home",
    "twitter_search",
    "xiaohongshu",
    "xiaohongshu_app_v2",
    "xiaohongshu_pgy",
}


def repository_files(pattern: str) -> list[Path]:
    ignored = {".git", ".venv", "node_modules", "__pycache__"}
    return sorted(
        path
        for path in ROOT.rglob(pattern)
        if ignored.isdisjoint(path.relative_to(ROOT).parts)
    )


class RuntimeContractTest(unittest.TestCase):
    def test_tests_are_root_owned_and_platform_memory_is_local(self) -> None:
        reverse_tests = sorted(
            path
            for path in REVERSE_DIR.rglob("*.py")
            if path.name.startswith("test_") or path.name.endswith("_test.py")
        )
        self.assertEqual(reverse_tests, [])

        test_files = sorted(
            path
            for path in (ROOT / "test").rglob("*.py")
            if path.name.startswith("test_") or path.name.endswith("_test.py")
        )
        self.assertGreater(len(test_files), 0)
        for path in test_files:
            relative = path.relative_to(ROOT)
            self.assertEqual(relative.parts[0], "test")
            self.assertGreaterEqual(len(relative.parts), 3)
            self.assertTrue((path.parent / "__init__.py").is_file())

        for package in sorted(REVERSE_DIR.glob("*_reverse")):
            with self.subTest(package=package.name):
                self.assertTrue((package / "AGENTS.md").is_file())

    def test_project_runtime_is_python_only(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["scripts"]["reverse"], "reverse.__main__:main")
        dependencies = " ".join(project["project"]["dependencies"]).lower()
        self.assertIsNone(
            re.search(r"\b(?:fastapi|uvicorn|mysql|pymysql|sqlalchemy)\b", dependencies)
        )
        self.assertEqual(repository_files("*.go"), [])
        self.assertEqual(repository_files("go.mod"), [])
        self.assertEqual(repository_files("go.sum"), [])
        self.assertEqual(repository_files("requirements*.txt"), [])
        for legacy in ("cli", "server", "work"):
            self.assertFalse((ROOT / legacy).exists())
        self.assertFalse((ROOT / "build" / "compile_releases.py").exists())
        self.assertFalse((ROOT / "build" / "release-manifest.schema.json").exists())

        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(
                r"\b(?:golang|fastapi|uvicorn|mysql)\b|REVERSE_API_KEY",
                makefile,
                re.IGNORECASE,
            )
        )
        runtime_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in REVERSE_DIR.rglob("*.py")
            if not path.name.startswith("test_")
        )
        for marker in ("REVERSE_API_KEY", "REVERSE_SERVER", "server.signing"):
            self.assertNotIn(marker, runtime_source)

    def test_platform_contexts_and_catalog_share_one_contract(self) -> None:
        self.assertEqual(set(PLATFORM_MODULES), EXPECTED_PLATFORMS)
        self.assertEqual(len(PLATFORM_MODULES), 26)
        for module_name in PLATFORM_MODULES.values():
            with self.subTest(module=module_name):
                directory = REVERSE_DIR / module_name
                required = {"__init__.py", "__main__.py", "client.py", "cli.py", "errors.py"}
                self.assertEqual(
                    required - {path.name for path in directory.iterdir() if path.is_file()},
                    set(),
                )
                self.assertIsNotNone(importlib.import_module(f"reverse.{module_name}"))

        catalog = platform_catalog()
        self.assertEqual([platform.name for platform in catalog], list(PLATFORM_MODULES))
        self.assertEqual(sum(len(platform.commands) for platform in catalog), 281)
        tiktok = next(platform for platform in catalog if platform.name == "tiktok")
        tiktok_commands = {command.name for command in tiktok.commands}
        self.assertTrue(
            {"search-opportunity", "creative-pipeline"}.isdisjoint(
                tiktok_commands
            )
        )
        workflows = [
            (platform.name, command.name)
            for platform in catalog
            for command in platform.commands
            if command.level == "workflow"
        ]
        self.assertEqual(workflows, [("twitter", "discover")])
        reddit = next(platform for platform in catalog if platform.name == "reddit")
        self.assertEqual(
            {parameter.destination for parameter in reddit.parameters},
            {"timeout", "retries", "proxy", "output"},
        )

        document = interface_document()
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(document["runtime"], "python")
        self.assertEqual([service["name"] for service in document["services"]], ["session"])
        self.assertEqual(
            {command["name"] for command in document["services"][0]["commands"]},
            {"start", "status", "login", "request", "stop"},
        )
        for section in [*document["platforms"], *document["services"]]:
            prose = [section["description"]]
            prose.extend(parameter["help"] for parameter in section["parameters"])
            for command in section["commands"]:
                self.assertIn(command["level"], {"primitive", "workflow"})
                prose.extend((command["summary"], command["description"]))
                prose.extend(parameter["help"] for parameter in command["parameters"])
            for text in filter(None, prose):
                with self.subTest(section=section["name"], text=text):
                    self.assertRegex(text, r"[\u4e00-\u9fff]")

    def test_generated_skill_matches_parser_contract(self) -> None:
        skill = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(skill, render_skill())
        self.assertIn("26 个平台上下文和 281 条命令", skill)
        self.assertIn("### 跨平台广告素材研究", skill)
        self.assertIn("`facebook_ads search-ads`", skill)
        self.assertIn("`facebook_ads ad-details`", skill)
        self.assertIn("`snapchat_ads search-ads`", skill)
        self.assertIn("领域工作流：`discover`", skill)
        self.assertNotIn("`search-opportunity`", skill)
        self.assertNotIn("`creative-pipeline`", skill)
        self.assertIn("不生成固定机会分", skill)
        markdown = render_markdown(interface_document())
        self.assertIn("# reverse CLI 接口", markdown)
        self.assertIn("| 参数 | 类型 | 必填 | 说明 |", markdown)
        self.assertNotIn("usage:", markdown)
        self.assertIn("用法:", markdown)
        self.assertFalse((ROOT / "skill" / "references").exists())
        self.assertFalse((ROOT / "docs" / "site").exists())
        self.assertFalse((REVERSE_DIR / "README.md").exists())

    def test_browser_bridge_retains_fifteen_loopback_scopes(self) -> None:
        self.assertEqual(PROTOCOL_VERSION, 4)
        self.assertEqual(set(BROWSER_PLATFORMS), EXPECTED_BROWSER_PLATFORMS)

        manifest = json.loads(
            (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(
            manifest["background"]["service_worker"], "service_worker_v2.js"
        )
        self.assertEqual(manifest["action"]["default_popup"], "ui/popup.html")
        self.assertNotIn("cookies", manifest["permissions"])
        self.assertNotIn("webRequest", manifest["permissions"])
        self.assertIn(
            "ws://127.0.0.1:18765",
            manifest["content_security_policy"]["extension_pages"],
        )
        protocol = (EXTENSION_DIR / "core" / "protocol.js").read_text(
            encoding="utf-8"
        )
        wire = (EXTENSION_DIR / "core" / "wire_protocol_v4.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('DEFAULT_BRIDGE_URL = "ws://127.0.0.1:18765"', protocol)
        self.assertIn("MAX_WIRE_BYTES = 7 * 1024 * 1024", protocol)
        self.assertIn(f"BRIDGE_PROTOCOL_VERSION = {PROTOCOL_VERSION}", wire)
        worker = (EXTENSION_DIR / "service_worker_v2.js").read_text(
            encoding="utf-8"
        )
        local_bridge = (EXTENSION_DIR / "core" / "local_bridge_v2.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("CANCELLATION_GRACE_MS = 1500", local_bridge)
        self.assertEqual(
            {int(value) for value in re.findall(r"timeout:\s*(\d+)", worker)},
            {15_000, 20_000, 35_000, 45_000},
        )
        self.assertEqual(
            {
                _rpc_timeout("reddit", "session"),
                _rpc_timeout("xiaohongshu_pgy", "session"),
                _rpc_timeout("reddit", "request"),
                _rpc_timeout("xiaohongshu_pgy", "request"),
            },
            {20, 25, 40, 50},
        )
        registered = set(
            re.findall(r"^  ([a-z0-9_]+): \{$", worker, flags=re.MULTILINE)
        )
        self.assertEqual(registered & EXPECTED_BROWSER_PLATFORMS, EXPECTED_BROWSER_PLATFORMS)

        required_assets = {
            "core/local_bridge_v2.js",
            "core/wire_protocol_v4.js",
            "ui/popup.html",
            "ui/popup_v2.js",
            "adapters/bilibili/adapter.js",
            "adapters/douyin/adapter.js",
            "adapters/douyin_index/adapter.js",
            "adapters/linkedin/adapter.js",
            "adapters/reddit/adapter.js",
            "adapters/tiktok_creative/adapter.js",
            "adapters/twitter/adapter.js",
            "adapters/xiaohongshu/adapter.js",
            "adapters/xiaohongshu_app_v2/adapter.js",
            "adapters/xiaohongshu_pgy/adapter.js",
        }
        present = {
            str(path.relative_to(EXTENSION_DIR))
            for path in EXTENSION_DIR.rglob("*")
            if path.is_file()
        }
        self.assertEqual(required_assets - present, set())

    def test_readme_records_the_current_project_contract(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for marker in (
            "26 个平台上下文",
            "281 条命令",
            "Python 3.11",
            "test/runtime/",
            "AGENTS.md",
            "Node.js 18",
            "creative-trending-hashtags",
            "facebook_ads",
            "snapchat_ads",
            "reverse session request",
            "REDDIT_OPPORTUNITY_PROXY",
            "make docs-check",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, readme)


if __name__ == "__main__":
    unittest.main()
