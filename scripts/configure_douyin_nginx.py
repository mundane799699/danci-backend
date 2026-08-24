import os
import tempfile
from pathlib import Path


VHOST_PATH = Path("/www/server/nginx/conf/vhost/danci.mundane.ink.conf")
INCLUDE_PATH = "/www/server/nginx/conf/snippets/douyin-protected-videos.conf"
SERVER_NAME = "danci.mundane.ink"


def insert_server_include(
    source: str,
    *,
    server_name: str = SERVER_NAME,
    include_path: str = INCLUDE_PATH,
) -> str:
    include_directive = f"include {include_path};"
    if any(line.strip() == include_directive for line in source.splitlines()):
        return source

    lines = source.splitlines(keepends=True)
    matches: list[int] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "server {":
            index += 1
            continue

        depth = 0
        block_start = index
        block_end = None
        for block_index in range(index, len(lines)):
            content = lines[block_index].split("#", 1)[0]
            depth += content.count("{") - content.count("}")
            if depth == 0:
                block_end = block_index
                break
        if block_end is None:
            raise ValueError("Nginx server block is not balanced")

        expected_name = f"server_name {server_name};"
        if any(
            line.strip() == expected_name
            for line in lines[block_start : block_end + 1]
        ):
            matches.append(block_end)
        index = block_end + 1

    if len(matches) != 1:
        raise ValueError("expected exactly one matching Nginx server block")

    insertion = f"  {include_directive}\n"
    lines.insert(matches[0], insertion)
    return "".join(lines)


def configure() -> bool:
    source = VHOST_PATH.read_text(encoding="utf-8")
    updated = insert_server_include(source)
    if updated == source:
        return False

    file_stat = VHOST_PATH.stat()
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=VHOST_PATH.parent,
            prefix=f".{VHOST_PATH.name}.",
            delete=False,
        ) as target:
            temporary_name = target.name
            target.write(updated)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary_name, file_stat.st_mode & 0o777)
        os.chown(temporary_name, file_stat.st_uid, file_stat.st_gid)
        os.replace(temporary_name, VHOST_PATH)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return True


def main() -> None:
    changed = configure()
    print("Nginx vhost include installed" if changed else "Nginx vhost include already installed")


if __name__ == "__main__":
    main()
