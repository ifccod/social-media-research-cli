"""统一的本地命令行入口。"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys

# `python reverse` 会把目录当作脚本执行，先补入仓库根路径。
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverse import PLATFORM_MODULES, normalize_platform  # noqa: E402
from reverse.catalog import (
    dump_json,
    platform_catalog,
    render_markdown,
    render_skill,
    select_document,
)  # noqa: E402


def _usage() -> str:
    platforms = ", ".join(PLATFORM_MODULES)
    return (
        "用法: reverse <platform> <command> [options]\n"
        "       reverse list [--json] [--platform PLATFORM]\n"
        "       reverse describe [PLATFORM] [COMMAND] [--format FORMAT]\n"
        "       reverse session <command> [options]\n\n"
        f"平台: {platforms}\n"
        "\n"
        "示例:\n"
        "  reverse reddit search 'python typing' --subreddit python --limit 10\n"
        "  reverse douyin hot --limit 10\n"
        "  reverse session status\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(_usage(), end="")
        return 0

    command = normalize_platform(args[0])
    if command == "list":
        return run_list(args[1:])
    if command == "describe":
        return run_describe(args[1:])
    if command == "session":
        from reverse.browser_session import main as session_main

        return session_main(args[1:])

    platform = normalize_platform(args.pop(0))
    module_name = PLATFORM_MODULES.get(platform)
    if module_name is None:
        print(f"错误: 不支持的平台: {platform}", file=sys.stderr)
        print(_usage(), file=sys.stderr, end="")
        return 2

    cli = importlib.import_module(f"reverse.{module_name}.cli")
    original_argv = sys.argv
    try:
        sys.argv = [f"python -m reverse {platform}", *args]
        return int(cli.main())
    finally:
        sys.argv = original_argv


def _parse_list_args(args: list[str]) -> tuple[bool, str]:
    parser = argparse.ArgumentParser(
        prog="reverse list",
        description="列出本地代码目录中的命令。",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="输出结构化 JSON",
    )
    parser.add_argument(
        "--platform",
        default="",
        help="仅显示指定平台",
    )
    namespace = parser.parse_args(args)
    return namespace.as_json, normalize_platform(namespace.platform)


def run_list(args: list[str]) -> int:
    as_json, platform = _parse_list_args(args)
    if platform and platform not in PLATFORM_MODULES:
        print(f"错误: 不支持的平台: {platform}", file=sys.stderr)
        return 2

    platforms = platform_catalog()
    if platform:
        platforms = tuple(item for item in platforms if item.name == platform)
        if not platforms:
            print(f"错误: 平台 {platform} 没有可用命令", file=sys.stderr)
            return 2

    if as_json:
        print(dump_json(select_document(platform)), end="")
        return 0

    command_count = sum(len(item.commands) for item in platforms)
    print(f"reverse: {len(platforms)} 个平台，{command_count} 条命令")
    print()
    for item in platforms:
        header = f"[{item.name}]"
        if item.description:
            header = f"{header} {item.description}"
        print(header)
        for command in item.commands:
            line = f"  {command.name}"
            if command.level == "workflow":
                line = f"{line}  [工作流]"
            if command.summary:
                line = f"{line}  {command.summary}"
            print(line)
        print()
    print("用法: reverse <platform> <command> [options]")
    return 0


def run_describe(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="reverse describe",
        description="根据 argparse 声明生成接口文档。",
    )
    parser.add_argument("platform", nargs="?", default="")
    parser.add_argument("command", nargs="?", default="")
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "skill"),
        default="json",
    )
    parser.add_argument("--output", type=Path)
    namespace = parser.parse_args(args)
    platform = normalize_platform(namespace.platform)
    try:
        document = select_document(platform, namespace.command)
    except KeyError as exc:
        print(f"错误: 未知接口: {exc.args[0]}", file=sys.stderr)
        return 2
    if namespace.format == "json":
        output = dump_json(document)
    elif namespace.format == "markdown":
        output = render_markdown(document)
    else:
        if platform or namespace.command:
            parser.error("--format skill 仅用于描述完整接口")
        output = render_skill()
    if namespace.output:
        namespace.output.parent.mkdir(parents=True, exist_ok=True)
        namespace.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
