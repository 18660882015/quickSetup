"""
Windows 本地部署引擎

- precheck(): netstat 检查端口占用
- backup(): 备份 Nginx html 目录、Tomcat webapps 目录
- transfer(): shutil.copy、zipfile 解压 frontend.zip
- install(): 复制 backend.jar 到 Tomcat webapps，解压 frontend.zip 到 Nginx html
- configure(): 根据 project.json 更新配置
- start_service(): subprocess.Popen 启动 Nginx 和 Tomcat，mysql 命令导入 SQL
- validate(): 调用验证器
- rollback(): 恢复备份文件

命令执行用 subprocess.Popen + 实时输出捕获 stdout.readline()
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from app.config.settings import DEPLOYMENTS_DIR
from app.core.base_engine import BaseDeployEngine, DeployContext
from app.core.rollback import RollbackManager
from app.core.validator import Validator
from app.utils.file_utils import copy_file, ensure_dir, extract_zip, files_identical, get_file_size_str
from app.utils.logger import get_logger

logger = get_logger("local_engine")


class LocalDeployEngine(BaseDeployEngine):
    """Windows 本地部署引擎"""

    def __init__(self, context: DeployContext, log_callback=None, confirm_callback=None):
        super().__init__(context, log_callback, confirm_callback)
        self.validator = Validator(is_local=True)
        self.rollback_mgr = RollbackManager(
            is_local=True, log_callback=log_callback
        )

        # 从上下文获取配置
        pc = context.project_config
        self.project_name = pc.get("project_name", "")
        self.project_dir = DEPLOYMENTS_DIR / self.project_name

        # 服务路径（从 project_config 或默认值获取）
        self.nginx_html_dir = pc.get(
            "nginx_html_dir", "tools/nginx/html"
        )
        self.tomcat_webapps_dir = pc.get(
            "tomcat_webapps_dir", "tools/tomcat/webapps"
        )
        self.nginx_exe = pc.get("nginx_exe", "tools/nginx/nginx.exe")
        self.tomcat_startup = pc.get(
            "tomcat_startup", "tools/tomcat/bin/startup.bat"
        )
        self.mysql_exe = pc.get(
            "mysql_exe", "tools/mysql/bin/mysql.exe"
        )
        self.db_name = pc.get("db_name") or context.deploy_config.get("db_name")
        self.jdk_version = pc.get("jdk_version") or context.deploy_config.get(
            "jdk_version", "8"
        )
        self.env_type = pc.get("env_type") or context.deploy_config.get(
            "env_type", "prod"
        )
        self.ports = pc.get("ports", {"nginx": 80, "tomcat": 8080})
        self.http_urls = pc.get(
            "http_urls", ["http://localhost", "http://localhost:8080"]
        )

    # ------------------------------------------------------------------
    # 预检
    # ------------------------------------------------------------------
    def precheck(self):
        """预检：端口占用、磁盘空间"""
        self.log("info", "开始预检...", "precheck")

        # 检查部署包是否存在
        if not self.project_dir.exists():
            raise FileNotFoundError(f"项目目录不存在: {self.project_dir}")

        # 检查端口占用
        for service, port in self.ports.items():
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            occupied = [
                l
                for l in result.stdout.splitlines()
                if f":{port}" in l and "LISTENING" in l.upper()
            ]
            if occupied:
                self.log(
                    "warn",
                    f"端口 {port} ({service}) 已被占用，将在启动步骤处理",
                    "precheck",
                )
            else:
                self.log("info", f"端口 {port} ({service}) 空闲", "precheck")

        # 检查磁盘空间
        try:
            import psutil

            drive = os.path.abspath(".").split(":")[0]
            disk = psutil.disk_usage(f"{drive}:\\")
            free_gb = disk.free / (1024**3)
            if free_gb < 1:
                raise RuntimeError(f"磁盘空间不足: 剩余 {free_gb:.1f}GB")
            self.log("info", f"磁盘空间: 剩余 {free_gb:.1f}GB", "precheck")
        except ImportError:
            self.log("warn", "psutil 未安装，跳过磁盘空间检查", "precheck")

    # ------------------------------------------------------------------
    # 备份
    # ------------------------------------------------------------------
    def backup(self):
        """备份当前版本"""
        self.log("info", "开始备份当前版本...", "backup")

        backup_paths = []
        if Path(self.nginx_html_dir).exists():
            backup_paths.append(self.nginx_html_dir)
        if Path(self.tomcat_webapps_dir).exists():
            backup_paths.append(self.tomcat_webapps_dir)

        if backup_paths:
            backup_dir = self.rollback_mgr.backup_local(
                self.context.record_id, backup_paths
            )
            self.context.backup_path = str(backup_dir)
            self.context.extra["backup_dir"] = backup_dir
        else:
            self.log("info", "无需备份的文件（首次部署）", "backup")

    # ------------------------------------------------------------------
    # 传输
    # ------------------------------------------------------------------
    def transfer(self):
        """传输/准备部署文件"""
        self.log("info", "准备部署文件...", "transfer")

        frontend_zip = None
        backend_file = None
        sql_file = None

        for f in self.project_dir.iterdir():
            if not f.is_file():
                continue
            lower = f.name.lower()
            if "frontend" in lower and (
                lower.endswith(".zip") or lower.endswith(".tar.gz")
            ):
                frontend_zip = str(f)
            elif lower.endswith(".jar") or lower.endswith(".war"):
                backend_file = str(f)
            elif lower.endswith(".sql"):
                sql_file = str(f)

        self.context.extra["frontend_zip"] = frontend_zip
        self.context.extra["backend_file"] = backend_file
        self.context.extra["sql_file"] = sql_file

        if frontend_zip:
            self.log("info", f"前端包: {frontend_zip}", "transfer")
        if backend_file:
            self.log("info", f"后端包: {backend_file}", "transfer")
        if sql_file:
            self.log("info", f"SQL 文件: {sql_file}", "transfer")

        if not frontend_zip and not backend_file:
            raise FileNotFoundError(
                f"项目目录中未找到部署包: {self.project_dir}"
            )

    # ------------------------------------------------------------------
    # 安装
    # ------------------------------------------------------------------
    def install(self):
        """安装部署文件（增量模式：MD5 比对跳过未变更文件）"""
        self.log("info", "开始安装...", "install")

        # 安装后端（增量比对）
        backend_file = self.context.extra.get("backend_file")
        if backend_file:
            ensure_dir(self.tomcat_webapps_dir)
            dst = os.path.join(
                self.tomcat_webapps_dir, os.path.basename(backend_file)
            )
            if os.path.exists(dst) and files_identical(backend_file, dst):
                self.log(
                    "info",
                    f"后端包未变更，跳过复制（增量模式）: {os.path.basename(backend_file)}",
                    "install",
                )
            elif copy_file(backend_file, dst):
                size_str = get_file_size_str(os.path.getsize(backend_file))
                self.log("info", f"后端包已复制到: {dst} ({size_str})", "install")
            else:
                raise RuntimeError(f"复制后端包失败: {backend_file}")

        # 安装前端
        frontend_zip = self.context.extra.get("frontend_zip")
        if frontend_zip:
            ensure_dir(self.nginx_html_dir)
            if extract_zip(frontend_zip, self.nginx_html_dir):
                self.log(
                    "info", f"前端包已解压到: {self.nginx_html_dir}", "install"
                )
            else:
                raise RuntimeError(f"解压前端包失败: {frontend_zip}")

        # 部署后自定义脚本（可选）
        post_script = (self.context.project_config or {}).get("post_deploy_script")
        if post_script:
            self._run_post_deploy_script(post_script)

    def _run_post_deploy_script(self, script: str):
        """执行部署后自定义脚本（本地 cmd）"""
        self.log("info", f"执行部署后脚本: {script}", "install")
        try:
            proc = subprocess.run(
                script, shell=True, capture_output=True, text=True, timeout=300
            )
            if proc.returncode != 0:
                self.log(
                    "warn",
                    f"部署后脚本退出码 {proc.returncode}: {proc.stderr[:300]}",
                    "install",
                )
            else:
                output = (proc.stdout or "").strip()
                if output:
                    self.log("info", f"脚本输出: {output[:300]}", "install")
                self.log("success", "部署后脚本执行成功", "install")
        except Exception as e:
            self.log("warn", f"部署后脚本执行失败: {e}", "install")

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def configure(self):
        """更新配置"""
        self.log("info", "更新配置...", "configure")

        project_json_path = self.project_dir / "project.json"
        if project_json_path.exists():
            try:
                with open(project_json_path, "r", encoding="utf-8-sig") as f:
                    project_config = json.load(f)
                self.log("info", "已加载 project.json 配置", "configure")
                # 可在此处根据配置更新 Nginx/Tomcat 配置
                # P1 阶段仅记录，实际配置模板渲染在 P3 实现
                self.context.extra["project_json"] = project_config
            except Exception as e:
                self.log("warn", f"读取 project.json 失败: {e}", "configure")
        else:
            self.log("info", "未找到 project.json，使用默认配置", "configure")

    # ------------------------------------------------------------------
    # 启动服务
    # ------------------------------------------------------------------
    def start_service(self):
        """启动服务"""
        self.log("info", "启动服务...", "start_service")

        # 导入 SQL
        sql_file = self.context.extra.get("sql_file")
        if sql_file and self.db_name:
            self._import_sql(sql_file)

        # 启动 Tomcat
        self._start_process(self.tomcat_startup, "Tomcat")

        # 启动 Nginx
        self._start_process(self.nginx_exe, "Nginx")

    def _start_process(self, cmd: str, name: str):
        """启动进程并实时捕获输出

        使用 subprocess.Popen + stdout.readline() 实时读取。
        """
        self.log("info", f"启动 {name}: {cmd}", "start_service")
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            # 等待一小段时间看是否启动成功
            try:
                proc.wait(timeout=3)
                # 进程已退出
                output = ""
                if proc.stdout:
                    output = proc.stdout.read()
                if proc.returncode != 0:
                    self.log(
                        "warn",
                        f"{name} 启动后立即退出 (code={proc.returncode}): {output.strip()}",
                        "start_service",
                    )
                else:
                    self.log("info", f"{name} 执行完成", "start_service")
            except subprocess.TimeoutExpired:
                # 进程仍在运行（后台服务）
                self.log(
                    "success",
                    f"{name} 已启动 (PID={proc.pid})",
                    "start_service",
                )
        except Exception as e:
            raise RuntimeError(f"启动 {name} 失败: {e}")

    def _import_sql(self, sql_file: str):
        """导入 SQL 文件"""
        self.log("info", f"导入 SQL: {sql_file}", "start_service")
        try:
            cmd = f'"{self.mysql_exe}" -u root < "{sql_file}"'
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0:
                self.log(
                    "warn",
                    f"SQL 导入可能有错误: {proc.stderr.strip()}",
                    "start_service",
                )
            else:
                self.log("success", "SQL 导入完成", "start_service")
        except Exception as e:
            self.log("error", f"SQL 导入失败: {e}", "start_service")

    # ------------------------------------------------------------------
    # 验证
    # ------------------------------------------------------------------
    def validate(self):
        """三重验证"""
        self.log("info", "开始三重验证...", "validate")

        # 等待服务启动
        time.sleep(3)

        results = self.validator.validate_all(
            ports=list(self.ports.values()),
            http_urls=self.http_urls,
            log_path=None,
        )

        self.context.extra["validation_results"] = results

        for key, result in results.items():
            if key == "overall":
                continue
            level = "success" if result["passed"] else "error"
            self.log(level, f"{key}: {result['detail']}", "validate")

        if not results.get("overall", False):
            raise RuntimeError("三重验证未通过")

    # ------------------------------------------------------------------
    # 回滚
    # ------------------------------------------------------------------
    def rollback(self):
        """恢复备份文件"""
        backup_dir = self.context.extra.get("backup_dir")
        if not backup_dir:
            self.log("warn", "无备份可回滚", "rollback")
            return

        target_paths = []
        nginx_name = Path(self.nginx_html_dir).name
        tomcat_name = Path(self.tomcat_webapps_dir).name

        if (backup_dir / nginx_name).exists():
            target_paths.append((nginx_name, self.nginx_html_dir))
        if (backup_dir / tomcat_name).exists():
            target_paths.append((tomcat_name, self.tomcat_webapps_dir))

        if target_paths:
            self.rollback_mgr.rollback_local(backup_dir, target_paths)
        else:
            self.log("warn", "备份目录中无可恢复的文件", "rollback")
