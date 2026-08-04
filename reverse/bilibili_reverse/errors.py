from __future__ import annotations


class BilibiliError(Exception):
    """Bilibili 客户端与签名辅助函数的基础异常。"""


class BilibiliInputError(BilibiliError):
    """调用方提供了格式错误或不受支持的输入。"""


class BilibiliResponseError(BilibiliError):
    """Bilibili 返回了不可用的 HTTP 或 API 响应。"""


class BilibiliSignatureError(BilibiliError):
    """本地 Bilibili 签名计算未能完成。"""
