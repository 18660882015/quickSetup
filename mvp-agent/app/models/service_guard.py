"""
service_guards 表 - 进程守护配置
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey

from app.models.database import Base


class ServiceGuard(Base):
    """进程守护配置表

    每条记录对应一个被守护的服务：
    - host 为空（host_id 为 NULL）表示本地 Windows 服务
    - status 为 stopped 且 enabled 时，定时任务自动执行 restart_command
    """

    __tablename__ = "service_guards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="守护项名称")
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True, comment="目标主机ID（空=本地）")
    service_name = Column(String(50), nullable=False, comment="服务名: nginx/tomcat/mysql/redis/自定义")

    # 重启命令：本地为 cmd 命令；远程为 shell 命令
    restart_command = Column(Text, nullable=True, comment="重启命令（空则使用内置默认命令）")

    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用守护")
    max_restart = Column(Integer, nullable=False, default=3, comment="最大连续重启次数")

    # 运行时状态
    consecutive_restarts = Column(Integer, nullable=False, default=0, comment="连续重启次数")
    last_status = Column(String(20), nullable=True, comment="最近一次检查状态")
    last_check_at = Column(DateTime, nullable=True, comment="最近检查时间")
    last_restart_at = Column(DateTime, nullable=True, comment="最近重启时间")
    last_error = Column(Text, nullable=True, comment="最近错误信息")

    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    def __repr__(self):
        return f"<ServiceGuard(id={self.id}, name={self.name}, service={self.service_name})>"
