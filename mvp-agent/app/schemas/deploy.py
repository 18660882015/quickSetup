"""
部署相关 Pydantic 模型
"""
from datetime import datetime
from typing import Optional, List, Any, Dict

from pydantic import BaseModel, Field


class DeployPlanRequest(BaseModel):
    """部署计划请求"""
    host_id: Optional[int] = Field(default=None, description="主机ID（本地部署可空）")
    project_name: str = Field(..., description="项目名称")
    env_type: str = Field(default="prod", description="环境类型: dev/prod")
    jdk_version: str = Field(default="8", description="JDK版本")
    db_name: Optional[str] = Field(default=None, description="数据库名")
    execute_mode: str = Field(default="auto", description="执行模式: auto/step_by_step")
    is_local: bool = Field(default=False, description="是否本地部署")


class DeployStep(BaseModel):
    """部署步骤"""
    step: str = Field(description="步骤名")
    name: str = Field(description="步骤中文名")
    description: str = Field(default="", description="步骤描述")
    command: Optional[str] = Field(default=None, description="执行的命令")
    is_dangerous: bool = Field(default=False, description="是否危险操作")
    estimated_time: Optional[int] = Field(default=None, description="预估耗时(秒)")


class DeployPlanResponse(BaseModel):
    """部署计划响应"""
    project_name: str
    env_type: str
    jdk_version: str
    steps: List[DeployStep] = Field(default_factory=list)
    ai_suggestion: Optional[str] = Field(default=None, description="AI建议")
    warnings: List[str] = Field(default_factory=list)


class DeployExecuteRequest(BaseModel):
    """部署执行请求"""
    host_id: Optional[int] = Field(default=None, description="主机ID")
    project_name: str = Field(..., description="项目名称")
    env_type: str = Field(default="prod")
    jdk_version: str = Field(default="8")
    db_name: Optional[str] = Field(default=None)
    execute_mode: str = Field(default="auto")
    is_local: bool = Field(default=False)
    deploy_dir: Optional[str] = Field(default=None, description="部署目录")
    version: Optional[str] = Field(default=None, description="版本号")


class DeployRecordResponse(BaseModel):
    """部署记录响应"""
    id: int
    host_id: Optional[int] = None
    project_name: str
    env_type: str
    execute_status: str
    execute_mode: str
    jdk_version: Optional[str] = None
    db_name: Optional[str] = None
    log_path: Optional[str] = None
    backup_path: Optional[str] = None
    version: Optional[str] = None
    steps_detail: Optional[Any] = None
    logs: Optional[str] = None
    ai_suggestion: Optional[str] = None
    rollback_info: Optional[Any] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration: Optional[float] = None
    error_message: Optional[str] = None
    operator: Optional[str] = None
    can_rollback: bool = False
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
