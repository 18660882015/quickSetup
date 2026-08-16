"""
AI 助手 API

- POST /chat: 多轮运维对话（自动附带系统上下文）
- POST /optimize-config: JVM/Nginx/MySQL 配置优化建议
- POST /generate-script: AI 生成部署脚本
- POST /test: 测试 AI 连通性
"""
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.database import SessionLocal
from app.models.deploy_record import DeployRecord
from app.models.host import Host
from app.models.monitor_daily import MonitorDaily
from app.schemas.common import success
from app.services import ai_service
from app.utils.logger import get_logger

logger = get_logger("api.ai")

router = APIRouter(prefix="/ai", tags=["AI 助手"])


def _build_context() -> dict:
    """构建当前系统上下文（最近部署记录 + 主机列表 + 最新监控）"""
    db = SessionLocal()
    try:
        context = {}

        records = (
            db.query(DeployRecord)
            .order_by(DeployRecord.created_at.desc())
            .limit(3)
            .all()
        )
        if records:
            context["deploy_records"] = [
                {
                    "project_name": r.project_name,
                    "host_ip": getattr(r, "host_ip", ""),
                    "execute_status": r.execute_status,
                    "error_message": r.error_message,
                }
                for r in records
            ]

        hosts = db.query(Host).limit(5).all()
        if hosts:
            context["hosts"] = [
                {
                    "name": h.name,
                    "ip": h.ip,
                    "jdk_version": h.jdk_version,
                    "status": h.status,
                }
                for h in hosts
            ]

        latest = db.query(MonitorDaily).order_by(MonitorDaily.id.desc()).first()
        if latest:
            context["monitor_summary"] = (
                f"CPU={latest.cpu_usage}%, 内存={latest.memory_usage}%, 磁盘={latest.disk_usage}%, "
                f"nginx={latest.nginx_status}, tomcat={latest.tomcat_status}, "
                f"mysql={latest.mysql_status}, redis={latest.redis_status}"
            )
        return context
    finally:
        db.close()


class ChatMessage(BaseModel):
    role: str = Field(..., description="user / assistant")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="对话历史")
    with_context: bool = Field(True, description="是否附带系统上下文")


@router.post("/chat")
async def chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """AI 运维助手对话"""
    context = _build_context() if req.with_context else None
    result = await ai_service.chat(
        [{"role": m.role, "content": m.content} for m in req.messages],
        context=context,
    )
    return success(data=result)


class OptimizeRequest(BaseModel):
    config_type: str = Field(..., description="配置类型: jvm / nginx / mysql")
    host_info: Optional[dict] = Field(None, description="主机信息")
    current_config: Optional[str] = Field(None, description="当前配置内容")


@router.post("/optimize-config")
async def optimize_config(req: OptimizeRequest, current_user: dict = Depends(get_current_user)):
    """AI 配置优化建议"""
    result = await ai_service.optimize_config(
        req.config_type, req.host_info, req.current_config
    )
    return success(data=result)


class GenerateScriptRequest(BaseModel):
    project_structure: str = Field(..., description="项目结构描述")
    target_type: str = Field("linux", description="目标类型: linux / windows")
    requirements: str = Field("", description="特殊要求")


@router.post("/generate-script")
async def generate_script(req: GenerateScriptRequest, current_user: dict = Depends(get_current_user)):
    """AI 生成部署脚本"""
    result = await ai_service.generate_deploy_script(
        req.project_structure, req.target_type, req.requirements
    )
    return success(data=result)


@router.post("/test")
async def test_ai(current_user: dict = Depends(get_current_user)):
    """测试 AI 连通性"""
    result = await ai_service.test_connection()
    return success(data=result)
