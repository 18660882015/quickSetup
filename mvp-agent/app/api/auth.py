"""
认证 API：登录、获取当前用户
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import (
    authenticate_user,
    create_access_token,
    get_current_user,
)
from app.schemas.common import ApiResponse, success, error

router = APIRouter(prefix="/auth", tags=["认证"])


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str = "admin"


@router.post("/login", response_model=ApiResponse, summary="用户登录")
def login(request: LoginRequest):
    """用户登录，验证 admin/admin123 后签发 JWT"""
    if not authenticate_user(request.username, request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    token = create_access_token(
        data={"sub": request.username, "role": "admin"}
    )

    login_data = LoginResponse(
        access_token=token,
        token_type="bearer",
        username=request.username,
        role="admin",
    )

    return success(data=login_data.model_dump())


@router.get("/me", response_model=ApiResponse, summary="获取当前用户信息")
def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return success(data=current_user)
