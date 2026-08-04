from __future__ import annotations


class SnapchatAdsError(Exception):
    """Snapchat Ads Gallery 错误基类。"""

    code = "snapchat_ads_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class SnapchatAdsInputError(SnapchatAdsError):
    """输入参数不满足公开接口合同。"""

    code = "invalid_input"


class SnapchatAdsTransportError(SnapchatAdsError):
    """网络、限流或上游 HTTP 状态错误。"""

    code = "transport_error"


class SnapchatAdsResponseError(SnapchatAdsError):
    """上游响应结构或媒体内容错误。"""

    code = "invalid_response"
