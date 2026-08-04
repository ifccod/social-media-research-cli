from __future__ import annotations


class NeteaseMusicError(Exception):
    """NetEase Cloud Music 匿名客户端的基础异常。"""


class NeteaseMusicInputError(NeteaseMusicError):
    """调用方提供了格式错误或不受支持的输入。"""


class NeteaseMusicResponseError(NeteaseMusicError):
    """NetEase Cloud Music 返回了不可用的 HTTP 或 API 响应。"""
