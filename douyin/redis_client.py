from pathlib import Path

from redis import Redis

from .config import DouyinSettings, settings


class RedisSecretError(RuntimeError):
    pass


def _load_password(filename: str | None) -> str | None:
    if not filename:
        return None
    try:
        raw = Path(filename).expanduser().read_bytes()
    except (OSError, ValueError) as exc:
        raise RedisSecretError("Redis password file is unavailable") from exc
    if not raw or len(raw) > 4096:
        raise RedisSecretError("Redis password file is invalid")
    try:
        password = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RedisSecretError("Redis password file is invalid") from exc
    if not password:
        raise RedisSecretError("Redis password file is invalid")
    return password


def create_redis_client(config: DouyinSettings = settings) -> Redis:
    password = _load_password(config.redis_password_file)
    authentication = {"password": password} if password is not None else {}
    return Redis.from_url(
        config.redis_url,
        decode_responses=True,
        socket_connect_timeout=config.redis_timeout_seconds,
        socket_timeout=config.redis_timeout_seconds,
        health_check_interval=30,
        **authentication,
    )
