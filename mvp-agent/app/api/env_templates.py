"""
多环境配置模板 API

- GET /env-templates: 模板列表（内置 + 自定义）
- GET /env-templates/{name}: 模板详情
- POST /env-templates: 保存自定义模板（同名覆盖）
- DELETE /env-templates/{name}: 删除自定义模板
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict

from app.core.security import get_current_user
from app.schemas.common import success
from app.services import env_template
from app.utils.logger import get_logger

logger = get_logger("api.env_templates")

router = APIRouter(prefix="/env-templates", tags=["环境模板"])


@router.get("", response_model=None, summary="模板列表")
def list_templates(current_user: dict = Depends(get_current_user)):
    return success(data=env_template.get_all_templates())


@router.get("/{name}", summary="模板详情")
def get_template_detail(name: str, current_user: dict = Depends(get_current_user)):
    tpl = env_template.get_template(name)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"环境模板不存在: {name}")
    return success(data=tpl)


class EnvTemplateRequest(BaseModel):
    name: str = Field(..., description="模板名（字母/数字/-/_）")
    label: Optional[str] = Field(default=None, description="显示名")
    description: Optional[str] = Field(default=None, description="说明")
    jvm_args: Optional[str] = Field(default=None, description="JVM 参数")
    log_level: Optional[str] = Field(default=None, description="日志级别")
    nginx: Optional[Dict] = Field(default=None, description="Nginx 参数")
    mysql: Optional[Dict] = Field(default=None, description="MySQL 参数")


@router.post("", summary="保存自定义模板")
def save_template(req: EnvTemplateRequest, current_user: dict = Depends(get_current_user)):
    try:
        saved = env_template.save_template(req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return success(data=saved, msg="模板已保存")


@router.delete("/{name}", summary="删除自定义模板")
def delete_template(name: str, current_user: dict = Depends(get_current_user)):
    try:
        removed = env_template.delete_template(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not removed:
        raise HTTPException(status_code=404, detail=f"自定义模板不存在: {name}")
    return success(msg="模板已删除")
