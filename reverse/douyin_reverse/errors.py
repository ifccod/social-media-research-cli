class DouyinError(Exception):
    """Douyin 匿名客户端的基础异常。"""


class DouyinInputError(DouyinError, ValueError):
    """aweme、用户或 URL 引用格式错误时抛出。"""


class DouyinResponseError(DouyinError):
    """Douyin 返回不可用的公开响应时抛出。"""
