"""
安全模块：AES 加解密 + JWT 签发验证 + 认证依赖

- Fernet AES 加解密（封装 utils.crypto）
- JWT 签发（python-jose）
- get_current_user FastAPI 依赖注入
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.config.settings import get_settings
from app.utils.crypto import encrypt_value, decrypt_value


# OAuth2 scheme（tokenUrl 仅用于 Swagger 文档展示）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def encrypt(plaintext: str) -> str:
    """AES 加密"""
    return encrypt_value(plaintext)


def decrypt(ciphertext: str) -> str:
    """AES 解密"""
    return decrypt_value(ciphertext)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """签发 JWT Token"""
    settings = get_settings()
    to_encode = data.copy()

    expire = datetime.utcnow() + (
        expires_delta or timedelta(hours=settings.jwt_expire_hours)
    )
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT Token，返回 payload 或 None"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """FastAPI 依赖：获取当前登录用户

    返回用户信息字典:
    {
        "username": "admin",
        "role": "admin"
    }
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "username": username,
        "role": payload.get("role", "admin"),
    }


def authenticate_user(username: str, password: str) -> bool:
    """验证用户凭据（固定账号 admin/admin123）"""
    settings = get_settings()
    return username == settings.admin_username and password == settings.admin_password
