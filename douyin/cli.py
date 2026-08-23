import argparse
import json
import sys
import uuid

from .config import settings
from .errors import DouyinError
from .resolver import DouyinResolver
from .security import extract_share_url


def main() -> int:
    parser = argparse.ArgumentParser(description="解析抖音分享文案并输出原始视频候选 URL")
    parser.add_argument("share_text", nargs="?", help="抖音分享文案；省略时从标准输入读取")
    args = parser.parse_args()
    share_text = args.share_text if args.share_text is not None else sys.stdin.read()
    request_id = f"req_{uuid.uuid4().hex}"
    try:
        source_url = extract_share_url(share_text, settings.entry_hosts, settings.max_share_text_bytes)
        metadata = DouyinResolver(settings).resolve(source_url)
        result = {
            "requestId": request_id,
            "awemeId": metadata.aweme_id,
            "title": metadata.title,
            "authorName": metadata.author_name,
            "durationMs": metadata.duration_ms,
            "coverUrl": metadata.cover_url,
            "videoUrl": metadata.media_candidates[0].url,
            "candidates": [item.__dict__ for item in metadata.media_candidates],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except DouyinError as exc:
        print(
            json.dumps(
                {"requestId": request_id, "error": {"code": exc.code, "message": exc.message}},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
