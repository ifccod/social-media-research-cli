"""本地平台客户端。

每个 ``*_reverse`` 包都是独立的平台限界上下文。共享 CLI 和生成式接口目录会
自动发现这些包，不再维护第二份注册表。
"""

from __future__ import annotations

from pkgutil import iter_modules


PLATFORM_MODULES: dict[str, str] = {
    module.name.removesuffix("_reverse"): module.name
    for module in sorted(iter_modules(__path__), key=lambda item: item.name)
    if module.ispkg
    and module.name.endswith("_reverse")
    and not module.name.endswith("_app_reverse")
}


def normalize_platform(name: str) -> str:
    """返回调度器接受的规范平台名。"""
    return name.strip().lower().replace("-", "_")
