"""
主机相关 Pydantic 模型
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class HostBase(BaseModel):
    """主机基础信息"""
    name: str = Field(..., max_length=100, description="主机名称")
    ip: str = Field(..., max_length=45, description="IP地址")
    port: int = Field(default=22, ge=1, le=65535, description="SSH端口")
    username: str = Field(default="root", max_length=50, description="SSH用户名")
    auth_type: str = Field(default="password", description="认证方式: password/key")
    jdk_version: Optional[str] = Field(default="8", description="JDK版本")
    deploy_dir: Optional[str] = Field(default=None, description="部署目录")
    backup_dir: Optional[str] = Field(default=None, description="备份目录")
    is_local: bool = Field(default=False, description="是否本地主机")

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, v):
        if v not in ("password", "key"):
            raise ValueError("auth_type 必须为 password 或 key")
        return v


class HostCreate(HostBase):
    """创建主机请求"""
    password: Optional[str] = Field(default=None, description="SSH密码（明文，存储时加密）")
    private_key: Optional[str] = Field(default=None, description="SSH私钥（明文，存储时加密）")


class HostUpdate(BaseModel):
    """更新主机请求"""
    name: Optional[str] = Field(default=None, max_length=100)
    ip: Optional[str] = Field(default=None, max_length=45)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = Field(default=None, max_length=50)
    auth_type: Optional[str] = Field(default=None)
    password: Optional[str] = Field(default=None, description="新密码（明文）")
    private_key: Optional[str] = Field(default=None, description="新私钥（明文）")
    jdk_version: Optional[str] = None
    deploy_dir: Optional[str] = None
    backup_dir: Optional[str] = None
    status: Optional[str] = None
    is_local: Optional[bool] = None
    os_info: Optional[str] = None
    cpu_info: Optional[str] = None
    memory_info: Optional[str] = None
    disk_info: Optional[str] = None

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, v):
        if v is not None and v not in ("password", "key"):
            raise ValueError("auth_type 必须为 password 或 key")
        return v


class HostResponse(BaseModel):
    """主机响应（不含密码）"""
    id: int
    name: str
    ip: str
    port: int
    username: str
    auth_type: str
    jdk_version: Optional[str] = None
    deploy_dir: Optional[str] = None
    backup_dir: Optional[str] = None
    status: str
    is_local: bool
    os_info: Optional[str] = None
    cpu_info: Optional[str] = None
    memory_info: Optional[str] = None
    disk_info: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class HostTestResult(BaseModel):
    """主机连接测试结果"""
    success: bool = Field(description="是否连接成功")
    message: str = Field(description="结果消息")
    os_info: Optional[str] = Field(default=None, description="操作系统信息")


class HostInspectResult(BaseModel):
    """主机参数信息采集结果"""
    success: bool = Field(description="是否采集成功")
    message: str = Field(description="结果消息")
    os_info: Optional[str] = None
    cpu_info: Optional[str] = None
    memory_info: Optional[str] = None
    disk_info: Optional[str] = None
