from __future__ import annotations


class XiguaError(Exception):
    """西瓜视频匿名客户端的基础异常。"""


class XiguaInputError(XiguaError):
    """调用方提供的西瓜视频参数格式错误或不受支持。"""


class XiguaResponseError(XiguaError):
    """西瓜视频返回了不可用的 HTTP、JSON、SSR 或加密响应。"""
