from __future__ import annotations


class YouTubeError(Exception):
    """YouTube 匿名客户端的基础异常。"""


class YouTubeInputError(YouTubeError):
    """调用方提供的 YouTube 视频引用无效。"""


class YouTubeResponseError(YouTubeError):
    """YouTube 返回了不可用的 HTTP、JSON 或播放器响应。"""
