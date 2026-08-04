from __future__ import annotations


class KuaishouError(Exception):
    """Kuaishou 匿名客户端的基础异常。"""


class KuaishouInputError(KuaishouError):
    """调用方提供了格式错误或不受支持的 Kuaishou 引用。"""


class KuaishouResponseError(KuaishouError):
    """Kuaishou 返回了不可用的 HTTP 或 hydration 响应。"""
