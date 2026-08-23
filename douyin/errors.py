class DouyinError(Exception):
    """A user-facing, stable error raised while processing a Douyin job."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


ERROR_MESSAGES = {
    "INVALID_SHARE_TEXT": "未识别到有效的抖音链接",
    "UNSUPPORTED_HOST": "目前仅支持抖音分享链接",
    "UNSUPPORTED_IMAGE_POST": "暂不支持图文作品",
    "VIDEO_UNAVAILABLE": "视频不可访问或已删除",
    "LOGIN_REQUIRED_UPSTREAM": "该视频需要登录后查看，暂不支持",
    "UPSTREAM_RATE_LIMITED": "抖音限制了访问，请稍后再试",
    "UPSTREAM_CHANGED": "解析服务暂时不可用",
    "JOB_TIMEOUT": "处理超时，请重试",
    "COOKIE_EXPIRED": "抖音 Cookie 缺失或已失效，请更新 Cookie 文件",
}


def error(code: str, *, retryable: bool = False) -> DouyinError:
    return DouyinError(code, ERROR_MESSAGES[code], retryable=retryable)
