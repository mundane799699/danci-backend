import ipaddress
import re
import socket
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from .errors import error

URL_RE = re.compile(r"https://[^\s<>，。；：！？）】》」』”’]+", re.IGNORECASE)
AWEME_ID_RE = re.compile(r"/(?:share/)?video/(\d+)(?:/|$)")
TRAILING_PUNCTUATION = "。．，,、；;：:！!？?）)]}〉》」』】\"'”’"


def host_matches(host: str, allowed: tuple[str, ...]) -> bool:
    host = host.rstrip(".").lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in allowed)


def normalize_and_validate_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    try:
        decoded = unquote(url.rstrip(TRAILING_PUNCTUATION))
        parsed = urlsplit(decoded)
        port = parsed.port
    except ValueError:
        raise error("INVALID_SHARE_TEXT")
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise error("INVALID_SHARE_TEXT")
    if port not in (None, 443):
        raise error("INVALID_SHARE_TEXT")
    if not host_matches(host, allowed_hosts):
        raise error("UNSUPPORTED_HOST")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def extract_share_url(share_text: str, allowed_hosts: tuple[str, ...], max_bytes: int = 4096) -> str:
    if not share_text or len(share_text.encode("utf-8")) > max_bytes:
        raise error("INVALID_SHARE_TEXT")
    match = URL_RE.search(share_text)
    if not match:
        raise error("INVALID_SHARE_TEXT")
    return normalize_and_validate_url(match.group(0), allowed_hosts)


def validate_public_dns(url: str) -> None:
    host = urlsplit(url).hostname
    if not host:
        raise error("UNSUPPORTED_HOST")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise error("VIDEO_UNAVAILABLE")
    if not addresses:
        raise error("VIDEO_UNAVAILABLE")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise error("UNSUPPORTED_HOST")


def redirect_target(current_url: str, location: str, allowed_hosts: tuple[str, ...]) -> str:
    return normalize_and_validate_url(urljoin(current_url, location), allowed_hosts)


def extract_aweme_id(url: str) -> str | None:
    match = AWEME_ID_RE.search(urlsplit(url).path)
    return match.group(1) if match else None
