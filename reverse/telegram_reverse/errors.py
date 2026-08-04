from __future__ import annotations


class TelegramError(Exception):
    """Telegram 匿名客户端的基础异常。"""


class TelegramInputError(TelegramError):
    """调用方提供的频道或帖子引用格式错误。"""


class TelegramResponseError(TelegramError):
    """Telegram 返回了不可用的 HTTP 或 HTML 响应。"""
