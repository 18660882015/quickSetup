"""
文件操作工具：解压、复制、目录扫描
"""
import os
import shutil
import zipfile
from pathlib import Path
from typing import List, Dict, Optional

from app.config.settings import DEPLOYMENTS_DIR
from app.utils.logger import get_logger

logger = get_logger("file_utils")


def scan_deployments() -> List[Dict]:
    """扫描 deployments 目录，返回项目列表"""
    projects = []
    if not DEPLOYMENTS_DIR.exists():
        return projects

    for entry in DEPLOYMENTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        # 跳过隐藏目录
        if entry.name.startswith("."):
            continue

        project_info = {
            "name": entry.name,
            "path": str(entry),
            "files": [],
            "has_project_json": False,
            "has_frontend": False,
            "has_backend": False,
            "has_sql": False,
        }

        for f in entry.iterdir():
            if f.is_file():
                project_info["files"].append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
                lower_name = f.name.lower()
                if f.name == "project.json":
                    project_info["has_project_json"] = True
                if "frontend" in lower_name and (lower_name.endswith(".zip") or lower_name.endswith(".tar.gz")):
                    project_info["has_frontend"] = True
                if lower_name.endswith(".jar") or lower_name.endswith(".war"):
                    project_info["has_backend"] = True
                if lower_name.endswith(".sql"):
                    project_info["has_sql"] = True

        projects.append(project_info)

    return projects


def list_directory(path: Path) -> List[Dict]:
    """列出目录下的文件和子目录"""
    result = []
    if not path.exists() or not path.is_dir():
        return result

    for entry in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        stat = entry.stat()
        result.append({
            "name": entry.name,
            "path": str(entry),
            "is_dir": entry.is_dir(),
            "size": stat.st_size if entry.is_file() else 0,
            "modified": stat.st_mtime,
        })

    return result


def extract_zip(zip_path: str, target_dir: str) -> bool:
    """解压 zip 文件到目标目录"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
        logger.info(f"解压完成: {zip_path} -> {target_dir}")
        return True
    except Exception as e:
        logger.error(f"解压失败: {zip_path}, 错误: {e}")
        return False


def copy_file(src: str, dst: str) -> bool:
    """复制文件"""
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        logger.info(f"复制文件: {src} -> {dst}")
        return True
    except Exception as e:
        logger.error(f"复制文件失败: {src} -> {dst}, 错误: {e}")
        return False


def delete_file(path: str) -> bool:
    """删除文件或目录"""
    try:
        p = Path(path)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
        logger.info(f"删除: {path}")
        return True
    except Exception as e:
        logger.error(f"删除失败: {path}, 错误: {e}")
        return False


def ensure_dir(path: str) -> Path:
    """确保目录存在"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_file_size_str(size_bytes: int) -> str:
    """获取人类可读的文件大小"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"
