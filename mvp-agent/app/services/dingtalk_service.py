"""
钉钉机器人推送服务

- 从 sys_configs 读取 Webhook URL 和签名秘钥（解密）
- send_text: 发送文本消息
- send_markdown: 发送 Markdown 消息
- _build_url: 生成带签名的 URL（HMAC-SHA256 + Base64 + URL 编码）
- notify_deploy_result: 部署结果通知
- notify_daily_report: 每日监控日报推送
- 每次请求从 sys_configs 读取最新配置（配置热更新）
- 使用 httpx.AsyncClient 异步发送
"""
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from app.models.database import SessionLocal
from app.models.sys_config import get_config_value
from app.utils.logger import get_logger

logger = get_logger("dingtalk_service")


# ======================================================================
# 配置热更新：每次请求读取最新 sys_configs
# ======================================================================
def _load_dingtalk_config() -> Dict[str, str]:
    """从 sys_configs 读取最新钉钉配置（配置热更新）

    Returns:
        {
            "webhook": str,      # Webhook URL（解密后）
            "secret": str,       # 签名密钥（解密后）
            "enabled": str,      # 是否启用
        }
    """
    db = SessionLocal()
    try:
        webhook = get_config_value(db, "dingtalk_webhook", "")
        secret = get_config_value(db, "dingtalk_secret", "")
        enabled = get_config_value(db, "dingtalk_enabled", "false")
        return {
            "webhook": webhook,
            "secret": secret,
            "enabled": enabled,
        }
    finally:
        db.close()


def _is_enabled(config: Dict[str, str]) -> bool:
    """检查钉钉是否启用"""
    return config["enabled"].lower() in ("true", "1", "yes", "on")


# ======================================================================
# 签名生成
# ======================================================================
def _build_url(webhook: str, secret: str) -> str:
    """生成带签名的钉钉 Webhook URL

    钉钉加签算法：
    1. timestamp = 当前毫秒时间戳
    2. string_to_sign = f"{timestamp}\n{secret}"
    3. hmac_code = HMAC-SHA256(string_to_sign, secret)
    4. sign = Base64(hmac_code)
    5. URL 编码 sign
    6. 拼接到 webhook URL: &timestamp={timestamp}&sign={sign}

    Args:
        webhook: 基础 Webhook URL
        secret: 签名密钥

    Returns:
        带签名参数的完整 URL
    """
    if not secret:
        return webhook

    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()

    import base64
    sign = base64.b64encode(hmac_code).decode("utf-8")
    sign = urllib.parse.quote_plus(sign)

    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"


# ======================================================================
# 消息发送
# ======================================================================
async def _send(webhook: str, secret: str, payload: dict) -> Dict[str, Any]:
    """发送消息到钉钉 Webhook

    Args:
        webhook: Webhook URL
        secret: 签名密钥
        payload: 消息体

    Returns:
        {"success": bool, "message": str, "response": dict}
    """
    url = _build_url(webhook, secret)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("errcode") == 0:
                return {"success": True, "message": "发送成功", "response": result}
            else:
                errmsg = result.get("errmsg", "未知错误")
                logger.error(f"钉钉推送失败: errcode={result.get('errcode')}, errmsg={errmsg}")
                return {"success": False, "message": f"钉钉返回错误: {errmsg}", "response": result}

    except httpx.HTTPStatusError as e:
        logger.error(f"钉钉推送 HTTP 错误: {e.response.status_code} - {e}")
        return {"success": False, "message": f"HTTP 错误: {e.response.status_code}", "response": None}
    except httpx.RequestError as e:
        logger.error(f"钉钉推送网络错误: {e}")
        return {"success": False, "message": f"网络错误: {e}", "response": None}
    except Exception as e:
        logger.error(f"钉钉推送异常: {e}")
        return {"success": False, "message": f"发送异常: {e}", "response": None}


async def send_text(content: str, at_all: bool = False) -> Dict[str, Any]:
    """发送文本消息

    Args:
        content: 文本内容
        at_all: 是否 @所有人

    Returns:
        {"success": bool, "message": str}
    """
    config = _load_dingtalk_config()

    if not _is_enabled(config):
        logger.info("钉钉通知未启用，跳过发送")
        return {"success": False, "message": "钉钉通知未启用"}

    if not config["webhook"]:
        logger.warning("未配置钉钉 Webhook URL")
        return {"success": False, "message": "未配置钉钉 Webhook URL"}

    payload = {
        "msgtype": "text",
        "text": {"content": content},
        "at": {"isAtAll": at_all},
    }

    result = await _send(config["webhook"], config["secret"], payload)
    logger.info(f"钉钉文本消息发送: {'成功' if result['success'] else '失败'}")
    return result


async def send_markdown(title: str, text: str, at_all: bool = False) -> Dict[str, Any]:
    """发送 Markdown 消息

    Args:
        title: 标题（用于通知列表展示）
        text: Markdown 正文
        at_all: 是否 @所有人

    Returns:
        {"success": bool, "message": str}
    """
    config = _load_dingtalk_config()

    if not _is_enabled(config):
        logger.info("钉钉通知未启用，跳过发送")
        return {"success": False, "message": "钉钉通知未启用"}

    if not config["webhook"]:
        logger.warning("未配置钉钉 Webhook URL")
        return {"success": False, "message": "未配置钉钉 Webhook URL"}

    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"isAtAll": at_all},
    }

    result = await _send(config["webhook"], config["secret"], payload)
    logger.info(f"钉钉 Markdown 消息发送: {'成功' if result['success'] else '失败'}")
    return result


# ======================================================================
# 业务通知方法
# ======================================================================
async def notify_deploy_result(record: Any, host: Any = None) -> Dict[str, Any]:
    """部署结果通知

    Args:
        record: 部署记录对象（DeployRecord 或字典）
        host: 主机对象（Host 或字典），可空

    Returns:
        {"success": bool, "message": str}
    """
    config = _load_dingtalk_config()

    if not _is_enabled(config):
        return {"success": False, "message": "钉钉通知未启用"}

    # 提取部署记录信息
    if isinstance(record, dict):
        project_name = record.get("project_name", "未知")
        status = record.get("execute_status", "unknown")
        error_message = record.get("error_message", "")
        started_at = record.get("started_at")
        finished_at = record.get("finished_at")
        duration = record.get("duration")
        operator = record.get("operator", "admin")
    else:
        project_name = getattr(record, "project_name", "未知")
        status = getattr(record, "execute_status", "unknown")
        error_message = getattr(record, "error_message", "") or ""
        started_at = getattr(record, "started_at", None)
        finished_at = getattr(record, "finished_at", None)
        duration = getattr(record, "duration", None)
        operator = getattr(record, "operator", "admin")

    # 提取主机信息
    host_ip = "本地"
    host_name = "本地主机"
    if host:
        if isinstance(host, dict):
            host_ip = host.get("ip", "本地")
            host_name = host.get("name", "本地主机")
        else:
            host_ip = getattr(host, "ip", "本地")
            host_name = getattr(host, "name", "本地主机")

    # 状态映射
    status_map = {
        "success": ("部署成功", "success"),
        "failed": ("部署失败", "error"),
        "rolled_back": ("已回滚", "warning"),
        "cancelled": ("已取消", "warning"),
    }
    status_text, level = status_map.get(status, (f"状态: {status}", "info"))

    # 构建时间信息
    time_str = ""
    if finished_at:
        if isinstance(finished_at, str):
            time_str = finished_at
        else:
            time_str = finished_at.strftime("%Y-%m-%d %H:%M:%S")
    else:
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    duration_str = f"{duration:.1f}秒" if duration else "未知"

    # 构建 Markdown 消息
    title = f"[{status_text}] {project_name}"
    text = (
        f"### 部署结果通知\n\n"
        f"**项目名称**: {project_name}\n\n"
        f"**部署状态**: {status_text}\n\n"
        f"**目标主机**: {host_name} ({host_ip})\n\n"
        f"**操作人**: {operator}\n\n"
        f"**完成时间**: {time_str}\n\n"
        f"**耗时**: {duration_str}\n\n"
    )

    if error_message:
        # 截断过长的错误信息
        display_error = error_message[:500] if len(error_message) > 500 else error_message
        text += f"**错误信息**:\n\n> {display_error}\n\n"

    text += f"---\n*由 MVP AI部署助手自动推送*"

    return await send_markdown(title, text)


async def notify_daily_report(monitor_data: Any) -> Dict[str, Any]:
    """每日监控日报推送

    Args:
        monitor_data: 监控日报数据，可以是字典（含 ai_alert_summary）或列表

    Returns:
        {"success": bool, "message": str}
    """
    config = _load_dingtalk_config()

    if not _is_enabled(config):
        return {"success": False, "message": "钉钉通知未启用"}

    title = f"[监控日报] {datetime.now().strftime('%Y-%m-%d')}"

    if isinstance(monitor_data, dict):
        # 单条日报
        summary = monitor_data.get("ai_alert_summary", "暂无总结")
        host_name = monitor_data.get("host_name", "未知")
        cpu = monitor_data.get("cpu_usage", 0)
        mem = monitor_data.get("memory_usage", 0)
        disk = monitor_data.get("disk_usage", 0)
        text = (
            f"### 每日监控日报\n\n"
            f"**主机**: {host_name}\n\n"
            f"**CPU 使用率**: {cpu}%\n\n"
            f"**内存使用率**: {mem}%\n\n"
            f"**磁盘使用率**: {disk}%\n\n"
            f"---\n\n"
            f"**AI 总结**:\n\n{summary}\n\n"
        )
    elif isinstance(monitor_data, list):
        # 多条日报
        text = f"### 每日监控日报\n\n"
        for item in monitor_data:
            host_name = item.get("host_name", "未知")
            cpu = item.get("cpu_usage", 0)
            mem = item.get("memory_usage", 0)
            disk = item.get("disk_usage", 0)
            text += f"**{host_name}**: CPU={cpu}%, 内存={mem}%, 磁盘={disk}%\n\n"
        summary = monitor_data[0].get("ai_alert_summary", "") if monitor_data else ""
        if summary:
            text += f"---\n\n**AI 总结**:\n\n{summary}\n\n"
    else:
        text = "### 每日监控日报\n\n暂无监控数据。\n"

    text += f"---\n*由 MVP AI部署助手自动推送*"

    return await send_markdown(title, text)


# ======================================================================
# 测试推送
# ======================================================================
async def test_push(message: str = "钉钉推送测试") -> Dict[str, Any]:
    """测试钉钉推送

    Args:
        message: 测试消息内容

    Returns:
        {"success": bool, "message": str}
    """
    config = _load_dingtalk_config()

    if not config["webhook"]:
        return {"success": False, "message": "未配置钉钉 Webhook URL"}

    # 测试时不检查 enabled，直接发送
    title = "[测试] 钉钉推送验证"
    text = (
        f"### 钉钉推送测试\n\n"
        f"**消息**: {message}\n\n"
        f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"**状态**: 推送成功，钉钉机器人配置正常。\n\n"
        f"---\n*MVP AI部署助手*"
    )

    url = _build_url(config["webhook"], config["secret"])
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"isAtAll": False},
    }

    # 直接发送（绕过 enabled 检查）
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("errcode") == 0:
                return {"success": True, "message": "钉钉推送测试成功"}
            else:
                errmsg = result.get("errmsg", "未知错误")
                return {"success": False, "message": f"钉钉返回错误: {errmsg}"}

    except httpx.RequestError as e:
        return {"success": False, "message": f"网络错误: {e}"}
    except Exception as e:
        return {"success": False, "message": f"发送异常: {e}"}
