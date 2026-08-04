class XiaohongshuError(Exception):
    """小红书匿名客户端的基础错误。"""


class XiaohongshuInputError(XiaohongshuError, ValueError):
    """笔记、资料、令牌或 URL 无效时抛出。"""


class XiaohongshuResponseError(XiaohongshuError):
    """小红书返回不可用的公开数据时抛出。"""
