import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .config import settings
from .errors import DouyinError
from .models import MediaCandidateResponse, ResolveRequest, ResolveResponse
from .resolver import DouyinResolver
from .security import extract_share_url

router = APIRouter()


def _error_response(request_id: str, exc: DouyinError) -> JSONResponse:
    status_code = 400 if exc.code in {"INVALID_SHARE_TEXT", "UNSUPPORTED_HOST", "UNSUPPORTED_IMAGE_POST"} else 502
    return JSONResponse(
        status_code=status_code,
        content={
            "requestId": request_id,
            "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
        },
    )


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
