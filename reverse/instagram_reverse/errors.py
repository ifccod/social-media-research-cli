from __future__ import annotations


class InstagramError(Exception):
    """Instagram 匿名客户端的基础异常。"""


class InstagramInputError(InstagramError):
    """调用方提供了格式错误的用户名、帖子或媒体引用。"""


class InstagramResponseError(InstagramError):
    """Instagram 返回了不可用的 HTTP 或数据响应。"""
