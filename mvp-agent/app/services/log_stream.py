"""
WebSocket 日志流管理器

按 deploy_id 分组管理 WebSocket 连接，支持:
- 新连接补发历史日志（优先内存缓存，回退数据库）
- 推送日志到所有监听客户端
- 日志同时写入数据库 deploy_records.logs
"""
import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import WebSocket

from app.utils.logger import get_logger

logger = get_logger("log_stream")


class LogStreamManager:
    """日志流管理器

    管理 WebSocket 连接，按 task_id（deploy_id）分组。
    支持推送实时日志和历史日志补发。
    """

    def __init__(self):
        # task_id -> List[WebSocket]
        self._connections: Dict[int, List[WebSocket]] = defaultdict(list)
        # task_id -> 历史日志缓存（用于新连接补发）
        self._history: Dict[int, List[dict]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, task_id: int, websocket: WebSocket):
        """接受连接，发送历史日志，加入推送列表"""
        async with self._lock:
            self._connections[task_id].append(websocket)

        # 补发历史日志：优先内存缓存，回退数据库
        history = self._history.get(task_id, [])
        if not history:
            history = self._load_history_from_db(task_id)

        if history:
            for msg in history:
                try:
                    await websocket.send_text(json.dumps(msg, ensure_ascii=False))
                except Exception as e:
                    logger.warning(
                        f"补发历史日志失败: task_id={task_id}, error={e}"
                    )
                    break

    async def disconnect(self, task_id: int, websocket: WebSocket):
        """移除连接"""
        async with self._lock:
            if task_id in self._connections:
                try:
                    self._connections[task_id].remove(websocket)
                except ValueError:
                    pass
                if not self._connections[task_id]:
                    del self._connections[task_id]

    async def push_log(
        self,
        task_id: int,
        level: str,
        message: str,
        step: Optional[str] = None,
    ):
        """推送日志到所有监听客户端，同时缓存到历史并写入数据库

        Args:
            task_id: 部署任务 ID
            level: 日志级别 info/warn/error/success
            message: 日志消息
            step: 当前步骤名
        """
        timestamp = datetime.now().isoformat()
        msg = {
            "type": "log",
            "level": level,
            "message": message,
            "step": step or "",
            "timestamp": timestamp,
        }

        # 缓存到历史
        self._history[task_id].append(msg)

        # 写入数据库
        self._write_log_to_db(task_id, level, message, step, timestamp)

        # 推送到所有连接
        connections = self._connections.get(task_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_text(json.dumps(msg, ensure_ascii=False))
            except Exception as e:
                logger.warning(f"推送日志失败: task_id={task_id}, error={e}")
                dead.append(ws)

        # 清理断开的连接
        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self._connections.get(task_id, []):
                        self._connections[task_id].remove(ws)

    async def push_status(
        self,
        task_id: int,
        status: str,
        message: str = "",
    ):
        """推送状态变更"""
        timestamp = datetime.now().isoformat()
        msg = {
            "type": "status",
            "status": status,
            "message": message,
            "timestamp": timestamp,
        }

        self._history[task_id].append(msg)

        # 状态变更也写入数据库日志
        self._write_log_to_db(
            task_id, "info", f"[状态变更] {status}: {message}", "status", timestamp
        )

        connections = self._connections.get(task_id, [])
        for ws in connections:
            try:
                await ws.send_text(json.dumps(msg, ensure_ascii=False))
            except Exception:
                pass

    async def push_progress(
        self,
        task_id: int,
        current_step: int,
        total_steps: int,
        step_name: str = "",
    ):
        """推送进度更新"""
        timestamp = datetime.now().isoformat()
        progress = (
            round(current_step / total_steps * 100, 1) if total_steps > 0 else 0
        )
        msg = {
            "type": "progress",
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "progress": progress,
            "timestamp": timestamp,
        }

        self._history[task_id].append(msg)

        connections = self._connections.get(task_id, [])
        for ws in connections:
            try:
                await ws.send_text(json.dumps(msg, ensure_ascii=False))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 数据库操作
    # ------------------------------------------------------------------
    def _write_log_to_db(
        self,
        task_id: int,
        level: str,
        message: str,
        step: Optional[str],
        timestamp: str,
    ):
        """将日志写入数据库 deploy_records.logs 字段"""
        try:
            from app.models.database import SessionLocal
            from app.models.deploy_record import DeployRecord

            db = SessionLocal()
            try:
                record = (
                    db.query(DeployRecord)
                    .filter(DeployRecord.id == task_id)
                    .first()
                )
                if record:
                    log_line = (
                        f"[{timestamp}] [{level.upper()}] "
                        f"[{step or ''}] {message}\n"
                    )
                    record.logs = (record.logs or "") + log_line
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"写入日志到数据库失败: task_id={task_id}, error={e}")

    def _load_history_from_db(self, task_id: int) -> List[dict]:
        """从数据库加载历史日志（内存缓存为空时回退）

        解析 deploy_records.logs 文本字段为结构化消息列表。
        """
        try:
            from app.models.database import SessionLocal
            from app.models.deploy_record import DeployRecord

            db = SessionLocal()
            try:
                record = (
                    db.query(DeployRecord)
                    .filter(DeployRecord.id == task_id)
                    .first()
                )
                if not record or not record.logs:
                    return []

                messages = []
                # 解析格式: [timestamp] [LEVEL] [step] message
                pattern = re.compile(
                    r"\[([^\]]+)\] \[([^\]]+)\] \[([^\]]*)\] (.+)"
                )
                for line in record.logs.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    match = pattern.match(line)
                    if match:
                        ts, level, step, msg_text = match.groups()
                        # 判断是否为状态变更日志
                        if msg_text.startswith("[状态变更]"):
                            status_msg = msg_text.replace("[状态变更] ", "")
                            messages.append(
                                {
                                    "type": "status",
                                    "status": status_msg.split(":")[0].strip()
                                    if ":" in status_msg
                                    else "",
                                    "message": status_msg,
                                    "timestamp": ts,
                                }
                            )
                        else:
                            messages.append(
                                {
                                    "type": "log",
                                    "level": level.lower(),
                                    "message": msg_text,
                                    "step": step,
                                    "timestamp": ts,
                                }
                            )
                return messages
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"从数据库加载历史日志失败: task_id={task_id}, error={e}")
            return []

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def clear_history(self, task_id: int):
        """清理指定任务的历史日志缓存"""
        if task_id in self._history:
            del self._history[task_id]

    def get_connection_count(self, task_id: int) -> int:
        """获取指定任务的连接数"""
        return len(self._connections.get(task_id, []))


# 全局单例
log_stream_manager = LogStreamManager()
