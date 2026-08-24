import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from douyin.config import DouyinSettings
from douyin.downloader import DownloadResult
from douyin.errors import error
from douyin.job_store import JobStoreUnavailable
from douyin.jobs import (
    InvalidJobTransition,
    JobRecord,
    transition_job,
    update_job_progress,
)
from douyin.models import DouyinVideoMetadata, MediaCandidate
from douyin.processor import DouyinJobProcessor


SOURCE_URL = "https://v.douyin.com/test-link/"


class _MemoryJobStore:
    def __init__(self):
        self.records: dict[str, JobRecord] = {}
        self.progress_history: list[int] = []

    def create(self, source_url: str) -> JobRecord:
        job = JobRecord.create(source_url, 7200)
        self.records[job.job_id] = job
        return job

    def require(self, job_id: str) -> JobRecord:
        return self.records[job_id]

    def transition(self, job_id: str, new_state: str, **kwargs) -> JobRecord:
        updated = transition_job(self.records[job_id], new_state, **kwargs)
        self.records[job_id] = updated
        return updated

    def update_progress(self, job_id: str, progress: int, **kwargs) -> JobRecord:
        updated = update_job_progress(self.records[job_id], progress, **kwargs)
        self.records[job_id] = updated
        self.progress_history.append(progress)
        return updated


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = DouyinSettings(
            downloading_dir=str(self.root / "downloading"),
            ready_dir=str(self.root / "ready"),
        )
        self.store = _MemoryJobStore()
        self.job = self.store.create(SOURCE_URL)
        self.metadata = DouyinVideoMetadata(
            aweme_id="12345",
            content_type="video",
            title="测试视频",
            author_name="作者",
            cover_url=None,
            duration_ms=12000,
            media_candidates=[MediaCandidate("https://media.example/video.mp4")],
        )
        self.resolver = Mock()
        self.resolver.resolver_version = "test-resolver-v1"
        self.resolver.resolve.return_value = self.metadata
        self.downloader = Mock()

    def tearDown(self):
        self.directory.cleanup()

    def processor(self) -> DouyinJobProcessor:
        return DouyinJobProcessor(
            self.config,
            store=self.store,
            resolver=self.resolver,
            downloader=self.downloader,
        )

    def test_processes_job_to_ready_and_reports_download_progress(self):
        def download(job_id, candidates, *, progress_callback):
            progress_callback(25, 100)
            progress_callback(50, 100)
            progress_callback(100, 100)
            return DownloadResult(job_id, self.root / "ready" / f"{job_id}.mp4", 4096, 0)

        self.downloader.download.side_effect = download
        completed = self.processor().process(self.job.job_id)

        self.assertEqual(completed.state, "ready")
        self.assertEqual(completed.progress, 100)
        self.assertEqual(completed.aweme_id, "12345")
        self.assertEqual(completed.bytes_written, 4096)
        self.assertEqual(completed.resolver_version, "test-resolver-v1")
        self.assertEqual(self.store.progress_history, [53, 67, 95])
        self.resolver.resolve.assert_called_once_with(SOURCE_URL)

    def test_resolver_error_marks_job_failed_without_downloading(self):
        self.resolver.resolve.side_effect = error("VIDEO_UNAVAILABLE")
        failed = self.processor().process(self.job.job_id)

        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.error_code, "VIDEO_UNAVAILABLE")
        self.downloader.download.assert_not_called()

    def test_downloader_error_marks_job_failed(self):
        self.downloader.download.side_effect = error("FILE_TOO_LARGE")
        failed = self.processor().process(self.job.job_id)

        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.error_code, "FILE_TOO_LARGE")

    def test_storage_error_has_stable_retryable_code(self):
        self.downloader.download.side_effect = OSError("disk full")
        failed = self.processor().process(self.job.job_id)

        self.assertEqual(failed.error_code, "STORAGE_ERROR")
        self.assertTrue(failed.error_retryable)

    def test_unexpected_error_has_stable_retryable_code(self):
        self.resolver.resolve.side_effect = RuntimeError("unexpected details")
        failed = self.processor().process(self.job.job_id)

        self.assertEqual(failed.error_code, "INTERNAL_ERROR")
        self.assertNotIn("unexpected details", failed.error_message)
        self.assertTrue(failed.error_retryable)

    def test_ready_job_is_idempotent(self):
        resolving = self.store.transition(
            self.job.job_id,
            "resolving",
            stage="解析中",
            progress=10,
        )
        downloading = self.store.transition(
            resolving.job_id,
            "downloading",
            stage="下载中",
            progress=40,
            aweme_id="12345",
        )
        ready = self.store.transition(
            downloading.job_id,
            "ready",
            stage="完成",
            bytes_written=1024,
        )

        result = self.processor().process(ready.job_id)
        self.assertEqual(result, ready)
        self.resolver.resolve.assert_not_called()
        self.downloader.download.assert_not_called()

    def test_rejects_resuming_non_terminal_in_progress_job(self):
        self.store.transition(
            self.job.job_id,
            "resolving",
            stage="解析中",
            progress=10,
        )
        with self.assertRaises(InvalidJobTransition):
            self.processor().process(self.job.job_id)

    def test_job_store_failure_is_not_converted_to_video_failure(self):
        store = Mock()
        store.require.side_effect = JobStoreUnavailable("Redis unavailable")
        processor = DouyinJobProcessor(
            self.config,
            store=store,
            resolver=self.resolver,
            downloader=self.downloader,
        )
        with self.assertRaises(JobStoreUnavailable):
            processor.process(self.job.job_id)


if __name__ == "__main__":
    unittest.main()
