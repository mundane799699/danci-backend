import logging

from .config import DouyinSettings, settings
from .downloader import DouyinVideoDownloader
from .errors import DouyinError, error
from .job_store import JobStoreError, RedisJobStore
from .jobs import InvalidJobTransition, JobRecord
from .resolver import DouyinResolver


logger = logging.getLogger(__name__)
TERMINAL_STATES = frozenset({"ready", "failed", "expired"})


class DouyinJobProcessor:
    def __init__(
        self,
        config: DouyinSettings = settings,
        *,
        store: RedisJobStore | None = None,
        resolver=None,
        downloader=None,
    ):
        self.config = config
        self.store = store or RedisJobStore(config)
        self.resolver = resolver or DouyinResolver(config)
        self.downloader = downloader or DouyinVideoDownloader(config)

    def process(self, job_id: str) -> JobRecord:
        job = self.store.require(job_id)
        if job.state in TERMINAL_STATES:
            return job
        if job.state != "queued":
            raise InvalidJobTransition(f"cannot start processing while job is {job.state}")

        self.store.transition(
            job_id,
            "resolving",
            stage="正在解析视频",
            progress=10,
        )

        try:
            metadata = self.resolver.resolve(job.source_url)
            self.store.transition(
                job_id,
                "downloading",
                stage="正在准备视频",
                progress=40,
                aweme_id=metadata.aweme_id,
                title=metadata.title,
                author_name=metadata.author_name,
                duration_ms=metadata.duration_ms,
                resolver_version=getattr(self.resolver, "resolver_version", None),
            )

            last_reported_progress = 40

            def report_download_progress(bytes_written: int, total_bytes: int | None) -> None:
                nonlocal last_reported_progress
                if not total_bytes or total_bytes <= 0:
                    return
                calculated = min(95, 40 + int((bytes_written / total_bytes) * 55))
                if calculated < last_reported_progress + 5:
                    return
                self.store.update_progress(
                    job_id,
                    calculated,
                    stage="正在下载视频",
                )
                last_reported_progress = calculated

            result = self.downloader.download(
                job_id,
                metadata.media_candidates,
                progress_callback=report_download_progress,
            )
            return self.store.transition(
                job_id,
                "ready",
                stage="视频已准备好",
                bytes_written=result.bytes_written,
            )
        except JobStoreError:
            raise
        except DouyinError as exc:
            logger.warning("Douyin job failed: job_id=%s code=%s", job_id, exc.code)
            return self._mark_failed(job_id, exc)
        except OSError:
            logger.exception("Douyin job storage failure: job_id=%s", job_id)
            return self._mark_failed(job_id, error("STORAGE_ERROR", retryable=True))
        except Exception:
            logger.exception("Unexpected Douyin job failure: job_id=%s", job_id)
            return self._mark_failed(job_id, error("INTERNAL_ERROR", retryable=True))

    def _mark_failed(self, job_id: str, exc: DouyinError) -> JobRecord:
        current = self.store.require(job_id)
        if current.state in TERMINAL_STATES:
            return current
        return self.store.transition(
            job_id,
            "failed",
            stage="处理失败",
            error_code=exc.code,
            error_message=exc.message,
            error_retryable=exc.retryable,
        )


def process_job(job_id: str, config: DouyinSettings = settings) -> JobRecord:
    return DouyinJobProcessor(config).process(job_id)
