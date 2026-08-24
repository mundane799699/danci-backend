import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in os.getenv(name, default).split(",") if item.strip())


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


@dataclass(frozen=True)
class DouyinSettings:
    max_share_text_bytes: int = int(os.getenv("DOUYIN_MAX_SHARE_TEXT_BYTES", "4096"))
    max_html_bytes: int = int(os.getenv("DOUYIN_MAX_HTML_BYTES", str(5 * 1024 * 1024)))
    max_redirects: int = int(os.getenv("DOUYIN_MAX_REDIRECTS", "5"))
    request_timeout_seconds: float = float(os.getenv("DOUYIN_REQUEST_TIMEOUT_SECONDS", "8"))
    skip_dns_safety_check: bool = os.getenv("DOUYIN_SKIP_DNS_SAFETY_CHECK", "false").lower() == "true"
    cookie_file: str = os.getenv("DOUYIN_COOKIE_FILE", ".douyin-cookie")
    max_cookie_bytes: int = int(os.getenv("DOUYIN_MAX_COOKIE_BYTES", str(32 * 1024)))
    api_retries: int = int(os.getenv("DOUYIN_API_RETRIES", "2"))
    max_media_bytes: int = int(os.getenv("DOUYIN_MAX_MEDIA_BYTES", str(200 * 1024 * 1024)))
    media_timeout_seconds: float = float(os.getenv("DOUYIN_MEDIA_TIMEOUT_SECONDS", "60"))
    media_chunk_bytes: int = int(os.getenv("DOUYIN_MEDIA_CHUNK_BYTES", str(64 * 1024)))
    downloading_dir: str = os.getenv(
        "DOUYIN_DOWNLOADING_DIR",
        "/data/remove-watermark/downloading",
    )
    ready_dir: str = os.getenv(
        "DOUYIN_READY_DIR",
        "/data/remove-watermark/ready",
    )
    redis_url: str = os.getenv("DOUYIN_REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_password_file: str | None = _optional("DOUYIN_REDIS_PASSWORD_FILE")
    redis_timeout_seconds: float = float(os.getenv("DOUYIN_REDIS_TIMEOUT_SECONDS", "2"))
    job_ttl_seconds: int = int(os.getenv("DOUYIN_JOB_TTL_SECONDS", "7200"))
    job_key_prefix: str = os.getenv("DOUYIN_JOB_KEY_PREFIX", "remove_watermark:job")
    user_agent: str = os.getenv(
        "DOUYIN_USER_AGENT",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),
    )
    entry_hosts: tuple[str, ...] = _csv(
        "DOUYIN_ENTRY_HOSTS",
        "v.douyin.com,www.douyin.com,m.douyin.com,www.iesdouyin.com",
    )
    media_hosts: tuple[str, ...] = _csv(
        "DOUYIN_MEDIA_HOSTS",
        "douyinvod.com",
    )
    media_content_types: tuple[str, ...] = _csv(
        "DOUYIN_MEDIA_CONTENT_TYPES",
        "video/mp4,application/mp4,application/octet-stream,binary/octet-stream",
    )
settings = DouyinSettings()
