from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import router as user_router, scheduler_manager
import os

app = FastAPI(title="背单词API")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 包含用户路由
app.include_router(user_router, prefix="/danci", tags=["users"])

# 设置测试模式
test_mode = os.getenv("TEST_MODE", "true").lower() == "true"
scheduler_manager.test_mode = test_mode

@app.on_event("startup")
async def startup_event():
    scheduler_manager.start()
    scheduler_manager.schedule_all_users()

@app.on_event("shutdown")
async def shutdown_event():
    scheduler_manager.stop()

@app.get("/")
async def root():
    return {"message": "欢迎使用背单词API"} 