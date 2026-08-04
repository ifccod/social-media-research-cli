from __future__ import annotations


class Lemon8Error(Exception):
    """Lemon8 匿名客户端的基础异常。"""


class Lemon8InputError(Lemon8Error):
    """调用方提供了格式错误的 Lemon8 引用或选项。"""


class Lemon8ResponseError(Lemon8Error):
    """Lemon8 返回了不可用的 HTTP 或页面响应。"""
