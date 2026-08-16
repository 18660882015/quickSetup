"""
AI 服务 - DeepSeek API 集成

- 使用 openai.AsyncOpenAI 客户端（兼容 DeepSeek API 格式）
- generate_deploy_plan: 生成结构化部署计划（JSON Mode）
- analyze_error: 分析部署错误给出修复建议
- generate_monitor_summary: 生成监控日报自然语言总结
- _fallback_plan: AI 不可用时返回预设默认计划
- 每次请求从 sys_configs 读取最新 api_key 和 model（配置热更新）
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.models.database import SessionLocal
from app.models.sys_config import get_config_value
from app.utils.logger import get_logger

logger = get_logger("ai_service")


# ======================================================================
# 配置热更新：每次请求读取最新 sys_configs
# ======================================================================
def _load_ai_config() -> Dict[str, str]:
    """从 sys_configs 读取最新 AI 配置（配置热更新）"""
    db = SessionLocal()
    try:
        api_key = get_config_value(db, "deepseek_api_key", "")
        base_url = get_config_value(db, "deepseek_base_url", "https://api.deepseek.com")
        model = get_config_value(db, "deepseek_model", "deepseek-chat")
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
        }
    finally:
        db.close()


def _create_client(config: Dict[str, str]) -> AsyncOpenAI:
    """创建 AsyncOpenAI 客户端"""
    return AsyncOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
    )


# ======================================================================
# 默认降级计划
# ======================================================================
def _fallback_plan(
    host_info: Optional[dict] = None,
    project_config: Optional[dict] = None,
) -> Dict[str, Any]:
    """AI 不可用时返回预设默认部署计划"""
    is_local = (host_info or {}).get("is_local", False)
    os_info = (host_info or {}).get("os_info", "")
    jdk_version = (project_config or {}).get("jdk_version", "8")
    env_type = (project_config or {}).get("env_type", "prod")
    db_name = (project_config or {}).get("db_name")

    steps = [
        {
            "step": "precheck",
            "name": "预检",
            "description": "检查端口占用、磁盘空间、已有服务状态",
            "command": "df -h && netstat -tlnp" if not is_local else "netstat -ano",
            "is_dangerous": False,
            "estimated_time": 5,
        },
        {
            "step": "backup",
            "name": "备份",
            "description": "备份当前版本文件和配置到备份目录",
            "command": "cp -r {deploy_dir} {backup_dir}" if not is_local else "xcopy /E /I",
            "is_dangerous": False,
            "estimated_time": 30,
        },
        {
            "step": "transfer",
            "name": "传输",
            "description": "传输部署包到目标目录",
            "command": "sftp upload" if not is_local else "copy",
            "is_dangerous": False,
            "estimated_time": 60,
        },
        {
            "step": "install",
            "name": "安装",
            "description": "拷贝/解压部署文件到部署目录",
            "command": "unzip -o frontend.zip -d html/" if not is_local else "tar -xf",
            "is_dangerous": False,
            "estimated_time": 30,
        },
    ]

    if db_name:
        steps.append({
            "step": "init_db",
            "name": "数据库初始化",
            "description": f"导入 SQL 到数据库: {db_name}",
            "command": f"mysql -u root {db_name} < init.sql",
            "is_dangerous": True,
            "estimated_time": 30,
        })

    steps.extend([
        {
            "step": "configure",
            "name": "配置",
            "description": "更新 Nginx/Tomcat 配置文件",
            "command": "nginx -t && systemctl reload nginx" if not is_local else "nginx -s reload",
            "is_dangerous": False,
            "estimated_time": 10,
        },
        {
            "step": "start_service",
            "name": "启动",
            "description": "启动 Nginx 和 Tomcat 服务",
            "command": "systemctl start nginx tomcat" if not is_local else "startup.bat",
            "is_dangerous": False,
            "estimated_time": 15,
        },
        {
            "step": "validate",
            "name": "验证",
            "description": "三重验证：进程存活、端口监听、HTTP 200 健康检查",
            "command": "curl -I http://localhost",
            "is_dangerous": False,
            "estimated_time": 10,
        },
        {
            "step": "cleanup",
            "name": "清理",
            "description": "清理临时文件和旧备份",
            "command": "rm -f /tmp/deploy_*" if not is_local else "del /Q temp\\*",
            "is_dangerous": False,
            "estimated_time": 5,
        },
    ])

    warnings = []
    if db_name:
        warnings.append(f"将导入 SQL 到数据库: {db_name}")

    return {
        "steps": steps,
        "ai_suggestion": (
            "AI 服务不可用，已使用默认部署计划。"
            f"环境: {env_type}, JDK: {jdk_version}, "
            f"目标: {'本地' if is_local else '远程'}主机"
        ),
        "warnings": warnings,
    }


# ======================================================================
# 核心方法
# ======================================================================
async def generate_deploy_plan(
    host_info: Optional[dict],
    project_config: dict,
) -> Dict[str, Any]:
    """生成结构化部署计划

    使用 DeepSeek JSON Mode（response_format={"type": "json_object"}）
    生成包含步骤列表、风险评估、建议的部署计划。

    Args:
        host_info: 主机信息字典（含 ip, os_info, jdk_version, is_local 等）
        project_config: 项目配置字典（含 project_name, env_type, jdk_version 等）

    Returns:
        {
            "steps": [...],
            "ai_suggestion": "...",
            "warnings": [...],
        }
    """
    config = _load_ai_config()

    if not config["api_key"]:
        logger.warning("未配置 DeepSeek API Key，使用降级计划")
        return _fallback_plan(host_info, project_config)

    # 构建提示词
    is_local = (host_info or {}).get("is_local", False)
    os_info = (host_info or {}).get("os_info", "未知")
    host_ip = (host_info or {}).get("ip", "127.0.0.1")
    host_jdk = (host_info or {}).get("jdk_version", "8")
    deploy_dir = (host_info or {}).get("deploy_dir", "/opt/deploy")

    project_name = project_config.get("project_name", "未知项目")
    env_type = project_config.get("env_type", "prod")
    jdk_version = project_config.get("jdk_version", host_jdk)
    db_name = project_config.get("db_name", "")
    project_files = project_config.get("files", [])

    system_prompt = (
        "你是一位资深的 DevOps 部署专家，擅长根据主机环境和项目配置生成结构化的部署计划。"
        "请根据提供的信息生成一份详细的部署计划，包含部署步骤、风险评估和操作建议。"
        "部署步骤序列为：预检 -> 备份 -> 传输 -> 安装 -> [数据库初始化] -> 配置 -> 启动 -> 验证 -> 清理。"
        "你必须以 JSON 格式返回结果。"
    )

    user_prompt = (
        f"请为以下部署任务生成结构化部署计划：\n\n"
        f"## 主机信息\n"
        f"- 部署模式: {'本地 Windows 部署' if is_local else '远程 Linux SSH 部署'}\n"
        f"- 主机 IP: {host_ip}\n"
        f"- 操作系统: {os_info}\n"
        f"- JDK 版本: {jdk_version}\n"
        f"- 部署目录: {deploy_dir}\n\n"
        f"## 项目配置\n"
        f"- 项目名称: {project_name}\n"
        f"- 环境类型: {env_type}\n"
        f"- JDK 版本要求: {jdk_version}\n"
        f"- 数据库名: {db_name or '无'}\n"
        f"- 项目文件: {', '.join(str(f) for f in project_files) if project_files else '未知'}\n\n"
        f"## 已有服务状态\n"
        f"- Nginx: 可能已安装\n"
        f"- Tomcat: 可能已安装\n"
        f"- MySQL: {'需要导入数据库' if db_name else '无需数据库操作'}\n\n"
        f"## 要求\n"
        f"1. 返回 JSON 格式，包含 steps 数组（每个元素含 step, name, description, command, is_dangerous, estimated_time 字段）\n"
        f"2. 返回 ai_suggestion 字段：整体部署建议和注意事项\n"
        f"3. 返回 warnings 数组：风险提示\n"
        f"4. 危险操作（如数据库导入、删除文件）标记 is_dangerous=true\n"
        f"5. {'本地 Windows 部署使用 Windows 命令' if is_local else '远程 Linux 部署使用 Linux 命令'}\n"
        f"6. 根据 JDK 版本 ({jdk_version}) 适配命令\n\n"
        f"请返回如下 JSON 结构：\n"
        f'{{"steps": [{{"step": "precheck", "name": "预检", "description": "...", "command": "...", "is_dangerous": false, "estimated_time": 5}}], "ai_suggestion": "...", "warnings": ["..."]}}'
    )

    try:
        client = _create_client(config)
        response = await client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
        )

        content = response.choices[0].message.content
        result = json.loads(content)

        # 确保返回结构完整
        if "steps" not in result:
            result["steps"] = _fallback_plan(host_info, project_config)["steps"]
        if "ai_suggestion" not in result:
            result["ai_suggestion"] = "AI 已生成部署计划"
        if "warnings" not in result:
            result["warnings"] = []

        logger.info(f"AI 部署计划生成成功: {project_name}, 步骤数={len(result['steps'])}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"AI 返回 JSON 解析失败: {e}")
        return _fallback_plan(host_info, project_config)
    except Exception as e:
        logger.error(f"AI 服务调用失败，降级为默认计划: {e}")
        return _fallback_plan(host_info, project_config)


async def analyze_error(
    error_log: str,
    host_info: Optional[dict],
    project_config: Optional[dict],
) -> str:
    """分析部署错误，给出修复建议

    Args:
        error_log: 错误日志文本
        host_info: 主机信息字典
        project_config: 项目配置字典

    Returns:
        AI 分析的修复建议文本
    """
    config = _load_ai_config()

    if not config["api_key"]:
        logger.warning("未配置 DeepSeek API Key，无法分析错误")
        return "AI 服务不可用，无法分析错误。请检查错误日志手动排查。"

    is_local = (host_info or {}).get("is_local", False)
    os_info = (host_info or {}).get("os_info", "未知")
    host_ip = (host_info or {}).get("ip", "127.0.0.1")
    project_name = (project_config or {}).get("project_name", "未知")

    # 截断过长的错误日志
    if len(error_log) > 3000:
        error_log = error_log[-3000:]

    system_prompt = (
        "你是一位资深的 DevOps 部署排错专家。"
        "请根据提供的错误日志、主机信息和项目配置，分析错误原因并给出具体的修复建议。"
        "回答用中文，简洁明了，给出可操作的建议。"
    )

    user_prompt = (
        f"## 部署错误分析请求\n\n"
        f"### 主机信息\n"
        f"- 部署模式: {'本地 Windows' if is_local else '远程 Linux SSH'}\n"
        f"- 主机 IP: {host_ip}\n"
        f"- 操作系统: {os_info}\n\n"
        f"### 项目信息\n"
        f"- 项目名称: {project_name}\n\n"
        f"### 错误日志\n"
        f"```\n{error_log}\n```\n\n"
        f"请分析：\n"
        f"1. 错误的根本原因\n"
        f"2. 具体的修复步骤\n"
        f"3. 预防措施"
    )

    try:
        client = _create_client(config)
        response = await client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        suggestion = response.choices[0].message.content
        logger.info(f"AI 错误分析完成: {project_name}")
        return suggestion

    except Exception as e:
        logger.error(f"AI 错误分析失败: {e}")
        return f"AI 分析失败: {e}。请检查错误日志手动排查。"


async def generate_monitor_summary(monitor_data: List[Dict[str, Any]]) -> str:
    """生成监控日报自然语言总结

    Args:
        monitor_data: 监控数据列表，每个元素包含主机名、CPU、内存、磁盘、服务状态等

    Returns:
        AI 生成的自然语言监控总结
    """
    config = _load_ai_config()

    if not config["api_key"]:
        logger.warning("未配置 DeepSeek API Key，使用基础总结")
        return _basic_monitor_summary(monitor_data)

    if not monitor_data:
        return "暂无监控数据。"

    # 构建监控数据描述
    data_lines = []
    for item in monitor_data:
        host_name = item.get("host_name", item.get("host_id", "未知"))
        cpu = item.get("cpu_usage", 0)
        mem = item.get("memory_usage", 0)
        disk = item.get("disk_usage", 0)
        services = []
        for svc in ("nginx_status", "tomcat_status", "mysql_status", "redis_status"):
            status = item.get(svc, "unknown")
            svc_name = svc.replace("_status", "")
            services.append(f"{svc_name}={status}")
        data_lines.append(
            f"- {host_name}: CPU={cpu}%, 内存={mem}%, 磁盘={disk}%, "
            f"服务状态: {', '.join(services)}"
        )

    monitor_text = "\n".join(data_lines)

    system_prompt = (
        "你是一位系统运维监控专家。请根据提供的监控数据生成一份简洁的监控日报总结。"
        "用中文回答，重点突出异常项和需要关注的问题。"
    )

    user_prompt = (
        f"## 监控日报 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"### 监控数据\n{monitor_text}\n\n"
        f"### 阈值配置\n"
        f"- CPU 告警阈值: 80%\n"
        f"- 内存告警阈值: 80%\n"
        f"- 磁盘告警阈值: 90%\n\n"
        f"请生成监控总结，包括：\n"
        f"1. 整体状态概述\n"
        f"2. 异项告警\n"
        f"3. 建议操作"
    )

    try:
        client = _create_client(config)
        response = await client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=800,
        )

        summary = response.choices[0].message.content
        logger.info("AI 监控日报生成成功")
        return summary

    except Exception as e:
        logger.error(f"AI 监控日报生成失败: {e}")
        return _basic_monitor_summary(monitor_data)


def _basic_monitor_summary(monitor_data: List[Dict[str, Any]]) -> str:
    """基础监控总结（AI 不可用时的降级方案）"""
    if not monitor_data:
        return "暂无监控数据。"

    lines = [f"## 监控日报 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    alerts = []

    for item in monitor_data:
        host_name = item.get("host_name", item.get("host_id", "未知"))
        cpu = item.get("cpu_usage", 0) or 0
        mem = item.get("memory_usage", 0) or 0
        disk = item.get("disk_usage", 0) or 0

        lines.append(f"- {host_name}: CPU={cpu}%, 内存={mem}%, 磁盘={disk}%")

        if cpu > 80:
            alerts.append(f"  - {host_name} CPU 使用率过高: {cpu}%")
        if mem > 80:
            alerts.append(f"  - {host_name} 内存使用率过高: {mem}%")
        if disk > 90:
            alerts.append(f"  - {host_name} 磁盘使用率过高: {disk}%")

        # 服务状态检查
        for svc in ("nginx_status", "tomcat_status", "mysql_status", "redis_status"):
            status = item.get(svc, "unknown")
            if status == "stopped":
                svc_name = svc.replace("_status", "")
                alerts.append(f"  - {host_name} {svc_name} 服务已停止")

    if alerts:
        lines.append("\n### 告警项")
        lines.extend(alerts)
    else:
        lines.append("\n所有指标正常。")

    return "\n".join(lines)


# ======================================================================
# 测试连通性
# ======================================================================
async def test_connection(message: str = "你好，请回复：AI 服务正常") -> Dict[str, Any]:
    """测试 AI 接口连通性

    Args:
        message: 测试消息

    Returns:
        {"success": bool, "message": str, "reply": str}
    """
    config = _load_ai_config()

    if not config["api_key"]:
        return {
            "success": False,
            "message": "未配置 DeepSeek API Key",
            "reply": None,
        }

    try:
        client = _create_client(config)
        response = await client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "user", "content": message},
            ],
            max_tokens=100,
        )

        reply = response.choices[0].message.content
        return {
            "success": True,
            "message": "AI 接口连接正常",
            "reply": reply,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"AI 接口连接失败: {e}",
            "reply": None,
        }
