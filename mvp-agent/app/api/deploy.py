"""
部署 API：计划、执行、查询、回滚、历史

P2 实现：
- POST /plan: 调用 ai_service.generate_deploy_plan 生成真实部署计划
  （AI 不可用时降级为默认计划）
- POST /execute: 创建记录 -> 获取事件循环 -> 创建日志回调
  (asyncio.run_coroutine_threadsafe) -> 选择执行器 -> 后台线程执行
  部署完成后调用 dingtalk_service.notify_deploy_result 推送钉钉通知
  部署失败时调用 ai_service.analyze_error 分析错误，存入 deploy_records.ai_suggestion
- 部署锁：检查同主机 pending/running 状态记录
- POST /rollback/{id}: 调用回滚管理器
"""
import asyncio
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config.settings import DEPLOYMENTS_DIR
from app.core.base_engine import DeployContext
from app.core.local_engine import LocalDeployEngine
from app.core.remote_engine import RemoteDeployEngine
from app.core.rollback import RollbackManager
from app.core.security import decrypt, get_current_user
from app.core.ssh_client import ssh_pool
from app.models.database import SessionLocal, get_db
from app.models.deploy_record import DeployRecord
from app.models.host import Host
from app.schemas.common import ApiResponse, success
from app.schemas.deploy import (
    BatchDeployRequest,
    DeployExecuteRequest,
    DeployPlanRequest,
    DeployPlanResponse,
    DeployRecordResponse,
    QuickDeployRequest,
)
from app.services.ai_service import generate_deploy_plan, analyze_error
from app.services.dingtalk_service import notify_deploy_result
from app.services.log_stream import log_stream_manager
from app.utils.logger import get_logger

logger = get_logger("api.deploy")

router = APIRouter(prefix="/deploy", tags=["部署管理"])

# 运行中的部署引擎注册表：task_id -> engine
# 用于 WebSocket 取消请求查找引擎实例
_running_engines: dict = {}
_engines_lock = threading.Lock()


def cancel_deploy_task(task_id: int) -> bool:
    """取消部署任务（供 WebSocket 调用）

    Returns: True 表示成功发送取消请求
    """
    with _engines_lock:
        engine = _running_engines.get(task_id)
    if engine is None:
        return False
    try:
        engine.cancel()
        return True
    except Exception as e:
        logger.error(f"取消部署任务失败: task_id={task_id}, error={e}")
        return False


def _host_to_dict(host: Host) -> dict:
    """将 Host 模型转换为字典"""
    return {
        "id": host.id,
        "name": host.name,
        "ip": host.ip,
        "port": host.port,
        "username": host.username,
        "auth_type": host.auth_type,
        "password": host.password,  # 加密的
        "private_key": host.private_key,  # 加密的
        "jdk_version": host.jdk_version,
        "deploy_dir": host.deploy_dir,
        "backup_dir": host.backup_dir,
        "is_local": host.is_local,
        "os_info": host.os_info,
    }


def _load_project_config(project_name: str, request_config: dict) -> dict:
    """加载项目配置：从 project.json 读取，合并请求参数

    Args:
        project_name: 项目名
        request_config: 从请求中获取的配置
    """
    project_dir = DEPLOYMENTS_DIR / project_name
    config = {
        "project_name": project_name,
        "project_dir": str(project_dir),
    }

    # 从 project.json 加载（utf-8-sig 兼容带 BOM 的 Windows 文件）
    project_json_path = project_dir / "project.json"
    if project_json_path.exists():
        try:
            with open(project_json_path, "r", encoding="utf-8-sig") as f:
                json_config = json.load(f)
            config.update(json_config)
        except Exception as e:
            logger.warning(f"读取 project.json 失败: {e}")

    # 请求参数覆盖
    config.update(request_config)

    # 多环境配置模板：按 env_type 合并 JVM/Nginx/MySQL/日志级别参数
    # （显式传入的配置已在上面覆盖，不会被模板改写）
    from app.services.env_template import apply_template_to_config

    apply_template_to_config(config.get("env_type"), config)

    return config


# ======================================================================
# 部署计划
# ======================================================================
@router.post("/plan", response_model=ApiResponse, summary="生成部署计划")
async def generate_plan(
    request: DeployPlanRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """调用 AI 生成部署计划（预览模式）

    P2 实现：
    - 调用 ai_service.generate_deploy_plan 生成结构化部署计划
    - AI 不可用时自动降级为默认部署计划
    - 提示词包含主机信息、项目配置、已有服务状态
    """
    # 获取主机信息
    host_info = None
    if request.host_id:
        host = db.query(Host).filter(Host.id == request.host_id).first()
        if host:
            host_info = _host_to_dict(host)
    else:
        host_info = {"is_local": request.is_local, "os_info": "Windows", "ip": "127.0.0.1"}

    # 构建项目配置
    project_config = _load_project_config(request.project_name, {
        "env_type": request.env_type,
        "jdk_version": request.jdk_version,
        "db_name": request.db_name,
        "execute_mode": request.execute_mode,
    })

    # 扫描项目文件
    project_dir = DEPLOYMENTS_DIR / request.project_name
    project_files = []
    if project_dir.exists():
        project_files = [f.name for f in project_dir.iterdir() if f.is_file()]
    project_config["files"] = project_files

    # 调用 AI 生成部署计划（AI 不可用时降级为默认计划）
    try:
        ai_result = await generate_deploy_plan(host_info, project_config)
    except Exception as e:
        logger.error(f"AI 生成部署计划失败，使用降级计划: {e}")
        from app.services.ai_service import _fallback_plan
        ai_result = _fallback_plan(host_info, project_config)

    # 根据 AI 结果构建响应步骤
    ai_steps = ai_result.get("steps", [])
    if not ai_steps:
        # 降级：使用默认步骤
        from app.services.ai_service import _fallback_plan
        fallback = _fallback_plan(host_info, project_config)
        ai_steps = fallback["steps"]
        if not ai_result.get("ai_suggestion"):
            ai_result["ai_suggestion"] = fallback["ai_suggestion"]

    # 构建部署步骤响应
    steps = []
    for s in ai_steps:
        steps.append({
            "step": s.get("step", ""),
            "name": s.get("name", s.get("step", "")),
            "description": s.get("description", ""),
            "command": s.get("command"),
            "is_dangerous": s.get("is_dangerous", False),
            "estimated_time": s.get("estimated_time"),
        })

    # 收集警告信息
    warnings = list(ai_result.get("warnings", []))
    if not project_dir.exists():
        warnings.append(f"项目目录不存在: {request.project_name}")
    else:
        has_sql = any(f.suffix == ".sql" for f in project_dir.iterdir() if f.is_file())
        if has_sql and request.db_name:
            warnings.append(f"将导入 SQL 到数据库: {request.db_name}")

    plan = DeployPlanResponse(
        project_name=request.project_name,
        env_type=request.env_type,
        jdk_version=request.jdk_version,
        steps=steps,
        ai_suggestion=ai_result.get("ai_suggestion"),
        warnings=warnings,
    )

    return success(data=plan.model_dump())


# ======================================================================
# 执行部署
# ======================================================================
def _launch_deploy(
    request: DeployExecuteRequest,
    db: Session,
    current_user: dict,
    loop,
) -> int:
    """校验并启动单个部署任务（后台线程执行），返回 task_id

    供 /execute、/quick、/batch 复用；校验失败抛 HTTPException。
    """
    # 1. 检查部署锁
    if request.host_id:
        running = (
            db.query(DeployRecord)
            .filter(
                DeployRecord.host_id == request.host_id,
                DeployRecord.execute_status.in_(["pending", "running"]),
            )
            .first()
        )
        if running:
            raise HTTPException(
                status_code=409,
                detail=f"主机已有部署任务进行中 (task_id={running.id})，"
                f"请等待完成或取消后重试",
            )

    # 2. 获取主机信息（提前提取，避免线程中 session 关闭）
    host = None
    host_dict = None
    if request.host_id:
        host = db.query(Host).filter(Host.id == request.host_id).first()
        if not host:
            raise HTTPException(status_code=404, detail="主机不存在")
        host_dict = _host_to_dict(host)

    # 3. 创建部署记录
    record = DeployRecord(
        host_id=request.host_id,
        project_name=request.project_name,
        env_type=request.env_type,
        execute_status="pending",
        execute_mode=request.execute_mode,
        jdk_version=request.jdk_version,
        db_name=request.db_name,
        version=request.version,
        operator=current_user.get("username", "admin"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    task_id = record.id
    logger.info(
        f"创建部署任务: id={task_id}, project={request.project_name}"
    )

    # 5. 创建日志回调（线程安全，通过 asyncio.run_coroutine_threadsafe 桥接）
    def log_callback(level: str, message: str, step: Optional[str] = None):
        asyncio.run_coroutine_threadsafe(
            log_stream_manager.push_log(task_id, level, message, step),
            loop,
        )

    # 6. 确认回调（P1 阶段自动确认）
    def confirm_callback(step: str, command: str, is_dangerous: bool) -> bool:
        if is_dangerous:
            logger.warning(
                f"[task={task_id}] 危险操作自动确认: step={step}, command={command}"
            )
        return True

    # 7. 构建部署上下文
    request_config = {
        "env_type": request.env_type,
        "jdk_version": request.jdk_version,
        "db_name": request.db_name,
        "deploy_dir": request.deploy_dir,
        "version": request.version,
        "post_deploy_script": request.post_deploy_script,
    }
    project_config = _load_project_config(request.project_name, request_config)
    deploy_config = {
        "execute_mode": request.execute_mode,
        "deploy_dir": request.deploy_dir,
        "version": request.version,
        "jdk_version": request.jdk_version,
        "env_type": request.env_type,
        "db_name": request.db_name,
    }

    context = DeployContext(
        record_id=task_id,
        host_config=host_dict,
        project_config=project_config,
        deploy_config=deploy_config,
    )

    # 8. 判断本地/远程
    is_local = request.is_local or (host and host.is_local)

    # 9. 后台线程执行部署
    def run_deploy():
        """部署线程主函数"""
        thread_db = SessionLocal()
        engine = None
        try:
            # 更新状态为 running
            record_obj = (
                thread_db.query(DeployRecord)
                .filter(DeployRecord.id == task_id)
                .first()
            )
            if record_obj:
                record_obj.execute_status = "running"
                record_obj.started_at = datetime.now()
                thread_db.commit()

            log_callback("info", f"部署任务已启动 (task_id={task_id})", "start")

            # 选择执行器
            if is_local:
                engine = LocalDeployEngine(
                    context, log_callback, confirm_callback
                )
            else:
                # 远程部署：获取 SSH 连接
                # 解密密码/私钥
                if host_dict and host_dict.get("password"):
                    host_dict["password"] = decrypt(host_dict["password"])
                if host_dict and host_dict.get("private_key"):
                    host_dict["private_key"] = decrypt(
                        host_dict["private_key"]
                    )

                ssh_conn = ssh_pool.get_connection(
                    host_dict["id"], host_dict
                )
                engine = RemoteDeployEngine(
                    context, ssh_conn, log_callback, confirm_callback
                )

            # 注册到运行中引擎表
            with _engines_lock:
                _running_engines[task_id] = engine

            # 执行部署
            deploy_success = engine.execute()

            # 更新记录
            record_obj = (
                thread_db.query(DeployRecord)
                .filter(DeployRecord.id == task_id)
                .first()
            )
            if record_obj:
                record_obj.finished_at = context.finished_at
                if context.started_at and context.finished_at:
                    record_obj.duration = (
                        context.finished_at - context.started_at
                    ).total_seconds()
                record_obj.steps_detail = context.steps_detail
                record_obj.error_message = context.error_message
                record_obj.backup_path = context.backup_path
                record_obj.can_rollback = bool(
                    context.backup_path
                ) and not context.is_rolled_back

                if deploy_success:
                    record_obj.execute_status = "success"
                elif context.is_cancelled:
                    record_obj.execute_status = "cancelled"
                elif context.is_rolled_back:
                    record_obj.execute_status = "rolled_back"
                else:
                    record_obj.execute_status = "failed"

                # 保存验证结果
                if context.extra.get("validation_results"):
                    record_obj.rollback_info = record_obj.rollback_info or {}
                    if isinstance(record_obj.rollback_info, dict):
                        record_obj.rollback_info["validation"] = (
                            context.extra["validation_results"]
                        )

                # 部署失败时调用 AI 分析错误
                if record_obj.execute_status in ("failed", "rolled_back"):
                    error_log = (
                        record_obj.logs or ""
                    )
                    if context.error_message:
                        error_log = f"{context.error_message}\n{error_log}"
                    if error_log.strip():
                        try:
                            ai_suggestion = asyncio.run_coroutine_threadsafe(
                                analyze_error(
                                    error_log,
                                    host_dict,
                                    project_config,
                                ),
                                loop,
                            ).result(timeout=30)
                            record_obj.ai_suggestion = ai_suggestion
                            log_callback("info", "AI 错误分析完成", "ai_analysis")
                        except Exception as ai_err:
                            logger.warning(f"AI 错误分析失败: {ai_err}")
                            record_obj.ai_suggestion = (
                                f"AI 分析失败: {ai_err}"
                            )

                thread_db.commit()

                final_status = record_obj.execute_status
            else:
                final_status = "failed"

            # 推送最终状态
            asyncio.run_coroutine_threadsafe(
                log_stream_manager.push_status(
                    task_id,
                    final_status,
                    f"部署{'成功' if deploy_success else '失败'}",
                ),
                loop,
            )

            # 部署完成后推送钉钉通知
            try:
                # 重新查询最新记录数据用于通知
                notify_record = (
                    thread_db.query(DeployRecord)
                    .filter(DeployRecord.id == task_id)
                    .first()
                )
                if notify_record:
                    notify_host = host
                    asyncio.run_coroutine_threadsafe(
                        notify_deploy_result(notify_record, notify_host),
                        loop,
                    ).result(timeout=15)
                    log_callback("info", "钉钉部署结果通知已发送", "notification")
            except Exception as dt_err:
                logger.warning(f"钉钉通知发送失败: {dt_err}")

            logger.info(
                f"部署任务完成: id={task_id}, status={final_status}"
            )

        except Exception as e:
            logger.error(f"部署线程异常: task_id={task_id}, error={e}", exc_info=True)
            # 更新记录为失败
            try:
                record_obj = (
                    thread_db.query(DeployRecord)
                    .filter(DeployRecord.id == task_id)
                    .first()
                )
                if record_obj:
                    record_obj.execute_status = "failed"
                    record_obj.error_message = str(e)
                    record_obj.finished_at = datetime.now()
                    if record_obj.started_at:
                        record_obj.duration = (
                            record_obj.finished_at - record_obj.started_at
                        ).total_seconds()

                    # AI 错误分析
                    error_log = str(e)
                    if record_obj.logs:
                        error_log = f"{error_log}\n{record_obj.logs}"
                    try:
                        ai_suggestion = asyncio.run_coroutine_threadsafe(
                            analyze_error(
                                error_log,
                                host_dict,
                                project_config,
                            ),
                            loop,
                        ).result(timeout=30)
                        record_obj.ai_suggestion = ai_suggestion
                    except Exception as ai_err:
                        logger.warning(f"AI 错误分析失败: {ai_err}")

                    thread_db.commit()

                    # 推送钉钉通知
                    try:
                        asyncio.run_coroutine_threadsafe(
                            notify_deploy_result(record_obj, host),
                            loop,
                        ).result(timeout=15)
                    except Exception as dt_err:
                        logger.warning(f"钉钉通知发送失败: {dt_err}")
            except Exception:
                pass

            # 推送错误日志
            asyncio.run_coroutine_threadsafe(
                log_stream_manager.push_log(
                    task_id, "error", f"部署异常: {e}", "error"
                ),
                loop,
            )
            asyncio.run_coroutine_threadsafe(
                log_stream_manager.push_status(
                    task_id, "failed", f"部署异常: {e}"
                ),
                loop,
            )
        finally:
            # 从运行中引擎表移除
            with _engines_lock:
                _running_engines.pop(task_id, None)
            thread_db.close()

    # 启动后台线程
    thread = threading.Thread(target=run_deploy, daemon=True)
    thread.start()

    return task_id


@router.post("/execute", response_model=ApiResponse, summary="执行部署")
async def execute_deploy(
    request: DeployExecuteRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """启动部署任务（后台线程执行）"""
    loop = asyncio.get_running_loop()
    task_id = _launch_deploy(request, db, current_user, loop)
    return success(
        data={"task_id": task_id, "status": "pending"},
        msg="部署任务已创建，正在后台执行",
    )


# ======================================================================
# 极简快速部署
# ======================================================================
@router.post("/quick", response_model=ApiResponse, summary="快速部署（智能配置）")
async def quick_deploy(
    request: QuickDeployRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """极简快速部署：智能识别项目 -> 自动填充配置 -> 直接执行

    - JDK 版本：项目识别值 > 主机配置 > 默认 8
    - 数据库名：识别值 > 项目名推断
    """
    from app.services.project_detector import detect_project

    project_dir = DEPLOYMENTS_DIR / request.project_name
    if not project_dir.exists():
        raise HTTPException(
            status_code=404, detail=f"项目目录不存在: {request.project_name}"
        )

    detected = detect_project(project_dir)

    # project.json 中的显式配置优先于识别推断值
    project_json = {}
    project_json_path = project_dir / "project.json"
    if project_json_path.exists():
        try:
            with open(project_json_path, "r", encoding="utf-8-sig") as f:
                project_json = json.load(f)
        except Exception:
            project_json = {}

    jdk_version = str(
        detected.get("jdk_version") or project_json.get("jdk_version") or "8"
    )
    if request.host_id:
        host = db.query(Host).filter(Host.id == request.host_id).first()
        if not host:
            raise HTTPException(status_code=404, detail="主机不存在")
        if (
            detected.get("jdk_version") is None
            and not project_json.get("jdk_version")
            and host.jdk_version
        ):
            jdk_version = str(host.jdk_version)

    db_name = (
        detected.get("db_name")
        or project_json.get("db_name")
        or request.project_name.replace("-", "_").replace(" ", "_").lower()
    )

    exec_request = DeployExecuteRequest(
        project_name=request.project_name,
        host_id=request.host_id,
        is_local=request.is_local,
        env_type=request.env_type,
        jdk_version=jdk_version,
        db_name=db_name,
    )

    loop = asyncio.get_running_loop()
    task_id = _launch_deploy(exec_request, db, current_user, loop)

    return success(
        data={"task_id": task_id, "detected": detected},
        msg="快速部署已启动（智能配置）",
    )


# ======================================================================
# 批量部署
# ======================================================================
_TERMINAL_STATUS = {"success", "failed", "cancelled", "rolled_back"}


def _wait_task_terminal(task_id: int, timeout: int = 3600) -> str:
    """轮询部署记录直到进入终态（供批量部署串行等待）"""
    import time as _time

    deadline = _time.time() + timeout
    while _time.time() < deadline:
        db = SessionLocal()
        try:
            rec = db.query(DeployRecord).filter(DeployRecord.id == task_id).first()
            if rec and rec.execute_status in _TERMINAL_STATUS:
                return rec.execute_status
        finally:
            db.close()
        _time.sleep(2)
    return "timeout"


@router.post("/batch", response_model=ApiResponse, summary="批量部署")
async def batch_deploy(
    request: BatchDeployRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """批量部署：多个项目按提交顺序依次执行

    同一主机的任务串行等待完成后再启动下一项，避免部署锁冲突；
    执行结果可通过部署历史查询。
    """
    # 预校验项目目录
    missing = [
        i.project_name
        for i in request.items
        if not (DEPLOYMENTS_DIR / i.project_name).exists()
    ]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"项目目录不存在: {', '.join(missing)}"
        )

    loop = asyncio.get_running_loop()
    username = current_user.get("username", "admin")
    items = [i.model_dump() for i in request.items]

    def run_batch():
        results = []
        for idx, item in enumerate(items, 1):
            name = item["project_name"]
            logger.info(f"[batch {idx}/{len(items)}] 开始部署: {name}")
            item_db = SessionLocal()
            try:
                exec_request = DeployExecuteRequest(**item)
                task_id = _launch_deploy(
                    exec_request, item_db, {"username": username}, loop
                )
            except HTTPException as e:
                results.append(
                    {"project_name": name, "status": "failed", "error": str(e.detail)}
                )
                logger.warning(f"[batch {idx}/{len(items)}] 启动失败: {name} - {e.detail}")
                continue
            finally:
                item_db.close()

            status = _wait_task_terminal(task_id)
            results.append(
                {"task_id": task_id, "project_name": name, "status": status}
            )
            logger.info(f"[batch {idx}/{len(items)}] 完成: {name} -> {status}")

        ok = sum(1 for r in results if r.get("status") == "success")
        logger.info(
            f"批量部署完成: 共 {len(results)} 项，成功 {ok}，"
            f"失败 {len(results) - ok}"
        )

    threading.Thread(target=run_batch, daemon=True).start()

    return success(
        msg=f"批量部署已启动（{len(items)} 项，按顺序执行）",
        data={"total": len(items)},
    )


# ======================================================================
# 查询任务状态
# ======================================================================
@router.get("/task/{task_id}", response_model=ApiResponse, summary="查询部署任务状态")
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """查询部署任务状态"""
    record = db.query(DeployRecord).filter(DeployRecord.id == task_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="部署任务不存在")

    result = DeployRecordResponse.model_validate(record).model_dump()
    return success(data=result)


# ======================================================================
# 回滚
# ======================================================================
@router.post("/rollback/{record_id}", response_model=ApiResponse, summary="回滚部署")
async def rollback_deploy(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """回滚到指定部署版本

    流程：停止服务 -> 恢复备份文件 -> 重启 -> 验证
    """
    record = db.query(DeployRecord).filter(DeployRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="部署记录不存在")

    if not record.can_rollback:
        raise HTTPException(
            status_code=400,
            detail="该部署记录不支持回滚（无备份或已回滚）",
        )

    if not record.backup_path:
        raise HTTPException(status_code=400, detail="备份路径不存在")

    # 获取主机信息
    host = None
    host_dict = None
    is_local = True
    if record.host_id:
        host = db.query(Host).filter(Host.id == record.host_id).first()
        if host:
            host_dict = _host_to_dict(host)
            is_local = host.is_local

    # 提前提取 record 数据（避免线程中 session 已关闭）
    backup_path = record.backup_path

    # 获取事件循环
    loop = asyncio.get_running_loop()
    task_id = record_id

    def log_callback(level: str, message: str, step: Optional[str] = None):
        asyncio.run_coroutine_threadsafe(
            log_stream_manager.push_log(task_id, level, message, step),
            loop,
        )

    def run_rollback():
        """回滚线程主函数"""
        thread_db = SessionLocal()
        try:
            log_callback("warn", f"开始回滚部署记录: {record_id}", "rollback")

            rollback_mgr = RollbackManager(
                is_local=is_local,
                log_callback=log_callback,
            )

            # 如果是远程部署，获取 SSH 连接
            if not is_local and host_dict:
                if host_dict.get("password"):
                    host_dict["password"] = decrypt(host_dict["password"])
                if host_dict.get("private_key"):
                    host_dict["private_key"] = decrypt(
                        host_dict["private_key"]
                    )
                ssh_conn = ssh_pool.get_connection(
                    host_dict["id"], host_dict
                )
                rollback_mgr.ssh_conn = ssh_conn

            success_flag = False

            if is_local:
                # 本地回滚
                backup_dir = Path(backup_path)
                # 构造目标路径（与部署时的路径一致）
                target_paths = []
                # 从 steps_detail 或 project_config 获取路径
                # 这里使用默认路径
                nginx_html = "tools/nginx/html"
                tomcat_webapps = "tools/tomcat/webapps"
                nginx_name = Path(nginx_html).name
                tomcat_name = Path(tomcat_webapps).name

                if (backup_dir / nginx_name).exists():
                    target_paths.append((nginx_name, nginx_html))
                if (backup_dir / tomcat_name).exists():
                    target_paths.append((tomcat_name, tomcat_webapps))

                if target_paths:
                    success_flag = rollback_mgr.rollback_local(
                        backup_dir, target_paths
                    )
                else:
                    log_callback("warn", "备份目录中无可恢复的文件", "rollback")
            else:
                # 远程回滚
                remote_backup_dir = backup_path
                deploy_dir = (
                    host_dict.get("deploy_dir", "/opt/deploy")
                    if host_dict
                    else "/opt/deploy"
                )
                target_paths = [
                    ("html", f"{deploy_dir}/html"),
                    ("webapps", f"{deploy_dir}/webapps"),
                ]
                success_flag = rollback_mgr.rollback_remote(
                    remote_backup_dir, target_paths
                )

            # 更新记录
            record_obj = (
                thread_db.query(DeployRecord)
                .filter(DeployRecord.id == record_id)
                .first()
            )
            if record_obj:
                if success_flag:
                    record_obj.execute_status = "rolled_back"
                    record_obj.can_rollback = False
                    rollback_info = record_obj.rollback_info or {}
                    if isinstance(rollback_info, dict):
                        rollback_info["rolled_back_at"] = (
                            datetime.now().isoformat()
                        )
                        rollback_info["rolled_back_by"] = current_user.get(
                            "username", "admin"
                        )
                        record_obj.rollback_info = rollback_info
                    log_callback("success", "回滚完成", "rollback")
                else:
                    log_callback("error", "回滚失败", "rollback")

                thread_db.commit()

            # 推送最终状态
            final_status = "rolled_back" if success_flag else "failed"
            asyncio.run_coroutine_threadsafe(
                log_stream_manager.push_status(
                    task_id, final_status, "回滚" + ("完成" if success_flag else "失败")
                ),
                loop,
            )

        except Exception as e:
            logger.error(
                f"回滚线程异常: record_id={record_id}, error={e}", exc_info=True
            )
            try:
                record_obj = (
                    thread_db.query(DeployRecord)
                    .filter(DeployRecord.id == record_id)
                    .first()
                )
                if record_obj:
                    record_obj.execute_status = "failed"
                    thread_db.commit()
            except Exception:
                pass
            asyncio.run_coroutine_threadsafe(
                log_stream_manager.push_log(
                    task_id, "error", f"回滚异常: {e}", "rollback"
                ),
                loop,
            )
        finally:
            thread_db.close()

    # 启动回滚线程
    thread = threading.Thread(target=run_rollback, daemon=True)
    thread.start()

    return success(
        msg="回滚任务已启动，正在后台执行",
        data={"record_id": record_id, "status": "rolling_back"},
    )


# ======================================================================
# 部署历史
# ======================================================================
@router.get("/history", response_model=ApiResponse, summary="获取部署历史")
def get_history(
    host_id: Optional[int] = Query(default=None, description="按主机过滤"),
    project_name: Optional[str] = Query(
        default=None, description="按项目名过滤"
    ),
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="按状态过滤"
    ),
    limit: int = Query(default=20, ge=1, le=100, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """获取部署历史列表（支持按主机过滤）"""
    query = db.query(DeployRecord)

    if host_id is not None:
        query = query.filter(DeployRecord.host_id == host_id)
    if project_name:
        query = query.filter(DeployRecord.project_name.like(f"%{project_name}%"))
    if status_filter:
        query = query.filter(DeployRecord.execute_status == status_filter)

    total = query.count()
    records = (
        query.order_by(DeployRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = [
        DeployRecordResponse.model_validate(r).model_dump() for r in records
    ]
    return success(data={"list": result, "total": total})
