from __future__ import annotations


class FacebookAdsError(Exception):
    """Facebook Ads Library 客户端的可分类错误。"""

    code = "facebook_ads_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or self.code


class FacebookAdsInputError(FacebookAdsError):
    code = "invalid_input"


class FacebookAdsTransportError(FacebookAdsError):
    code = "network_error"


class FacebookAdsResponseError(FacebookAdsError):
    code = "invalid_response"
