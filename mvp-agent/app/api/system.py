"""
系统管理 API

- 数据库备份：手动备份/列表/恢复
- 配置导出/导入
- 数据清空
- 磁盘空间查询/清理
- 开机自启动（Windows 注册表）
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.models.database import get_db
from app.schemas.common import success
from app.services import backup_service
from app.utils.logger import get_logger

logger = get_logger("api.system")

router = APIRouter(prefix="/system", tags=["系统管理"])


# ======================================================================
# 数据库备份
# ======================================================================
@router.get("/db-backups")
def list_db_backups(current_user: dict = Depends(get_current_user)):
    """列出数据库备份"""
    backups = backup_service.list_db_backups()
    return success(data=backups)


@router.post("/db-backups")
def create_db_backup(current_user: dict = Depends(get_current_user)):
    """手动创建数据库备份"""
    result = backup_service.backup_database(reason="manual")
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return success(data=result)


class RestoreRequest(BaseModel):
    backup_path: str = Field(..., description="备份文件路径")


@router.post("/db-backups/restore")
def restore_db_backup(req: RestoreRequest, current_user: dict = Depends(get_current_user)):
    """从备份恢复数据库（恢复后需重启服务）"""
    result = backup_service.restore_database(req.backup_path)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return success(data=result)


# ======================================================================
# 配置导出/导入
# ======================================================================
@router.get("/configs/export")
def export_configs(current_user: dict = Depends(get_current_user)):
    """导出主机 + 系统配置（加密 JSON）"""
    result = backup_service.export_configs()
    return success(data=result)


class ImportRequest(BaseModel):
    encrypted_blob: str = Field(..., description="导出的加密内容")
    mode: str = Field("merge", description="导入模式: merge / overwrite")


@router.post("/configs/import")
def import_configs(req: ImportRequest, current_user: dict = Depends(get_current_user)):
    """导入配置"""
    if req.mode not in ("merge", "overwrite"):
        raise HTTPException(status_code=400, detail="mode 仅支持 merge / overwrite")
    result = backup_service.import_configs(req.encrypted_blob, req.mode)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return success(data=result)


# ======================================================================
# 数据清空
# ======================================================================
class ResetDataRequest(BaseModel):
    scope: str = Field("deploy_records", description="清空范围: deploy_records / monitor_data / all")


@router.post("/reset-data")
def reset_data(req: ResetDataRequest, current_user: dict = Depends(get_current_user)):
    """清空数据（部署记录 / 监控数据 / 全部）"""
    if req.scope not in ("deploy_records", "monitor_data", "all"):
        raise HTTPException(status_code=400, detail="scope 仅支持 deploy_records / monitor_data / all")
    result = backup_service.reset_data(req.scope)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return success(data=result)


# ======================================================================
# 磁盘管理
# ======================================================================
@router.get("/disk-usage")
def get_disk_usage(current_user: dict = Depends(get_current_user)):
    """磁盘空间占用统计"""
    return success(data=backup_service.get_disk_usage())


@router.post("/disk-cleanup")
def disk_cleanup(current_user: dict = Depends(get_current_user)):
    """手动执行磁盘清理"""
    result = backup_service.cleanup_disk()
    return success(data=result)


# ======================================================================
# 开机自启动（Windows 注册表）
# ======================================================================
_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "MVP_AI_Deploy_Assistant"


def _get_autostart_status() -> dict:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY) as key:
            winreg.QueryValueEx(key, _AUTOSTART_NAME)
            return {"enabled": True}
    except FileNotFoundError:
        return {"enabled": False}
    except ImportError:
        return {"enabled": False, "supported": False}
    except OSError:
        return {"enabled": False}


def _set_autostart(enabled: bool) -> dict:
    try:
        import winreg
    except ImportError:
        raise HTTPException(status_code=400, detail="当前系统不支持开机自启动（仅 Windows）")

    if enabled:
        import os
        project_root = os.path.dirname(os.path.abspath(__file__)) + "\\..\\..\\.."
        project_root = os.path.normpath(project_root)
        bat = os.path.join(project_root, "start.bat")
        if not os.path.exists(bat):
            raise HTTPException(status_code=404, detail=f"未找到启动脚本: {bat}")
        value = f'cmd /c "cd /d "{project_root}" && start "" /min "{bat}""'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY) as key:
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, value)
        logger.info(f"已注册开机自启动: {value}")
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY) as key:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            logger.info("已移除开机自启动")
        except FileNotFoundError:
            pass

    return _get_autostart_status()


@router.get("/autostart")
def get_autostart(current_user: dict = Depends(get_current_user)):
    """查询开机自启动状态"""
    return success(data=_get_autostart_status())


class AutostartRequest(BaseModel):
    enabled: bool


@router.post("/autostart")
def set_autostart(req: AutostartRequest, current_user: dict = Depends(get_current_user)):
    """设置/取消开机自启动"""
    result = _set_autostart(req.enabled)
    return success(data=result)
