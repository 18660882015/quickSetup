"""
备份与配置迁移服务

- 数据库每日自动备份（保留 N 天）
- 主机配置 + 系统配置一键导出/导入（AES 加密 JSON）
- 数据清空（部署记录/监控数据/全部数据）
- 磁盘空间统计与清理（旧备份、日志、监控数据）
"""
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from app.config.settings import get_settings, BACKUPS_DIR, LOGS_DIR
from app.models.database import SessionLocal
from app.models.host import Host
from app.models.sys_config import SysConfig, get_config_value
from app.models.deploy_record import DeployRecord
from app.models.monitor_daily import MonitorDaily
from app.utils.crypto import encrypt_value, decrypt_value
from app.utils.logger import get_logger

logger = get_logger("backup_service")

# 数据库备份目录
DB_BACKUP_DIR = BACKUPS_DIR / "db_backups"


def get_db_backup_dir() -> Path:
    DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return DB_BACKUP_DIR


# ======================================================================
# 数据库备份
# ======================================================================
def backup_database(reason: str = "auto") -> Dict:
    """备份 SQLite 数据库文件

    Returns:
        {"success": bool, "file": str, "size": int, "message": str}
    """
    settings = get_settings()
    db_file = settings.db_file_path

    if not os.path.exists(db_file):
        return {"success": False, "file": "", "size": 0, "message": f"数据库文件不存在: {db_file}"}

    try:
        backup_dir = get_db_backup_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"mvp_{reason}_{ts}.db"
        shutil.copy2(db_file, backup_file)

        # 清理过期备份
        db = SessionLocal()
        try:
            keep_days = int(get_config_value(db, "db_backup_keep_days", "7"))
        finally:
            db.close()
        cleanup_db_backups(keep_days)

        size = backup_file.stat().st_size
        logger.info(f"数据库备份完成: {backup_file} ({size / 1024:.1f} KB)")
        return {
            "success": True,
            "file": str(backup_file),
            "size": size,
            "message": f"备份成功: {backup_file.name}",
        }
    except Exception as e:
        logger.error(f"数据库备份失败: {e}", exc_info=True)
        return {"success": False, "file": "", "size": 0, "message": f"备份失败: {e}"}


def cleanup_db_backups(keep_days: int = 7):
    """删除超过保留天数的数据库备份"""
    backup_dir = get_db_backup_dir()
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for f in backup_dir.glob("mvp_*.db"):
        if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            removed += 1
    if removed > 0:
        logger.info(f"清理过期数据库备份 {removed} 个（保留 {keep_days} 天）")


def list_db_backups() -> List[Dict]:
    """列出所有数据库备份"""
    backup_dir = get_db_backup_dir()
    result = []
    for f in sorted(backup_dir.glob("mvp_*.db"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = f.stat()
        result.append({
            "filename": f.name,
            "path": str(f),
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


def restore_database(backup_path: str) -> Dict:
    """从备份恢复数据库

    仅在服务停止时执行才安全；运行时恢复会先写标记文件，
    由下次启动时应用（简化实现：直接覆盖并重建连接）。
    """
    settings = get_settings()
    db_file = settings.db_file_path
    backup_file = Path(backup_path)

    if not backup_file.exists():
        return {"success": False, "message": f"备份文件不存在: {backup_path}"}

    try:
        # 先备份当前数据库
        if os.path.exists(db_file):
            backup_database("pre_restore")

        shutil.copy2(backup_file, db_file)
        logger.info(f"数据库已从备份恢复: {backup_file.name}")
        return {"success": True, "message": f"恢复成功，请重启服务使数据生效"}
    except Exception as e:
        logger.error(f"数据库恢复失败: {e}", exc_info=True)
        return {"success": False, "message": f"恢复失败: {e}"}


# ======================================================================
# 配置导出/导入
# ======================================================================
def export_configs() -> Dict:
    """导出主机配置 + 系统配置为加密 JSON

    Returns:
        {"version": 1, "exported_at": str, "data": {...}, "checksum": str}
    """
    db = SessionLocal()
    try:
        hosts = []
        for h in db.query(Host).all():
            hosts.append({
                "name": h.name,
                "ip": h.ip,
                "port": h.port,
                "username": h.username,
                "auth_type": h.auth_type,
                "password": h.password,      # 已是密文
                "private_key": h.private_key,  # 已是密文
                "jdk_version": h.jdk_version,
                "deploy_dir": h.deploy_dir,
                "backup_dir": h.backup_dir,
                "is_local": h.is_local,
            })

        configs = []
        for c in db.query(SysConfig).all():
            configs.append({
                "config_key": c.config_key,
                "config_value": c.config_value,  # 加密项保持密文
                "is_encrypted": c.is_encrypted,
                "description": c.description,
            })

        payload = {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "hosts": hosts,
            "configs": configs,
        }

        # 整体再加密一层（防止明文泄露非加密项）
        raw = json.dumps(payload, ensure_ascii=False, default=str)
        encrypted = encrypt_value(raw)

        result = {
            "version": 1,
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "host_count": len(hosts),
            "config_count": len(configs),
            "encrypted_blob": encrypted,
        }
        logger.info(f"配置导出成功: {len(hosts)} 主机, {len(configs)} 配置项")
        return result
    finally:
        db.close()


def import_configs(encrypted_blob: str, mode: str = "merge") -> Dict:
    """导入配置（合并或覆盖）

    Args:
        encrypted_blob: export_configs 输出的加密内容
        mode: merge（存在则跳过）/ overwrite（存在则覆盖）
    """
    try:
        raw = decrypt_value(encrypted_blob)
        payload = json.loads(raw)
    except Exception as e:
        return {"success": False, "message": f"解密失败（密钥不匹配或数据损坏）: {e}"}

    if payload.get("version") != 1:
        return {"success": False, "message": f"不支持的配置版本: {payload.get('version')}"}

    hosts_added, hosts_skipped, hosts_updated = 0, 0, 0
    configs_added, configs_updated = 0, 0

    db = SessionLocal()
    try:
        # 导入主机
        for h in payload.get("hosts", []):
            existing = db.query(Host).filter(Host.ip == h.get("ip"), Host.name == h.get("name")).first()
            if existing:
                if mode == "overwrite":
                    existing.port = h.get("port", existing.port)
                    existing.username = h.get("username", existing.username)
                    existing.auth_type = h.get("auth_type", existing.auth_type)
                    existing.password = h.get("password", existing.password)
                    existing.private_key = h.get("private_key", existing.private_key)
                    existing.jdk_version = h.get("jdk_version", existing.jdk_version)
                    existing.deploy_dir = h.get("deploy_dir", existing.deploy_dir)
                    existing.backup_dir = h.get("backup_dir", existing.backup_dir)
                    hosts_updated += 1
                else:
                    hosts_skipped += 1
            else:
                host = Host(
                    name=h.get("name", ""),
                    ip=h.get("ip", ""),
                    port=h.get("port", 22),
                    username=h.get("username", "root"),
                    auth_type=h.get("auth_type", "password"),
                    password=h.get("password"),
                    private_key=h.get("private_key"),
                    jdk_version=h.get("jdk_version", "8"),
                    deploy_dir=h.get("deploy_dir"),
                    backup_dir=h.get("backup_dir"),
                    is_local=h.get("is_local", False),
                )
                db.add(host)
                hosts_added += 1

        # 导入配置
        for c in payload.get("configs", []):
            key = c.get("config_key")
            if not key:
                continue
            existing = db.query(SysConfig).filter(SysConfig.config_key == key).first()
            value = c.get("config_value")
            if existing:
                if mode == "overwrite" and value:
                    existing.config_value = value
                    existing.is_encrypted = c.get("is_encrypted", False)
                    configs_updated += 1
            else:
                db.add(SysConfig(
                    config_key=key,
                    config_value=value,
                    is_encrypted=c.get("is_encrypted", False),
                    description=c.get("description", ""),
                ))
                configs_added += 1

        db.commit()
        result = {
            "success": True,
            "message": (
                f"导入完成: 新增主机 {hosts_added}，更新 {hosts_updated}，跳过 {hosts_skipped}；"
                f"新增配置 {configs_added}，更新 {configs_updated}"
            ),
            "hosts_added": hosts_added,
            "hosts_updated": hosts_updated,
            "configs_added": configs_added,
            "configs_updated": configs_updated,
        }
        logger.info(result["message"])
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"配置导入失败: {e}", exc_info=True)
        return {"success": False, "message": f"导入失败: {e}"}
    finally:
        db.close()


# ======================================================================
# 数据清空
# ======================================================================
def reset_data(scope: str = "deploy_records") -> Dict:
    """清空数据

    Args:
        scope: deploy_records / monitor_data / all（不含主机和系统配置）
    """
    db = SessionLocal()
    try:
        counts = {}
        if scope in ("deploy_records", "all"):
            counts["deploy_records"] = db.query(DeployRecord).delete()
        if scope in ("monitor_data", "all"):
            counts["monitor_data"] = db.query(MonitorDaily).delete()

        db.commit()
        result = {"success": True, "message": f"已清空: {counts}", "counts": counts}
        logger.info(f"数据清空[{scope}]: {counts}")
        return result
    except Exception as e:
        db.rollback()
        return {"success": False, "message": f"清空失败: {e}"}
    finally:
        db.close()


# ======================================================================
# 磁盘空间管理
# ======================================================================
def get_dir_size(path: Path) -> int:
    """递归计算目录大小（字节）"""
    total = 0
    if not path.exists():
        return 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def get_disk_usage() -> Dict:
    """统计各数据目录磁盘占用"""
    import psutil

    settings = get_settings()
    data_dir = settings.DATA_DIR

    dirs = {
        "db": data_dir / "db",
        "deployments": data_dir / "deployments",
        "backups": data_dir / "backups",
        "logs": data_dir / "logs",
        "chunks": data_dir / "chunks",
    }

    result = {}
    for name, path in dirs.items():
        if path.exists():
            size = get_dir_size(path)
            result[name] = {
                "path": str(path),
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
            }
        else:
            result[name] = {"path": str(path), "size_bytes": 0, "size_mb": 0}

    total = sum(v["size_bytes"] for v in result.values())
    disk = psutil.disk_usage(str(data_dir))

    return {
        "dirs": result,
        "total_mb": round(total / 1024 / 1024, 2),
        "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 2),
        "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 2),
        "disk_percent": disk.percent,
    }


def cleanup_disk() -> Dict:
    """手动/定时磁盘清理

    - 清理超过保留天数的日志文件
    - 清理超过保留天数的监控数据
    - 清理过期数据库备份
    - 清理部署备份（保留最近 N 次）
    """
    db = SessionLocal()
    try:
        log_keep_days = int(get_config_value(db, "log_retention_days", "30"))
        backup_keep = int(get_config_value(db, "backup_max_count", "5"))
        db_backup_keep_days = int(get_config_value(db, "db_backup_keep_days", "7"))
    finally:
        db.close()

    removed = {"logs": 0, "monitor_data": 0, "db_backups": 0, "deploy_backups": 0}
    freed_bytes = 0

    # 1. 旧日志文件
    cutoff = datetime.now() - timedelta(days=log_keep_days)
    if LOGS_DIR.exists():
        for f in LOGS_DIR.glob("*.log*"):
            try:
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    freed_bytes += f.stat().st_size
                    f.unlink()
                    removed["logs"] += 1
            except OSError:
                pass

    # 2. 旧监控数据（保留 90 天）
    monitor_cutoff = datetime.now() - timedelta(days=90)
    db = SessionLocal()
    try:
        removed["monitor_data"] = (
            db.query(MonitorDaily)
            .filter(MonitorDaily.created_at < monitor_cutoff)
            .delete()
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    # 3. 过期数据库备份
    backup_dir = get_db_backup_dir()
    db_cutoff = datetime.now() - timedelta(days=db_backup_keep_days)
    for f in backup_dir.glob("mvp_*.db"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < db_cutoff:
                freed_bytes += f.stat().st_size
                f.unlink()
                removed["db_backups"] += 1
        except OSError:
            pass

    # 4. 部署备份目录（保留最近 N 个）
    if BACKUPS_DIR.exists():
        backup_dirs = [
            d for d in BACKUPS_DIR.iterdir()
            if d.is_dir() and d.name not in ("db_backups",)
        ]
        backup_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for d in backup_dirs[backup_keep:]:
            try:
                size = get_dir_size(d)
                shutil.rmtree(d)
                freed_bytes += size
                removed["deploy_backups"] += 1
            except OSError:
                pass

    result = {
        "success": True,
        "removed": removed,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
        "message": (
            f"清理完成: 日志 {removed['logs']} 个，监控数据 {removed['monitor_data']} 条，"
            f"数据库备份 {removed['db_backups']} 个，部署备份 {removed['deploy_backups']} 个，"
            f"释放 {freed_bytes / 1024 / 1024:.1f} MB"
        ),
    }
    logger.info(result["message"])
    return result
