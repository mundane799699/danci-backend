import argparse
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path

from .config import settings
from .downloader import DouyinVideoDownloader
from .errors import DouyinError
from .resolver import DouyinResolver
from .security import extract_share_url


def main() -> int:
    parser = argparse.ArgumentParser(description="解析抖音分享文案并将视频下载到测试目录")
    parser.add_argument("share_text", nargs="?", help="抖音分享文案；省略时从标准输入读取")
    parser.add_argument(
        "--output-root",
        required=True,
        help="测试输出根目录；将在其中创建 downloading 和 ready 子目录",
    )
    args = parser.parse_args()

    share_text = args.share_text if args.share_text is not None else sys.stdin.read()
    output_root = Path(args.output_root).expanduser().resolve()
    config = replace(
        settings,
        downloading_dir=str(output_root / "downloading"),
        ready_dir=str(output_root / "ready"),
    )
    job_id = str(uuid.uuid4())

    try:
        source_url = extract_share_url(
            share_text,
            config.entry_hosts,
            config.max_share_text_bytes,
        )
        metadata = DouyinResolver(config).resolve(source_url)
        result = DouyinVideoDownloader(config).download(job_id, metadata.media_candidates)
        print(
            json.dumps(
                {
                    "jobId": result.job_id,
                    "awemeId": metadata.aweme_id,
                    "title": metadata.title,
                    "authorName": metadata.author_name,
                    "bytes": result.bytes_written,
                    "filePath": str(result.file_path),
                    "candidateIndex": result.candidate_index,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except DouyinError as exc:
        print(
            json.dumps(
                {"jobId": job_id, "error": {"code": exc.code, "message": exc.message}},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"jobId": job_id, "error": {"code": "LOCAL_IO_ERROR", "message": str(exc)}},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
