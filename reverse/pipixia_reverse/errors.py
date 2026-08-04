from __future__ import annotations


class PiPiXiaError(Exception):
    """PiPiXia 匿名客户端的基础异常。"""


class PiPiXiaInputError(PiPiXiaError):
    """调用方提供了格式错误或不受支持的 PiPiXia 值。"""


class PiPiXiaResponseError(PiPiXiaError):
    """PiPiXia 返回了不可用的 HTTP 或 JSON 响应。"""
