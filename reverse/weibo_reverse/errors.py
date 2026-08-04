from __future__ import annotations


class WeiboError(Exception):
    """微博移动网页匿名客户端的基础异常。"""


class WeiboInputError(WeiboError):
    """调用方提供的微博公开引用格式错误。"""


class WeiboResponseError(WeiboError):
    """微博返回了不可用的 HTTP、JSON 或访客响应。"""
