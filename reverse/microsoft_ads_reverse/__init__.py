"""Microsoft Advertising Ad Library 匿名客户端。"""

from .client import MicrosoftAdsClient
from .errors import (
    MicrosoftAdsError,
    MicrosoftAdsInputError,
    MicrosoftAdsResponseError,
    MicrosoftAdsTransportError,
)

__all__ = [
    "MicrosoftAdsClient",
    "MicrosoftAdsError",
    "MicrosoftAdsInputError",
    "MicrosoftAdsResponseError",
    "MicrosoftAdsTransportError",
]
