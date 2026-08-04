class LinkedInError(Exception):
    """LinkedIn 匿名客户端的基础异常。"""


class LinkedInInputError(LinkedInError, ValueError):
    """LinkedIn URL、URN、id 或 slug 无效时抛出。"""


class LinkedInResponseError(LinkedInError):
    """LinkedIn 公开页面返回不可用数据时抛出。"""
