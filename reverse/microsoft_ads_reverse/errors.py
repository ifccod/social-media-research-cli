from __future__ import annotations


class MicrosoftAdsError(Exception):
    """Microsoft Ad Library 错误基类。"""

    code = "microsoft_ads_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class MicrosoftAdsInputError(MicrosoftAdsError):
    """输入参数不满足公开接口合同。"""

    code = "invalid_input"


class MicrosoftAdsTransportError(MicrosoftAdsError):
    """网络、限流或上游 HTTP 状态错误。"""

    code = "transport_error"


class MicrosoftAdsResponseError(MicrosoftAdsError):
    """上游响应结构或内容错误。"""

    code = "invalid_response"
