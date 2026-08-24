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
    "FILE_TOO_LARGE": "视频文件过大，暂不支持",
    "UNSUPPORTED_MEDIA_FORMAT": "当前视频格式暂不支持",
    "STORAGE_ERROR": "服务器存储暂时不可用，请稍后重试",
    "INTERNAL_ERROR": "处理服务暂时不可用，请稍后重试",
    "JOB_NOT_FOUND": "任务不存在或已过期",
    "SERVICE_UNAVAILABLE": "任务服务暂时不可用，请稍后重试",
}


def error(code: str, *, retryable: bool = False) -> DouyinError:
    return DouyinError(code, ERROR_MESSAGES[code], retryable=retryable)
