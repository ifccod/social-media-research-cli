from __future__ import annotations


class TwitterError(Exception):
    """X/Twitter 匿名客户端的基础异常。"""


class TwitterInputError(TwitterError):
    """调用方提供的输入格式错误或不受支持。"""


class TwitterResponseError(TwitterError):
    """Syndication 接口返回了不可用的响应。"""


class TwitterSignatureError(TwitterError):
    """Syndication 令牌计算失败。"""
