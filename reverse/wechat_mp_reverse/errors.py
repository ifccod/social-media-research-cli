class WeChatMPError(Exception):
    """微信公众号匿名客户端的基础异常。"""


class WeChatMPInputError(WeChatMPError):
    """调用方提供的文章引用或选项无效。"""


class WeChatMPResponseError(WeChatMPError):
    """微信返回了不可用的响应。"""

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
