"""
路由聚合

将所有 API 路由聚合到统一前缀 /api/v1 下
"""
from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.hosts import router as hosts_router
from app.api.deploy import router as deploy_router
from app.api.files import router as files_router
from app.api.configs import router as configs_router
from app.api.monitor import router as monitor_router

api_router = APIRouter(prefix="/api/v1")

# 注册子路由
api_router.include_router(auth_router)
api_router.include_router(hosts_router)
api_router.include_router(deploy_router)
api_router.include_router(files_router)
api_router.include_router(configs_router)
api_router.include_router(monitor_router)
