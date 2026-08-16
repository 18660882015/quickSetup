"""
主机管理 API：CRUD + 测试连接 + 采集主机参数

- 密码 AES 加密存储
- 查询响应不返回密码字段
- 测试连接：本地直接返回，远程创建临时 SSH 连接
- 采集参数：本地用 psutil，远程用 SSH 命令
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import decrypt, encrypt, get_current_user
from app.core.ssh_client import SSHConnection, ssh_pool
from app.models.database import get_db
from app.models.host import Host
from app.schemas.common import ApiResponse, success
from app.schemas.host import (
    HostCreate,
    HostInspectResult,
    HostResponse,
    HostTestResult,
    HostUpdate,
)
from app.utils.logger import get_logger

logger = get_logger("api.hosts")

router = APIRouter(prefix="/hosts", tags=["主机管理"])


@router.get("", response_model=ApiResponse, summary="获取所有主机列表")
def list_hosts(
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """获取所有主机列表（不返回密码字段）"""
    hosts = db.query(Host).order_by(Host.created_at.desc()).all()
    # 转换为响应模型，排除密码字段
    result = [HostResponse.model_validate(h).model_dump() for h in hosts]
    return success(data=result)


@router.post("", response_model=ApiResponse, summary="添加主机")
def create_host(
    host: HostCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """添加新主机（密码 AES 加密后存储）"""
    # 创建主机实例
    db_host = Host(
        name=host.name,
        ip=host.ip,
        port=host.port,
        username=host.username,
        auth_type=host.auth_type,
        jdk_version=host.jdk_version,
        deploy_dir=host.deploy_dir,
        backup_dir=host.backup_dir,
        is_local=host.is_local,
        status="online" if host.is_local else "unknown",
    )

    # 加密密码
    if host.password:
        db_host.password = encrypt(host.password)
    if host.private_key:
        db_host.private_key = encrypt(host.private_key)

    db.add(db_host)
    db.commit()
    db.refresh(db_host)

    logger.info(f"添加主机: {db_host.name} ({db_host.ip})")

    result = HostResponse.model_validate(db_host).model_dump()
    return success(data=result, msg="主机添加成功")


@router.get("/{host_id}", response_model=ApiResponse, summary="获取主机详情")
def get_host(
    host_id: int,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """获取主机详情（不返回密码）"""
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")

    result = HostResponse.model_validate(host).model_dump()
    return success(data=result)


@router.put("/{host_id}", response_model=ApiResponse, summary="更新主机信息")
def update_host(
    host_id: int,
    host_update: HostUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """更新主机信息（如提供密码则加密存储）"""
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")

    update_data = host_update.model_dump(exclude_unset=True)

    # 密码单独加密处理
    password = update_data.pop("password", None)
    private_key = update_data.pop("private_key", None)

    # 更新普通字段
    for field, value in update_data.items():
        setattr(host, field, value)

    # 更新密码
    if password is not None:
        host.password = encrypt(password) if password else None
    if private_key is not None:
        host.private_key = encrypt(private_key) if private_key else None

    db.commit()
    db.refresh(host)

    logger.info(f"更新主机: {host.name} (id={host.id})")

    result = HostResponse.model_validate(host).model_dump()
    return success(data=result, msg="主机更新成功")


@router.delete("/{host_id}", response_model=ApiResponse, summary="删除主机")
def delete_host(
    host_id: int,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """删除主机（同时关闭 SSH 连接）"""
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")

    host_name = host.name

    # 关闭 SSH 连接
    try:
        ssh_pool.close_connection(host_id)
    except Exception:
        pass

    db.delete(host)
    db.commit()

    logger.info(f"删除主机: {host_name} (id={host_id})")

    return success(msg="主机删除成功")


@router.post("/{host_id}/test", response_model=ApiResponse, summary="测试主机连接")
def test_host(
    host_id: int,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """测试 SSH 连接是否成功

    本地主机直接返回成功。
    远程主机创建临时 SSH 连接，执行 uname -a 返回 OS 信息。
    """
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")

    # 本地主机直接返回成功
    if host.is_local:
        result = HostTestResult(
            success=True,
            message="本地主机连接成功",
            os_info=f"Local Windows ({host.ip})",
        )
        return success(data=result.model_dump())

    # 远程主机：创建临时 SSH 连接测试
    password = decrypt(host.password) if host.password else None
    private_key = decrypt(host.private_key) if host.private_key else None

    if host.auth_type == "password" and not password:
        result = HostTestResult(
            success=False, message="未配置密码，无法测试连接"
        )
        return success(data=result.model_dump())

    if host.auth_type == "key" and not private_key:
        result = HostTestResult(
            success=False, message="未配置私钥，无法测试连接"
        )
        return success(data=result.model_dump())

    try:
        # 创建临时连接测试
        conn = SSHConnection(
            host_id=host.id,
            host=host.ip,
            port=host.port,
            username=host.username,
            password=password if host.auth_type == "password" else None,
            private_key=private_key if host.auth_type == "key" else None,
            timeout=10,
        )

        try:
            stdout, stderr, exit_code = conn.execute("uname -a")
            os_info = stdout.strip() if exit_code == 0 else None

            if exit_code == 0:
                result = HostTestResult(
                    success=True,
                    message=f"SSH 连接成功: {host.ip}:{host.port}",
                    os_info=os_info,
                )
                # 更新主机状态为 online
                host.status = "online"
                if os_info:
                    host.os_info = os_info
                db.commit()
            else:
                result = HostTestResult(
                    success=False,
                    message=f"SSH 连接成功但命令执行失败: {stderr}",
                )
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"SSH 连接测试失败: {host.ip}:{host.port}, error={e}")
        # 更新主机状态为 offline
        host.status = "offline"
        db.commit()

        result = HostTestResult(
            success=False,
            message=f"SSH 连接失败: {e}",
        )

    return success(data=result.model_dump())


@router.get("/{host_id}/inspect", response_model=ApiResponse, summary="采集主机参数信息")
def inspect_host(
    host_id: int,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """采集主机参数信息（CPU、内存、OS、服务状态）

    本地用 psutil，远程用 SSH 命令。
    """
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")

    # 本地主机：使用 psutil
    if host.is_local:
        result = _inspect_local(host)
        # 更新主机参数信息
        _update_host_info(host, result, db)
        return success(data=result.model_dump())

    # 远程主机：使用 SSH 命令
    password = decrypt(host.password) if host.password else None
    private_key = decrypt(host.private_key) if host.private_key else None

    if host.auth_type == "password" and not password:
        return success(
            data=HostInspectResult(
                success=False, message="未配置密码，无法采集信息"
            ).model_dump()
        )

    try:
        conn = ssh_pool.get_connection(
            host.id,
            {
                "ip": host.ip,
                "port": host.port,
                "username": host.username,
                "auth_type": host.auth_type,
                "password": host.password,
                "private_key": host.private_key,
            },
            decrypt_fn=decrypt,
        )

        result = _inspect_remote(conn)

        # 更新主机参数信息
        _update_host_info(host, result, db)

    except Exception as e:
        logger.error(f"远程主机信息采集失败: {host.ip}, error={e}")
        result = HostInspectResult(
            success=False, message=f"采集失败: {e}"
        )

    return success(data=result.model_dump())


# ======================================================================
# 辅助函数
# ======================================================================
def _inspect_local(host: Host) -> HostInspectResult:
    """本地主机信息采集（使用 psutil）"""
    try:
        import psutil
        import platform

        # OS 信息
        os_info = (
            f"{platform.system()} {platform.release()} "
            f"({platform.machine()})"
        )

        # CPU 信息
        cpu_count = psutil.cpu_count(logical=True)
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_info = f"CPU 核心数: {cpu_count}, 使用率: {cpu_percent}%"

        # 内存信息
        mem = psutil.virtual_memory()
        mem_total_gb = mem.total / (1024**3)
        mem_used_gb = mem.used / (1024**3)
        memory_info = (
            f"总内存: {mem_total_gb:.1f}GB, "
            f"已用: {mem_used_gb:.1f}GB ({mem.percent}%)"
        )

        # 磁盘信息
        disk_parts = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                total_gb = usage.total / (1024**3)
                used_gb = usage.used / (1024**3)
                disk_parts.append(
                    f"{partition.device}: {used_gb:.1f}GB / {total_gb:.1f}GB "
                    f"({usage.percent}%)"
                )
            except Exception:
                continue
        disk_info = "; ".join(disk_parts) if disk_parts else "无可用磁盘信息"

        return HostInspectResult(
            success=True,
            message="本地主机信息采集成功",
            os_info=os_info,
            cpu_info=cpu_info,
            memory_info=memory_info,
            disk_info=disk_info,
        )
    except Exception as e:
        return HostInspectResult(
            success=False, message=f"本地信息采集失败: {e}"
        )


def _inspect_remote(conn: SSHConnection) -> HostInspectResult:
    """远程主机信息采集（使用 SSH 命令）"""
    try:
        # OS 信息
        stdout, _, exit_code = conn.execute("cat /etc/os-release 2>/dev/null | head -5")
        os_info = stdout.strip() if exit_code == 0 else "Unknown"
        if not os_info:
            stdout, _, _ = conn.execute("uname -a")
            os_info = stdout.strip()

        # CPU 信息
        stdout, _, _ = conn.execute(
            "echo 'CPU核心数:' $(nproc) && "
            "echo 'CPU使用率:' $(top -bn1 | grep 'Cpu(s)' | "
            "awk '{print $2}')'%'"
        )
        cpu_info = stdout.strip()

        # 内存信息
        stdout, _, _ = conn.execute("free -h | grep Mem")
        memory_info = stdout.strip()

        # 磁盘信息
        stdout, _, _ = conn.execute("df -h | grep -v tmpfs | grep -v devtmpfs")
        disk_info = stdout.strip()

        return HostInspectResult(
            success=True,
            message="远程主机信息采集成功",
            os_info=os_info,
            cpu_info=cpu_info,
            memory_info=memory_info,
            disk_info=disk_info,
        )
    except Exception as e:
        return HostInspectResult(
            success=False, message=f"远程信息采集失败: {e}"
        )


def _update_host_info(host: Host, result: HostInspectResult, db: Session):
    """更新主机参数信息到数据库"""
    try:
        if result.success:
            host.os_info = result.os_info
            host.cpu_info = result.cpu_info
            host.memory_info = result.memory_info
            host.disk_info = result.disk_info
            host.status = "online"
            db.commit()
    except Exception as e:
        logger.warning(f"更新主机信息失败: {e}")
