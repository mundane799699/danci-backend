import html
import json
import threading
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import unquote, urlencode, urlsplit

import httpx

from .abogus import ABogus, BrowserFingerprintGenerator
from .config import DouyinSettings, settings
from .cookies import load_cookie_file, ms_token
from .errors import DouyinError, error
from .models import DouyinVideoMetadata, MediaCandidate
from .security import extract_aweme_id, host_matches, redirect_target, validate_public_dns
from .xbogus import XBogus

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
)


class PlatformResolver(Protocol):
    def can_handle(self, url: str) -> bool: ...

    def resolve(self, url: str) -> DouyinVideoMetadata: ...


class _HydrationScriptParser(HTMLParser):
    accepted_ids = {"RENDER_DATA", "__UNIVERSAL_DATA_FOR_REHYDRATION__"}

    def __init__(self) -> None:
        super().__init__()
        self.current_id: str | None = None
        self.parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            attributes = dict(attrs)
            script_id = attributes.get("id")
            if script_id in self.accepted_ids or not attributes.get("src"):
                self.current_id = script_id or "__inline__"
                self.parts = []

    def handle_data(self, data: str) -> None:
        if self.current_id:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self.current_id:
            self.scripts.append("".join(self.parts))
            self.current_id = None
            self.parts = []


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return default


def _url_list(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    urls = _first(value, "url_list", "urlList", default=[])
    result = []
    for url in urls:
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        normalized = url.replace("\\u0026", "&")
        lowered = normalized.lower()
        if "playwm" in lowered or "watermark=1" in lowered or "watermark=true" in lowered:
            continue
        result.append(normalized)
    return result


def _candidate_from_address(address: Any, *, bitrate: int | None = None, codec: str | None = None) -> list[MediaCandidate]:
    if not isinstance(address, dict):
        return []
    width = _first(address, "width")
    height = _first(address, "height")
    return [
        MediaCandidate(url=url, width=width, height=height, bitrate=bitrate, codec=codec)
        for url in _url_list(address)
    ]


def _extract_candidates(video: dict[str, Any]) -> list[MediaCandidate]:
    candidates: list[MediaCandidate] = []
    for key in ("play_addr_h264", "playAddrH264", "play_addr", "playAddr"):
        candidates.extend(_candidate_from_address(video.get(key), codec="h264" if "h264" in key.lower() else None))
    bitrates = _first(video, "bit_rate", "bitRate", default=[])
    if isinstance(bitrates, list):
        for item in bitrates:
            if not isinstance(item, dict):
                continue
            codec = str(_first(item, "codec_type", "codecType", default="")).lower() or None
            if codec and not any(name in codec for name in ("h264", "avc")):
                continue
            address = _first(item, "play_addr", "playAddr")
            candidates.extend(
                _candidate_from_address(
                    address,
                    bitrate=_first(item, "bit_rate", "bitRate"),
                    codec=codec,
                )
            )
    unique: dict[str, MediaCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.url, candidate)
    return sorted(unique.values(), key=lambda item: item.quality_score, reverse=True)


def _find_aweme(payloads: list[Any], expected_id: str | None) -> dict[str, Any] | None:
    fallback = None
    for payload in payloads:
        for item in _walk(payload):
            if not isinstance(item, dict):
                continue
            aweme_id = str(_first(item, "aweme_id", "awemeId", "itemId", default=""))
            if not aweme_id or not (item.get("video") or item.get("images") or item.get("image_post_info")):
                continue
            if expected_id and aweme_id == expected_id:
                return item
            fallback = fallback or item
    return None if expected_id else fallback


def parse_aweme(aweme: dict[str, Any], expected_id: str | None = None) -> DouyinVideoMetadata:
    aweme_id = str(_first(aweme, "aweme_id", "awemeId", "itemId", default=expected_id or ""))
    if expected_id and aweme_id != expected_id:
        raise error("VIDEO_UNAVAILABLE")
    video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
    candidates = _extract_candidates(video)
    has_images = bool(aweme.get("images") or aweme.get("image_post_info") or aweme.get("imagePostInfo"))
    if has_images and not candidates:
        content_type = "image"
    elif candidates:
        content_type = "video"
    elif aweme.get("live_room") or aweme.get("liveRoom"):
        content_type = "live"
    else:
        content_type = "unknown"
    if content_type == "image":
        raise error("UNSUPPORTED_IMAGE_POST")
    if content_type != "video":
        raise error("VIDEO_UNAVAILABLE")

    author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
    cover = _first(video, "cover", "origin_cover", "originCover", default={})
    cover_urls = _url_list(cover)
    duration = _first(video, "duration", default=aweme.get("duration"))
    return DouyinVideoMetadata(
        aweme_id=aweme_id,
        content_type="video",
        title=str(_first(aweme, "desc", "title", default="")),
        author_name=str(_first(author, "nickname", "name", default="")),
        cover_url=cover_urls[0] if cover_urls else None,
        duration_ms=int(duration) if isinstance(duration, (int, float)) else None,
        media_candidates=candidates,
    )


def parse_hydration(page_html: str, expected_id: str | None = None) -> DouyinVideoMetadata:
    parser = _HydrationScriptParser()
    parser.feed(page_html)
    payloads: list[Any] = []
    for raw in parser.scripts:
        unescaped = html.unescape(raw).strip()
        candidates = [unescaped, unquote(unescaped)]
        for marker in ("window._ROUTER_DATA =", "window._SSR_DATA ="):
            if marker in unescaped:
                assigned = unescaped.split(marker, 1)[1].strip().removesuffix(";")
                candidates.extend((assigned, unquote(assigned)))
        for candidate in candidates:
            try:
                payloads.append(json.loads(candidate))
                break
            except json.JSONDecodeError:
                continue
    if not payloads:
        raise error("UPSTREAM_CHANGED", retryable=True)
    aweme = _find_aweme(payloads, expected_id)
    if not aweme:
        if "请登录后" in page_html or "登录后查看" in page_html:
            raise error("LOGIN_REQUIRED_UPSTREAM")
        raise error("VIDEO_UNAVAILABLE")
    return parse_aweme(aweme, expected_id)


class DouyinSharePageResolver:
    resolver_version = "share-page-v1"

    def __init__(self, config: DouyinSettings = settings, client: httpx.Client | None = None):
        self.config = config
        self.client = client

    def can_handle(self, url: str) -> bool:
        from .security import host_matches
        from urllib.parse import urlsplit

        return host_matches((urlsplit(url).hostname or "").lower(), self.config.entry_hosts)

    def resolve(self, url: str) -> DouyinVideoMetadata:
        client = self.client or httpx.Client(
            headers={"User-Agent": MOBILE_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=False,
            timeout=self.config.request_timeout_seconds,
        )
        should_close = self.client is None
        current = url
        try:
            for redirect_count in range(self.config.max_redirects + 1):
                if not self.config.skip_dns_safety_check:
                    validate_public_dns(current)
                with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect_count >= self.config.max_redirects:
                            raise error("VIDEO_UNAVAILABLE")
                        location = response.headers.get("location")
                        if not location:
                            raise error("VIDEO_UNAVAILABLE")
                        current = redirect_target(current, location, self.config.entry_hosts)
                        continue
                    if response.status_code in (401, 403):
                        raise error("LOGIN_REQUIRED_UPSTREAM")
                    if response.status_code == 429:
                        raise error("UPSTREAM_RATE_LIMITED", retryable=True)
                    if response.status_code in (404, 410):
                        raise error("VIDEO_UNAVAILABLE")
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self.config.max_html_bytes:
                            raise error("UPSTREAM_CHANGED", retryable=True)
                    encoding = response.encoding or "utf-8"
                    page_html = bytes(body).decode(encoding, errors="replace")
                    return parse_hydration(page_html, extract_aweme_id(current))
            raise error("VIDEO_UNAVAILABLE")
        except DouyinError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError):
            raise error("JOB_TIMEOUT", retryable=True)
        except httpx.HTTPError:
            raise error("VIDEO_UNAVAILABLE")
        finally:
            if should_close:
                client.close()


class DouyinCookieResolver:
    """Resolve public video metadata with a manually maintained Cookie file."""

    resolver_version = "cookie-api-v1"
    detail_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
    aid_candidates = ("6383", "1128")

    def __init__(self, config: DouyinSettings = settings, client: httpx.Client | None = None):
        self.config = config
        self.client = client

    def can_handle(self, url: str) -> bool:
        return DouyinSharePageResolver(self.config).can_handle(url)

    def _headers(self, aweme_id: str | None = None) -> dict[str, str]:
        referer = (
            f"https://www.douyin.com/video/{aweme_id}"
            if aweme_id
            else "https://www.douyin.com/?recommend=1"
        )
        return {
            "User-Agent": self.config.user_agent,
            "Referer": referer,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _expand_aweme_id(
        self,
        client: httpx.Client,
        url: str,
        cookies: dict[str, str],
    ) -> str:
        direct_id = extract_aweme_id(url)
        if direct_id:
            return direct_id

        current = url
        for redirect_count in range(self.config.max_redirects + 1):
            if not self.config.skip_dns_safety_check:
                validate_public_dns(current)
            response = client.get(current, headers=self._headers())
            if response.status_code in (301, 302, 303, 307, 308):
                if redirect_count >= self.config.max_redirects:
                    raise error("VIDEO_UNAVAILABLE")
                location = response.headers.get("location")
                if not location:
                    raise error("VIDEO_UNAVAILABLE")
                current = redirect_target(current, location, self.config.entry_hosts)
                aweme_id = extract_aweme_id(current)
                if aweme_id:
                    return aweme_id
                continue
            if response.status_code == 401:
                raise error("COOKIE_EXPIRED")
            if response.status_code in (403, 429):
                raise error("UPSTREAM_RATE_LIMITED", retryable=True)
            if response.status_code in (404, 410):
                raise error("VIDEO_UNAVAILABLE")
            response.raise_for_status()
            aweme_id = extract_aweme_id(str(response.url)) or extract_aweme_id(current)
            if aweme_id:
                return aweme_id
            raise error("VIDEO_UNAVAILABLE")
        raise error("VIDEO_UNAVAILABLE")

    def _query(self, aweme_id: str, aid: str, cookies: dict[str, str]) -> dict[str, str]:
        return {
            "device_platform": "webapp",
            "aid": aid,
            "channel": "channel_pc_web",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "pc_libra_divert": "Windows",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1536",
            "screen_height": "864",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "139.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "139.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "8",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "100",
            "support_h265": "0",
            "support_dash": "0",
            "uifid": "",
            "msToken": ms_token(cookies),
            "aweme_id": aweme_id,
        }

    def _signed_url(self, params: dict[str, str], attempt: int) -> str:
        query = urlencode(params)
        if attempt % 2 == 0:
            fingerprint = BrowserFingerprintGenerator.generate_fingerprint("Chrome")
            signer = ABogus(fp=fingerprint, user_agent=self.config.user_agent)
            signed_query, _signature, _ua, _body = signer.generate_abogus(query, "")
            return f"{self.detail_url}?{signed_query}"
        signed, _signature, _ua = XBogus(self.config.user_agent).build(
            f"{self.detail_url}?{query}"
        )
        return signed

    @staticmethod
    def _is_cookie_error(payload: dict[str, Any]) -> bool:
        try:
            status_code = int(payload.get("status_code") or 0)
        except (TypeError, ValueError):
            status_code = 0
        if status_code == 2483:
            return True
        message = str(payload.get("status_msg") or "").lower()
        return any(marker in message for marker in ("登录", "login", "cookie", "session"))

    def resolve(self, url: str) -> DouyinVideoMetadata:
        cookies = load_cookie_file(self.config.cookie_file, self.config.max_cookie_bytes)
        client = self.client or httpx.Client(
            timeout=self.config.request_timeout_seconds,
            follow_redirects=False,
            cookies=cookies,
        )
        if self.client is not None:
            client.cookies.update(cookies)
        should_close = self.client is None
        cookie_rejected = False
        valid_api_response = False
        try:
            aweme_id = self._expand_aweme_id(client, url, cookies)
            if not self.config.skip_dns_safety_check:
                validate_public_dns(self.detail_url)

            attempts = max(1, self.config.api_retries)
            for aid in self.aid_candidates:
                for attempt in range(attempts):
                    response = client.get(
                        self._signed_url(self._query(aweme_id, aid, cookies), attempt),
                        headers=self._headers(aweme_id),
                    )
                    if response.status_code == 401:
                        cookie_rejected = True
                        continue
                    if response.status_code in (403, 429):
                        raise error("UPSTREAM_RATE_LIMITED", retryable=True)
                    if response.status_code in (404, 410):
                        raise error("VIDEO_UNAVAILABLE")
                    response.raise_for_status()
                    if not response.content:
                        cookie_rejected = True
                        continue
                    try:
                        payload = response.json()
                    except ValueError:
                        cookie_rejected = True
                        continue
                    if not isinstance(payload, dict):
                        cookie_rejected = True
                        continue
                    if self._is_cookie_error(payload):
                        cookie_rejected = True
                        continue
                    valid_api_response = True
                    detail = payload.get("aweme_detail")
                    if isinstance(detail, dict):
                        return parse_aweme(detail, aweme_id)
                    filter_detail = payload.get("filter_detail")
                    if isinstance(filter_detail, dict) and "image" in str(
                        filter_detail.get("filter_reason") or ""
                    ).lower():
                        raise error("UNSUPPORTED_IMAGE_POST")

            if valid_api_response:
                raise error("VIDEO_UNAVAILABLE")
            if cookie_rejected:
                raise error("COOKIE_EXPIRED")
            raise error("UPSTREAM_CHANGED", retryable=True)
        except DouyinError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError):
            raise error("JOB_TIMEOUT", retryable=True)
        except httpx.HTTPError:
            raise error("UPSTREAM_CHANGED", retryable=True)
        finally:
            if should_close:
                client.close()


_BROWSER_RESOLVER_LOCK = threading.Lock()


class DouyinBrowserResolver:
    """Resolve inside a real Douyin page so its security SDK signs the detail request."""

    resolver_version = "browser-detail-v1"
    detail_path = "/aweme/v1/web/aweme/detail/"

    def __init__(self, config: DouyinSettings = settings):
        self.config = config

    def can_handle(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return host_matches(host, self.config.entry_hosts)

    def _browser_cookies(self, cookies: dict[str, str]) -> list[dict[str, str]]:
        return [
            {"name": name, "value": value, "domain": ".douyin.com", "path": "/"}
            for name, value in cookies.items()
        ]

    def resolve(self, url: str) -> DouyinVideoMetadata:
        cookies = load_cookie_file(self.config.cookie_file, self.config.max_cookie_bytes)
        if not self.config.skip_dns_safety_check:
            validate_public_dns(url)
        with httpx.Client(
            timeout=self.config.request_timeout_seconds,
            follow_redirects=False,
            cookies=cookies,
        ) as client:
            aweme_id = DouyinCookieResolver(self.config)._expand_aweme_id(client, url, cookies)
        target_url = f"https://www.douyin.com/video/{aweme_id}"
        if not self.config.skip_dns_safety_check:
            validate_public_dns(target_url)

        acquired = _BROWSER_RESOLVER_LOCK.acquire(timeout=self.config.browser_timeout_seconds)
        if not acquired:
            raise error("SERVICE_UNAVAILABLE", retryable=True)
        try:
            return self._resolve_in_browser(target_url, aweme_id, cookies)
        finally:
            _BROWSER_RESOLVER_LOCK.release()

    def _resolve_in_browser(
        self,
        url: str,
        expected_id: str,
        cookies: dict[str, str],
    ) -> DouyinVideoMetadata:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise error("SERVICE_UNAVAILABLE", retryable=True)

        timeout_ms = max(1, int(self.config.browser_timeout_seconds * 1000))

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.config.browser_headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
                try:
                    context = browser.new_context(
                        user_agent=self.config.user_agent,
                        locale="zh-CN",
                        viewport={"width": 1536, "height": 864},
                    )
                    context.add_cookies(self._browser_cookies(cookies))
                    page = context.new_page()
                    with page.expect_response(
                        lambda response: urlsplit(response.url).path == self.detail_path,
                        timeout=timeout_ms,
                    ) as pending_response:
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                    response = pending_response.value
                    if response.status == 401:
                        raise error("COOKIE_EXPIRED")
                    if response.status in (403, 429):
                        raise error("UPSTREAM_RATE_LIMITED", retryable=True)
                    if response.status in (404, 410):
                        raise error("VIDEO_UNAVAILABLE")
                    if response.status != 200:
                        raise error("UPSTREAM_CHANGED", retryable=True)

                    try:
                        payload = response.json()
                    except ValueError:
                        raise error("UPSTREAM_CHANGED", retryable=True)
                    if not isinstance(payload, dict):
                        raise error("UPSTREAM_CHANGED", retryable=True)
                    if DouyinCookieResolver._is_cookie_error(payload):
                        raise error("COOKIE_EXPIRED")

                    detail = payload.get("aweme_detail")
                    if not isinstance(detail, dict):
                        raise error("VIDEO_UNAVAILABLE")
                    return parse_aweme(detail, expected_id)
                finally:
                    browser.close()
        except DouyinError:
            raise
        except PlaywrightTimeoutError:
            raise error("UPSTREAM_RATE_LIMITED", retryable=True)
        except PlaywrightError:
            raise error("SERVICE_UNAVAILABLE", retryable=True)


class DouyinResolver:
    """Resolve through a signed browser page, with the legacy HTTP path opt-in."""

    resolver_version = DouyinBrowserResolver.resolver_version

    def __init__(self, config: DouyinSettings = settings):
        self.config = config

    def can_handle(self, url: str) -> bool:
        return DouyinBrowserResolver(self.config).can_handle(url)

    def resolve(self, url: str) -> DouyinVideoMetadata:
        if self.config.browser_resolver_enabled:
            return DouyinBrowserResolver(self.config).resolve(url)
        return DouyinCookieResolver(self.config).resolve(url)
