import uuid
from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .config import settings
from .errors import DouyinError, error
from .job_store import JobStoreError, RedisJobStore
from .jobs import JobModelError, canonical_job_id
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


def _error_response(request_id: str, exc: DouyinError) -> JSONResponse:
    if exc.code in {"INVALID_SHARE_TEXT", "UNSUPPORTED_HOST", "UNSUPPORTED_IMAGE_POST"}:
        status_code = 400
    elif exc.code == "JOB_NOT_FOUND":
        status_code = 404
    elif exc.code == "SERVICE_UNAVAILABLE":
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
                downloadUrl=(
                    f"{str(request.base_url).rstrip('/')}"
                    f"/api/v1/douyin/jobs/{job.job_id}/download"
                ),
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
