import argparse
import json
import sys
from pathlib import Path

from .config import settings
from .errors import DouyinError
from .job_store import JobStoreError, RedisJobStore
from .jobs import JobModelError
from .processor import DouyinJobProcessor
from .redis_client import RedisSecretError
from .security import extract_share_url


def _result(job) -> dict:
    payload = {
        "jobId": job.job_id,
        "requestId": job.request_id,
        "state": job.state,
        "stage": job.stage,
        "progress": job.progress,
    }
    if job.state == "ready":
        payload["video"] = {
            "awemeId": job.aweme_id,
            "title": job.title,
            "authorName": job.author_name,
            "durationMs": job.duration_ms,
            "bytes": job.bytes_written,
            "filePath": str(Path(settings.ready_dir) / f"{job.job_id}.mp4"),
        }
    if job.state == "failed":
        payload["error"] = {
            "code": job.error_code,
            "message": job.error_message,
            "retryable": job.error_retryable,
        }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="同步创建或执行一个抖音视频任务")
    parser.add_argument("share_text", nargs="?", help="抖音分享文案；省略时从标准输入读取")
    parser.add_argument("--job-id", help="处理 Redis 中已经存在的任务，不再创建新任务")
    args = parser.parse_args()

    try:
        store = RedisJobStore(settings)
        if args.job_id:
            if args.share_text:
                parser.error("使用 --job-id 时不能同时传入分享文案")
            job_id = args.job_id
        else:
            share_text = args.share_text if args.share_text is not None else sys.stdin.read()
            source_url = extract_share_url(
                share_text,
                settings.entry_hosts,
                settings.max_share_text_bytes,
            )
            job_id = store.create(source_url).job_id

        completed = DouyinJobProcessor(settings, store=store).process(job_id)
        print(json.dumps(_result(completed), ensure_ascii=False, indent=2))
        return 0 if completed.state == "ready" else 1
    except DouyinError as exc:
        print(
            json.dumps(
                {"error": {"code": exc.code, "message": exc.message}},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    except (JobStoreError, JobModelError, RedisSecretError) as exc:
        print(
            json.dumps(
                {"error": {"code": "JOB_STORE_ERROR", "message": str(exc)}},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
