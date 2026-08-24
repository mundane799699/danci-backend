import time
import tempfile
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from redis import Redis
from redis.exceptions import RedisError

from douyin.config import DouyinSettings
from douyin.job_store import (
    JobAlreadyExistsError,
    JobNotFoundError,
    JobStoreUnavailable,
    RedisJobStore,
)
from douyin.jobs import (
    InvalidJobTransition,
    JobModelError,
    JobRecord,
    transition_job,
    update_job_progress,
)
from douyin.redis_client import RedisSecretError, create_redis_client


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
SOURCE_URL = "https://v.douyin.com/test-link/"


class JobModelTests(unittest.TestCase):
    def job(self) -> JobRecord:
        return JobRecord.create(SOURCE_URL, 7200, now=NOW)

    def test_creates_queued_job_with_expiry(self):
        job = self.job()
        self.assertEqual(job.state, "queued")
        self.assertEqual(job.progress, 0)
        self.assertEqual(job.expires_at, NOW + timedelta(hours=2))
        self.assertTrue(job.request_id.startswith("req_"))

    def test_transitions_through_happy_path(self):
        resolving = transition_job(
            self.job(),
            "resolving",
            stage="正在解析视频",
            progress=10,
            now=NOW + timedelta(seconds=1),
        )
        downloading = transition_job(
            resolving,
            "downloading",
            stage="正在准备视频",
            progress=25,
            now=NOW + timedelta(seconds=2),
            aweme_id="12345",
            title="测试视频",
            author_name="作者",
            duration_ms=12000,
            resolver_version="cookie-api-v1",
        )
        ready = transition_job(
            downloading,
            "ready",
            stage="视频已准备好",
            now=NOW + timedelta(seconds=3),
            bytes_written=2048,
        )

        self.assertEqual(ready.state, "ready")
        self.assertEqual(ready.progress, 100)
        self.assertEqual(ready.aweme_id, "12345")
        self.assertEqual(ready.bytes_written, 2048)

    def test_rejects_invalid_transition_and_ready_without_file(self):
        with self.assertRaises(InvalidJobTransition):
            transition_job(self.job(), "ready", stage="完成", now=NOW + timedelta(seconds=1))

        resolving = transition_job(
            self.job(),
            "resolving",
            stage="解析中",
            now=NOW + timedelta(seconds=1),
        )
        downloading = transition_job(
            resolving,
            "downloading",
            stage="下载中",
            now=NOW + timedelta(seconds=2),
        )
        with self.assertRaises(JobModelError):
            transition_job(
                downloading,
                "ready",
                stage="完成",
                now=NOW + timedelta(seconds=3),
            )

    def test_progress_is_monotonic_and_only_allowed_while_processing(self):
        resolving = transition_job(
            self.job(),
            "resolving",
            stage="解析中",
            progress=10,
            now=NOW + timedelta(seconds=1),
        )
        progressed = update_job_progress(
            resolving,
            40,
            stage="解析元数据",
            now=NOW + timedelta(seconds=2),
        )
        self.assertEqual(progressed.progress, 40)
        with self.assertRaises(JobModelError):
            update_job_progress(
                progressed,
                39,
                now=NOW + timedelta(seconds=3),
            )
        with self.assertRaises(InvalidJobTransition):
            update_job_progress(self.job(), 10, now=NOW + timedelta(seconds=1))

    def test_failed_state_requires_error_code(self):
        with self.assertRaises(JobModelError):
            transition_job(
                self.job(),
                "failed",
                stage="处理失败",
                now=NOW + timedelta(seconds=1),
            )
        failed = transition_job(
            self.job(),
            "failed",
            stage="处理失败",
            now=NOW + timedelta(seconds=1),
            error_code="VIDEO_UNAVAILABLE",
            error_message="视频不可用",
        )
        self.assertEqual(failed.error_code, "VIDEO_UNAVAILABLE")

    def test_rejects_non_uuid_and_naive_timestamps(self):
        with self.assertRaises(JobModelError):
            JobRecord.create(SOURCE_URL, 7200, job_id="../bad", now=NOW)
        with self.assertRaises(JobModelError):
            JobRecord.create(SOURCE_URL, 7200, now=datetime(2026, 8, 24, 12, 0))

    def test_record_validation_detects_invalid_stored_shape(self):
        with self.assertRaises(JobModelError):
            replace(self.job(), progress=101)
        with self.assertRaises(JobModelError):
            replace(self.job(), progress=1)
        with self.assertRaises(JobModelError):
            replace(self.job(), duration_ms=-1)


class RedisJobStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Redis.from_url(
            "redis://127.0.0.1:6379/0",
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        try:
            cls.client.ping()
        except RedisError as exc:
            raise unittest.SkipTest(f"local Redis is unavailable: {exc}")

    def setUp(self):
        self.prefix = f"test:remove_watermark:job:{uuid.uuid4().hex}"
        self.config = DouyinSettings(
            redis_url="redis://127.0.0.1:6379/0",
            redis_timeout_seconds=0.2,
            job_ttl_seconds=60,
            job_key_prefix=self.prefix,
        )
        self.store = RedisJobStore(self.config, self.client)

    def tearDown(self):
        keys = list(self.client.scan_iter(match=f"{self.prefix}:*"))
        if keys:
            self.client.delete(*keys)

    def test_create_get_and_duplicate_protection(self):
        job_id = str(uuid.uuid4())
        created = self.store.create(SOURCE_URL, job_id=job_id)
        loaded = self.store.get(job_id)

        self.assertEqual(loaded, created)
        ttl = self.client.ttl(self.store.key_for(job_id))
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 60)
        with self.assertRaises(JobAlreadyExistsError):
            self.store.create(SOURCE_URL, job_id=job_id)

    def test_transitions_and_progress_updates_preserve_ttl(self):
        created = self.store.create(SOURCE_URL)
        key = self.store.key_for(created.job_id)
        original_ttl = self.client.ttl(key)

        resolving = self.store.transition(
            created.job_id,
            "resolving",
            stage="解析中",
            progress=10,
        )
        progressed = self.store.update_progress(
            created.job_id,
            35,
            stage="读取视频信息",
        )

        self.assertEqual(resolving.state, "resolving")
        self.assertEqual(progressed.progress, 35)
        updated_ttl = self.client.ttl(key)
        self.assertGreater(updated_ttl, 0)
        self.assertLessEqual(updated_ttl, original_ttl)

    def test_failed_job_round_trips_error_fields(self):
        created = self.store.create(SOURCE_URL)
        failed = self.store.transition(
            created.job_id,
            "failed",
            stage="处理失败",
            error_code="COOKIE_EXPIRED",
            error_message="Cookie 已失效",
            error_retryable=False,
        )
        loaded = self.store.require(created.job_id)

        self.assertEqual(loaded, failed)
        self.assertEqual(loaded.error_code, "COOKIE_EXPIRED")

    def test_missing_and_expired_jobs(self):
        missing_id = str(uuid.uuid4())
        self.assertIsNone(self.store.get(missing_id))
        with self.assertRaises(JobNotFoundError):
            self.store.require(missing_id)

        created = self.store.create(SOURCE_URL)
        self.client.pexpire(self.store.key_for(created.job_id), 30)
        time.sleep(0.08)
        self.assertIsNone(self.store.get(created.job_id))

    def test_redis_connection_failure_has_stable_store_error(self):
        unavailable_client = Redis.from_url(
            "redis://127.0.0.1:6399/0",
            decode_responses=True,
            socket_connect_timeout=0.05,
            socket_timeout=0.05,
        )
        store = RedisJobStore(self.config, unavailable_client)
        with self.assertRaises(JobStoreUnavailable):
            store.get(str(uuid.uuid4()))


class RedisClientTests(unittest.TestCase):
    def test_reads_password_from_restricted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            password_file = f"{directory}/redis-password.txt"
            with open(password_file, "w", encoding="utf-8") as target:
                target.write("test-password\n")
            config = DouyinSettings(
                redis_url="redis://127.0.0.1:6379/0",
                redis_password_file=password_file,
            )
            client = create_redis_client(config)
            self.assertEqual(client.connection_pool.connection_kwargs["password"], "test-password")

    def test_missing_password_file_is_rejected(self):
        config = DouyinSettings(redis_password_file="/path/that/does/not/exist")
        with self.assertRaises(RedisSecretError):
            create_redis_client(config)


if __name__ == "__main__":
    unittest.main()
