"""Standalone FastAPI app for testing the resolver without the main app database."""

from fastapi import FastAPI

from .router import router

app = FastAPI(title="抖音链接解析 Spike")
app.include_router(router, prefix="/api/v1/douyin", tags=["douyin"])
