"""
deploy_records 表 - 部署记录
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, JSON
from sqlalchemy.orm import relationship

from app.models.database import Base


class DeployRecord(Base):
    """部署记录表"""

    __tablename__ = "deploy_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True, comment="主机ID")

    project_name = Column(String(200), nullable=False, comment="项目名称")
    env_type = Column(String(20), nullable=False, default="prod", comment="环境类型: dev/prod")

    # 执行状态: pending / running / success / failed / rolled_back / cancelled
    execute_status = Column(String(20), nullable=False, default="pending", comment="执行状态")

    # 执行模式: auto / step_by_step
    execute_mode = Column(String(20), nullable=False, default="auto", comment="执行模式")

    jdk_version = Column(String(10), nullable=True, comment="JDK版本")
    db_name = Column(String(100), nullable=True, comment="数据库名")

    # 文件路径
    log_path = Column(String(500), nullable=True, comment="日志文件路径")
    backup_path = Column(String(500), nullable=True, comment="备份路径")
    version = Column(String(100), nullable=True, comment="版本号")

    # 部署步骤明细 JSON: [{step, status, duration, error}]
    steps_detail = Column(JSON, nullable=True, comment="步骤明细")

    # 完整部署日志
    logs = Column(Text, nullable=True, default="", comment="完整部署日志")

    # AI 建议
    ai_suggestion = Column(Text, nullable=True, comment="AI建议")

    # 回滚信息 JSON
    rollback_info = Column(JSON, nullable=True, comment="回滚信息")

    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration = Column(Float, nullable=True, comment="耗时（秒）")

    error_message = Column(Text, nullable=True, comment="错误信息")
    operator = Column(String(50), nullable=True, default="admin", comment="操作人")

    can_rollback = Column(Boolean, nullable=False, default=False, comment="是否可回滚")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    # 关联关系
    host = relationship("Host", backref="deploy_records", lazy="select")

    def __repr__(self):
        return (
            f"<DeployRecord(id={self.id}, project={self.project_name}, "
            f"status={self.execute_status})>"
        )
