from __future__ import annotations


class PinterestAdsError(Exception):
    """Pinterest 素材研究错误基类。"""

    code = "pinterest_ads_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class PinterestAdsInputError(PinterestAdsError):
    """输入参数不满足 Pinterest 公开接口合同。"""

    code = "invalid_input"


class PinterestAdsTransportError(PinterestAdsError):
    """网络、限流或上游 HTTP 状态错误。"""

    code = "transport_error"


class PinterestAdsResponseError(PinterestAdsError):
    """上游响应结构或媒体内容错误。"""

    code = "invalid_response"
