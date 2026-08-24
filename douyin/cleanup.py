import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from stat import S_ISDIR, S_ISREG

from .config import DouyinSettings, settings
from .errors import error
from .job_store import JobStoreError, RedisJobStore
from .jobs import JobModelError, canonical_job_id, utc_now


@dataclass(frozen=True)
class CleanupResult:
    scanned: int = 0
    removed_parts: int = 0
    removed_videos: int = 0
    removed_jobs: int = 0
    skipped: int = 0
    file_failures: int = 0
    redis_failures: int = 0


def _validate_config(config: DouyinSettings) -> tuple[Path, Path]:
    if config.part_ttl_seconds <= 0:
        raise ValueError("part_ttl_seconds must be positive")
    if config.ready_file_ttl_seconds <= 0:
        raise ValueError("ready_file_ttl_seconds must be positive")
    if not 0 < config.disk_usage_limit_percent <= 100:
        raise ValueError("disk_usage_limit_percent must be between 0 and 100")

    roots = (Path(config.downloading_dir), Path(config.ready_dir))
    if any(not root.is_absolute() or root == Path("/") for root in roots):
        raise ValueError("cleanup directories must be absolute and cannot be root")
    if any(root != Path(os.path.abspath(root)) for root in roots):
        raise ValueError("cleanup directories must be normalized")
    if roots[0] == roots[1]:
        raise ValueError("cleanup directories must be different")

    for root in roots:
        root_stat = root.lstat()
        if not S_ISDIR(root_stat.st_mode):
            raise ValueError("cleanup directory must be a real directory")
    return roots


def _job_id_from_filename(filename: str, suffix: str) -> str | None:
    if not filename.endswith(suffix):
        return None
    candidate = filename[: -len(suffix)]
    try:
        return canonical_job_id(candidate)
    except JobModelError:
        return None


def _regular_file_exists(path: Path) -> bool:
    try:
        return S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def cleanup_expired_files(
    config: DouyinSettings = settings,
    *,
    store: RedisJobStore | None = None,
    now: datetime | None = None,
) -> CleanupResult:
    downloading_dir, ready_dir = _validate_config(config)
    job_store = store or RedisJobStore(config)
    current_timestamp = (now or utc_now()).timestamp()
    scanned = removed_parts = removed_videos = skipped = file_failures = 0
    expired_job_ids: set[str] = set()

    targets = (
        (downloading_dir, ".part", config.part_ttl_seconds),
        (ready_dir, ".mp4", config.ready_file_ttl_seconds),
    )
    for root, suffix, ttl_seconds in targets:
        cutoff = current_timestamp - ttl_seconds
        for path in root.iterdir():
            scanned += 1
            job_id = _job_id_from_filename(path.name, suffix)
            if job_id is None:
                skipped += 1
                continue
            try:
                file_stat = path.lstat()
                if not S_ISREG(file_stat.st_mode) or file_stat.st_mtime > cutoff:
                    skipped += 1
                    continue
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                file_failures += 1
                continue

            if suffix == ".part":
                removed_parts += 1
                if not _regular_file_exists(ready_dir / f"{job_id}.mp4"):
                    expired_job_ids.add(job_id)
            else:
                removed_videos += 1
                expired_job_ids.add(job_id)

    removed_jobs = redis_failures = 0
    for job_id in expired_job_ids:
        try:
            removed_jobs += int(job_store.delete(job_id))
        except JobStoreError:
            redis_failures += 1

    return CleanupResult(
        scanned=scanned,
        removed_parts=removed_parts,
        removed_videos=removed_videos,
        removed_jobs=removed_jobs,
        skipped=skipped,
        file_failures=file_failures,
        redis_failures=redis_failures,
    )


def storage_usage_percent(config: DouyinSettings = settings) -> float:
    downloading_dir, ready_dir = _validate_config(config)
    percentages = []
    for root in (downloading_dir, ready_dir):
        usage = shutil.disk_usage(root)
        if usage.total <= 0:
            raise OSError("storage volume has invalid capacity")
        percentages.append((usage.used / usage.total) * 100)
    return max(percentages)


def ensure_storage_capacity(
    config: DouyinSettings = settings,
    *,
    store: RedisJobStore | None = None,
) -> float:
    usage_percent = storage_usage_percent(config)
    if usage_percent < config.disk_usage_limit_percent:
        return usage_percent

    cleanup_expired_files(config, store=store)
    usage_percent = storage_usage_percent(config)
    if usage_percent >= config.disk_usage_limit_percent:
        raise error("DISK_PRESSURE", retryable=True)
    return usage_percent
