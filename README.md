## 环境搭建

使用conda

```bash
conda create -n danci python=3.10
conda activate danci
pip install -r requirements.txt
```

使用uv

```bash
uv python install 3.10
uv python pin 3.10
uv venv --python 3.10
source .venv/bin/activate
uv pip install -r requirements.txt
```

## 运行

```bash
uvicorn main:app --reload
```

## 抖音链接解析 Spike

当前阶段只解析公开单视频的元信息和最佳原始播放 URL，不下载或缓存视频，也不需要 Redis、MySQL 和 Nginx。
解析使用手工维护的抖音 Cookie 和纯 HTTP 请求，不启动 Chrome。先把浏览器中复制的完整 Cookie 请求头保存到项目根目录 `.douyin-cookie`（该文件不会提交到 Git）：

```bash
chmod 600 .douyin-cookie
```

最简单的测试方式：

```bash
python -m douyin.cli '这里粘贴完整抖音分享文案'
```

Cookie 缺失或失效时会返回 `COOKIE_EXPIRED`，替换 `.douyin-cookie` 后不需要重启服务。

也可以启动不依赖项目数据库的独立 API：

```bash
uvicorn douyin.app:app --host 127.0.0.1 --port 8000 --reload
```

完整方案、接口说明和测试步骤见 [docs/douyin-link-resolver-spike.md](docs/douyin-link-resolver-spike.md)。

## 部署运行

在本机项目根目录执行：

```bash
./scripts/deploy.sh
```

脚本会依次完成：同步当前本地代码、复制 `.env.production`、安全复制 Cookie、创建 `/data/remove-watermark/downloading` 和 `/data/remove-watermark/ready`、安装依赖、停止旧 Uvicorn、启动并启用 systemd，以及执行健康检查。部署脚本不运行自动化测试。服务器现有 Nginx 路由独立维护，部署脚本不会修改 Nginx 配置。

服务管理：

```bash
ssh root@118.25.22.240 'systemctl status danci-backend'
ssh root@118.25.22.240 'systemctl restart danci-backend'
ssh root@118.25.22.240 'journalctl -u danci-backend -f'
```

默认部署目标是 `root@118.25.22.240`。如需覆盖，可设置 `DEPLOY_HOST`、`DEPLOY_APP_DIR`、`DEPLOY_ENV_FILE` 或 `DEPLOY_COOKIE_FILE`。

## 前端代码

https://github.com/mundane799699/danci-frontend

## jwt

https://jwt.io

## 参考

[fastapi 搭建平台实战教程二：快速实现用户注册和登录](https://www.cnblogs.com/zerotest/p/17802155.html)
