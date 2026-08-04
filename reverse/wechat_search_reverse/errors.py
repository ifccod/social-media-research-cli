class WeChatSearchError(Exception):
    """微信公开搜索匿名客户端的基础异常。"""


class WeChatSearchInputError(WeChatSearchError):
    """调用方提供的搜索选项或 URL 无效。"""


class WeChatSearchResponseError(WeChatSearchError):
    """公开搜索服务返回了不可用的响应。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | str | None = None,
        url: str | None = None,
        payload: object = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.url = url
        self.payload = payload
        self.retryable = retryable
