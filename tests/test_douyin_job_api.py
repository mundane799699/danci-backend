import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from douyin.config import settings
from douyin.errors import error
from douyin.job_store import JobStoreUnavailable
from douyin.jobs import JobRecord, transition_job, utc_now
from douyin.queueing import JobQueueUnavailable
from douyin.router import router


SOURCE_URL = "https://v.douyin.com/test-link/"


class _MemoryStore:
    def __init__(self):
        self.records: dict[str, JobRecord] = {}

    def create(self, source_url: str, *, request_id: str) -> JobRecord:
        job = JobRecord.create(source_url, 7200, request_id=request_id)
        self.records[job.job_id] = job
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self.records.get(job_id)

    def delete(self, job_id: str) -> bool:
        return self.records.pop(job_id, None) is not None


class JobApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.downloading_dir = Path(self.directory.name) / "downloading"
        self.ready_dir = Path(self.directory.name) / "ready"
        self.downloading_dir.mkdir()
        self.ready_dir.mkdir()
        self.settings_patch = patch(
            "douyin.router.settings",
            replace(
                settings,
                downloading_dir=str(self.downloading_dir),
                ready_dir=str(self.ready_dir),
            ),
        )
        self.settings_patch.start()
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/douyin")
        self.client = TestClient(app)
        self.store = _MemoryStore()
        self.queue = Mock()
        self.queue.enqueue.return_value = "rq-job-id"
        self.store_patch = patch("douyin.router.get_job_store", return_value=self.store)
        self.queue_patch = patch("douyin.router.get_job_queue", return_value=self.queue)
        self.store_patch.start()
        self.queue_patch.start()

    def tearDown(self):
        self.queue_patch.stop()
        self.store_patch.stop()
        self.settings_patch.stop()
        self.directory.cleanup()

    def create_job(self):
        return self.client.post(
            "/api/v1/douyin/jobs",
            json={"shareText": f"复制 {SOURCE_URL} 打开抖音"},
        )

    @staticmethod
    def ready_job(bytes_written: int = 4096) -> JobRecord:
        created = JobRecord.create(SOURCE_URL, 7200)
        resolving = transition_job(created, "resolving", stage="解析", progress=10)
        downloading = transition_job(
            resolving,
            "downloading",
            stage="下载",
            progress=40,
            aweme_id="12345",
            title="测试视频",
            author_name="作者",
            duration_ms=12000,
        )
        return transition_job(
            downloading,
            "ready",
            stage="完成",
            bytes_written=bytes_written,
        )

    def test_create_returns_202_without_processing(self):
        response = self.create_job()
        body = response.json()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(body["state"], "queued")
        self.assertTrue(body["requestId"].startswith("req_"))
        self.assertIn(body["jobId"], self.store.records)
        self.queue.enqueue.assert_called_once_with(body["jobId"])

    def test_invalid_share_text_does_not_touch_queue(self):
        response = self.client.post(
            "/api/v1/douyin/jobs",
            json={"shareText": "https://example.com/video"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_HOST")
        self.queue.enqueue.assert_not_called()

    def test_enqueue_failure_deletes_created_business_job(self):
        self.queue.enqueue.side_effect = JobQueueUnavailable("down")
        response = self.create_job()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "SERVICE_UNAVAILABLE")
        self.assertEqual(self.store.records, {})

    def test_disk_pressure_rejects_job_before_redis_create_or_enqueue(self):
        with patch(
            "douyin.router.ensure_storage_capacity",
            side_effect=error("DISK_PRESSURE", retryable=True),
        ):
            response = self.create_job()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "DISK_PRESSURE")
        self.assertEqual(self.store.records, {})
        self.queue.enqueue.assert_not_called()

    def test_get_processing_job(self):
        created = JobRecord.create(SOURCE_URL, 7200)
        processing = transition_job(created, "resolving", stage="正在解析视频", progress=10)
        self.store.records[created.job_id] = processing
        response = self.client.get(f"/api/v1/douyin/jobs/{created.job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "resolving")
        self.assertNotIn("video", response.json())

    def test_get_ready_job_only_returns_public_video_fields(self):
        ready = self.ready_job()
        self.store.records[ready.job_id] = ready
        response = self.client.get(f"/api/v1/douyin/jobs/{ready.job_id}")
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["video"]["bytes"], 4096)
        self.assertTrue(body["video"]["downloadUrl"].endswith(f"/{ready.job_id}/download"))
        self.assertNotIn("sourceUrl", body)
        self.assertNotIn("filePath", str(body))

    def test_get_failed_job_returns_stable_error(self):
        created = JobRecord.create(SOURCE_URL, 7200)
        failed = transition_job(
            created,
            "failed",
            stage="失败",
            error_code="VIDEO_UNAVAILABLE",
            error_message="视频不可访问或已删除",
            error_retryable=False,
        )
        self.store.records[created.job_id] = failed
        response = self.client.get(f"/api/v1/douyin/jobs/{created.job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"]["code"], "VIDEO_UNAVAILABLE")

    def test_missing_or_invalid_job_id_returns_404(self):
        missing = JobRecord.create(SOURCE_URL, 7200).job_id
        self.assertEqual(
            self.client.get(f"/api/v1/douyin/jobs/{missing}").status_code,
            404,
        )
        response = self.client.get("/api/v1/douyin/jobs/not-a-uuid")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "JOB_NOT_FOUND")

    def test_redis_failure_returns_503(self):
        with patch(
            "douyin.router.get_job_store",
            side_effect=JobStoreUnavailable("down"),
        ):
            response = self.client.get(
                f"/api/v1/douyin/jobs/{JobRecord.create(SOURCE_URL, 7200).job_id}"
            )
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.json()["error"]["retryable"])

    def test_download_ready_job_returns_only_internal_redirect_headers(self):
        ready = self.ready_job()
        self.store.records[ready.job_id] = ready
        (self.ready_dir / f"{ready.job_id}.mp4").write_bytes(b"x" * ready.bytes_written)

        response = self.client.get(f"/api/v1/douyin/jobs/{ready.job_id}/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="video.mp4"',
        )
        self.assertEqual(
            response.headers["x-accel-redirect"],
            f"/_protected-videos/{ready.job_id}.mp4",
        )
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertTrue(response.headers["x-request-id"].startswith("req_"))

    def test_download_rejects_invalid_uuid_and_path_traversal(self):
        invalid = self.client.get("/api/v1/douyin/jobs/not-a-uuid/download")
        traversal = self.client.get(
            "/api/v1/douyin/jobs/..%252F..%252Fetc%252Fpasswd/download"
        )
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(invalid.json()["error"]["code"], "JOB_NOT_FOUND")
        self.assertEqual(traversal.status_code, 404)
        self.assertNotIn("x-accel-redirect", traversal.headers)

    def test_download_rejects_missing_and_expired_jobs(self):
        missing = JobRecord.create(SOURCE_URL, 7200).job_id
        missing_response = self.client.get(
            f"/api/v1/douyin/jobs/{missing}/download"
        )

        expired = JobRecord.create(
            SOURCE_URL,
            60,
            now=utc_now() - timedelta(hours=2),
        )
        self.store.records[expired.job_id] = expired
        expired_response = self.client.get(
            f"/api/v1/douyin/jobs/{expired.job_id}/download"
        )

        self.assertEqual(missing_response.status_code, 404)
        self.assertEqual(expired_response.status_code, 404)
        self.assertEqual(expired_response.json()["error"]["code"], "JOB_NOT_FOUND")

    def test_download_processing_job_returns_file_not_ready(self):
        processing = JobRecord.create(SOURCE_URL, 7200)
        self.store.records[processing.job_id] = processing
        response = self.client.get(
            f"/api/v1/douyin/jobs/{processing.job_id}/download"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "FILE_NOT_READY")
        self.assertTrue(response.json()["error"]["retryable"])

    def test_download_failed_job_returns_original_error(self):
        created = JobRecord.create(SOURCE_URL, 7200)
        failed = transition_job(
            created,
            "failed",
            stage="失败",
            error_code="VIDEO_UNAVAILABLE",
            error_message="视频不可访问或已删除",
            error_retryable=False,
        )
        self.store.records[failed.job_id] = failed
        response = self.client.get(f"/api/v1/douyin/jobs/{failed.job_id}/download")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "VIDEO_UNAVAILABLE")

    def test_download_ready_job_rejects_missing_or_wrong_sized_file(self):
        ready = self.ready_job()
        self.store.records[ready.job_id] = ready
        missing = self.client.get(f"/api/v1/douyin/jobs/{ready.job_id}/download")
        self.assertEqual(missing.status_code, 503)
        self.assertEqual(missing.json()["error"]["code"], "STORAGE_ERROR")

        (self.ready_dir / f"{ready.job_id}.mp4").write_bytes(b"too short")
        mismatch = self.client.get(f"/api/v1/douyin/jobs/{ready.job_id}/download")
        self.assertEqual(mismatch.status_code, 503)
        self.assertEqual(mismatch.json()["error"]["code"], "STORAGE_ERROR")

    def test_download_redis_failure_returns_service_unavailable(self):
        job_id = JobRecord.create(SOURCE_URL, 7200).job_id
        with patch(
            "douyin.router.get_job_store",
            side_effect=JobStoreUnavailable("down"),
        ):
            response = self.client.get(f"/api/v1/douyin/jobs/{job_id}/download")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "SERVICE_UNAVAILABLE")

    def test_download_rejects_symlink_even_when_target_size_matches(self):
        ready = self.ready_job()
        self.store.records[ready.job_id] = ready
        target = Path(self.directory.name) / "outside.mp4"
        target.write_bytes(b"x" * ready.bytes_written)
        (self.ready_dir / f"{ready.job_id}.mp4").symlink_to(target)

        response = self.client.get(f"/api/v1/douyin/jobs/{ready.job_id}/download")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "STORAGE_ERROR")


if __name__ == "__main__":
    unittest.main()
