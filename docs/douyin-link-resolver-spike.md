# 抖音 Cookie HTTP 解析方案

## 1. 目标与边界

本阶段输入抖音公开单视频分享文案，返回作品元信息和最佳原始播放 URL。

解析过程只使用 HTTP、Cookie 和纯 Python 签名，不启动 Chrome，不下载或缓存视频，也不依赖 Redis、MySQL、Nginx。暂不支持图文、直播、私密或需要额外验证的作品。

“无水印”指选择详情接口返回的直接 CDN 播放候选，不使用历史上的 `playwm` 字符串替换。作者直接制作在画面里的文字或 Logo 不会被移除。播放 URL 是上游临时签名地址，可能过期，客户端不应长期保存。

## 2. 解析流程

1. 从最多 4 KB 的分享文案中提取第一个 HTTPS URL。
2. 只允许 `v.douyin.com`、`www.douyin.com`、`m.douyin.com` 和 `www.iesdouyin.com`。
3. 展开短链时限制跳转次数，并逐跳校验域名、端口和公网 IP，防止 SSRF。
4. 从最终 `/video/{id}` 或 `/share/video/{id}` 路径提取 `awemeId`。
5. 每次解析时重新读取 Cookie 文件，因此手工更新后不需要重启 FastAPI。
6. 使用 Cookie、匹配的 User-Agent 和 `a_bogus`/`X-Bogus` 签名请求公开作品详情接口。
7. 从 `aweme_detail.video.bit_rate` 等播放候选中排除明确水印地址和 H.265，优先选择最高分辨率、最高码率的 H.264 地址。
8. Cookie 文件缺失、内容为空或上游拒绝会话时返回 `COOKIE_EXPIRED`。

浏览器回退和 Playwright 依赖已删除，生产服务器不需要安装 Chrome。

## 3. 配置 Cookie

### 3.1 获取 Cookie

在你自己的电脑浏览器中登录抖音，然后：

1. 打开 `https://www.douyin.com/`。
2. 按 F12 打开开发者工具，进入 Network。
3. 刷新页面，选择任意发往 `www.douyin.com` 的请求。
4. 在 Request Headers 中复制完整的 `Cookie` 请求头值。

Cookie 等同于登录凭证，不要粘贴到聊天、Git、接口参数或应用日志中。

### 3.2 本地 Cookie 文件

项目默认读取根目录下的 `.douyin-cookie`：

```text
ttwid=...; msToken=...; odin_tt=...; passport_csrf_token=...; 其他Cookie=...
```

也支持把完整的 `Cookie:` 前缀一起粘贴，或者保存为 JSON 对象。文件已经加入 `.gitignore`。

```bash
chmod 600 .douyin-cookie
```

### 3.3 生产 Cookie 文件

推荐放在项目目录之外：

```dotenv
DOUYIN_COOKIE_FILE=/etc/danci/douyin-cookie.txt
DOUYIN_SKIP_DNS_SAFETY_CHECK=false
DOUYIN_API_RETRIES=2
```

```bash
sudo chown danci:danci /etc/danci/douyin-cookie.txt
sudo chmod 600 /etc/danci/douyin-cookie.txt
```

如果 Cookie 来源浏览器的 User-Agent 与默认值差异较大，可以通过 `DOUYIN_USER_AGENT` 配置同一浏览器的完整 User-Agent。

## 4. API

```http
POST /api/v1/douyin/resolve
Content-Type: application/json

{
  "shareText": "https://v.douyin.com/xxxx/"
}
```

成功响应：

```json
{
  "requestId": "req_xxx",
  "awemeId": "1234567890",
  "title": "视频标题",
  "authorName": "作者",
  "durationMs": 12000,
  "coverUrl": "https://...",
  "videoUrl": "https://...",
  "candidates": []
}
```

Cookie 无效响应：

```json
{
  "requestId": "req_xxx",
  "error": {
    "code": "COOKIE_EXPIRED",
    "message": "抖音 Cookie 缺失或已失效，请更新 Cookie 文件",
    "retryable": false
  }
}
```

## 5. 本地测试

安装依赖：

```bash
cd /Users/mundane/projects/python_projects/danci/danci-backend
source .venv/bin/activate
uv pip install -r requirements.txt
```

运行自动化测试：

```bash
python -m unittest discover -s tests -v
```

配置 `.douyin-cookie` 后直接测试真实链接：

```bash
python -m douyin.cli 'https://v.douyin.com/L3ssTZBcxrU/'
```

启动不加载项目数据库的独立 API：

```bash
uvicorn douyin.app:app --host 127.0.0.1 --port 8000 --reload
```

发送请求：

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/douyin/resolve \
  -H 'Content-Type: application/json' \
  -d '{"shareText":"https://v.douyin.com/L3ssTZBcxrU/"}'
```

如果本机 Clash/TUN 的 Fake-IP 导致 `UNSUPPORTED_HOST`，仅本地测试可以临时设置：

```bash
DOUYIN_SKIP_DNS_SAFETY_CHECK=true python -m douyin.cli \
  'https://v.douyin.com/L3ssTZBcxrU/'
```

生产环境必须保持 DNS 安全检查开启。

## 6. 错误码

| 错误码 | 含义 |
|---|---|
| `INVALID_SHARE_TEXT` | 没有识别到合法 HTTPS 链接或文本过长 |
| `UNSUPPORTED_HOST` | 非抖音域名、非标准端口或 DNS 指向非公网地址 |
| `COOKIE_EXPIRED` | Cookie 文件缺失、无法解析或被上游拒绝，需要人工更新 |
| `UNSUPPORTED_IMAGE_POST` | 当前是图文/图集作品 |
| `VIDEO_UNAVAILABLE` | 作品不可访问、已删除或没有视频候选 |
| `UPSTREAM_RATE_LIMITED` | 上游限流 |
| `UPSTREAM_CHANGED` | 上游响应结构或签名规则变化 |
| `JOB_TIMEOUT` | 展开短链或详情请求超时 |

## 7. 运行与安全注意事项

- Cookie 文件只保存在服务端，不通过客户端上传。
- 代码不会记录 Cookie、签名值或完整请求 URL。
- 更新 Cookie 文件使用原子替换更稳妥，例如先写临时文件、设置权限，再移动到目标位置。
- 本地 Cookie 移到腾讯云后可能因 IP、User-Agent 或风控策略被拒绝，此时会返回 `COOKIE_EXPIRED`。
- 不尝试绕过验证码、账号验证或访问非公开作品。
- 详情接口和签名规则属于上游非稳定实现，需要通过真实样本持续回归。

## 8. 实现参考与许可

Cookie 管理、详情参数和签名调用链参考 `jiji262/douyin-downloader`。项目内 `douyin/xbogus.py` 和 `douyin/abogus.py` 保留了各自上游的 Apache-2.0 许可与作者声明；没有引入参考项目的浏览器、下载器、数据库或批量任务代码。

## 9. 独立视频下载器

解析阶段之后已经增加独立的服务器视频下载器，当前仍不依赖 Redis、RQ 或 Nginx：

- `douyin/downloader.py`：按候选顺序流式下载、限制文件大小、校验媒体域名和逐跳重定向、检查 `Content-Type` 与 MP4 `ftyp` 签名，并从 `.part` 原子移动为 `.mp4`。
- `douyin/download_cli.py`：将解析和下载串联到指定测试目录，但不会输出完整上游媒体 URL。
- `tests/test_douyin_downloader.py`：覆盖正常下载、候选回退、伪装响应、大小超限、流中断、私网重定向、文件发布失败和路径安全。

主要配置：

```dotenv
DOUYIN_MEDIA_HOSTS=douyinvod.com
DOUYIN_MAX_MEDIA_BYTES=209715200
DOUYIN_MEDIA_TIMEOUT_SECONDS=60
DOUYIN_MEDIA_CHUNK_BYTES=65536
DOUYIN_DOWNLOADING_DIR=/data/remove-watermark/downloading
DOUYIN_READY_DIR=/data/remove-watermark/ready
```

默认媒体白名单保持保守，只包含 `douyinvod.com`。真实回归样本如果出现其他字节系 CDN 主机，应先确认域名归属，再通过 `DOUYIN_MEDIA_HOSTS` 显式加入后缀，不要临时放开为任意 HTTPS 主机。

配置 Cookie 后，可以将真实视频下载到一个明确的测试目录：

```bash
.venv/bin/python -m douyin.download_cli \
  'https://v.douyin.com/xxxx/' \
  --output-root /tmp/remove-watermark-download-test
```

成功结果只输出 `jobId`、作品元信息、文件字节数、候选序号和本地路径。当前已经用同一条真实样本分别完成本机和生产服务器下载：两端均生成 2,492,850 字节的有效 MP4，且原子发布后没有残留 `.part`；本机 `ffprobe` 检测时长约 10.93 秒。生产服务器磁盘使用率为 35%，下载后 FastAPI 服务保持健康。2026-08-24 经开发者确认，不再补充其余真实样本，将当前结果作为步骤 1 验收基线并进入 Redis 任务阶段。

## 10. Redis 任务模型

Redis 阶段已经完成独立的任务模型和存储层，尚未接入 RQ 和任务 API：

- `douyin/jobs.py`：定义 `queued -> resolving -> downloading -> ready`、失败和过期状态，集中校验 UUID、进度、时间戳和状态跳转。
- `douyin/job_store.py`：使用 Redis Hash 保存任务，通过 `WATCH/MULTI` 防止并发覆盖；更新 Hash 时保留原 TTL。
- `douyin/redis_client.py`：统一创建短超时 Redis 客户端，并支持从受限文件读取生产密码。
- `tests/test_douyin_jobs.py`：覆盖纯模型、真实 Redis、TTL、过期、重复任务、连接失败和密码文件。

配置：

```dotenv
DOUYIN_REDIS_URL=redis://127.0.0.1:6379/0
DOUYIN_REDIS_TIMEOUT_SECONDS=2
DOUYIN_REDIS_PASSWORD_FILE=/etc/danci/redis-password.txt
DOUYIN_JOB_TTL_SECONDS=7200
DOUYIN_JOB_KEY_PREFIX=remove_watermark:job
```

本地 Redis 没有密码时不设置 `DOUYIN_REDIS_PASSWORD_FILE`。生产 Redis 密码只保存在 `/etc/danci/redis-password.txt`，权限为 `0600`；代码、`.env.production`、日志和 Redis URL 都不包含密码。

Redis key 格式为：

```text
remove_watermark:job:{UUIDv4}
```

任务创建时一次性设置 TTL，后续状态和进度更新只修改 Hash，不刷新两小时生命周期。任务过期后 `get()` 返回不存在，业务 API 将在后续步骤映射为 `JOB_NOT_FOUND`。
