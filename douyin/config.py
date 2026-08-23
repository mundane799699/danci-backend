import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in os.getenv(name, default).split(",") if item.strip())


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
settings = DouyinSettings()
