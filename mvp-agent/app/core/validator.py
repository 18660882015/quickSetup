"""
三重验证器

- check_port(port): 远程 netstat -tlnp|grep, 本地 netstat -ano|findstr
- check_http(url): httpx.get 检查 HTTP 200
- check_log(log_path, keywords): 检查 ERROR/Exception/OutOfMemoryError
- validate_all(ports, http_urls, log_path): 返回结构化结果
"""
import os
import subprocess
from typing import Dict, List, Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger("validator")

# 日志错误关键字（与 deploy_config.yaml 中 log_error_keywords 一致）
LOG_ERROR_KEYWORDS = [
    "ERROR",
    "Exception",
    "OutOfMemoryError",
    "StackOverflowError",
    "NullPointerException",
    "FATAL",
    "CRITICAL",
]


class Validator:
    """三重验证器

    支持本地（Windows）和远程（SSH）两种模式。
    """

    def __init__(self, is_local: bool = False, ssh_conn=None):
        """
        Args:
            is_local: 是否本地部署
            ssh_conn: SSH 连接（远程部署时使用 SSHConnection 实例）
        """
        self.is_local = is_local
        self.ssh_conn = ssh_conn

    # ------------------------------------------------------------------
    # 端口检查
    # ------------------------------------------------------------------
    def check_port(self, port: int) -> Dict:
        """检查端口监听状态

        本地: netstat -ano | findstr :{port}
        远程: netstat -tlnp | grep :{port}
        """
        port = int(port)

        if self.is_local:
            try:
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                lines = [
                    l
                    for l in result.stdout.splitlines()
                    if f":{port}" in l and "LISTENING" in l.upper()
                ]
                if lines:
                    return {"passed": True, "detail": f"端口 {port} 监听正常"}
                return {"passed": False, "detail": f"端口 {port} 未监听"}
            except Exception as e:
                return {"passed": False, "detail": f"端口检查失败: {e}"}
        else:
            if not self.ssh_conn:
                return {"passed": False, "detail": "无 SSH 连接，无法检查远程端口"}
            try:
                stdout, _, _ = self.ssh_conn.execute(
                    f"netstat -tlnp 2>/dev/null | grep ':{port} '"
                )
                if stdout.strip():
                    return {"passed": True, "detail": f"端口 {port} 监听正常"}
                return {"passed": False, "detail": f"端口 {port} 未监听"}
            except Exception as e:
                return {"passed": False, "detail": f"端口检查失败: {e}"}

    # ------------------------------------------------------------------
    # HTTP 健康检查
    # ------------------------------------------------------------------
    def check_http(self, url: str) -> Dict:
        """检查 HTTP 健康状态

        httpx.get(url, timeout=5)，检查 HTTP 200。
        """
        try:
            resp = httpx.get(url, timeout=5, follow_redirects=True)
            if resp.status_code == 200:
                return {"passed": True, "detail": f"HTTP 200 OK ({url})"}
            return {
                "passed": False,
                "detail": f"HTTP {resp.status_code} ({url})",
            }
        except httpx.TimeoutException:
            return {"passed": False, "detail": f"HTTP 请求超时 ({url})"}
        except httpx.ConnectError:
            return {"passed": False, "detail": f"HTTP 连接失败 ({url})"}
        except Exception as e:
            return {"passed": False, "detail": f"HTTP 检查失败 ({url}): {e}"}

    # ------------------------------------------------------------------
    # 日志关键字检查
    # ------------------------------------------------------------------
    def check_log(
        self, log_path: str, keywords: Optional[List[str]] = None
    ) -> Dict:
        """检查日志中的错误关键字

        检查 ERROR、Exception、OutOfMemoryError 等关键字。
        """
        if not keywords:
            keywords = LOG_ERROR_KEYWORDS

        if self.is_local:
            if not os.path.exists(log_path):
                return {
                    "passed": True,
                    "detail": f"日志文件不存在，跳过检查: {log_path}",
                }
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                found = [kw for kw in keywords if kw in content]
                if found:
                    return {
                        "passed": False,
                        "detail": f"日志中发现错误关键字: {', '.join(found)}",
                    }
                return {"passed": True, "detail": "未发现错误关键字"}
            except Exception as e:
                return {"passed": False, "detail": f"日志检查失败: {e}"}
        else:
            if not self.ssh_conn:
                return {"passed": False, "detail": "无 SSH 连接，无法检查远程日志"}
            try:
                # 检查日志文件是否存在
                stdout, _, _ = self.ssh_conn.execute(
                    f"test -f {log_path} && echo exists"
                )
                if "exists" not in stdout:
                    return {
                        "passed": True,
                        "detail": f"日志文件不存在，跳过检查: {log_path}",
                    }
                # 读取最后 500 行
                stdout, _, _ = self.ssh_conn.execute(f"tail -n 500 {log_path}")
                found = [kw for kw in keywords if kw in stdout]
                if found:
                    return {
                        "passed": False,
                        "detail": f"日志中发现错误关键字: {', '.join(found)}",
                    }
                return {"passed": True, "detail": "未发现错误关键字"}
            except Exception as e:
                return {"passed": False, "detail": f"日志检查失败: {e}"}

    # ------------------------------------------------------------------
    # 综合验证
    # ------------------------------------------------------------------
    def validate_all(
        self,
        ports: List[int],
        http_urls: List[str],
        log_path: Optional[str] = None,
    ) -> Dict:
        """执行全部验证，返回结构化结果

        Returns:
            {
                "port_80": {"passed": True, "detail": "..."},
                "port_8080": {"passed": True, "detail": "..."},
                "http_0": {"passed": True, "detail": "..."},
                "log_check": {"passed": True, "detail": "..."},
                "overall": True/False
            }
        """
        results: Dict = {}
        all_passed = True

        # 端口检查
        for port in ports:
            key = f"port_{port}"
            result = self.check_port(port)
            results[key] = result
            if not result["passed"]:
                all_passed = False

        # HTTP 检查
        for i, url in enumerate(http_urls):
            key = f"http_{i}"
            result = self.check_http(url)
            results[key] = result
            if not result["passed"]:
                all_passed = False

        # 日志检查
        if log_path:
            result = self.check_log(log_path)
            results["log_check"] = result
            if not result["passed"]:
                all_passed = False

        results["overall"] = all_passed
        return results
