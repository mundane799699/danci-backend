import logging

from rq import Queue, Worker
from rq.exceptions import DeserializationError
from rq.job import Job
from rq.serializers import JSONSerializer
from rq.timeouts import JobTimeoutException

from .config import settings
from .errors import error
from .job_store import JobStoreError, RedisJobStore
from .jobs import JobModelError, canonical_job_id
from .redis_client import RedisSecretError, create_redis_client


logger = logging.getLogger(__name__)
TERMINAL_STATES = frozenset({"ready", "failed", "expired"})


def _business_job_id(job: Job) -> str | None:
    try:
        value = job.args[0]
        return canonical_job_id(value)
    except (AttributeError, DeserializationError, IndexError, JobModelError, TypeError):
        logger.error("RQ job does not contain a valid Douyin job id: rq_job_id=%s", job.id)
        return None


def _mark_worker_failure(job: Job, *, timed_out: bool) -> None:
    job_id = _business_job_id(job)
    if job_id is None:
        return

    failure = error("JOB_TIMEOUT" if timed_out else "INTERNAL_ERROR", retryable=True)
    try:
        store = RedisJobStore(settings)
        current = store.require(job_id)
        if current.state in TERMINAL_STATES:
            return
        store.transition(
            job_id,
            "failed",
            stage="处理超时" if timed_out else "Worker 异常退出",
            error_code=failure.code,
            error_message=failure.message,
            error_retryable=failure.retryable,
        )
    except (JobModelError, JobStoreError, RedisSecretError):
        logger.exception("Unable to record RQ worker failure: job_id=%s", job_id)


def handle_job_exception(job: Job, exc_type, _exc_value, _traceback) -> bool:
    _mark_worker_failure(job, timed_out=issubclass(exc_type, JobTimeoutException))
    return True


def handle_work_horse_killed(job: Job, _retpid, _ret_val, _rusage) -> None:
    _mark_worker_failure(job, timed_out=True)


def main() -> None:
    client = create_redis_client(settings, decode_responses=False)
    queue = Queue(
        settings.rq_queue_name,
        connection=client,
        serializer=JSONSerializer,
    )
    worker = Worker(
        [queue],
        connection=client,
        serializer=JSONSerializer,
        exception_handlers=[handle_job_exception],
        work_horse_killed_handler=handle_work_horse_killed,
    )
    worker.work()


if __name__ == "__main__":
    main()
