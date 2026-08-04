from __future__ import annotations


class ThreadsError(Exception):
    """Threads 匿名客户端的基础异常。"""


class ThreadsInputError(ThreadsError):
    """调用方提供的 Threads 引用格式错误或不受支持。"""


class ThreadsResponseError(ThreadsError):
    """Threads 返回了不可用的 HTTP 或公开页面响应。"""
