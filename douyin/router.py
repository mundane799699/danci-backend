import uuid
from functools import lru_cache
from pathlib import Path
from stat import S_ISREG

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from .config import settings
from .cleanup import ensure_storage_capacity
from .errors import DouyinError, error
from .job_store import JobStoreError, RedisJobStore
from .jobs import JobModelError, canonical_job_id, utc_now
from .models import (
    CreateJobResponse,
    JobErrorResponse,
    JobStatusResponse,
    JobVideoResponse,
    MediaCandidateResponse,
    ResolveRequest,
    ResolveResponse,
)
from .queueing import JobQueueError, RQJobQueue
from .redis_client import RedisSecretError
from .resolver import DouyinResolver
from .security import extract_share_url

router = APIRouter()


def _error_response(
    request_id: str,
    exc: DouyinError,
    *,
    status_code: int | None = None,
) -> JSONResponse:
    if status_code is None:
        if exc.code in {"INVALID_SHARE_TEXT", "UNSUPPORTED_HOST", "UNSUPPORTED_IMAGE_POST"}:
            status_code = 400
        elif exc.code == "JOB_NOT_FOUND":
            status_code = 404
        elif exc.code == "FILE_NOT_READY":
            status_code = 409
        elif exc.code in {"DISK_PRESSURE", "SERVICE_UNAVAILABLE"}:
            status_code = 503
        else:
            status_code = 502
    return JSONResponse(
        status_code=status_code,
        content={
            "requestId": request_id,
            "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
        },
    )


@lru_cache(maxsize=1)
def get_job_store() -> RedisJobStore:
    return RedisJobStore(settings)


@lru_cache(maxsize=1)
def get_job_queue() -> RQJobQueue:
    return RQJobQueue(settings)


@router.post("/resolve", response_model=ResolveResponse)
def resolve_video(payload: ResolveRequest):
    request_id = f"req_{uuid.uuid4().hex}"
    try:
        source_url = extract_share_url(payload.share_text, settings.entry_hosts, settings.max_share_text_bytes)
        metadata = DouyinResolver(settings).resolve(source_url)
        best = metadata.media_candidates[0]
        return ResolveResponse(
            requestId=request_id,
            awemeId=metadata.aweme_id,
            title=metadata.title,
            authorName=metadata.author_name,
            durationMs=metadata.duration_ms,
            coverUrl=metadata.cover_url,
            videoUrl=best.url,
            candidates=[
                MediaCandidateResponse(
                    url=item.url,
                    width=item.width,
                    height=item.height,
                    bitrate=item.bitrate,
                    codec=item.codec,
                )
                for item in metadata.media_candidates
            ],
        )
    except DouyinError as exc:
        return _error_response(request_id, exc)


@router.post("/jobs", response_model=CreateJobResponse, status_code=202)
def create_job(payload: ResolveRequest):
    request_id = f"req_{uuid.uuid4().hex}"
    job = None
    store = None
    try:
        source_url = extract_share_url(
            payload.share_text,
            settings.entry_hosts,
            settings.max_share_text_bytes,
        )
        store = get_job_store()
        ensure_storage_capacity(settings, store=store)
        job = store.create(source_url, request_id=request_id)
        get_job_queue().enqueue(job.job_id)
        return CreateJobResponse(
            requestId=job.request_id,
            jobId=job.job_id,
            state="queued",
            createdAt=job.created_at,
        )
    except DouyinError as exc:
        return _error_response(request_id, exc)
    except (JobStoreError, JobQueueError, RedisSecretError):
        if job is not None and store is not None:
            try:
                store.delete(job.job_id)
            except JobStoreError:
                pass
        return _error_response(request_id, error("SERVICE_UNAVAILABLE", retryable=True))
    except OSError:
        return _error_response(
            request_id,
            error("STORAGE_ERROR", retryable=True),
            status_code=503,
        )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    response_model_exclude_none=True,
)
def get_job(job_id: str, request: Request):
    request_id = f"req_{uuid.uuid4().hex}"
    try:
        canonical_job_id(job_id)
        job = get_job_store().get(job_id)
        if job is None:
            return _error_response(request_id, error("JOB_NOT_FOUND"))

        video = None
        job_error = None
        if job.state == "ready":
            video = JobVideoResponse(
                awemeId=job.aweme_id,
                title=job.title or "",
                authorName=job.author_name or "",
                durationMs=job.duration_ms,
                bytes=job.bytes_written,
                downloadUrl=str(request.url_for("download_job", job_id=job.job_id)),
                expiresAt=job.expires_at,
            )
        elif job.state == "failed":
            job_error = JobErrorResponse(
                code=job.error_code or "INTERNAL_ERROR",
                message=job.error_message or error("INTERNAL_ERROR").message,
                retryable=job.error_retryable,
            )

        return JobStatusResponse(
            requestId=job.request_id,
            jobId=job.job_id,
            state=job.state,
            stage=job.stage,
            progress=job.progress,
            video=video,
            error=job_error,
        )
    except JobModelError:
        return _error_response(request_id, error("JOB_NOT_FOUND"))
    except (JobStoreError, RedisSecretError):
        return _error_response(request_id, error("SERVICE_UNAVAILABLE", retryable=True))


def _ready_file_matches(job_id: str, expected_bytes: int) -> bool:
    file_path = Path(settings.ready_dir) / f"{job_id}.mp4"
    try:
        file_stat = file_path.lstat()
    except OSError:
        return False
    return S_ISREG(file_stat.st_mode) and file_stat.st_size == expected_bytes


@router.get("/jobs/{job_id}/download", name="download_job")
def download_job(job_id: str):
    request_id = f"req_{uuid.uuid4().hex}"
    try:
        canonical_job_id(job_id)
        job = get_job_store().get(job_id)
        if job is None or job.state == "expired" or job.expires_at <= utc_now():
            return _error_response(request_id, error("JOB_NOT_FOUND"))
        if job.state in {"queued", "resolving", "downloading"}:
            return _error_response(request_id, error("FILE_NOT_READY", retryable=True))
        if job.state == "failed":
            failure = DouyinError(
                job.error_code or "INTERNAL_ERROR",
                job.error_message or error("INTERNAL_ERROR").message,
                retryable=job.error_retryable,
            )
            return _error_response(request_id, failure, status_code=409)
        if not _ready_file_matches(job.job_id, job.bytes_written):
            return _error_response(
                request_id,
                error("STORAGE_ERROR", retryable=True),
                status_code=503,
            )

        return Response(
            status_code=200,
            media_type="video/mp4",
            headers={
                "Content-Disposition": 'attachment; filename="video.mp4"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Request-ID": request_id,
                "X-Accel-Redirect": f"/_protected-videos/{job.job_id}.mp4",
            },
        )
    except JobModelError:
        return _error_response(request_id, error("JOB_NOT_FOUND"))
    except (JobStoreError, RedisSecretError):
        return _error_response(request_id, error("SERVICE_UNAVAILABLE", retryable=True))
