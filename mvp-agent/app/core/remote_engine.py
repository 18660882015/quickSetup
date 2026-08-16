"""
SSH 远程部署引擎

- precheck(): SSH 检查 df -h、netstat -tlnp、已有服务状态
- backup(): SSH 执行备份命令
- transfer(): SFTP 上传部署包
- install(): Jinja2 模板生成部署脚本，exec_command_stream 执行
- configure(): 上传配置文件
- start_service(): systemctl start 或直接启动
- validate(): 调用验证器
- rollback(): SSH 恢复备份
"""
import io
import time
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from app.config.settings import DEPLOYMENTS_DIR
from app.core.base_engine import BaseDeployEngine, DeployContext
from app.core.rollback import RollbackManager
from app.core.ssh_client import SSHConnection
from app.core.validator import Validator
from app.utils.logger import get_logger

logger = get_logger("remote_engine")

# Jinja2 模板目录
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class RemoteDeployEngine(BaseDeployEngine):
    """SSH 远程部署引擎"""

    def __init__(
        self,
        context: DeployContext,
        ssh_conn: SSHConnection,
        log_callback=None,
        confirm_callback=None,
    ):
        super().__init__(context, log_callback, confirm_callback)
        self.ssh_conn = ssh_conn
        self.validator = Validator(is_local=False, ssh_conn=ssh_conn)
        self.rollback_mgr = RollbackManager(
            is_local=False, ssh_conn=ssh_conn, log_callback=log_callback
        )

        pc = context.project_config
        self.project_name = pc.get("project_name", "")
        self.project_dir = DEPLOYMENTS_DIR / self.project_name
        self.deploy_dir = (
            pc.get("deploy_dir")
            or context.host_config.get("deploy_dir", "/opt/deploy")
        )
        self.backup_dir = pc.get("backup_dir") or context.host_config.get(
            "backup_dir", "/opt/deploy/backups"
        )
        self.jdk_version = pc.get("jdk_version") or context.deploy_config.get(
            "jdk_version", "8"
        )
        self.env_type = pc.get("env_type") or context.deploy_config.get(
            "env_type", "prod"
        )
        self.db_name = pc.get("db_name") or context.deploy_config.get("db_name")
        self.ports = pc.get("ports", {"nginx": 80, "tomcat": 8080})
        self.http_urls = pc.get("http_urls", [])

        # Jinja2 环境
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,
        )

    # ------------------------------------------------------------------
    # 预检
    # ------------------------------------------------------------------
    def precheck(self):
        """预检：磁盘空间、端口占用、服务状态"""
        self.log("info", "开始远程预检...", "precheck")

        # 检查磁盘空间
        stdout, stderr, exit_code = self.ssh_conn.execute("df -h /")
        if exit_code == 0:
            for line in stdout.strip().splitlines():
                self.log("info", line, "precheck")
        else:
            self.log("warn", f"获取磁盘空间失败: {stderr}", "precheck")

        # 检查端口占用
        for service, port in self.ports.items():
            stdout, _, _ = self.ssh_conn.execute(
                f"netstat -tlnp 2>/dev/null | grep ':{port} '"
            )
            if stdout.strip():
                self.log(
                    "warn",
                    f"端口 {port} ({service}) 已被占用",
                    "precheck",
                )
            else:
                self.log("info", f"端口 {port} ({service}) 空闲", "precheck")

        # 检查部署目录
        stdout, _, _ = self.ssh_conn.execute(
            f"test -d {self.deploy_dir} && echo exists"
        )
        if "exists" in stdout:
            self.log("info", f"部署目录已存在: {self.deploy_dir}", "precheck")
        else:
            self.log(
                "info",
                f"部署目录不存在，将创建: {self.deploy_dir}",
                "precheck",
            )

    # ------------------------------------------------------------------
    # 备份
    # ------------------------------------------------------------------
    def backup(self):
        """备份当前版本"""
        self.log("info", "开始远程备份...", "backup")

        # 检查需要备份的路径
        backup_paths = []
        for check_path in [f"{self.deploy_dir}/html", f"{self.deploy_dir}/webapps"]:
            stdout, _, _ = self.ssh_conn.execute(
                f"test -e {check_path} && echo exists"
            )
            if "exists" in stdout:
                backup_paths.append(check_path)

        if backup_paths:
            remote_backup_dir = self.rollback_mgr.backup_remote(
                self.context.record_id, backup_paths
            )
            self.context.backup_path = remote_backup_dir
            self.context.extra["remote_backup_dir"] = remote_backup_dir
        else:
            self.log("info", "无需备份的文件（首次部署）", "backup")

    # ------------------------------------------------------------------
    # 传输
    # ------------------------------------------------------------------
    def transfer(self):
        """SFTP 上传部署包"""
        self.log("info", "开始上传部署包...", "transfer")

        if not self.project_dir.exists():
            raise FileNotFoundError(f"项目目录不存在: {self.project_dir}")

        # 创建远程临时目录
        remote_tmp = f"/tmp/mvp-deploy-{self.context.record_id}"
        self.ssh_conn.execute(f"mkdir -p {remote_tmp}")
        self.context.extra["remote_tmp"] = remote_tmp

        # 上传文件
        sftp = self.ssh_conn.get_sftp()
        uploaded = []
        try:
            for f in self.project_dir.iterdir():
                if f.is_file():
                    remote_path = f"{remote_tmp}/{f.name}"
                    self.log("info", f"上传: {f.name} -> {remote_path}", "transfer")
                    sftp.put(str(f), remote_path)
                    uploaded.append(f.name)
        finally:
            sftp.close()

        self.context.extra["uploaded_files"] = uploaded
        self.log("success", f"上传完成: {len(uploaded)} 个文件", "transfer")

    # ------------------------------------------------------------------
    # 安装
    # ------------------------------------------------------------------
    def install(self):
        """Jinja2 模板生成部署脚本并执行"""
        self.log("info", "开始远程安装...", "install")

        uploaded = self.context.extra.get("uploaded_files", [])
        remote_tmp = self.context.extra.get("remote_tmp", "")

        # 确定后端文件类型
        backend_file = None
        for f in uploaded:
            if f.endswith(".jar"):
                backend_file = f
                break
            if f.endswith(".war"):
                backend_file = f
                break

        if backend_file:
            # 选择模板
            if backend_file.endswith(".jar"):
                template_name = "deploy_jar.sh.j2"
            else:
                template_name = "deploy_war.sh.j2"

            try:
                template = self.jinja_env.get_template(template_name)
            except Exception:
                self.log(
                    "warn",
                    f"模板不存在: {template_name}，使用默认安装方式",
                    "install",
                )
                self._default_install(backend_file, remote_tmp)
                return

            # JVM 参数根据 JDK 版本选择
            if self.jdk_version == "17":
                jvm_args = "-Xms256m -Xmx512m -XX:MetaspaceSize=128m -XX:MaxMetaspaceSize=256m"
            else:
                jvm_args = "-Xms256m -Xmx512m -XX:PermSize=128m -XX:MaxPermSize=256m"

            script = template.render(
                jdk_version=self.jdk_version,
                deploy_dir=self.deploy_dir,
                backend_file=backend_file,
                remote_tmp=remote_tmp,
                env_type=self.env_type,
                jvm_args=jvm_args,
                db_name=self.db_name or "",
            )

            # 上传脚本并执行
            script_path = f"{remote_tmp}/deploy.sh"
            sftp = self.ssh_conn.get_sftp()
            try:
                sftp.putfo(io.BytesIO(script.encode("utf-8")), script_path)
            finally:
                sftp.close()

            self.ssh_conn.execute(f"chmod +x {script_path}")

            # 流式执行部署脚本
            self.log("info", "执行部署脚本...", "install")
            output, exit_code = self.ssh_conn.exec_command_stream(
                f"bash {script_path}",
                callback=lambda data: self._stream_log(data, "install"),
                timeout=120,
            )

            if exit_code != 0:
                raise RuntimeError(f"部署脚本执行失败 (exit_code={exit_code})")

            self.log("success", "部署脚本执行完成", "install")

        # 解压前端
        frontend_zip = None
        for f in uploaded:
            if "frontend" in f.lower() and (
                f.endswith(".zip") or f.endswith(".tar.gz")
            ):
                frontend_zip = f
                break

        if frontend_zip:
            html_dir = f"{self.deploy_dir}/html"
            self.ssh_conn.execute(f"mkdir -p {html_dir}")
            if frontend_zip.endswith(".zip"):
                cmd = f"cd {html_dir} && unzip -o {remote_tmp}/{frontend_zip}"
            else:
                cmd = f"cd {html_dir} && tar -xzf {remote_tmp}/{frontend_zip}"

            output, exit_code = self.ssh_conn.exec_command_stream(
                cmd,
                callback=lambda data: self._stream_log(data, "install"),
                timeout=60,
            )
            if exit_code != 0:
                raise RuntimeError("解压前端包失败")
            self.log("success", f"前端包已解压到: {html_dir}", "install")

    def _default_install(self, backend_file: str, remote_tmp: str):
        """默认安装方式（无模板时）"""
        target_dir = f"{self.deploy_dir}/webapps"
        self.ssh_conn.execute(f"mkdir -p {target_dir}")
        self.ssh_conn.execute(
            f"cp {remote_tmp}/{backend_file} {target_dir}/"
        )
        self.log("info", f"后端包已复制到: {target_dir}", "install")

    def _stream_log(self, data: str, step: str):
        """流式输出回调"""
        for line in data.splitlines():
            line = line.strip()
            if line:
                self.log("info", line, step)

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def configure(self):
        """上传配置文件"""
        self.log("info", "更新远程配置...", "configure")

        project_json_path = self.project_dir / "project.json"
        if project_json_path.exists():
            remote_tmp = self.context.extra.get("remote_tmp", "")
            remote_config = f"{remote_tmp}/project.json"
            sftp = self.ssh_conn.get_sftp()
            try:
                sftp.put(str(project_json_path), remote_config)
            finally:
                sftp.close()
            self.log("info", "project.json 已上传", "configure")
        else:
            self.log("info", "未找到 project.json，跳过配置上传", "configure")

    # ------------------------------------------------------------------
    # 启动服务
    # ------------------------------------------------------------------
    def start_service(self):
        """启动服务"""
        self.log("info", "启动远程服务...", "start_service")

        # 导入 SQL
        uploaded = self.context.extra.get("uploaded_files", [])
        sql_file = None
        for f in uploaded:
            if f.endswith(".sql"):
                sql_file = f
                break

        if sql_file and self.db_name:
            remote_tmp = self.context.extra.get("remote_tmp", "")
            cmd = f"mysql -u root {self.db_name} < {remote_tmp}/{sql_file}"
            output, exit_code = self.ssh_conn.exec_command_stream(
                cmd,
                callback=lambda data: self._stream_log(data, "start_service"),
                timeout=60,
            )
            if exit_code == 0:
                self.log("success", "SQL 导入完成", "start_service")
            else:
                self.log(
                    "warn",
                    f"SQL 导入可能有错误 (exit_code={exit_code})",
                    "start_service",
                )

        # 尝试 systemctl 启动
        for service in ["nginx", "tomcat"]:
            cmd = f"systemctl start {service} 2>/dev/null || echo fallback"
            output, exit_code = self.ssh_conn.exec_command_stream(
                cmd,
                callback=lambda data: self._stream_log(data, "start_service"),
                timeout=30,
            )
            if "fallback" in output:
                self.log(
                    "warn",
                    f"{service} systemctl 启动失败，尝试直接启动",
                    "start_service",
                )
                # 尝试直接启动
                if service == "nginx":
                    self.ssh_conn.execute("nginx 2>/dev/null || echo skip")
                elif service == "tomcat":
                    startup = f"{self.deploy_dir}/tomcat/bin/startup.sh"
                    self.ssh_conn.execute(
                        f"test -f {startup} && nohup {startup} & || echo skip"
                    )
            else:
                self.log("success", f"{service} 已启动", "start_service")

        # 等待服务就绪
        time.sleep(3)

    # ------------------------------------------------------------------
    # 验证
    # ------------------------------------------------------------------
    def validate(self):
        """三重验证"""
        self.log("info", "开始远程三重验证...", "validate")

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
        """远程回滚"""
        remote_backup_dir = self.context.extra.get("remote_backup_dir")
        if not remote_backup_dir:
            self.log("warn", "无备份可回滚", "rollback")
            return

        target_paths = [
            ("html", f"{self.deploy_dir}/html"),
            ("webapps", f"{self.deploy_dir}/webapps"),
        ]
        self.rollback_mgr.rollback_remote(remote_backup_dir, target_paths)
