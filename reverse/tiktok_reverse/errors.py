class TikTokError(Exception):
    """TikTok 客户端的基础异常。"""


class TikTokInputError(TikTokError):
    """提供的资料或视频 URL 格式错误。"""


class TikTokResponseError(TikTokError):
    """TikTok 返回了不可用的 HTTP 或 API 响应。"""


class TikTokSignatureError(TikTokError):
    """本地 ExecJS 签名运行时执行失败。"""
