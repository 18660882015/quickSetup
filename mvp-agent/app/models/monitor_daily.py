"""
monitor_dailies 表 - 每日监控数据
"""
from datetime import datetime, date

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey, Date
from sqlalchemy.orm import relationship

from app.models.database import Base


class MonitorDaily(Base):
    """每日监控数据表"""

    __tablename__ = "monitor_dailies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True, comment="主机ID")

    check_date = Column(Date, nullable=False, default=date.today, comment="检查日期")

    # 服务状态: running / stopped / unknown
    tomcat_status = Column(String(20), nullable=True, comment="Tomcat状态")
    nginx_status = Column(String(20), nullable=True, comment="Nginx状态")
    mysql_status = Column(String(20), nullable=True, comment="MySQL状态")
    redis_status = Column(String(20), nullable=True, comment="Redis状态")

    # 资源使用率
    cpu_usage = Column(Float, nullable=True, comment="CPU使用率(%)")
    memory_usage = Column(Float, nullable=True, comment="内存使用率(%)")
    disk_usage = Column(Float, nullable=True, comment="磁盘使用率(%)")

    error_log_count = Column(Integer, nullable=False, default=0, comment="错误日志数")

    ai_alert_summary = Column(Text, nullable=True, comment="AI告警总结")
    dingtalk_pushed = Column(Boolean, nullable=False, default=False, comment="是否已推送钉钉")

    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    # 关联关系
    host = relationship("Host", backref="monitor_dailies", lazy="select")

    def __repr__(self):
        return f"<MonitorDaily(id={self.id}, host_id={self.host_id}, date={self.check_date})>"
