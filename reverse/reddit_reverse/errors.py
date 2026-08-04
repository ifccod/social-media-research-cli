from __future__ import annotations


class RedditError(Exception):
    """Reddit 匿名客户端的基础异常。"""


class RedditInputError(RedditError):
    """调用方提供的 Reddit 公开引用格式错误。"""


class RedditResponseError(RedditError):
    """Reddit 返回了不可用的 HTTP 或 JSON 响应。"""


class RedditRateLimited(RedditResponseError):
    """Reddit 要求当前会话暂停后再继续请求。"""

    def __init__(self, path: str, *, retry_after_seconds: float | None = None) -> None:
        self.path = path
        self.retry_after_seconds = retry_after_seconds
        detail = f"Reddit returned HTTP 429 for {path}"
        if retry_after_seconds is not None:
            detail += f"; retry after {max(0, int(retry_after_seconds + 0.999))}s"
        super().__init__(detail)
