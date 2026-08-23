from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class MediaCandidate:
    url: str
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    codec: str | None = None

    @property
    def quality_score(self) -> tuple[int, int]:
        return ((self.width or 0) * (self.height or 0), self.bitrate or 0)


@dataclass(frozen=True)
class DouyinVideoMetadata:
    aweme_id: str
    content_type: Literal["video", "image", "live", "unknown"]
    title: str
    author_name: str
    cover_url: str | None
    duration_ms: int | None
    media_candidates: list[MediaCandidate]


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ResolveRequest(ApiModel):
    share_text: str = Field(alias="shareText")


class MediaCandidateResponse(ApiModel):
    url: str
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    codec: str | None = None


class ResolveResponse(ApiModel):
    request_id: str = Field(alias="requestId")
    aweme_id: str = Field(alias="awemeId")
    title: str
    author_name: str = Field(alias="authorName")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    cover_url: str | None = Field(default=None, alias="coverUrl")
    video_url: str = Field(alias="videoUrl")
    candidates: list[MediaCandidateResponse]
