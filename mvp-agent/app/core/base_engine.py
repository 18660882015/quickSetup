"""
部署引擎抽象基类

模板方法模式：预检 -> 备份 -> 传输 -> 安装 -> 配置 -> 启动 -> 验证 -> 清理
- execute() 模板方法按序执行，失败触发回滚
- 支持两种执行模式：自动执行 / 每步确认
- cancel() 取消机制：标志位 + 步骤间检查
- 危险操作检测：识别 rm -rf、del /f、shutdown、format 等
- log_callback 推送日志
"""
import re
import time
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from app.utils.logger import get_logger

logger = get_logger("base_engine")

# 部署步骤定义：(step_key, step_name)
DEPLOY_STEPS = [
    ("precheck", "预检"),
    ("backup", "备份"),
    ("transfer", "传输"),
    ("install", "安装"),
    ("configure", "配置"),
    ("start_service", "启动"),
    ("validate", "验证"),
    ("cleanup", "清理"),
]


def _load_dangerous_commands() -> List[str]:
    """从 deploy_config.yaml 加载危险命令正则列表"""
    config_path = (
        Path(__file__).resolve().parent.parent / "config" / "deploy_config.yaml"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("dangerous_commands", [])
    except Exception as e:
        logger.warning(f"加载危险命令列表失败，使用内置默认: {e}")
        return [
            r"rm\s+-rf\s+/",
            r"rm\s+-rf\s+\*",
            r"del\s+/[fqsS].*C:",
            r"format\s+",
            r"shutdown",
            r"reboot",
            r"halt",
            r"init\s+0",
            r"mkfs",
            r"dd\s+.*of=/dev/",
            r":\(\)\{.*\|:&\}",
            r"chmod\s+-R\s+777\s+/",
            r"DROP\s+DATABASE",
            r"DROP\s+TABLE",
            r"TRUNCATE\s+TABLE",
        ]


DANGEROUS_PATTERNS = _load_dangerous_commands()


def detect_dangerous_command(command: str) -> bool:
    """检测命令是否危险

    覆盖 rm -rf、del /f、shutdown、format 等危险操作。
    """
    if not command:
        return False
    for pattern in DANGEROUS_PATTERNS:
        try:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


class DeployContext:
    """部署上下文，在各步骤间传递数据"""

    def __init__(
        self,
        record_id: int,
        host_config: Optional[dict],
        project_config: dict,
        deploy_config: dict,
    ):
        self.record_id = record_id
        self.host_config = host_config or {}
        self.project_config = project_config
        self.deploy_config = deploy_config
        self.backup_path: Optional[str] = None
        self.steps_detail: List[Dict] = []
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        self.is_rolled_back = False
        self.is_cancelled = False
        # 额外数据存储（各步骤间共享）
        self.extra: Dict[str, Any] = {}

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class BaseDeployEngine(ABC):
    """部署引擎抽象基类

    模板方法模式，子类实现各步骤具体逻辑。
    """

    def __init__(
        self,
        context: DeployContext,
        log_callback: Optional[Callable[[str, str, Optional[str]], None]] = None,
        confirm_callback: Optional[Callable[[str, str, bool], bool]] = None,
    ):
        """
        Args:
            context: 部署上下文
            log_callback: 日志回调 (level, message, step) -> None
            confirm_callback: 确认回调 (step, command, is_dangerous) -> bool
        """
        self.context = context
        self.log_callback = log_callback
        self.confirm_callback = confirm_callback
        self._cancelled = threading.Event()
        self._current_step: Optional[str] = None

    # ------------------------------------------------------------------
    # 日志与取消
    # ------------------------------------------------------------------
    def log(self, level: str, message: str, step: Optional[str] = None):
        """推送日志"""
        effective_step = step or self._current_step
        if self.log_callback:
            try:
                self.log_callback(level, message, effective_step)
            except Exception as e:
                logger.error(f"日志回调异常: {e}")

        # 同时记录到引擎日志
        if level == "error":
            logger.error(f"[{self.context.record_id}] {message}")
        elif level == "warn":
            logger.warning(f"[{self.context.record_id}] {message}")
        else:
            logger.info(f"[{self.context.record_id}] {message}")

    def cancel(self):
        """取消部署"""
        self._cancelled.set()
        self.context.is_cancelled = True
        self.log("warn", "收到取消请求，将在当前步骤完成后终止", self._current_step)

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def _check_cancelled(self):
        """检查是否已取消（在步骤间调用）"""
        if self.is_cancelled:
            raise InterruptedError("部署已被用户取消")

    # ------------------------------------------------------------------
    # 步骤记录
    # ------------------------------------------------------------------
    def _record_step(
        self,
        step: str,
        name: str,
        status: str,
        duration: float,
        error: Optional[str] = None,
    ):
        """记录步骤执行详情"""
        self.context.steps_detail.append(
            {
                "step": step,
                "name": name,
                "status": status,  # success / failed / skipped / cancelled
                "duration": round(duration, 2),
                "error": error,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def _needs_confirm(self, step: str) -> bool:
        """是否需要确认此步骤"""
        execute_mode = self.context.deploy_config.get("execute_mode", "auto")
        if execute_mode == "step_by_step":
            return True
        # 自动模式：仅危险操作需确认（在实际执行命令时检测）
        return False

    def _confirm(self, step: str, command: Optional[str] = None) -> bool:
        """调用确认回调"""
        if not self.confirm_callback:
            return True
        is_dangerous = bool(command and detect_dangerous_command(command))
        try:
            return self.confirm_callback(step, command or "", is_dangerous)
        except Exception:
            return True

    # ------------------------------------------------------------------
    # 模板方法
    # ------------------------------------------------------------------
    def execute(self) -> bool:
        """模板方法：按序执行部署步骤

        Returns: True 表示成功，False 表示失败
        """
        self.context.started_at = datetime.now()
        self.log(
            "info",
            f"开始部署: {self.context.project_config.get('project_name', 'unknown')}",
            "start",
        )

        total = len(DEPLOY_STEPS)

        try:
            for idx, (step_key, step_name) in enumerate(DEPLOY_STEPS):
                self._check_cancelled()
                self._current_step = step_key

                self.log(
                    "info",
                    f"[{idx + 1}/{total}] 开始执行: {step_name}",
                    step_key,
                )

                # 确认检查（每步确认模式）
                if self._needs_confirm(step_key):
                    if not self._confirm(step_key):
                        self.log("warn", f"步骤 '{step_name}' 被用户跳过", step_key)
                        self._record_step(step_key, step_name, "skipped", 0)
                        continue

                start = time.time()
                try:
                    method = getattr(self, step_key)
                    method()
                    duration = time.time() - start
                    self._record_step(step_key, step_name, "success", duration)
                    self.log(
                        "success",
                        f"步骤 '{step_name}' 完成 (耗时 {duration:.1f}s)",
                        step_key,
                    )
                except InterruptedError:
                    duration = time.time() - start
                    self._record_step(step_key, step_name, "cancelled", duration)
                    raise
                except Exception as e:
                    duration = time.time() - start
                    self._record_step(step_key, step_name, "failed", duration, str(e))
                    self.log("error", f"步骤 '{step_name}' 失败: {e}", step_key)
                    self.context.error_message = str(e)
                    # 触发回滚
                    self._do_rollback()
                    self.context.finished_at = datetime.now()
                    return False

            self.context.finished_at = datetime.now()
            if self.context.duration is not None:
                self.log(
                    "success",
                    f"部署完成，总耗时 {self.context.duration:.1f}s",
                    "done",
                )
            return True

        except InterruptedError:
            self.context.error_message = "部署已被用户取消"
            self.log("warn", "部署已取消", "cancelled")
            self.context.finished_at = datetime.now()
            return False
        except Exception as e:
            self.context.error_message = str(e)
            self.log("error", f"部署异常: {e}", "error")
            self.context.finished_at = datetime.now()
            return False

    def _do_rollback(self):
        """执行回滚"""
        self.log("warn", "开始执行回滚...", "rollback")
        try:
            self.rollback()
            self.context.is_rolled_back = True
            self.log("success", "回滚完成", "rollback")
        except Exception as e:
            self.log("error", f"回滚失败: {e}", "rollback")

    # ------------------------------------------------------------------
    # 抽象方法，子类实现
    # ------------------------------------------------------------------
    @abstractmethod
    def precheck(self):
        """预检：端口占用、磁盘空间、服务状态"""

    @abstractmethod
    def backup(self):
        """备份当前版本"""

    @abstractmethod
    def transfer(self):
        """传输部署包"""

    @abstractmethod
    def install(self):
        """安装部署文件"""

    @abstractmethod
    def configure(self):
        """更新配置"""

    @abstractmethod
    def start_service(self):
        """启动服务"""

    @abstractmethod
    def validate(self):
        """三重验证"""

    @abstractmethod
    def rollback(self):
        """回滚"""

    def cleanup(self):
        """清理临时文件（默认实现）"""
        self.log("info", "清理临时文件", "cleanup")
