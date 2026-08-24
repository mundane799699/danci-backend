import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx

from douyin.config import DouyinSettings
from douyin.downloader import DouyinVideoDownloader
from douyin.errors import DouyinError
from douyin.models import MediaCandidate


MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + (b"video-data" * 32)


class _InspectingStream(httpx.SyncByteStream):
    def __init__(self, ready_path: Path):
        self.ready_path = ready_path

    def __iter__(self):
        if self.ready_path.exists():
            raise AssertionError("ready file became visible before the stream completed")
        yield MP4_BYTES[:7]
        if self.ready_path.exists():
            raise AssertionError("ready file became visible during the stream")
        yield MP4_BYTES[7:]


class _InterruptedStream(httpx.SyncByteStream):
    def __iter__(self):
        yield MP4_BYTES[:32]
        raise httpx.ReadError("upstream disconnected")


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.job_id = str(uuid.uuid4())

    def tearDown(self):
        self.temporary_directory.cleanup()

    def config(self, **overrides) -> DouyinSettings:
        values = {
            "skip_dns_safety_check": True,
            "media_hosts": ("media.example",),
            "downloading_dir": str(self.root / "downloading"),
            "ready_dir": str(self.root / "ready"),
            "max_media_bytes": 1024 * 1024,
            "media_chunk_bytes": 16,
            "max_redirects": 2,
        }
        values.update(overrides)
        return DouyinSettings(**values)

    @staticmethod
    def candidate(path: str = "/video.mp4") -> MediaCandidate:
        return MediaCandidate(f"https://media.example{path}", 1080, 1920, 200, "h264")

    def test_streams_mp4_and_only_publishes_ready_file_after_completion(self):
        ready_path = self.root / "ready" / f"{self.job_id}.mp4"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "video/mp4", "content-length": str(len(MP4_BYTES))},
                stream=_InspectingStream(ready_path),
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = DouyinVideoDownloader(self.config(), client).download(
                self.job_id,
                [self.candidate()],
            )

        self.assertEqual(result.bytes_written, len(MP4_BYTES))
        self.assertEqual(result.candidate_index, 0)
        self.assertEqual(ready_path.read_bytes(), MP4_BYTES)
        self.assertFalse((self.root / "downloading" / f"{self.job_id}.part").exists())

    def test_rejects_html_response_even_when_status_is_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(DouyinError) as caught:
                DouyinVideoDownloader(self.config(), client).download(
                    self.job_id,
                    [self.candidate()],
                )

        self.assertEqual(caught.exception.code, "UNSUPPORTED_MEDIA_FORMAT")
        self.assertFalse((self.root / "ready" / f"{self.job_id}.mp4").exists())

    def test_rejects_non_mp4_bytes_with_allowed_binary_content_type(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "application/octet-stream"},
                content=b"not-an-mp4-file",
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(DouyinError) as caught:
                DouyinVideoDownloader(self.config(), client).download(
                    self.job_id,
                    [self.candidate()],
                )

        self.assertEqual(caught.exception.code, "UNSUPPORTED_MEDIA_FORMAT")
        self.assertFalse((self.root / "downloading" / f"{self.job_id}.part").exists())

    def test_rejects_announced_file_larger_than_limit(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "video/mp4", "content-length": "9999"},
                content=MP4_BYTES,
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(DouyinError) as caught:
                DouyinVideoDownloader(self.config(max_media_bytes=128), client).download(
                    self.job_id,
                    [self.candidate()],
                )

        self.assertEqual(caught.exception.code, "FILE_TOO_LARGE")

    def test_stops_stream_when_actual_bytes_exceed_limit(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "video/mp4"}, content=MP4_BYTES)

        part_path = self.root / "downloading" / f"{self.job_id}.part"
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(DouyinError) as caught:
                DouyinVideoDownloader(self.config(max_media_bytes=64), client).download(
                    self.job_id,
                    [self.candidate()],
                )

        self.assertEqual(caught.exception.code, "FILE_TOO_LARGE")
        self.assertFalse(part_path.exists())

    def test_removes_part_file_when_upstream_disconnects(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "video/mp4"},
                stream=_InterruptedStream(),
            )

        part_path = self.root / "downloading" / f"{self.job_id}.part"
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(DouyinError) as caught:
                DouyinVideoDownloader(self.config(), client).download(
                    self.job_id,
                    [self.candidate()],
                )

        self.assertEqual(caught.exception.code, "JOB_TIMEOUT")
        self.assertFalse(part_path.exists())

    @patch("douyin.downloader.os.replace", side_effect=OSError("disk unavailable"))
    def test_removes_part_file_when_atomic_publish_fails(self, replace):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "video/mp4"}, content=MP4_BYTES)

        part_path = self.root / "downloading" / f"{self.job_id}.part"
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(OSError):
                DouyinVideoDownloader(self.config(), client).download(
                    self.job_id,
                    [self.candidate()],
                )

        replace.assert_called_once()
        self.assertFalse(part_path.exists())

    def test_falls_back_to_second_candidate(self):
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            if request.url.path == "/broken.mp4":
                return httpx.Response(503)
            return httpx.Response(200, headers={"content-type": "video/mp4"}, content=MP4_BYTES)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = DouyinVideoDownloader(self.config(), client).download(
                self.job_id,
                [self.candidate("/broken.mp4"), self.candidate("/working.mp4")],
            )

        self.assertEqual(result.candidate_index, 1)
        self.assertEqual(requested_paths, ["/broken.mp4", "/working.mp4"])

    def test_rejects_redirect_to_non_media_host(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://evil.example/video.mp4"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(DouyinError) as caught:
                DouyinVideoDownloader(self.config(), client).download(
                    self.job_id,
                    [self.candidate()],
                )

        self.assertEqual(caught.exception.code, "UNSUPPORTED_MEDIA_FORMAT")

    @patch("douyin.security.socket.getaddrinfo")
    def test_rejects_allowed_redirect_when_dns_resolves_to_private_ip(self, getaddrinfo):
        def resolve(host, port, **kwargs):
            address = "127.0.0.1" if host == "private.media.example" else "93.184.216.34"
            return [(2, 1, 6, "", (address, port))]

        getaddrinfo.side_effect = resolve
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.host)
            return httpx.Response(
                302,
                headers={"location": "https://private.media.example/video.mp4"},
            )

        config = self.config(skip_dns_safety_check=False)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(DouyinError) as caught:
                DouyinVideoDownloader(config, client).download(
                    self.job_id,
                    [self.candidate()],
                )

        self.assertEqual(caught.exception.code, "UNSUPPORTED_MEDIA_FORMAT")
        self.assertEqual(requests, ["media.example"])

    def test_rejects_non_uuid_job_id_before_creating_directories(self):
        with self.assertRaises(ValueError):
            DouyinVideoDownloader(self.config()).download("../../etc/passwd", [self.candidate()])

        self.assertFalse((self.root / "downloading").exists())
        self.assertFalse((self.root / "ready").exists())


if __name__ == "__main__":
    unittest.main()
