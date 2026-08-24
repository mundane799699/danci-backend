#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${DEPLOY_HOST:-root@118.25.22.240}"
REMOTE_APP_DIR="${DEPLOY_APP_DIR:-/home/danci/danci-backend}"
PRODUCTION_ENV="${DEPLOY_ENV_FILE:-${PROJECT_DIR}/.env.production}"
COOKIE_SOURCE="${DEPLOY_COOKIE_FILE:-${PROJECT_DIR}/douyin-cookie.txt}"
SERVICE_SOURCE="${PROJECT_DIR}/deploy/danci-backend.service"
WORKER_SERVICE_SOURCE="${PROJECT_DIR}/deploy/douyin-worker.service"
CLEANUP_SERVICE_SOURCE="${PROJECT_DIR}/deploy/douyin-cleanup.service"
CLEANUP_TIMER_SOURCE="${PROJECT_DIR}/deploy/douyin-cleanup.timer"
NGINX_SNIPPET_SOURCE="${PROJECT_DIR}/deploy/nginx/douyin-protected-videos.conf"
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
require_file "$CLEANUP_SERVICE_SOURCE"
require_file "$CLEANUP_TIMER_SOURCE"
require_file "$NGINX_SNIPPET_SOURCE"

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
remote_cleanup_service="/tmp/douyin-cleanup.service.$$"
remote_cleanup_timer="/tmp/douyin-cleanup.timer.$$"
remote_nginx_snippet="/tmp/douyin-protected-videos.conf.$$"

rsync -lp "$PRODUCTION_ENV" "${REMOTE_HOST}:${remote_env}"
rsync -lp "$COOKIE_SOURCE" "${REMOTE_HOST}:${remote_cookie}"
rsync -lp "$SERVICE_SOURCE" "${REMOTE_HOST}:${remote_service}"
rsync -lp "$WORKER_SERVICE_SOURCE" "${REMOTE_HOST}:${remote_worker_service}"
rsync -lp "$CLEANUP_SERVICE_SOURCE" "${REMOTE_HOST}:${remote_cleanup_service}"
rsync -lp "$CLEANUP_TIMER_SOURCE" "${REMOTE_HOST}:${remote_cleanup_timer}"
rsync -lp "$NGINX_SNIPPET_SOURCE" "${REMOTE_HOST}:${remote_nginx_snippet}"

printf '安装依赖并切换 systemd 服务...\n'
ssh "${SSH_OPTIONS[@]}" "$REMOTE_HOST" bash -s -- \
    "$REMOTE_APP_DIR" "$remote_env" "$remote_cookie" "$remote_service" "$remote_worker_service" \
    "$remote_cleanup_service" "$remote_cleanup_timer" "$remote_nginx_snippet" <<'REMOTE_SCRIPT'
set -Eeuo pipefail

app_dir="$1"
staged_env="$2"
staged_cookie="$3"
staged_service="$4"
staged_worker_service="$5"
staged_cleanup_service="$6"
staged_cleanup_timer="$7"
staged_nginx_snippet="$8"
backend_service="danci-backend.service"
worker_service="douyin-worker.service"
cleanup_service="douyin-cleanup.service"
cleanup_timer="douyin-cleanup.timer"

cleanup() {
    rm -f \
        "$staged_env" \
        "$staged_cookie" \
        "$staged_service" \
        "$staged_worker_service" \
        "$staged_cleanup_service" \
        "$staged_cleanup_timer" \
        "$staged_nginx_snippet"
}
trap cleanup EXIT

test -x "$app_dir/venv/bin/python"
test -f "$app_dir/requirements.txt"

install -m 600 "$staged_env" "$app_dir/.env"
install -d -m 700 /etc/danci
install -m 600 "$staged_cookie" /etc/danci/douyin-cookie.txt
getent group www >/dev/null
install -d -m 750 -o root -g www \
    /data/remove-watermark \
    /data/remove-watermark/downloading \
    /data/remove-watermark/ready
chown root:www \
    /data/remove-watermark \
    /data/remove-watermark/downloading \
    /data/remove-watermark/ready
chmod 750 \
    /data/remove-watermark \
    /data/remove-watermark/downloading \
    /data/remove-watermark/ready
test -s /etc/danci/redis-password.txt
chmod 600 /etc/danci/redis-password.txt
install -m 644 "$staged_service" /etc/systemd/system/danci-backend.service
install -m 644 "$staged_worker_service" /etc/systemd/system/douyin-worker.service
install -m 644 "$staged_cleanup_service" /etc/systemd/system/douyin-cleanup.service
install -m 644 "$staged_cleanup_timer" /etc/systemd/system/douyin-cleanup.timer

"$app_dir/venv/bin/python" -m pip install --disable-pip-version-check -r "$app_dir/requirements.txt"

systemctl daemon-reload
systemctl stop "$backend_service" "$worker_service" "$cleanup_timer" 2>/dev/null || true

find /data/remove-watermark/downloading /data/remove-watermark/ready \
    -maxdepth 1 -type f -exec chown root:www -- {} +
find /data/remove-watermark/downloading /data/remove-watermark/ready \
    -maxdepth 1 -type f -exec chmod 640 -- {} +

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

if ! systemctl start "$cleanup_service"; then
    printf '清理服务首次运行失败。最近日志：\n' >&2
    journalctl -u "$cleanup_service" -n 80 --no-pager >&2
    exit 1
fi
systemctl enable --now "$cleanup_timer"

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

if ! systemctl is-active --quiet "$cleanup_timer"; then
    printf '清理定时器启动失败。最近日志：\n' >&2
    journalctl -u "$cleanup_timer" -n 80 --no-pager >&2
    exit 1
fi

nginx_vhost="/www/server/nginx/conf/vhost/danci.mundane.ink.conf"
nginx_snippet="/www/server/nginx/conf/snippets/douyin-protected-videos.conf"
nginx_vhost_backup="$(mktemp /tmp/danci-nginx-vhost.XXXXXX)"
nginx_snippet_backup="$(mktemp /tmp/douyin-nginx-snippet.XXXXXX)"
nginx_snippet_existed=0
cp -a "$nginx_vhost" "$nginx_vhost_backup"
if [[ -f "$nginx_snippet" ]]; then
    cp -a "$nginx_snippet" "$nginx_snippet_backup"
    nginx_snippet_existed=1
fi

restore_nginx() {
    cp -a "$nginx_vhost_backup" "$nginx_vhost"
    if ((nginx_snippet_existed)); then
        cp -a "$nginx_snippet_backup" "$nginx_snippet"
    else
        rm -f "$nginx_snippet"
    fi
    nginx -t >/dev/null 2>&1 && nginx -s reload >/dev/null 2>&1 || true
    rm -f "$nginx_vhost_backup" "$nginx_snippet_backup"
}

install -d -m 755 /www/server/nginx/conf/snippets
install -m 644 "$staged_nginx_snippet" "$nginx_snippet"
if ! "$app_dir/venv/bin/python" "$app_dir/scripts/configure_douyin_nginx.py"; then
    restore_nginx
    printf '写入 Nginx include 失败，已恢复原配置。\n' >&2
    exit 1
fi
if ! nginx -t; then
    restore_nginx
    printf 'Nginx 配置检查失败，已恢复原配置。\n' >&2
    exit 1
fi
if ! nginx -s reload; then
    restore_nginx
    printf 'Nginx reload 失败，已恢复原配置。\n' >&2
    exit 1
fi

sleep 1
protected_status="$(
    curl -ksS \
        --resolve danci.mundane.ink:443:127.0.0.1 \
        -o /dev/null \
        -w '%{http_code}' \
        https://danci.mundane.ink/_protected-videos/00000000-0000-4000-8000-000000000000.mp4 \
        || true
)"
if [[ "$protected_status" != "404" ]]; then
    restore_nginx
    printf 'Nginx internal 地址隔离检查失败（HTTP %s），已恢复原配置。\n' "$protected_status" >&2
    exit 1
fi
rm -f "$nginx_vhost_backup" "$nginx_snippet_backup"

systemctl --no-pager --full status "$backend_service" | sed -n '1,12p'
systemctl --no-pager --full status "$worker_service" | sed -n '1,12p'
systemctl --no-pager --full status "$cleanup_timer" | sed -n '1,12p'
printf 'Nginx internal 地址直访状态: HTTP %s\n' "$protected_status"
REMOTE_SCRIPT

printf '部署完成。查看日志：ssh %s journalctl -u danci-backend -u douyin-worker -u douyin-cleanup -f\n' "$REMOTE_HOST"
