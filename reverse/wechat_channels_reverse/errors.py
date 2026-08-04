class WeChatChannelsError(Exception):
    """微信视频号公开客户端的基础异常。"""


class WeChatChannelsInputError(WeChatChannelsError, ValueError):
    """调用方提供的分享引用或选项无效。"""


class WeChatChannelsResponseError(WeChatChannelsError):
    """公开预览接口返回了不可用的响应。"""

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
