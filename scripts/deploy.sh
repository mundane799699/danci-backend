#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${DEPLOY_HOST:-root@118.25.22.240}"
REMOTE_APP_DIR="${DEPLOY_APP_DIR:-/home/danci/danci-backend}"
PRODUCTION_ENV="${DEPLOY_ENV_FILE:-${PROJECT_DIR}/.env.production}"
COOKIE_SOURCE="${DEPLOY_COOKIE_FILE:-${PROJECT_DIR}/douyin-cookie.txt}"
SERVICE_SOURCE="${PROJECT_DIR}/deploy/danci-backend.service"
WORKER_SERVICE_SOURCE="${PROJECT_DIR}/deploy/douyin-worker.service"
SSH_OPTIONS=(-o BatchMode=yes -o ConnectTimeout=15)

require_file() {
    if [[ ! -f "$1" ]]; then
        printf '缺少部署文件: %s\n' "$1" >&2
        exit 1
    fi
}

require_file "$PRODUCTION_ENV"
require_file "$COOKIE_SOURCE"
require_file "$SERVICE_SOURCE"
require_file "$WORKER_SERVICE_SOURCE"

printf '检查 SSH 连接...\n'
ssh "${SSH_OPTIONS[@]}" "$REMOTE_HOST" true

printf '同步当前本地代码到 %s:%s ...\n' "$REMOTE_HOST" "$REMOTE_APP_DIR"
rsync -rlptz --no-owner --no-group \
    --exclude='.git/' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='uvicorn.log' \
    --exclude='.douyin-cookie' \
    --exclude='douyin-cookie.txt' \
    "${PROJECT_DIR}/" "${REMOTE_HOST}:${REMOTE_APP_DIR}/"

remote_env="/tmp/danci-backend.env.$$"
remote_cookie="/tmp/douyin-cookie.$$"
remote_service="/tmp/danci-backend.service.$$"
remote_worker_service="/tmp/douyin-worker.service.$$"

rsync -lp "$PRODUCTION_ENV" "${REMOTE_HOST}:${remote_env}"
rsync -lp "$COOKIE_SOURCE" "${REMOTE_HOST}:${remote_cookie}"
rsync -lp "$SERVICE_SOURCE" "${REMOTE_HOST}:${remote_service}"
rsync -lp "$WORKER_SERVICE_SOURCE" "${REMOTE_HOST}:${remote_worker_service}"

printf '安装依赖并切换 systemd 服务...\n'
ssh "${SSH_OPTIONS[@]}" "$REMOTE_HOST" bash -s -- \
    "$REMOTE_APP_DIR" "$remote_env" "$remote_cookie" "$remote_service" "$remote_worker_service" <<'REMOTE_SCRIPT'
set -Eeuo pipefail

app_dir="$1"
staged_env="$2"
staged_cookie="$3"
staged_service="$4"
staged_worker_service="$5"
backend_service="danci-backend.service"
worker_service="douyin-worker.service"

cleanup() {
    rm -f "$staged_env" "$staged_cookie" "$staged_service" "$staged_worker_service"
}
trap cleanup EXIT

test -x "$app_dir/venv/bin/python"
test -f "$app_dir/requirements.txt"

install -m 600 "$staged_env" "$app_dir/.env"
install -d -m 700 /etc/danci
install -m 600 "$staged_cookie" /etc/danci/douyin-cookie.txt
install -d -m 700 \
    /data/remove-watermark \
    /data/remove-watermark/downloading \
    /data/remove-watermark/ready
test -s /etc/danci/redis-password.txt
chmod 600 /etc/danci/redis-password.txt
install -m 644 "$staged_service" /etc/systemd/system/danci-backend.service
install -m 644 "$staged_worker_service" /etc/systemd/system/douyin-worker.service

"$app_dir/venv/bin/python" -m pip install --disable-pip-version-check -r "$app_dir/requirements.txt"

systemctl daemon-reload
systemctl stop "$backend_service" "$worker_service" 2>/dev/null || true

mapfile -t legacy_pids < <(
    pgrep -f "$app_dir/venv/bin/uvicorn main:app" || true
)
if ((${#legacy_pids[@]})); then
    kill -TERM "${legacy_pids[@]}"
    for _ in {1..20}; do
        alive=()
        for pid in "${legacy_pids[@]}"; do
            kill -0 "$pid" 2>/dev/null && alive+=("$pid")
        done
        ((${#alive[@]} == 0)) && break
        sleep 0.5
    done
    for pid in "${legacy_pids[@]}"; do
        kill -0 "$pid" 2>/dev/null && kill -KILL "$pid"
    done
fi

systemctl enable --now "$worker_service"
systemctl enable --now "$backend_service"

healthy=0
for _ in {1..30}; do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/ >/dev/null; then
        healthy=1
        break
    fi
    sleep 1
done

if ((healthy == 0)); then
    printf '服务健康检查失败。最近日志：\n' >&2
    journalctl -u "$backend_service" -n 80 --no-pager >&2
    exit 1
fi

if ! systemctl is-active --quiet "$worker_service"; then
    printf 'RQ Worker 启动失败。最近日志：\n' >&2
    journalctl -u "$worker_service" -n 80 --no-pager >&2
    exit 1
fi

systemctl --no-pager --full status "$backend_service" | sed -n '1,12p'
systemctl --no-pager --full status "$worker_service" | sed -n '1,12p'
REMOTE_SCRIPT

printf '部署完成。查看日志：ssh %s journalctl -u danci-backend -u douyin-worker -f\n' "$REMOTE_HOST"
