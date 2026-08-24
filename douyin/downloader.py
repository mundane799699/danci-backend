import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .config import DouyinSettings, settings
from .errors import DouyinError, error
from .models import MediaCandidate
from .security import host_matches, validate_public_dns


DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)
MP4_HEADER_BYTES = 12


@dataclass(frozen=True)
class DownloadResult:
    job_id: str
    file_path: Path
    bytes_written: int
    candidate_index: int


def _canonical_job_id(job_id: str) -> str:
    try:
        parsed = uuid.UUID(job_id)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("job_id must be a UUID v4") from None
    if parsed.version != 4 or str(parsed) != job_id.lower():
        raise ValueError("job_id must be a canonical UUID v4")
    return str(parsed)


def _normalize_media_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (AttributeError, TypeError, ValueError):
        raise error("UNSUPPORTED_MEDIA_FORMAT") from None

    host = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or not host_matches(host, allowed_hosts)
    ):
        raise error("UNSUPPORTED_MEDIA_FORMAT")

    return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _validate_mp4_header(header: bytes) -> None:
    if len(header) < MP4_HEADER_BYTES or header[4:8] != b"ftyp":
        raise error("UNSUPPORTED_MEDIA_FORMAT")


class DouyinVideoDownloader:
    """Stream a resolved Douyin media candidate into an atomically published MP4."""

    def __init__(self, config: DouyinSettings = settings, client: httpx.Client | None = None):
        self.config = config
        self.client = client

    def _validate_url(self, url: str) -> str:
        normalized = _normalize_media_url(url, self.config.media_hosts)
        if not self.config.skip_dns_safety_check:
            try:
                validate_public_dns(normalized)
            except DouyinError as exc:
                if exc.code == "UNSUPPORTED_HOST":
                    raise error("UNSUPPORTED_MEDIA_FORMAT") from None
                raise
        return normalized

    def _check_response(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            raise error("UPSTREAM_RATE_LIMITED", retryable=True)
        if response.status_code in (404, 410):
            raise error("VIDEO_UNAVAILABLE")
        if response.status_code >= 500:
            raise error("UPSTREAM_CHANGED", retryable=True)
        if not 200 <= response.status_code < 300:
            raise error("VIDEO_UNAVAILABLE")

        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in self.config.media_content_types:
            raise error("UNSUPPORTED_MEDIA_FORMAT")

        content_length = response.headers.get("content-length")
        if content_length:
            try:
                announced_bytes = int(content_length)
            except ValueError:
                raise error("UNSUPPORTED_MEDIA_FORMAT") from None
            if announced_bytes < 0:
                raise error("UNSUPPORTED_MEDIA_FORMAT")
            if announced_bytes > self.config.max_media_bytes:
                raise error("FILE_TOO_LARGE")

    def _download_candidate(
        self,
        client: httpx.Client,
        candidate: MediaCandidate,
        part_path: Path,
        ready_path: Path,
    ) -> int:
        current_url = self._validate_url(candidate.url)

        for redirect_count in range(self.config.max_redirects + 1):
            current_url = self._validate_url(current_url)
            with client.stream("GET", current_url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirect_count >= self.config.max_redirects:
                        raise error("VIDEO_UNAVAILABLE")
                    location = response.headers.get("location")
                    if not location:
                        raise error("VIDEO_UNAVAILABLE")
                    current_url = self._validate_url(urljoin(current_url, location))
                    continue

                self._check_response(response)
                total_bytes = 0
                header = bytearray()
                header_checked = False

                with part_path.open("wb") as target:
                    for chunk in response.iter_bytes(self.config.media_chunk_bytes):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > self.config.max_media_bytes:
                            raise error("FILE_TOO_LARGE")
                        if len(header) < MP4_HEADER_BYTES:
                            needed = MP4_HEADER_BYTES - len(header)
                            header.extend(chunk[:needed])
                            if len(header) == MP4_HEADER_BYTES:
                                _validate_mp4_header(bytes(header))
                                header_checked = True
                        target.write(chunk)

                    if not header_checked:
                        _validate_mp4_header(bytes(header))
                    target.flush()
                    os.fsync(target.fileno())

                os.replace(part_path, ready_path)
                return total_bytes

        raise error("VIDEO_UNAVAILABLE")

    def download(self, job_id: str, candidates: list[MediaCandidate]) -> DownloadResult:
        canonical_job_id = _canonical_job_id(job_id)
        if not candidates:
            raise error("VIDEO_UNAVAILABLE")

        downloading_dir = Path(self.config.downloading_dir)
        ready_dir = Path(self.config.ready_dir)
        downloading_dir.mkdir(parents=True, exist_ok=True)
        ready_dir.mkdir(parents=True, exist_ok=True)
        part_path = downloading_dir / f"{canonical_job_id}.part"
        ready_path = ready_dir / f"{canonical_job_id}.mp4"

        client = self.client or httpx.Client(
            headers={
                "User-Agent": self.config.user_agent or DOWNLOAD_USER_AGENT,
                "Accept": "video/mp4,application/octet-stream;q=0.9,*/*;q=0.1",
                "Referer": "https://www.douyin.com/",
            },
            follow_redirects=False,
            timeout=self.config.media_timeout_seconds,
        )
        should_close = self.client is None
        last_error: DouyinError | None = None

        try:
            for candidate_index, candidate in enumerate(candidates):
                try:
                    bytes_written = self._download_candidate(
                        client,
                        candidate,
                        part_path,
                        ready_path,
                    )
                    return DownloadResult(
                        job_id=canonical_job_id,
                        file_path=ready_path,
                        bytes_written=bytes_written,
                        candidate_index=candidate_index,
                    )
                except DouyinError as exc:
                    last_error = exc
                    part_path.unlink(missing_ok=True)
                except (httpx.TimeoutException, httpx.NetworkError):
                    last_error = error("JOB_TIMEOUT", retryable=True)
                    part_path.unlink(missing_ok=True)
                except httpx.HTTPError:
                    last_error = error("UPSTREAM_CHANGED", retryable=True)
                    part_path.unlink(missing_ok=True)
                except OSError:
                    part_path.unlink(missing_ok=True)
                    raise

            raise last_error or error("VIDEO_UNAVAILABLE")
        finally:
            if should_close:
                client.close()
