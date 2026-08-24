import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal


JobState = Literal["queued", "resolving", "downloading", "ready", "failed", "expired"]

ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    "queued": frozenset({"resolving", "failed", "expired"}),
    "resolving": frozenset({"downloading", "failed", "expired"}),
    "downloading": frozenset({"ready", "failed", "expired"}),
    "ready": frozenset({"expired"}),
    "failed": frozenset({"expired"}),
    "expired": frozenset(),
}
PROGRESS_STATES = frozenset({"resolving", "downloading"})


class JobModelError(ValueError):
    pass


class InvalidJobTransition(JobModelError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_job_id(job_id: str) -> str:
    try:
        parsed = uuid.UUID(job_id)
    except (AttributeError, TypeError, ValueError):
        raise JobModelError("job_id must be a UUID v4") from None
    if parsed.version != 4 or str(parsed) != job_id.lower():
        raise JobModelError("job_id must be a canonical UUID v4")
    return str(parsed)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise JobModelError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    request_id: str
    source_url: str
    state: JobState
    stage: str
    progress: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    aweme_id: str | None = None
    title: str | None = None
    author_name: str | None = None
    duration_ms: int | None = None
    bytes_written: int = 0
    resolver_version: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_retryable: bool = False

    def __post_init__(self) -> None:
        canonical_job_id(self.job_id)
        if not self.request_id.startswith("req_") or len(self.request_id) <= 4:
            raise JobModelError("request_id is invalid")
        if not self.source_url.startswith("https://"):
            raise JobModelError("source_url must use HTTPS")
        if self.state not in ALLOWED_TRANSITIONS:
            raise JobModelError("state is invalid")
        if not 0 <= self.progress <= 100:
            raise JobModelError("progress must be between 0 and 100")
        if self.state == "queued" and self.progress != 0:
            raise JobModelError("queued jobs must have zero progress")
        if self.state in PROGRESS_STATES and self.progress >= 100:
            raise JobModelError("processing jobs must have progress below 100")
        if self.bytes_written < 0:
            raise JobModelError("bytes_written cannot be negative")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise JobModelError("duration_ms cannot be negative")

        created_at = _aware_utc(self.created_at, "created_at")
        updated_at = _aware_utc(self.updated_at, "updated_at")
        expires_at = _aware_utc(self.expires_at, "expires_at")
        if updated_at < created_at:
            raise JobModelError("updated_at cannot precede created_at")
        if expires_at <= created_at:
            raise JobModelError("expires_at must follow created_at")

        if self.state == "ready":
            if self.progress != 100 or not self.aweme_id or self.bytes_written <= 0:
                raise JobModelError("ready jobs require progress, aweme_id and bytes")
        if self.state == "failed" and not self.error_code:
            raise JobModelError("failed jobs require an error_code")

    @classmethod
    def create(
        cls,
        source_url: str,
        ttl_seconds: int,
        *,
        job_id: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> "JobRecord":
        if ttl_seconds <= 0:
            raise JobModelError("ttl_seconds must be positive")
        created_at = _aware_utc(now or utc_now(), "now")
        return cls(
            job_id=canonical_job_id(job_id or str(uuid.uuid4())),
            request_id=request_id or f"req_{uuid.uuid4().hex}",
            source_url=source_url,
            state="queued",
            stage="等待处理",
            progress=0,
            created_at=created_at,
            updated_at=created_at,
            expires_at=created_at + timedelta(seconds=ttl_seconds),
        )


def transition_job(
    job: JobRecord,
    new_state: JobState,
    *,
    stage: str,
    progress: int | None = None,
    now: datetime | None = None,
    **updates,
) -> JobRecord:
    if new_state not in ALLOWED_TRANSITIONS[job.state]:
        raise InvalidJobTransition(f"cannot transition {job.state} to {new_state}")
    if not stage.strip():
        raise JobModelError("stage cannot be empty")

    next_progress = job.progress if progress is None else progress
    if next_progress < job.progress and new_state not in {"failed", "expired"}:
        raise JobModelError("progress cannot decrease")
    if new_state == "ready":
        next_progress = 100

    allowed_updates = {
        "aweme_id",
        "title",
        "author_name",
        "duration_ms",
        "bytes_written",
        "resolver_version",
        "error_code",
        "error_message",
        "error_retryable",
    }
    unknown_updates = set(updates) - allowed_updates
    if unknown_updates:
        raise JobModelError(f"unsupported job fields: {sorted(unknown_updates)}")

    changed_at = _aware_utc(now or utc_now(), "now")
    if changed_at < job.updated_at:
        raise JobModelError("updated_at cannot move backwards")
    return replace(
        job,
        state=new_state,
        stage=stage.strip(),
        progress=next_progress,
        updated_at=changed_at,
        **updates,
    )


def update_job_progress(
    job: JobRecord,
    progress: int,
    *,
    stage: str | None = None,
    now: datetime | None = None,
) -> JobRecord:
    if job.state not in PROGRESS_STATES:
        raise InvalidJobTransition(f"cannot update progress while job is {job.state}")
    if progress < job.progress:
        raise JobModelError("progress cannot decrease")
    if progress >= 100:
        raise JobModelError("processing progress must be below 100")
    next_stage = job.stage if stage is None else stage.strip()
    if not next_stage:
        raise JobModelError("stage cannot be empty")
    changed_at = _aware_utc(now or utc_now(), "now")
    if changed_at < job.updated_at:
        raise JobModelError("updated_at cannot move backwards")
    return replace(job, progress=progress, stage=next_stage, updated_at=changed_at)
