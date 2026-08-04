class ToutiaoError(Exception):
    """今日头条公开 HTTP 客户端的基础错误。"""


class ToutiaoInputError(ToutiaoError, ValueError):
    """引用或分页值无效时抛出。"""


class ToutiaoResponseError(ToutiaoError):
    """今日头条返回不可用的公开响应时抛出。"""
