"""
监控数据采集服务

- collect_host_metrics: 采集单台主机监控数据
  - 远程: SSH 执行 top -bn1(CPU)、free(内存)、df -h(磁盘)、systemctl status(服务状态)
  - 本地: psutil 库采集
- check_service_status: 检查 Nginx/Tomcat/MySQL/Redis 进程
- collect_all_hosts: 采集所有在线主机数据，存入 monitor_dailies 表
- generate_daily_report: 调用 AI 生成告警总结，推送钉钉日报
"""
import re
import subprocess
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.core.security import decrypt
from app.core.ssh_client import ssh_pool
from app.models.database import SessionLocal
from app.models.host import Host
from app.models.monitor_daily import MonitorDaily
from app.models.sys_config import get_config_value
from app.utils.logger import get_logger

logger = get_logger("monitor_service")


# ======================================================================
# 本地监控数据采集（使用 psutil）
# ======================================================================
def _collect_local_metrics() -> Dict[str, Any]:
    """使用 psutil 采集本地主机监控数据"""
    try:
        import psutil
    except ImportError:
        logger.warning("psutil 未安装，本地监控数据采集受限")
        return {
            "cpu_usage": 0,
            "memory_usage": 0,
            "disk_usage": 0,
        }

    # CPU 使用率
    cpu_usage = psutil.cpu_percent(interval=1)

    # 内存使用率
    mem = psutil.virtual_memory()
    memory_usage = mem.percent

    # 磁盘使用率（系统盘）
    disk_usage = 0
    try:
        disk = psutil.disk_usage("/")
        disk_usage = disk.percent
    except Exception:
        try:
            disk = psutil.disk_usage("C:")
            disk_usage = disk.percent
        except Exception:
            disk_usage = 0

    return {
        "cpu_usage": round(cpu_usage, 1),
        "memory_usage": round(memory_usage, 1),
        "disk_usage": round(disk_usage, 1),
    }


def _check_local_service(service: str) -> str:
    """检查本地服务状态

    Args:
        service: 服务名 (nginx/tomcat/mysql/redis)

    Returns:
        "running" / "stopped"
    """
    try:
        import psutil
    except ImportError:
        return "unknown"

    service_patterns = {
        "nginx": ["nginx"],
        "tomcat": ["tomcat", "catalina", "java"],
        "mysql": ["mysqld", "mysql"],
        "redis": ["redis-server", "redis"],
    }

    patterns = service_patterns.get(service, [service])
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            for pattern in patterns:
                if pattern in name or pattern in cmdline:
                    return "running"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return "stopped"


# ======================================================================
# 远程监控数据采集（通过 SSH）
# ======================================================================
def _collect_remote_metrics(ssh_conn) -> Dict[str, Any]:
    """通过 SSH 执行命令采集远程主机监控数据

    Args:
        ssh_conn: SSHConnection 实例

    Returns:
        {
            "cpu_usage": float,
            "memory_usage": float,
            "disk_usage": float,
        }
    """
    result = {
        "cpu_usage": 0,
        "memory_usage": 0,
        "disk_usage": 0,
    }

    try:
        # CPU 使用率: top -bn1 | grep "Cpu(s)"
        out, err, code = ssh_conn.execute("top -bn1 | grep 'Cpu(s)'", timeout=10)
        if code == 0 and out:
            # 解析: %Cpu(s):  5.0 us,  2.0 sy,  0.0 ni, 92.0 id,  1.0 wa, ...
            match = re.search(r"([\d.]+)\s*id", out)
            if match:
                idle = float(match.group(1))
                result["cpu_usage"] = round(100 - idle, 1)

    except Exception as e:
        logger.warning(f"远程 CPU 采集失败: {e}")

    try:
        # 内存使用率: free | grep Mem
        out, err, code = ssh_conn.execute("free | grep Mem", timeout=10)
        if code == 0 and out:
            # 解析: Mem:  16384000  8000000  2000000  100000  6000000  7000000
            parts = out.split()
            if len(parts) >= 3:
                total = float(parts[1])
                used = float(parts[2])
                if total > 0:
                    result["memory_usage"] = round((used / total) * 100, 1)

    except Exception as e:
        logger.warning(f"远程内存采集失败: {e}")

    try:
        # 磁盘使用率: df -h / | tail -1
        out, err, code = ssh_conn.execute("df -h / | tail -1", timeout=10)
        if code == 0 and out:
            # 解析: /dev/sda1  50G  30G  20G  60% /
            match = re.search(r"(\d+)%", out)
            if match:
                result["disk_usage"] = float(match.group(1))

    except Exception as e:
        logger.warning(f"远程磁盘采集失败: {e}")

    return result


def _check_remote_service(ssh_conn, service: str) -> str:
    """检查远程服务状态

    Args:
        ssh_conn: SSHConnection 实例
        service: 服务名 (nginx/tomcat/mysql/redis)

    Returns:
        "running" / "stopped"
    """
    # 服务对应的进程检查命令
    check_commands = {
        "nginx": "pgrep -x nginx || systemctl is-active --quiet nginx && echo running",
        "tomcat": "pgrep -f catalina || pgrep -f tomcat",
        "mysql": "pgrep -x mysqld || systemctl is-active --quiet mysqld && echo running",
        "redis": "pgrep -x redis-server || systemctl is-active --quiet redis && echo running",
    }

    cmd = check_commands.get(service, f"pgrep -f {service}")
    try:
        out, err, code = ssh_conn.execute(cmd, timeout=5)
        if code == 0 and out.strip():
            return "running"
        return "stopped"
    except Exception as e:
        logger.warning(f"远程服务状态检查失败: service={service}, error={e}")
        return "unknown"


# ======================================================================
# 统一采集接口
# ======================================================================
def collect_host_metrics(host: Any) -> Dict[str, Any]:
    """采集单台主机监控数据

    Args:
        host: Host 模型对象或字典

    Returns:
        {
            "host_id": int,
            "host_name": str,
            "cpu_usage": float,
            "memory_usage": float,
            "disk_usage": float,
            "nginx_status": str,
            "tomcat_status": str,
            "mysql_status": str,
            "redis_status": str,
        }
    """
    # 提取主机信息
    if isinstance(host, dict):
        host_id = host.get("id")
        host_name = host.get("name", "未知")
        is_local = host.get("is_local", False)
        ip = host.get("ip", "127.0.0.1")
        password = host.get("password")
        private_key = host.get("private_key")
        auth_type = host.get("auth_type", "password")
        port = host.get("port", 22)
        username = host.get("username", "root")
    else:
        host_id = host.id
        host_name = host.name
        is_local = host.is_local
        ip = host.ip
        password = host.password
        private_key = host.private_key
        auth_type = host.auth_type
        port = host.port
        username = host.username

    metrics: Dict[str, Any] = {
        "host_id": host_id,
        "host_name": host_name,
        "ip": ip,
        "cpu_usage": 0,
        "memory_usage": 0,
        "disk_usage": 0,
        "nginx_status": "unknown",
        "tomcat_status": "unknown",
        "mysql_status": "unknown",
        "redis_status": "unknown",
    }

    if is_local:
        # 本地采集
        local_metrics = _collect_local_metrics()
        metrics.update(local_metrics)

        # 检查本地服务状态
        for svc in ("nginx", "tomcat", "mysql", "redis"):
            metrics[f"{svc}_status"] = _check_local_service(svc)
    else:
        # 远程采集
        try:
            # 解密密码/私钥
            if password:
                password = decrypt(password)
            if private_key:
                private_key = decrypt(private_key)

            host_config = {
                "ip": ip,
                "port": port,
                "username": username,
                "password": password,
                "private_key": private_key,
                "auth_type": auth_type,
            }

            ssh_conn = ssh_pool.get_connection(host_id, host_config)

            # 采集资源指标
            remote_metrics = _collect_remote_metrics(ssh_conn)
            metrics.update(remote_metrics)

            # 检查服务状态
            for svc in ("nginx", "tomcat", "mysql", "redis"):
                metrics[f"{svc}_status"] = _check_remote_service(ssh_conn, svc)

        except Exception as e:
            logger.error(f"远程主机监控采集失败: host={host_name}({ip}), error={e}")

    return metrics


def check_service_status(host: Any, service: str) -> str:
    """检查指定主机上的服务状态

    Args:
        host: Host 模型对象或字典
        service: 服务名 (nginx/tomcat/mysql/redis)

    Returns:
        "running" / "stopped" / "unknown"
    """
    if isinstance(host, dict):
        is_local = host.get("is_local", False)
        host_id = host.get("id")
    else:
        is_local = host.is_local
        host_id = host.id

    if is_local:
        return _check_local_service(service)
    else:
        try:
            if isinstance(host, dict):
                password = host.get("password")
                private_key = host.get("private_key")
                auth_type = host.get("auth_type", "password")
                port = host.get("port", 22)
                username = host.get("username", "root")
                ip = host.get("ip")
            else:
                password = host.password
                private_key = host.private_key
                auth_type = host.auth_type
                port = host.port
                username = host.username
                ip = host.ip

            if password:
                password = decrypt(password)
            if private_key:
                private_key = decrypt(private_key)

            host_config = {
                "ip": ip,
                "port": port,
                "username": username,
                "password": password,
                "private_key": private_key,
                "auth_type": auth_type,
            }

            ssh_conn = ssh_pool.get_connection(host_id, host_config)
            return _check_remote_service(ssh_conn, service)

        except Exception as e:
            logger.error(f"服务状态检查失败: host_id={host_id}, service={service}, error={e}")
            return "unknown"


# ======================================================================
# 采集所有主机
# ======================================================================
def collect_all_hosts() -> List[Dict[str, Any]]:
    """采集所有主机监控数据，存入 monitor_dailies 表

    Returns:
        采集到的监控数据列表
    """
    db = SessionLocal()
    results: List[Dict[str, Any]] = []

    try:
        hosts = db.query(Host).all()
        today = date.today()

        for host in hosts:
            logger.info(f"采集主机监控数据: {host.name} ({host.ip})")

            metrics = collect_host_metrics(host)

            # 存入数据库
            monitor_record = MonitorDaily(
                host_id=host.id,
                check_date=today,
                tomcat_status=metrics.get("tomcat_status", "unknown"),
                nginx_status=metrics.get("nginx_status", "unknown"),
                mysql_status=metrics.get("mysql_status", "unknown"),
                redis_status=metrics.get("redis_status", "unknown"),
                cpu_usage=metrics.get("cpu_usage", 0),
                memory_usage=metrics.get("memory_usage", 0),
                disk_usage=metrics.get("disk_usage", 0),
                error_log_count=0,
                created_at=datetime.now(),
            )
            db.add(monitor_record)
            db.commit()
            db.refresh(monitor_record)

            metrics["record_id"] = monitor_record.id
            results.append(metrics)

            logger.info(
                f"主机 {host.name} 监控数据已保存: "
                f"CPU={metrics['cpu_usage']}%, "
                f"内存={metrics['memory_usage']}%, "
                f"磁盘={metrics['disk_usage']}%"
            )

    except Exception as e:
        logger.error(f"采集所有主机监控数据失败: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

    return results


# ======================================================================
# 生成每日报告
# ======================================================================
async def generate_daily_report() -> Dict[str, Any]:
    """生成每日监控报告

    1. 采集所有主机最新监控数据
    2. 调用 AI 生成告警总结
    3. 更新 monitor_dailies 表的 ai_alert_summary
    4. 推送钉钉日报

    Returns:
        {
            "summary": str,
            "monitor_data": list,
            "dingtalk_pushed": bool,
        }
    """
    from app.services.ai_service import generate_monitor_summary
    from app.services import dingtalk_service

    logger.info("开始生成每日监控报告...")

    # 1. 采集所有主机监控数据
    monitor_data = collect_all_hosts()

    if not monitor_data:
        logger.warning("无监控数据可生成报告")
        return {
            "summary": "暂无监控数据。",
            "monitor_data": [],
            "dingtalk_pushed": False,
        }

    # 2. 调用 AI 生成告警总结
    try:
        summary = await generate_monitor_summary(monitor_data)
    except Exception as e:
        logger.error(f"AI 生成监控总结失败: {e}")
        summary = "AI 总结生成失败，请查看原始监控数据。"

    # 3. 更新数据库中的 ai_alert_summary
    db = SessionLocal()
    try:
        today = date.today()
        for item in monitor_data:
            record_id = item.get("record_id")
            if record_id:
                record = db.query(MonitorDaily).filter(MonitorDaily.id == record_id).first()
                if record:
                    record.ai_alert_summary = summary
                    db.commit()
    except Exception as e:
        logger.error(f"更新监控报告 AI 总结失败: {e}")
    finally:
        db.close()

    # 4. 推送钉钉日报
    dingtalk_pushed = False
    try:
        push_result = await dingtalk_service.notify_daily_report(monitor_data)
        dingtalk_pushed = push_result.get("success", False)

        # 更新钉钉推送状态
        if dingtalk_pushed:
            db = SessionLocal()
            try:
                today = date.today()
                for item in monitor_data:
                    record_id = item.get("record_id")
                    if record_id:
                        record = db.query(MonitorDaily).filter(MonitorDaily.id == record_id).first()
                        if record:
                            record.dingtalk_pushed = True
                            db.commit()
            except Exception as e:
                logger.error(f"更新钉钉推送状态失败: {e}")
            finally:
                db.close()

    except Exception as e:
        logger.error(f"钉钉日报推送失败: {e}")

    logger.info(f"每日监控报告生成完成，钉钉推送: {'成功' if dingtalk_pushed else '未推送/失败'}")

    return {
        "summary": summary,
        "monitor_data": monitor_data,
        "dingtalk_pushed": dingtalk_pushed,
    }


# ======================================================================
# 主机状态检查
# ======================================================================
def check_hosts_status() -> Dict[str, int]:
    """检查所有主机的 SSH 连通性，更新 hosts 表 status 字段

    Returns:
        {"online": int, "offline": int, "total": int}
    """
    db = SessionLocal()
    online_count = 0
    offline_count = 0
    total = 0

    try:
        hosts = db.query(Host).all()
        total = len(hosts)

        for host in hosts:
            if host.is_local:
                # 本地主机始终在线
                host.status = "online"
                online_count += 1
                continue

            # 远程主机：尝试 SSH 连接
            try:
                # 简单连通性检查：尝试创建临时连接
                from app.core.ssh_client import SSHConnection

                password = decrypt(host.password) if host.password else None
                private_key = decrypt(host.private_key) if host.private_key else None

                conn = SSHConnection(
                    host_id=host.id,
                    host=host.ip,
                    port=host.port,
                    username=host.username,
                    password=password if host.auth_type == "password" else None,
                    private_key=private_key if host.auth_type == "key" else None,
                    timeout=5,
                )
                # 执行简单命令验证
                out, err, code = conn.execute("echo ok", timeout=5)
                if code == 0:
                    host.status = "online"
                    online_count += 1
                else:
                    host.status = "offline"
                    offline_count += 1
                conn.close()

            except Exception as e:
                logger.warning(f"主机状态检查失败: {host.name}({host.ip}), error={e}")
                host.status = "offline"
                offline_count += 1

        db.commit()

    except Exception as e:
        logger.error(f"主机状态检查异常: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

    logger.info(f"主机状态检查完成: 在线={online_count}, 离线={offline_count}, 总计={total}")
    return {"online": online_count, "offline": offline_count, "total": total}
