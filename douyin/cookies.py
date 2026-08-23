import json
import secrets
import string
from pathlib import Path
from typing import Any

from .errors import error


INVALID_COOKIE_NAME_CHARS = set('()<>@,;:\\"/[]?={} \t\r\n')


def _valid_cookie_name(name: str) -> bool:
    return bool(name) and all(
        33 <= ord(char) <= 126 and char not in INVALID_COOKIE_NAME_CHARS for char in name
    )


def _sanitize(mapping: dict[Any, Any]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for raw_name, raw_value in mapping.items():
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if not _valid_cookie_name(name):
            continue
        cookies[name] = "" if raw_value is None else str(raw_value).strip()
    return cookies


def parse_cookie_text(value: str) -> dict[str, str]:
    text = value.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()

    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return _sanitize(parsed) if isinstance(parsed, dict) else {}

    cookies: dict[str, str] = {}
    for item in text.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, cookie_value = item.split("=", 1)
        name = name.strip()
        if _valid_cookie_name(name):
            cookies[name] = cookie_value.strip()
    return cookies


def load_cookie_file(filename: str, max_bytes: int) -> dict[str, str]:
    path = Path(filename).expanduser()
    try:
        raw = path.read_bytes()
    except (OSError, ValueError):
        raise error("COOKIE_EXPIRED")
    if not raw or len(raw) > max_bytes:
        raise error("COOKIE_EXPIRED")
    try:
        cookies = parse_cookie_text(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise error("COOKIE_EXPIRED")
    if not cookies:
        raise error("COOKIE_EXPIRED")
    return cookies


def ms_token(cookies: dict[str, str]) -> str:
    configured = cookies.get("msToken", "").strip()
    if configured:
        return configured
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(182)) + "=="
