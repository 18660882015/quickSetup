"""
监控数据 API

- GET /api/v1/monitor/latest: 获取所有主机最新监控数据
- GET /api/v1/monitor/history/{host_id}: 获取主机监控历史
- GET /api/v1/monitor/daily-report: 获取最新日报
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.models.database import get_db
from app.models.host import Host
from app.models.monitor_daily import MonitorDaily
from app.schemas.common import ApiResponse, success
from app.utils.logger import get_logger

logger = get_logger("api.monitor")

router = APIRouter(prefix="/monitor", tags=["监控管理"])


def _monitor_to_dict(m: MonitorDaily, host_name: str = None) -> dict:
    """将 MonitorDaily 模型转为字典"""
    return {
        "id": m.id,
        "host_id": m.host_id,
        "host_name": host_name,
        "check_date": m.check_date.isoformat() if m.check_date else None,
        "tomcat_status": m.tomcat_status,
        "nginx_status": m.nginx_status,
        "mysql_status": m.mysql_status,
        "redis_status": m.redis_status,
        "cpu_usage": m.cpu_usage,
        "memory_usage": m.memory_usage,
        "disk_usage": m.disk_usage,
        "error_log_count": m.error_log_count,
        "ai_alert_summary": m.ai_alert_summary,
        "dingtalk_pushed": m.dingtalk_pushed,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/latest", response_model=ApiResponse, summary="获取所有主机最新监控数据")
def get_latest_monitor(
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """获取所有主机最新监控数据

    返回每台主机最近一次采集的监控数据。
    """
    # 获取所有主机
    hosts = db.query(Host).all()
    host_map = {h.id: h for h in hosts}

    # 获取每台主机最新的监控记录
    results = []
    for host in hosts:
        # 查询该主机最新的监控记录
        latest = (
            db.query(MonitorDaily)
            .filter(MonitorDaily.host_id == host.id)
            .order_by(desc(MonitorDaily.created_at))
            .first()
        )
        if latest:
            results.append(_monitor_to_dict(latest, host.name))
        else:
            # 无监控数据的主机
            results.append({
                "host_id": host.id,
                "host_name": host.name,
                "ip": host.ip,
                "status": host.status,
                "message": "暂无监控数据",
            })

    return success(data=results)


@router.get("/history/{host_id}", response_model=ApiResponse, summary="获取主机监控历史")
def get_monitor_history(
    host_id: int,
    days: int = Query(default=7, ge=1, le=90, description="查询天数"),
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """获取主机监控历史数据

    Args:
        host_id: 主机 ID
        days: 查询天数（默认 7 天，最大 90 天）
    """
    # 检查主机是否存在
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="主机不存在")

    # 计算日期范围
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # 查询历史数据
    records = (
        db.query(MonitorDaily)
        .filter(
            MonitorDaily.host_id == host_id,
            MonitorDaily.check_date >= start_date,
            MonitorDaily.check_date <= end_date,
        )
        .order_by(desc(MonitorDaily.created_at))
        .all()
    )

    results = [_monitor_to_dict(r, host.name) for r in records]

    return success(data={
        "host_id": host_id,
        "host_name": host.name,
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "records": results,
        "total": len(results),
    })


@router.get("/daily-report", response_model=ApiResponse, summary="获取最新日报")
def get_daily_report(
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """获取最新的监控日报

    返回最近一天的监控数据和 AI 告警总结。
    """
    # 获取今天的数据
    today = date.today()

    # 查询最新的日报记录（按 created_at 降序，取所有主机最新一批）
    latest_records = (
        db.query(MonitorDaily)
        .filter(MonitorDaily.check_date == today)
        .order_by(desc(MonitorDaily.created_at))
        .all()
    )

    # 如果今天没有数据，尝试获取最近一天的数据
    if not latest_records:
        latest_date = (
            db.query(func.max(MonitorDaily.check_date))
            .scalar()
        )
        if latest_date:
            latest_records = (
                db.query(MonitorDaily)
                .filter(MonitorDaily.check_date == latest_date)
                .order_by(desc(MonitorDaily.created_at))
                .all()
            )
            today = latest_date

    if not latest_records:
        return success(data={
            "check_date": today.isoformat() if today else None,
            "records": [],
            "ai_summary": None,
            "dingtalk_pushed": False,
            "message": "暂无监控日报数据",
        })

    # 获取主机名映射
    host_ids = {r.host_id for r in latest_records if r.host_id}
    hosts = db.query(Host).filter(Host.id.in_(host_ids)).all()
    host_map = {h.id: h.name for h in hosts}

    results = []
    ai_summary = None
    dingtalk_pushed = False

    for r in latest_records:
        host_name = host_map.get(r.host_id, "未知")
        results.append(_monitor_to_dict(r, host_name))
        # 取第一条的 AI 总结
        if ai_summary is None and r.ai_alert_summary:
            ai_summary = r.ai_alert_summary
        if r.dingtalk_pushed:
            dingtalk_pushed = True

    return success(data={
        "check_date": today.isoformat() if today else None,
        "records": results,
        "ai_summary": ai_summary,
        "dingtalk_pushed": dingtalk_pushed,
        "total": len(results),
    })
