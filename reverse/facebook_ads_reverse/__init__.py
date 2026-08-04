"""Meta Ads Library 匿名公开协议客户端。"""

from .client import FacebookAdsClient
from .errors import FacebookAdsError

__all__ = ["FacebookAdsClient", "FacebookAdsError"]
