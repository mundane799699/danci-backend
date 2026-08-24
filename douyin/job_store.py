from datetime import datetime
from typing import Callable

from redis import Redis
from redis.exceptions import RedisError, WatchError

from .config import DouyinSettings, settings
from .jobs import (
    JobRecord,
    JobState,
    canonical_job_id,
    transition_job,
    update_job_progress,
)
from .redis_client import create_redis_client


class JobStoreError(RuntimeError):
    pass


class JobStoreUnavailable(JobStoreError):
    pass


class JobNotFoundError(JobStoreError):
    pass


class JobAlreadyExistsError(JobStoreError):
    pass


class ConcurrentJobUpdateError(JobStoreError):
    pass


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional(value: str | None) -> str | None:
    return value or None


def _to_hash(job: JobRecord) -> dict[str, str | int]:
    return {
        "jobId": job.job_id,
        "requestId": job.request_id,
        "sourceUrl": job.source_url,
        "state": job.state,
        "stage": job.stage,
        "progress": job.progress,
        "createdAt": _timestamp(job.created_at),
        "updatedAt": _timestamp(job.updated_at),
        "expiresAt": _timestamp(job.expires_at),
        "awemeId": job.aweme_id or "",
        "title": job.title or "",
        "authorName": job.author_name or "",
        "durationMs": "" if job.duration_ms is None else job.duration_ms,
        "bytes": job.bytes_written,
        "resolverVersion": job.resolver_version or "",
        "errorCode": job.error_code or "",
        "errorMessage": job.error_message or "",
        "errorRetryable": "1" if job.error_retryable else "0",
    }


def _from_hash(values: dict[str, str]) -> JobRecord:
    try:
        return JobRecord(
            job_id=values["jobId"],
            request_id=values["requestId"],
            source_url=values["sourceUrl"],
            state=values["state"],
            stage=values["stage"],
            progress=int(values["progress"]),
            created_at=_parse_timestamp(values["createdAt"]),
            updated_at=_parse_timestamp(values["updatedAt"]),
            expires_at=_parse_timestamp(values["expiresAt"]),
            aweme_id=_optional(values.get("awemeId")),
            title=_optional(values.get("title")),
            author_name=_optional(values.get("authorName")),
            duration_ms=int(values["durationMs"]) if values.get("durationMs") else None,
            bytes_written=int(values.get("bytes") or 0),
            resolver_version=_optional(values.get("resolverVersion")),
            error_code=_optional(values.get("errorCode")),
            error_message=_optional(values.get("errorMessage")),
            error_retryable=values.get("errorRetryable") == "1",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise JobStoreError("stored job data is invalid") from exc


class RedisJobStore:
    def __init__(
        self,
        config: DouyinSettings = settings,
        client: Redis | None = None,
        *,
        max_update_retries: int = 3,
    ):
        if config.job_ttl_seconds <= 0:
            raise ValueError("job_ttl_seconds must be positive")
        if not config.job_key_prefix.strip():
            raise ValueError("job_key_prefix cannot be empty")
        if max_update_retries <= 0:
            raise ValueError("max_update_retries must be positive")
        self.config = config
        self.client = client or create_redis_client(config)
        self.max_update_retries = max_update_retries

    def key_for(self, job_id: str) -> str:
        return f"{self.config.job_key_prefix}:{canonical_job_id(job_id)}"

    def create(
        self,
        source_url: str,
        *,
        job_id: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> JobRecord:
        job = JobRecord.create(
            source_url,
            self.config.job_ttl_seconds,
            job_id=job_id,
            request_id=request_id,
            now=now,
        )
        key = self.key_for(job.job_id)

        try:
            with self.client.pipeline() as pipe:
                for _ in range(self.max_update_retries):
                    try:
                        pipe.watch(key)
                        if pipe.exists(key):
                            pipe.unwatch()
                            raise JobAlreadyExistsError(job.job_id)
                        pipe.multi()
                        pipe.hset(key, mapping=_to_hash(job))
                        pipe.expire(key, self.config.job_ttl_seconds)
                        pipe.execute()
                        return job
                    except WatchError:
                        continue
            raise ConcurrentJobUpdateError(job.job_id)
        except RedisError as exc:
            raise JobStoreUnavailable("Redis is unavailable") from exc

    def get(self, job_id: str) -> JobRecord | None:
        key = self.key_for(job_id)
        try:
            values = self.client.hgetall(key)
        except RedisError as exc:
            raise JobStoreUnavailable("Redis is unavailable") from exc
        return _from_hash(values) if values else None

    def require(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def transition(
        self,
        job_id: str,
        new_state: JobState,
        *,
        stage: str,
        progress: int | None = None,
        now: datetime | None = None,
        **updates,
    ) -> JobRecord:
        return self._mutate(
            job_id,
            lambda job: transition_job(
                job,
                new_state,
                stage=stage,
                progress=progress,
                now=now,
                **updates,
            ),
        )

    def update_progress(
        self,
        job_id: str,
        progress: int,
        *,
        stage: str | None = None,
        now: datetime | None = None,
    ) -> JobRecord:
        return self._mutate(
            job_id,
            lambda job: update_job_progress(job, progress, stage=stage, now=now),
        )

    def delete(self, job_id: str) -> bool:
        key = self.key_for(job_id)
        try:
            return bool(self.client.delete(key))
        except RedisError as exc:
            raise JobStoreUnavailable("Redis is unavailable") from exc

    def _mutate(self, job_id: str, mutation: Callable[[JobRecord], JobRecord]) -> JobRecord:
        key = self.key_for(job_id)
        try:
            with self.client.pipeline() as pipe:
                for _ in range(self.max_update_retries):
                    try:
                        pipe.watch(key)
                        values = pipe.hgetall(key)
                        if not values:
                            pipe.unwatch()
                            raise JobNotFoundError(job_id)
                        updated = mutation(_from_hash(values))
                        pipe.multi()
                        pipe.hset(key, mapping=_to_hash(updated))
                        pipe.execute()
                        return updated
                    except WatchError:
                        continue
            raise ConcurrentJobUpdateError(job_id)
        except RedisError as exc:
            raise JobStoreUnavailable("Redis is unavailable") from exc
