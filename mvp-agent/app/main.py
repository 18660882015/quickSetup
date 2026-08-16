"""
FastAPI 主应用

- lifespan 上下文管理器：建表、种子数据、APScheduler 启动
- CORS 中间件
- 路由注册
- 全局异常处理（统一响应格式）
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED, JobEvent

from app.api.router import api_router
from app.api.ws import router as ws_router
from app.config.settings import get_settings, ensure_runtime_dirs, BASE_DIR
from app.models.database import init_database, SessionLocal
from app.models.sys_config import get_config_value
from app.utils.logger import setup_logger

# 初始化日志
logger = setup_logger("main")

# 全局调度器引用
scheduler: AsyncIOScheduler = None


# ======================================================================
# APScheduler 定时任务
# ======================================================================
def _job_ssh_pool_cleanup():
    """定时任务：SSH 连接池空闲清理（每 30 分钟）"""
    from app.core.ssh_client import ssh_pool
    try:
        ssh_pool.cleanup_idle()
    except Exception as e:
        logger.error(f"SSH 连接池清理任务异常: {e}")


def _job_check_hosts_status():
    """定时任务：主机状态检查（每 5 分钟）

    检查所有主机 SSH 连通性，更新 hosts 表 status 字段。
    """
    from app.services.monitor_service import check_hosts_status
    try:
        result = check_hosts_status()
        logger.info(
            f"主机状态检查完成: 在线={result['online']}, "
            f"离线={result['offline']}, 总计={result['total']}"
        )
    except Exception as e:
        logger.error(f"主机状态检查任务异常: {e}")


def _job_collect_monitor_data():
    """定时任务：监控数据采集（每小时）

    采集所有主机监控数据，存入 monitor_dailies 表。
    """
    from app.services.monitor_service import collect_all_hosts
    try:
        results = collect_all_hosts()
        logger.info(f"监控数据采集完成: 共采集 {len(results)} 台主机")
    except Exception as e:
        logger.error(f"监控数据采集任务异常: {e}")


async def _job_daily_report():
    """定时任务：每日监控报告（每天凌晨，时间可配置）

    调用 monitor_service.generate_daily_report 生成报告并推送钉钉。
    """
    from app.services.monitor_service import generate_daily_report
    try:
        logger.info("开始执行每日监控报告任务...")
        result = await generate_daily_report()
        logger.info(
            f"每日监控报告完成: 钉钉推送={'成功' if result.get('dingtalk_pushed') else '未推送/失败'}"
        )
    except Exception as e:
        logger.error(f"每日监控报告任务异常: {e}", exc_info=True)


async def _job_service_guard():
    """定时任务：进程守护检查（默认每 30 秒，间隔可配置）

    检查所有启用的守护项，服务停止时自动重启并推送钉钉。
    """
    from app.services.guard_service import run_guard_check
    from app.models.database import SessionLocal
    from app.models.sys_config import get_config_value

    try:
        db = SessionLocal()
        try:
            if get_config_value(db, "guard_enabled", "true").lower() not in ("true", "1", "yes", "on"):
                return
        finally:
            db.close()

        stats = await run_guard_check()
        if stats.get("total", 0) > 0 and (stats.get("restarted", 0) > 0 or stats.get("failed", 0) > 0):
            logger.info(
                f"进程守护检查: 守护 {stats['total']} 项, "
                f"运行 {stats['running']}, 重启 {stats['restarted']}, 异常 {stats['failed']}"
            )
    except Exception as e:
        logger.error(f"进程守护任务异常: {e}", exc_info=True)


def _job_db_backup():
    """定时任务：数据库自动备份（每天 02:30，保留 N 天）"""
    from app.services.backup_service import backup_database
    from app.models.database import SessionLocal
    from app.models.sys_config import get_config_value

    try:
        db = SessionLocal()
        try:
            if get_config_value(db, "db_backup_enabled", "true").lower() not in ("true", "1", "yes", "on"):
                return
        finally:
            db.close()

        result = backup_database(reason="auto")
        if result["success"]:
            logger.info(f"数据库自动备份完成: {result['file']}")
        else:
            logger.warning(f"数据库自动备份失败: {result['message']}")
    except Exception as e:
        logger.error(f"数据库备份任务异常: {e}", exc_info=True)


def _job_disk_cleanup():
    """定时任务：磁盘空间清理（每天 03:00）"""
    from app.services.backup_service import cleanup_disk
    from app.models.database import SessionLocal
    from app.models.sys_config import get_config_value

    try:
        db = SessionLocal()
        try:
            if get_config_value(db, "disk_cleanup_enabled", "true").lower() not in ("true", "1", "yes", "on"):
                return
        finally:
            db.close()

        result = cleanup_disk()
        if result.get("removed") and any(result["removed"].values()):
            logger.info(f"磁盘清理完成: {result['message']}")
    except Exception as e:
        logger.error(f"磁盘清理任务异常: {e}", exc_info=True)


def _get_monitor_cron_time():
    """从 sys_configs 读取每日监控报告时间，转换为 cron 参数

    配置值格式: "02:00" -> cron: hour=2, minute=0
    """
    db = SessionLocal()
    try:
        monitor_time = get_config_value(db, "monitor_time", "02:00")
    finally:
        db.close()

    try:
        parts = monitor_time.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return {"hour": hour, "minute": minute}
    except (ValueError, IndexError):
        logger.warning(f"监控时间配置格式无效: {monitor_time}，使用默认 02:00")
        return {"hour": 2, "minute": 0}


def _on_job_error(event: JobEvent):
    """APScheduler 异常监听器：捕获任务错误"""
    if event.exception:
        logger.error(
            f"定时任务异常: job_id={event.job_id}, "
            f"exception={event.exception}",
            exc_info=event.exception,
        )


def _on_job_missed(event: JobEvent):
    """APScheduler 错过执行监听器"""
    logger.warning(f"定时任务错过执行: job_id={event.job_id}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理

    启动时：
    - 确保运行时目录
    - 初始化数据库（建表 + 种子数据）
    - 启动 APScheduler（注册定时任务）

    关闭时：
    - 关闭 APScheduler
    - 关闭所有 SSH 连接
    """
    global scheduler

    logger.info("=" * 60)
    logger.info("MVP AI部署助手 - 启动中...")
    logger.info("=" * 60)

    # 确保运行时目录
    ensure_runtime_dirs()

    # 初始化数据库
    try:
        init_database()
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise

    # 启动 APScheduler
    try:
        scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

        # 添加异常监听器
        scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
        scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

        # a. SSH 连接池空闲清理（每 30 分钟）
        scheduler.add_job(
            _job_ssh_pool_cleanup,
            trigger="interval",
            minutes=30,
            id="ssh_pool_cleanup",
            name="SSH连接池清理",
            replace_existing=True,
        )

        # b. 主机状态检查（每 5 分钟）
        scheduler.add_job(
            _job_check_hosts_status,
            trigger="interval",
            minutes=5,
            id="check_hosts_status",
            name="主机状态检查",
            replace_existing=True,
        )

        # c. 监控数据采集（每小时）
        scheduler.add_job(
            _job_collect_monitor_data,
            trigger="interval",
            hours=1,
            id="collect_monitor_data",
            name="监控数据采集",
            replace_existing=True,
        )

        # d. 每日监控报告（每天凌晨，时间从 sys_configs 读取）
        cron_params = _get_monitor_cron_time()
        scheduler.add_job(
            _job_daily_report,
            trigger="cron",
            **cron_params,
            id="daily_report",
            name="每日监控报告",
            replace_existing=True,
        )

        # e. 进程守护检查（默认每 30 秒）
        scheduler.add_job(
            _job_service_guard,
            trigger="interval",
            seconds=30,
            id="service_guard",
            name="进程守护检查",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # f. 数据库自动备份（每天 02:30）
        scheduler.add_job(
            _job_db_backup,
            trigger="cron",
            hour=2,
            minute=30,
            id="db_backup",
            name="数据库自动备份",
            replace_existing=True,
        )

        # g. 磁盘空间清理（每天 03:00）
        scheduler.add_job(
            _job_disk_cleanup,
            trigger="cron",
            hour=3,
            minute=0,
            id="disk_cleanup",
            name="磁盘空间清理",
            replace_existing=True,
        )

        scheduler.start()
        logger.info(
            f"APScheduler 已启动，注册定时任务: "
            f"SSH清理(30min), 主机检查(5min), 监控采集(1h), "
            f"日报({cron_params['hour']:02d}:{cron_params['minute']:02d}), "
            f"进程守护(30s), 数据库备份(02:30), 磁盘清理(03:00)"
        )
    except Exception as e:
        logger.warning(f"APScheduler 启动失败（非致命）: {e}")

    settings = get_settings()
    logger.info(f"服务已启动: http://0.0.0.0:{settings.app_port}")
    logger.info(f"Swagger 文档: http://localhost:{settings.app_port}/docs")
    logger.info(f"ReDoc 文档: http://localhost:{settings.app_port}/redoc")
    logger.info(f"默认账号: {settings.admin_username} / {settings.admin_password}")

    yield

    # 关闭 APScheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler 已关闭")

    # 关闭所有 SSH 连接
    try:
        from app.core.ssh_client import ssh_pool
        ssh_pool.close_all()
    except Exception:
        pass

    logger.info("MVP AI部署助手 - 已停止")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    settings = get_settings()

    app = FastAPI(
        title="MVP AI部署助手",
        description="Windows 本地运行的 AI 智能部署工具，支持本地 Windows 部署和远程 Linux SSH 部署。",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",    # Vue 开发服务器
            "http://localhost:8080",    # 本服务
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
            "*",                        # 开发环境允许所有来源
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 API 路由（/api/v1 前缀）
    app.include_router(api_router)

    # 注册 WebSocket 路由（/ws 前缀，不包含 /api/v1）
    app.include_router(ws_router)

    # 全局异常处理：HTTPException -> 统一响应格式
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "msg": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                "data": None,
            },
        )

    # 全局异常处理：未捕获异常
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"未捕获异常: {request.url.path} - {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "msg": f"服务器内部错误: {exc}",
                "data": None,
            },
        )

    # 健康检查端点
    @app.get("/health", tags=["系统"])
    async def health_check():
        return {"code": 0, "msg": "success", "data": {"status": "healthy"}}

    # API 信息端点
    @app.get("/api-info", tags=["系统"])
    async def api_info():
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "name": "MVP AI部署助手",
                "version": "0.1.0",
                "docs": "/docs",
                "health": "/health",
            },
        }

    # 挂载前端静态文件（Vue3 SPA）
    frontend_dist = BASE_DIR.parent / "mvp-frontend" / "dist"
    if frontend_dist.exists():
        from fastapi.responses import FileResponse

        app.mount(
            "/assets",
            StaticFiles(directory=str(frontend_dist / "assets")),
            name="assets",
        )

        # 挂载其他静态文件（favicon 等）
        static_files_dir = frontend_dist
        for static_file in static_files_dir.iterdir():
            if static_file.is_file():
                # 为根目录下的静态文件（如 favicon.svg）创建路由
                pass

        # SPA catch-all：所有未匹配的路由返回 index.html
        @app.get("/{full_path:path}")
        async def spa_catch_all(full_path: str):
            # 如果是 API 或 WebSocket 路径，返回 404
            if full_path.startswith("api/") or full_path.startswith("ws/") or full_path == "docs" or full_path == "redoc":
                raise HTTPException(status_code=404, detail="Not Found")

            # 检查是否是静态文件
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))

            # 其他所有路径返回 index.html（Vue Router 接管）
            index_file = frontend_dist / "index.html"
            if index_file.exists():
                return FileResponse(str(index_file))
            raise HTTPException(status_code=404, detail="Frontend not built")
    else:
        # 前端未构建，返回 API 信息
        @app.get("/", tags=["系统"])
        async def root():
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "name": "MVP AI部署助手",
                    "version": "0.1.0",
                    "docs": "/docs",
                    "health": "/health",
                    "warning": "Frontend not built. Run: cd mvp-frontend && npm run build",
                },
            }

    return app


# 创建应用实例
app = create_app()
