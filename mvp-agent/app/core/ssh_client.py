"""
SSH 连接池管理

- SSHConnection: 包装 paramiko.SSHClient，内部 threading.Lock 保证命令串行执行
- SSHConnectionPool: dict 缓存（host_id 为 key），get/close/cleanup
"""
import io
import threading
import time
from typing import Callable, Optional, Tuple

import paramiko

from app.utils.logger import get_logger

logger = get_logger("ssh_client")


class SSHConnection:
    """SSH 连接包装类

    内部 threading.Lock 保证命令串行执行。
    支持 execute（同步）和 exec_command_stream（流式实时回调）。
    """

    def __init__(
        self,
        host_id: int,
        host: str,
        port: int,
        username: str,
        password: Optional[str] = None,
        private_key: Optional[str] = None,
        timeout: int = 10,
    ):
        self.host_id = host_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.timeout = timeout
        self._lock = threading.Lock()
        self._client: Optional[paramiko.SSHClient] = None
        self._last_used = time.time()
        self._connect()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def _connect(self):
        """建立 SSH 连接"""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }

        if self.private_key:
            # 密钥认证
            key_file = io.StringIO(self.private_key)
            pkey = None
            for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
                try:
                    key_file.seek(0)
                    pkey = key_class.from_private_key(key_file)
                    break
                except Exception:
                    continue
            if pkey is None:
                raise ValueError("无法解析 SSH 私钥，请检查密钥格式")
            connect_kwargs["pkey"] = pkey
        elif self.password:
            connect_kwargs["password"] = self.password
        else:
            raise ValueError("SSH 连接需要密码或私钥")

        self._client.connect(**connect_kwargs)
        logger.info(
            f"SSH 连接成功: {self.host}:{self.port} (host_id={self.host_id})"
        )

    def is_active(self) -> bool:
        """检查连接是否活跃"""
        if self._client is None:
            return False
        transport = self._client.get_transport()
        if transport is None:
            return False
        return transport.is_active()

    def reconnect(self) -> bool:
        """重新连接"""
        try:
            self._close_client()
            self._connect()
            return True
        except Exception as e:
            logger.error(f"SSH 重连失败: {self.host}:{self.port}, error={e}")
            return False

    def _close_client(self):
        """关闭底层 client"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def close(self):
        """关闭连接"""
        self._close_client()
        logger.info(f"SSH 连接已关闭: {self.host}:{self.port} (host_id={self.host_id})")

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------
    def execute(self, command: str, timeout: Optional[int] = None) -> Tuple[str, str, int]:
        """执行命令，返回 (stdout, stderr, exit_code)

        通过内部锁保证串行执行。
        """
        with self._lock:
            self._ensure_active()
            self._last_used = time.time()

            stdin, stdout, stderr = self._client.exec_command(
                command, timeout=timeout
            )
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return out, err, exit_code

    def exec_command_stream(
        self,
        command: str,
        callback: Optional[Callable[[str], None]] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[str, int]:
        """流式执行命令，实时回调输出

        通过 channel + get_pty() + recv_ready() 轮询，
        适配 WebSocket 日志推送需求。

        Returns:
            (full_output, exit_code)
        """
        with self._lock:
            self._ensure_active()
            self._last_used = time.time()

            transport = self._client.get_transport()
            chan = transport.open_session()
            chan.settimeout(timeout)
            chan.get_pty()
            chan.exec_command(command)

            full_output = ""
            start_time = time.time()

            try:
                while True:
                    # 超时检查
                    if timeout and (time.time() - start_time) > timeout:
                        chan.close()
                        raise TimeoutError(f"命令执行超时({timeout}s): {command}")

                    if chan.recv_ready():
                        data = chan.recv(4096).decode("utf-8", errors="replace")
                        full_output += data
                        if callback and data.strip():
                            callback(data)

                    if chan.exit_status_ready() and not chan.recv_ready():
                        break

                    time.sleep(0.1)

                # 读取残留数据
                while chan.recv_ready():
                    data = chan.recv(4096).decode("utf-8", errors="replace")
                    full_output += data
                    if callback and data.strip():
                        callback(data)

                exit_code = chan.recv_exit_status()
                chan.close()
                return full_output, exit_code
            except Exception:
                try:
                    chan.close()
                except Exception:
                    pass
                raise

    def get_sftp(self) -> paramiko.SFTPClient:
        """获取 SFTP 通道"""
        with self._lock:
            self._ensure_active()
            self._last_used = time.time()
            return self._client.open_sftp()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _ensure_active(self):
        """确保连接活跃，否则尝试重连"""
        if not self.is_active():
            if not self.reconnect():
                raise ConnectionError(
                    f"SSH 连接已断开且重连失败: {self.host}:{self.port}"
                )

    @property
    def last_used(self) -> float:
        return self._last_used

    @property
    def idle_seconds(self) -> float:
        """空闲秒数"""
        return time.time() - self._last_used


class SSHConnectionPool:
    """SSH 连接池

    基于 dict 缓存，key 为 host_id。
    threading.Lock 保护连接池操作。
    """

    # 空闲超时（秒），超过此时间未使用的连接将被清理
    IDLE_TIMEOUT = 1800  # 30 分钟

    def __init__(self):
        self._pool: dict = {}  # host_id -> SSHConnection
        self._lock = threading.Lock()

    def get_connection(
        self,
        host_id: int,
        host_config: dict,
        decrypt_fn: Optional[Callable[[str], str]] = None,
    ) -> SSHConnection:
        """获取或创建连接

        Args:
            host_id: 主机 ID
            host_config: 主机配置字典
                - ip, port, username, auth_type, password, private_key
            decrypt_fn: 解密函数（用于解密密码/私钥）
        """
        # 尝试从池中获取
        with self._lock:
            conn = self._pool.get(host_id)
            if conn is not None:
                if conn.is_active():
                    return conn
                # 尝试重连
                if conn.reconnect():
                    return conn
                # 重连失败，移除
                del self._pool[host_id]

        # 在锁外创建新连接（避免长时间持锁）
        password = host_config.get("password")
        private_key = host_config.get("private_key")

        if decrypt_fn:
            if password:
                password = decrypt_fn(password)
            if private_key:
                private_key = decrypt_fn(private_key)

        auth_type = host_config.get("auth_type", "password")
        conn = SSHConnection(
            host_id=host_id,
            host=host_config["ip"],
            port=host_config.get("port", 22),
            username=host_config.get("username", "root"),
            password=password if auth_type == "password" else None,
            private_key=private_key if auth_type == "key" else None,
            timeout=host_config.get("timeout", 10),
        )

        with self._lock:
            # 如果已有其他线程抢先创建，关闭新建的并返回已有的
            existing = self._pool.get(host_id)
            if existing is not None and existing.is_active():
                conn.close()
                return existing
            self._pool[host_id] = conn

        return conn

    def close_connection(self, host_id: int):
        """关闭指定连接"""
        with self._lock:
            conn = self._pool.pop(host_id, None)
        if conn:
            conn.close()

    def close_all(self):
        """关闭所有连接"""
        with self._lock:
            connections = list(self._pool.values())
            self._pool.clear()
        for conn in connections:
            try:
                conn.close()
            except Exception:
                pass
        logger.info(f"关闭所有 SSH 连接: {len(connections)} 个")

    def cleanup_idle(self):
        """清理空闲连接（APScheduler 每 30 分钟调用）"""
        with self._lock:
            idle_ids = [
                hid
                for hid, conn in self._pool.items()
                if conn.idle_seconds > self.IDLE_TIMEOUT
            ]
            for hid in idle_ids:
                conn = self._pool.pop(hid, None)
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
        if idle_ids:
            logger.info(f"清理空闲 SSH 连接: {len(idle_ids)} 个 (host_ids={idle_ids})")


# 全局连接池单例
ssh_pool = SSHConnectionPool()
