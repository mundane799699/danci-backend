from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import DuplicateJobError, InvalidJobOperationError
from rq.serializers import JSONSerializer

from .config import DouyinSettings, settings
from .redis_client import create_redis_client


class JobQueueError(RuntimeError):
    pass


class JobQueueUnavailable(JobQueueError):
    pass


class RQJobQueue:
    def __init__(
        self,
        config: DouyinSettings = settings,
        *,
        queue: Queue | None = None,
    ):
        if not config.rq_queue_name.strip():
            raise ValueError("rq_queue_name cannot be empty")
        if config.rq_job_timeout_seconds <= 0:
            raise ValueError("rq_job_timeout_seconds must be positive")
        if config.rq_result_ttl_seconds < 0:
            raise ValueError("rq_result_ttl_seconds cannot be negative")
        if config.rq_failure_ttl_seconds < 0:
            raise ValueError("rq_failure_ttl_seconds cannot be negative")

        self.config = config
        self.queue = queue or Queue(
            config.rq_queue_name,
            connection=create_redis_client(config, decode_responses=False),
            serializer=JSONSerializer,
        )

    def enqueue(self, job_id: str) -> str:
        rq_job_id = f"douyin-{job_id}"
        try:
            job = self.queue.enqueue_call(
                func="douyin.rq_tasks.process_queued_job",
                args=(job_id,),
                timeout=self.config.rq_job_timeout_seconds,
                result_ttl=self.config.rq_result_ttl_seconds,
                failure_ttl=self.config.rq_failure_ttl_seconds,
                job_id=rq_job_id,
                description=f"process Douyin job {job_id}",
            )
        except (RedisError, DuplicateJobError, InvalidJobOperationError) as exc:
            raise JobQueueUnavailable("RQ queue is unavailable") from exc
        return job.id
