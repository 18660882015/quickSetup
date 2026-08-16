"""
回滚管理

- 部署前备份到 data/backups/{deploy_id}/
- 回滚流程：停止服务 -> 恢复备份文件 -> 重启 -> 验证
- 保留最近 N 次备份，超出自动清理
"""
import shutil
from pathlib import Path
from typing import Callable, List, Optional

from app.config.settings import BACKUPS_DIR
from app.utils.logger import get_logger

logger = get_logger("rollback")


class RollbackManager:
    """回滚管理器

    支持本地（Windows）和远程（SSH）两种模式。
    """

    def __init__(
        self,
        is_local: bool = False,
        ssh_conn=None,
        log_callback: Optional[Callable[[str, str, Optional[str]], None]] = None,
    ):
        self.is_local = is_local
        self.ssh_conn = ssh_conn
        self.log_callback = log_callback

    def _log(self, level: str, message: str, step: str = "rollback"):
        if self.log_callback:
            try:
                self.log_callback(level, message, step)
            except Exception:
                pass
        if level == "error":
            logger.error(message)
        else:
            logger.info(message)

    # ------------------------------------------------------------------
    # 备份目录管理
    # ------------------------------------------------------------------
    def create_backup_dir(self, deploy_id: int) -> Path:
        """创建本地备份目录 data/backups/{deploy_id}/"""
        backup_dir = BACKUPS_DIR / str(deploy_id)
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    # ------------------------------------------------------------------
    # 本地备份与回滚
    # ------------------------------------------------------------------
    def backup_local(self, deploy_id: int, paths: List[str]) -> Path:
        """本地备份

        Args:
            deploy_id: 部署记录 ID
            paths: 需要备份的本地路径列表
        Returns:
            备份目录 Path
        """
        backup_dir = self.create_backup_dir(deploy_id)
        self._log("info", f"开始本地备份到: {backup_dir}")

        for src_path in paths:
            src = Path(src_path)
            if not src.exists():
                self._log("warn", f"备份源不存在，跳过: {src_path}")
                continue
            dst = backup_dir / src.name
            try:
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                self._log("info", f"已备份: {src_path} -> {dst}")
            except Exception as e:
                self._log("error", f"备份失败: {src_path}, error={e}")

        self._log("success", f"本地备份完成: {backup_dir}")
        return backup_dir

    def rollback_local(
        self, backup_dir: Path, target_paths: List[tuple]
    ) -> bool:
        """本地回滚

        Args:
            backup_dir: 备份目录
            target_paths: [(backup_name, target_path), ...]
        """
        self._log("warn", "开始本地回滚...")

        for backup_name, target_path in target_paths:
            src = backup_dir / backup_name
            if not src.exists():
                self._log("warn", f"备份文件不存在，跳过: {src}")
                continue
            try:
                target = Path(target_path)
                # 删除当前文件
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                # 恢复备份
                if src.is_dir():
                    shutil.copytree(src, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                self._log("info", f"已恢复: {src} -> {target_path}")
            except Exception as e:
                self._log("error", f"恢复失败: {src} -> {target_path}, error={e}")
                return False

        self._log("success", "本地回滚完成")
        return True

    # ------------------------------------------------------------------
    # 远程备份与回滚
    # ------------------------------------------------------------------
    def backup_remote(
        self,
        deploy_id: int,
        remote_paths: List[str],
        backup_base_dir: str = "/tmp/mvp-backups",
    ) -> str:
        """远程备份

        Args:
            deploy_id: 部署记录 ID
            remote_paths: 远程需要备份的路径列表
            backup_base_dir: 远程备份根目录
        Returns:
            远程备份目录路径
        """
        backup_dir = f"{backup_base_dir}/{deploy_id}"
        self._log("info", f"开始远程备份到: {backup_dir}")

        # 创建备份目录
        self.ssh_conn.execute(f"mkdir -p {backup_dir}")

        for remote_path in remote_paths:
            # 检查路径是否存在
            stdout, _, _ = self.ssh_conn.execute(
                f"test -e {remote_path} && echo exists"
            )
            if "exists" not in stdout:
                self._log("warn", f"远程备份源不存在，跳过: {remote_path}")
                continue
            # 获取 basename
            basename = remote_path.rstrip("/").rsplit("/", 1)[-1]
            if not basename:
                basename = "backup"
            dst = f"{backup_dir}/{basename}"
            try:
                self.ssh_conn.execute(f"cp -r {remote_path} {dst}")
                self._log("info", f"已备份: {remote_path} -> {dst}")
            except Exception as e:
                self._log("error", f"备份失败: {remote_path}, error={e}")

        self._log("success", f"远程备份完成: {backup_dir}")
        return backup_dir

    def rollback_remote(
        self, backup_dir: str, target_paths: List[tuple]
    ) -> bool:
        """远程回滚

        Args:
            backup_dir: 远程备份目录
            target_paths: [(backup_name, target_path), ...]
        """
        self._log("warn", "开始远程回滚...")

        for backup_name, target_path in target_paths:
            src = f"{backup_dir}/{backup_name}"
            # 检查备份文件是否存在
            stdout, _, _ = self.ssh_conn.execute(f"test -e {src} && echo exists")
            if "exists" not in stdout:
                self._log("warn", f"远程备份文件不存在，跳过: {src}")
                continue
            try:
                self.ssh_conn.execute(f"rm -rf {target_path}")
                self.ssh_conn.execute(f"cp -r {src} {target_path}")
                self._log("info", f"已恢复: {src} -> {target_path}")
            except Exception as e:
                self._log(
                    "error", f"恢复失败: {src} -> {target_path}, error={e}"
                )
                return False

        self._log("success", "远程回滚完成")
        return True

    # ------------------------------------------------------------------
    # 备份清理
    # ------------------------------------------------------------------
    def cleanup_old_backups(self, max_count: int = 5):
        """清理旧备份，保留最近 N 次

        按 deploy_id 目录的修改时间排序，删除超出的旧备份。
        """
        try:
            if not BACKUPS_DIR.exists():
                return
            backup_dirs = [d for d in BACKUPS_DIR.iterdir() if d.is_dir()]
            backup_dirs.sort(
                key=lambda x: x.stat().st_mtime, reverse=True
            )

            if len(backup_dirs) > max_count:
                for d in backup_dirs[max_count:]:
                    shutil.rmtree(d)
                    self._log("info", f"清理旧备份: {d.name}")
        except Exception as e:
            self._log("error", f"清理旧备份失败: {e}")
