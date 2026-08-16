"""
系统配置相关 Pydantic 模型
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ConfigUpdate(BaseModel):
    """配置更新请求"""
    config_value: str = Field(..., description="配置值")
    is_encrypted: bool = Field(default=False, description="是否加密存储")


class ConfigResponse(BaseModel):
    """配置响应（加密字段返回掩码）"""
    id: int
    config_key: str
    config_value: str = Field(description="配置值（加密字段返回 ****）")
    is_encrypted: bool
    description: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TestAIRequest(BaseModel):
    """AI 测试请求"""
    message: str = Field(default="你好，请回复：AI 服务正常", description="测试消息")


class TestAIResponse(BaseModel):
    """AI 测试响应"""
    success: bool
    message: str
    reply: Optional[str] = None


class TestDingTalkRequest(BaseModel):
    """钉钉测试请求"""
    message: str = Field(default="钉钉推送测试", description="测试消息")


class TestDingTalkResponse(BaseModel):
    """钉钉测试响应"""
    success: bool
    message: str
