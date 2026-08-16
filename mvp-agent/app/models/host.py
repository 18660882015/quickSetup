"""
hosts 表 - 主机信息
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime

from app.models.database import Base


class Host(Base):
    """主机信息表"""

    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="主机名称")
    ip = Column(String(45), nullable=False, comment="IP地址")
    port = Column(Integer, nullable=False, default=22, comment="SSH端口")
    username = Column(String(50), nullable=False, default="root", comment="SSH用户名")

    # 认证方式: password / key
    auth_type = Column(String(10), nullable=False, default="password", comment="认证方式")

    # AES 加密存储的密码
    password = Column(Text, nullable=True, comment="AES加密后的密码")
    # AES 加密存储的私钥
    private_key = Column(Text, nullable=True, comment="AES加密后的私钥")

    # 部署配置
    jdk_version = Column(String(10), nullable=True, default="8", comment="JDK版本")
    deploy_dir = Column(String(255), nullable=True, comment="部署目录")
    backup_dir = Column(String(255), nullable=True, comment="备份目录")

    # 状态: online / offline / unknown
    status = Column(String(20), nullable=False, default="unknown", comment="主机状态")

    # 是否本地主机
    is_local = Column(Boolean, nullable=False, default=False, comment="是否本地主机")

    # 主机参数信息
    os_info = Column(Text, nullable=True, comment="操作系统信息")
    cpu_info = Column(Text, nullable=True, comment="CPU信息")
    memory_info = Column(Text, nullable=True, comment="内存信息")
    disk_info = Column(Text, nullable=True, comment="磁盘信息")

    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    def __repr__(self):
        return f"<Host(id={self.id}, name={self.name}, ip={self.ip})>"
