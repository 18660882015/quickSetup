"""
进程守护服务

- 定时检查所有启用的守护项（本地 psutil / 远程 SSH）
- 服务停止时自动执行重启命令（最多 N 次）
- 重启成功/失败推送钉钉通知
"""
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

from app.models.database import SessionLocal, Base
from app.models.service_guard import ServiceGuard
from app.models.host import Host
from app.models.sys_config import get_config_value
from app.core.security import decrypt
from app.services.dingtalk_service import send_markdown
from app.utils.logger import get_logger

logger = get_logger("guard_service")

# 内置默认重启命令（本地 Windows / 远程 Linux）
DEFAULT_LOCAL_COMMANDS = {
    "nginx": r"tools\nginx\nginx.exe",
    "tomcat": r"tools\tomcat\bin\startup.bat",
    "mysql": "net start mysql",
    "redis": r"tools\redis\redis-server.exe",
}
DEFAULT_REMOTE_COMMANDS = {
    "nginx": "systemctl start nginx || nginx",
    "tomcat": "systemctl start tomcat || {TOMCAT_HOME}/bin/startup.sh",
    "mysql": "systemctl start mysqld",
    "redis": "systemctl start redis",
}


# ======================================================================
# 状态检查
# ======================================================================
def _check_local(service_name: str) -> bool:
    """检查本地服务进程是否运行"""
    import psutil

    patterns = {
        "nginx": ["nginx.exe"],
        "tomcat": ["tomcat", "java.exe"],
        "mysql": ["mysqld.exe"],
        "redis": ["redis-server.exe"],
    }
    keywords = patterns.get(service_name.lower())
    if not keywords:
        return False

    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
            if any(k in name for k in keywords):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _check_remote(ssh_conn, service_name: str) -> bool:
    """检查远程服务是否运行"""
    commands = {
        "nginx": "pgrep -x nginx || pgrep -f 'nginx: master'",
        "tomcat": "pgrep -f '.*tomcat.*java.*' || systemctl is-active tomcat 2>/dev/null | grep -q active",
        "mysql": "pgrep -x mysqld || systemctl is-active mysqld mysql 2>/dev/null | grep -q active",
        "redis": "pgrep -x redis-server || systemctl is-active redis 2>/dev/null | grep -q active",
    }
    cmd = commands.get(service_name.lower(), f"pgrep -f {service_name}")
    try:
        _, _, exit_code = ssh_conn.execute(cmd, timeout=10)
        return exit_code == 0
    except Exception as e:
        logger.error(f"远程服务检查失败 [{service_name}]: {e}")
        return False


# ======================================================================
# 服务重启
# ======================================================================
def _restart_local(guard: ServiceGuard) -> tuple:
    """执行本地重启命令"""
    cmd = guard.restart_command or DEFAULT_LOCAL_COMMANDS.get(guard.service_name.lower())
    if not cmd:
        return False, f"未配置重启命令，且 {guard.service_name} 无内置默认命令"

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return True, "重启命令执行成功"
        return False, f"退出码 {result.returncode}: {result.stderr[:200] or result.stdout[:200]}"
    except Exception as e:
        return False, f"执行异常: {e}"


def _restart_remote(ssh_conn, guard: ServiceGuard) -> tuple:
    """执行远程重启命令"""
    cmd = guard.restart_command or DEFAULT_REMOTE_COMMANDS.get(guard.service_name.lower())
    if not cmd:
        return False, f"未配置重启命令，且 {guard.service_name} 无内置默认命令"

    try:
        _, err, exit_code = ssh_conn.execute(cmd, timeout=60)
        if exit_code == 0:
            return True, "重启命令执行成功"
        return False, f"退出码 {exit_code}: {err[:200]}"
    except Exception as e:
        return False, f"执行异常: {e}"


# ======================================================================
# 通知
# ======================================================================
async def _notify_guard(guard: ServiceGuard, host_name: str, event: str, detail: str = ""):
    """推送守护事件通知"""
    icon = "✅" if event == "recovered" else "❌"
    title = f"{icon} [{guard.name}] " + ("服务已自动恢复" if event == "recovered" else "服务异常")
    text = (
        f"### {title}\n\n"
        f"**守护项**: {guard.name}\n\n"
        f"**服务**: {guard.service_name}\n\n"
        f"**主机**: {host_name}\n\n"
        f"**连续重启次数**: {guard.consecutive_restarts}\n\n"
        f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    if detail:
        text += f"**详情**:\n\n> {detail[:300]}\n\n"
    text += f"---\n*MVP AI部署助手进程守护*"
    try:
        await send_markdown(title, text)
    except Exception as e:
        logger.error(f"守护通知推送失败: {e}")


# ======================================================================
# 守护检查主流程
# ======================================================================
async def run_guard_check() -> Dict:
    """执行一轮守护检查（由 APScheduler 调用）

    Returns:
        {"total": int, "running": int, "restarted": int, "failed": int}
    """
    db = SessionLocal()
    stats = {"total": 0, "running": 0, "restarted": 0, "failed": 0}

    try:
        # 全局开关
        if get_config_value(db, "guard_enabled", "true").lower() not in ("true", "1", "yes", "on"):
            return stats

        guards: List[ServiceGuard] = db.query(ServiceGuard).filter(ServiceGuard.enabled == True).all()
        if not guards:
            return stats

        from app.core.ssh_client import ssh_pool

        for guard in guards:
            stats["total"] += 1
            host = None
            ssh_conn = None

            if guard.host_id:
                host = db.query(Host).filter(Host.id == guard.host_id).first()
                if not host:
                    guard.last_status = "host_missing"
                    guard.last_error = "目标主机不存在"
                    continue
                try:
                    ssh_conn = ssh_pool.get_connection(
                        host_id=host.id,
                        host_config={
                            "ip": host.ip,
                            "port": host.port,
                            "username": host.username,
                            "auth_type": host.auth_type,
                            "password": host.password,
                            "private_key": host.private_key,
                        },
                        decrypt_fn=decrypt,
                    )
                except Exception as e:
                    guard.last_status = "ssh_failed"
                    guard.last_error = f"SSH 连接失败: {e}"
                    stats["failed"] += 1
                    continue
                running = _check_remote(ssh_conn, guard.service_name)
                host_name = f"{host.name} ({host.ip})"
            else:
                running = _check_local(guard.service_name)
                host_name = "本地主机"

            guard.last_check_at = datetime.now()

            if running:
                guard.last_status = "running"
                # 恢复正常，重置计数
                if guard.consecutive_restarts > 0:
                    await _notify_guard(guard, host_name, "recovered")
                guard.consecutive_restarts = 0
                guard.last_error = None
                stats["running"] += 1
            else:
                guard.last_status = "stopped"
                max_restart = guard.max_restart or 3

                if guard.consecutive_restarts >= max_restart:
                    # 超过最大重启次数，不再尝试，推送告警
                    if guard.consecutive_restarts == max_restart:
                        await _notify_guard(
                            guard, host_name, "failed",
                            f"已连续重启 {guard.consecutive_restarts} 次仍失败，请手动检查",
                        )
                    stats["failed"] += 1
                    continue

                # 尝试重启
                if ssh_conn:
                    ok, msg = _restart_remote(ssh_conn, guard)
                else:
                    ok, msg = _restart_local(guard)

                guard.consecutive_restarts += 1
                guard.last_restart_at = datetime.now()
                guard.last_error = None if ok else msg

                if ok:
                    stats["restarted"] += 1
                    logger.info(f"守护项 [{guard.name}] 已执行重启（第 {guard.consecutive_restarts} 次）")
                else:
                    stats["failed"] += 1
                    logger.warning(f"守护项 [{guard.name}] 重启失败: {msg}")

        db.commit()
        return stats
    except Exception as e:
        db.rollback()
        logger.error(f"进程守护检查异常: {e}", exc_info=True)
        return stats
    finally:
        db.close()


def get_guard_status() -> List[Dict]:
    """获取所有守护项状态"""
    db = SessionLocal()
    try:
        result = []
        guards = db.query(ServiceGuard).order_by(ServiceGuard.id).all()
        for g in guards:
            host_name = "本地主机"
            if g.host_id:
                host = db.query(Host).filter(Host.id == g.host_id).first()
                if host:
                    host_name = f"{host.name} ({host.ip})"
            result.append({
                "id": g.id,
                "name": g.name,
                "host_id": g.host_id,
                "host_name": host_name,
                "service_name": g.service_name,
                "restart_command": g.restart_command,
                "enabled": g.enabled,
                "max_restart": g.max_restart,
                "consecutive_restarts": g.consecutive_restarts,
                "last_status": g.last_status,
                "last_check_at": g.last_check_at.strftime("%Y-%m-%d %H:%M:%S") if g.last_check_at else None,
                "last_restart_at": g.last_restart_at.strftime("%Y-%m-%d %H:%M:%S") if g.last_restart_at else None,
                "last_error": g.last_error,
            })
        return result
    finally:
        db.close()
