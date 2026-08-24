import unittest
import uuid
from unittest.mock import Mock, patch

from redis.exceptions import RedisError
from rq.serializers import JSONSerializer
from rq.timeouts import JobTimeoutException

from douyin.config import DouyinSettings, settings
from douyin.job_store import JobNotFoundError
from douyin.jobs import JobRecord, transition_job
from douyin.queueing import JobQueueUnavailable, RQJobQueue
from douyin.rq_tasks import process_queued_job
from douyin.worker import handle_job_exception, handle_work_horse_killed, main


SOURCE_URL = "https://v.douyin.com/test-link/"


class QueueTests(unittest.TestCase):
    def test_builds_json_queue_and_enqueues_bounded_job(self):
        config = DouyinSettings(
            rq_queue_name="test-douyin",
            rq_job_timeout_seconds=123,
            rq_result_ttl_seconds=45,
            rq_failure_ttl_seconds=678,
        )
        redis_client = Mock()
        rq_job = Mock(id="douyin-result")
        with patch("douyin.queueing.create_redis_client", return_value=redis_client) as client_factory, patch(
            "douyin.queueing.Queue"
        ) as queue_class:
            queue = queue_class.return_value
            queue.enqueue_call.return_value = rq_job
            job_queue = RQJobQueue(config)
            job_id = str(uuid.uuid4())
            result = job_queue.enqueue(job_id)

        queue_class.assert_called_once_with(
            "test-douyin",
            connection=redis_client,
            serializer=JSONSerializer,
        )
        client_factory.assert_called_once_with(config, decode_responses=False)
        self.assertEqual(result, "douyin-result")
        queue.enqueue_call.assert_called_once_with(
            func="douyin.rq_tasks.process_queued_job",
            args=(job_id,),
            timeout=123,
            result_ttl=45,
            failure_ttl=678,
            job_id=f"douyin-{job_id}",
            description=f"process Douyin job {job_id}",
        )

    def test_maps_redis_enqueue_failure(self):
        queue = Mock()
        queue.enqueue_call.side_effect = RedisError("unavailable")
        job_queue = RQJobQueue(DouyinSettings(), queue=queue)
        with self.assertRaises(JobQueueUnavailable):
            job_queue.enqueue(str(uuid.uuid4()))

    @patch("douyin.rq_tasks.process_job")
    def test_rq_task_discards_business_result(self, process_job: Mock):
        process_job.return_value = Mock()
        job_id = str(uuid.uuid4())
        self.assertIsNone(process_queued_job(job_id))
        process_job.assert_called_once_with(job_id)

    @patch("douyin.worker.Worker")
    @patch("douyin.worker.Queue")
    @patch("douyin.worker.create_redis_client")
    def test_worker_uses_binary_json_connection(
        self,
        client_factory: Mock,
        queue_class: Mock,
        worker_class: Mock,
    ):
        client = client_factory.return_value
        queue = queue_class.return_value
        main()
        client_factory.assert_called_once_with(settings, decode_responses=False)
        queue_class.assert_called_once_with(
            settings.rq_queue_name,
            connection=client,
            serializer=JSONSerializer,
        )
        worker_class.return_value.work.assert_called_once_with()


class _MemoryStore:
    def __init__(self, record: JobRecord):
        self.record = record

    def require(self, job_id: str) -> JobRecord:
        if self.record.job_id != job_id:
            raise JobNotFoundError(job_id)
        return self.record

    def transition(self, job_id: str, state: str, **kwargs) -> JobRecord:
        self.record = transition_job(self.require(job_id), state, **kwargs)
        return self.record


class WorkerFailureTests(unittest.TestCase):
    def setUp(self):
        self.record = JobRecord.create(SOURCE_URL, 7200)
        self.store = _MemoryStore(self.record)
        self.rq_job = Mock(id=f"douyin-{self.record.job_id}")
        self.rq_job.args = (self.record.job_id,)

    @patch("douyin.worker.RedisJobStore")
    def test_timeout_marks_business_job_failed(self, store_class: Mock):
        store_class.return_value = self.store
        handle_job_exception(
            self.rq_job,
            JobTimeoutException,
            JobTimeoutException(),
            None,
        )
        self.assertEqual(self.store.record.state, "failed")
        self.assertEqual(self.store.record.error_code, "JOB_TIMEOUT")
        self.assertTrue(self.store.record.error_retryable)

    @patch("douyin.worker.RedisJobStore")
    def test_killed_work_horse_marks_business_job_failed(self, store_class: Mock):
        store_class.return_value = self.store
        handle_work_horse_killed(self.rq_job, 1, 9, None)
        self.assertEqual(self.store.record.error_code, "JOB_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
