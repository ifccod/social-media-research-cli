"""浏览器会话命令的终端进度输出。"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, TextIO


def stderr_progress(stream: TextIO | None = None) -> Callable[[dict[str, Any]], None]:
    """返回去重的进度回调，保持 JSON 独占标准输出。"""

    previous: tuple[str, str] | None = None

    def report(event: dict[str, Any]) -> None:
        nonlocal previous
        label = str(event.get("label", "浏览器")).strip() or "浏览器"
        message = str(event.get("message", "")).strip()
        current = (label, message)
        if not message or current == previous:
            return
        previous = current
        print(
            f"[{label}] {message}",
            file=stream or sys.stderr,
            flush=True,
        )

    return report


__all__ = ["stderr_progress"]
