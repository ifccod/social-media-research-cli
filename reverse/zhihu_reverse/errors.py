from __future__ import annotations

from typing import Any


class ZhihuError(Exception):
    """知乎匿名客户端的基础异常。"""


class ZhihuInputError(ZhihuError):
    """调用方提供的知乎引用或选项格式错误。"""


class ZhihuSignatureError(ZhihuError):
    """本地签名或 V8 验证步骤失败。"""


class ZhihuResponseError(ZhihuError):
    """知乎返回了不可用的响应。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | str | None = None,
        payload: Any = None,
        url: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.payload = payload
        self.url = url
        self.retryable = retryable
