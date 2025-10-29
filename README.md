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

## 前端代码

https://github.com/mundane799699/danci-frontend

## jwt

https://jwt.io

## 参考

[fastapi 搭建平台实战教程二：快速实现用户注册和登录](https://www.cnblogs.com/zerotest/p/17802155.html)
