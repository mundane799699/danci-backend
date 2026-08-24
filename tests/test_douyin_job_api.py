import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from douyin.job_store import JobStoreUnavailable
from douyin.jobs import JobRecord, transition_job
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

    def create_job(self):
        return self.client.post(
            "/api/v1/douyin/jobs",
            json={"shareText": f"复制 {SOURCE_URL} 打开抖音"},
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

    def test_get_processing_job(self):
        created = JobRecord.create(SOURCE_URL, 7200)
        processing = transition_job(created, "resolving", stage="正在解析视频", progress=10)
        self.store.records[created.job_id] = processing
        response = self.client.get(f"/api/v1/douyin/jobs/{created.job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "resolving")
        self.assertNotIn("video", response.json())

    def test_get_ready_job_only_returns_public_video_fields(self):
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
        ready = transition_job(
            downloading,
            "ready",
            stage="完成",
            bytes_written=4096,
        )
        self.store.records[created.job_id] = ready
        response = self.client.get(f"/api/v1/douyin/jobs/{created.job_id}")
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["video"]["bytes"], 4096)
        self.assertTrue(body["video"]["downloadUrl"].endswith(f"/{created.job_id}/download"))
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


if __name__ == "__main__":
    unittest.main()
