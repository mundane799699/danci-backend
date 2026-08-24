import json
import sys

from .cleanup import cleanup_expired_files
from .job_store import JobStoreError
from .redis_client import RedisSecretError


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit("cleanup command does not accept paths or arguments")
    try:
        result = cleanup_expired_files()
    except (JobStoreError, OSError, RedisSecretError, ValueError) as exc:
        raise SystemExit(f"cleanup failed: {type(exc).__name__}") from None

    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
    if result.file_failures or result.redis_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
