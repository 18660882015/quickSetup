"""
系统配置 API：获取、更新、测试 AI、测试钉钉

P2 实现：
- GET /: 获取所有配置（加密字段返回 **** 掩码）
- PUT /{key}: 更新配置（如果是加密字段，先 AES 加密后存储）
- POST /test-ai: 创建临时 AI 客户端，发送简单测试消息验证连通性
- POST /test-dingtalk: 创建临时钉钉客户端，发送测试消息验证推送
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.models.database import get_db
from app.models.sys_config import SysConfig, get_config_value, set_config_value
from app.schemas.common import ApiResponse, success
from app.schemas.config import (
    ConfigUpdate,
    ConfigResponse,
    TestAIRequest,
    TestAIResponse,
    TestDingTalkRequest,
    TestDingTalkResponse,
)
from app.utils.crypto import encrypt_value
from app.utils.logger import get_logger

logger = get_logger("api.configs")

router = APIRouter(prefix="/configs", tags=["系统配置"])


def _mask_if_encrypted(config: SysConfig) -> dict:
    """如果配置是加密的，返回掩码"""
    data = {
        "id": config.id,
        "config_key": config.config_key,
        "config_value": config.config_value,
        "is_encrypted": config.is_encrypted,
        "description": config.description,
        "updated_at": config.updated_at,
    }
    if config.is_encrypted and config.config_value:
        data["config_value"] = "****"
    return data


@router.get("", response_model=ApiResponse, summary="获取所有系统配置")
def list_configs(
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """获取所有系统配置（加密字段返回掩码 ****）"""
    configs = db.query(SysConfig).order_by(SysConfig.config_key).all()
    result = [_mask_if_encrypted(c) for c in configs]
    return success(data=result)


@router.put("/{config_key}", response_model=ApiResponse, summary="更新指定配置")
def update_config(
    config_key: str,
    config_update: ConfigUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """更新指定配置

    - 如果 is_encrypted=True，值将 AES 加密后存储
    - 配置热更新：AI/DingTalk 服务实时读取最新配置
    """
    config = db.query(SysConfig).filter(SysConfig.config_key == config_key).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"配置项不存在: {config_key}")

    # 加密存储
    if config_update.is_encrypted and config_update.config_value:
        config.config_value = encrypt_value(config_update.config_value)
    else:
        config.config_value = config_update.config_value

    config.is_encrypted = config_update.is_encrypted
    db.commit()
    db.refresh(config)

    logger.info(f"更新配置: {config_key}")

    return success(
        data=_mask_if_encrypted(config),
        msg="配置更新成功",
    )


@router.post("/test-ai", response_model=ApiResponse, summary="测试 AI 接口连通性")
async def test_ai(
    request: TestAIRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """测试 DeepSeek AI 接口连通性

    P2 实现：
    - 从 sys_configs 读取最新 API Key 和模型配置
    - 创建临时 AI 客户端发送简单测试消息
    - 验证 DeepSeek API 是否可用
    """
    from app.services.ai_service import test_connection

    # 检查是否已配置 API Key
    api_key = get_config_value(db, "deepseek_api_key", "")
    if not api_key:
        result = TestAIResponse(
            success=False,
            message="未配置 DeepSeek API Key，请先在系统配置中设置",
        )
        return success(data=result.model_dump())

    # 调用 AI 服务测试连通性
    try:
        result = await test_connection(request.message)
        return success(
            data=TestAIResponse(
                success=result["success"],
                message=result["message"],
                reply=result.get("reply"),
            ).model_dump()
        )
    except Exception as e:
        logger.error(f"AI 测试异常: {e}")
        return success(
            data=TestAIResponse(
                success=False,
                message=f"AI 测试异常: {e}",
            ).model_dump()
        )


@router.post("/test-dingtalk", response_model=ApiResponse, summary="测试钉钉推送")
async def test_dingtalk(
    request: TestDingTalkRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """测试钉钉机器人推送

    P2 实现：
    - 从 sys_configs 读取最新 Webhook URL 和签名密钥
    - 创建临时钉钉客户端发送测试消息
    - 验证钉钉机器人是否可用
    """
    from app.services.dingtalk_service import test_push

    # 检查是否已配置 Webhook
    webhook = get_config_value(db, "dingtalk_webhook", "")
    if not webhook:
        result = TestDingTalkResponse(
            success=False,
            message="未配置钉钉 Webhook URL，请先在系统配置中设置",
        )
        return success(data=result.model_dump())

    # 调用钉钉服务测试推送
    try:
        result = await test_push(request.message)
        return success(
            data=TestDingTalkResponse(
                success=result["success"],
                message=result["message"],
            ).model_dump()
        )
    except Exception as e:
        logger.error(f"钉钉测试异常: {e}")
        return success(
            data=TestDingTalkResponse(
                success=False,
                message=f"钉钉测试异常: {e}",
            ).model_dump()
        )
