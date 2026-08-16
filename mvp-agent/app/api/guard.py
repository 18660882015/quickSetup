"""
进程守护 API

- 守护项 CRUD
- 立即执行一轮守护检查
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.models.database import get_db
from app.models.service_guard import ServiceGuard
from app.models.host import Host
from app.schemas.common import success
from app.services.guard_service import get_guard_status, run_guard_check
from app.utils.logger import get_logger

logger = get_logger("api.guard")

router = APIRouter(prefix="/guard", tags=["进程守护"])


class GuardCreate(BaseModel):
    name: str = Field(..., description="守护项名称")
    host_id: Optional[int] = Field(None, description="目标主机ID（空=本地）")
    service_name: str = Field(..., description="服务名: nginx/tomcat/mysql/redis/自定义")
    restart_command: Optional[str] = Field(None, description="重启命令（空则用内置默认）")
    max_restart: int = Field(3, ge=1, le=10, description="最大连续重启次数")
    enabled: bool = Field(True, description="是否启用")


class GuardUpdate(BaseModel):
    name: Optional[str] = None
    host_id: Optional[int] = None
    service_name: Optional[str] = None
    restart_command: Optional[str] = None
    max_restart: Optional[int] = Field(None, ge=1, le=10)
    enabled: Optional[bool] = None


@router.get("")
def list_guards(current_user: dict = Depends(get_current_user)):
    """获取所有守护项"""
    return success(data=get_guard_status())


@router.post("")
def create_guard(req: GuardCreate, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """新增守护项"""
    if req.host_id:
        host = db.query(Host).filter(Host.id == req.host_id).first()
        if not host:
            raise HTTPException(status_code=404, detail=f"主机不存在: {req.host_id}")

    guard = ServiceGuard(
        name=req.name,
        host_id=req.host_id,
        service_name=req.service_name,
        restart_command=req.restart_command,
        max_restart=req.max_restart,
        enabled=req.enabled,
    )
    db.add(guard)
    db.commit()
    return success(data={"id": guard.id}, msg="守护项已创建")


@router.put("/{guard_id}")
def update_guard(guard_id: int, req: GuardUpdate, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """更新守护项"""
    guard = db.query(ServiceGuard).filter(ServiceGuard.id == guard_id).first()
    if not guard:
        raise HTTPException(status_code=404, detail=f"守护项不存在: {guard_id}")

    if req.name is not None:
        guard.name = req.name
    if req.host_id is not None:
        guard.host_id = req.host_id
    if req.service_name is not None:
        guard.service_name = req.service_name
    if req.restart_command is not None:
        guard.restart_command = req.restart_command
    if req.max_restart is not None:
        guard.max_restart = req.max_restart
    if req.enabled is not None:
        guard.enabled = req.enabled

    db.commit()
    return success(msg="守护项已更新")


@router.delete("/{guard_id}")
def delete_guard(guard_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除守护项"""
    guard = db.query(ServiceGuard).filter(ServiceGuard.id == guard_id).first()
    if not guard:
        raise HTTPException(status_code=404, detail=f"守护项不存在: {guard_id}")
    db.delete(guard)
    db.commit()
    return success(msg="守护项已删除")


@router.post("/reset/{guard_id}")
def reset_guard(guard_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """重置守护项的连续重启计数"""
    guard = db.query(ServiceGuard).filter(ServiceGuard.id == guard_id).first()
    if not guard:
        raise HTTPException(status_code=404, detail=f"守护项不存在: {guard_id}")
    guard.consecutive_restarts = 0
    guard.last_error = None
    db.commit()
    return success(msg="计数已重置")


@router.post("/check-now")
async def check_now(current_user: dict = Depends(get_current_user)):
    """立即执行一轮守护检查"""
    stats = await run_guard_check()
    return success(data=stats, msg=f"检查完成: 运行 {stats['running']}，已重启 {stats['restarted']}，异常 {stats['failed']}")
