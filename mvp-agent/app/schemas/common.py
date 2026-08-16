"""
统一响应格式
"""
from typing import Any, Optional, Generic, TypeVar
from pydantic import BaseModel, Field


T = TypeVar("T")


class ApiResponse(BaseModel):
    """统一 API 响应格式

    code: 0=成功，非0=错误码
    msg: 消息
    data: 数据
    """
    code: int = Field(default=0, description="0=成功，非0=错误码")
    msg: str = Field(default="success", description="消息")
    data: Optional[Any] = Field(default=None, description="数据")


def success(data: Any = None, msg: str = "success") -> dict:
    """构造成功响应"""
    return {"code": 0, "msg": msg, "data": data}


def error(msg: str = "error", code: int = -1, data: Any = None) -> dict:
    """构造错误响应"""
    return {"code": code, "msg": msg, "data": data}


class PageResponse(BaseModel):
    """分页响应"""
    code: int = 0
    msg: str = "success"
    data: Any = None
    total: int = 0
    page: int = 1
    page_size: int = 20
