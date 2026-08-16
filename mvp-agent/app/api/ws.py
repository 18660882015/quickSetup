"""
WebSocket 日志推送端点

/ws/logs/{task_id} - 实时推送部署日志

- 接受连接、补发历史日志、心跳、断开处理
- 支持取消部署任务
"""
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.log_stream import log_stream_manager
from app.utils.logger import get_logger

logger = get_logger("api.ws")

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/logs/{task_id}")
async def ws_logs(websocket: WebSocket, task_id: int):
    """WebSocket 日志推送端点

    消息格式:
    {
        "type": "log|status|progress",
        "level": "info|warn|error|success",
        "message": "...",
        "step": "...",
        "timestamp": "..."
    }

    客户端可发送:
    - "ping" 心跳
    - {"type": "cancel"} 取消部署任务
    """
    await websocket.accept()
    logger.info(f"WebSocket 连接: task_id={task_id}")

    # 发送连接成功消息
    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "level": "info",
                "message": f"已连接到部署任务 {task_id} 的日志流",
                "step": "connect",
                "timestamp": datetime.now().isoformat(),
            }
        )
    )

    # 加入日志流管理器（会自动补发历史日志）
    await log_stream_manager.connect(task_id, websocket)

    try:
        # 保持连接，接收客户端心跳和指令
        while True:
            data = await websocket.receive_text()

            # 处理心跳
            if data == "ping":
                await websocket.send_text("pong")
            elif data.startswith("{"):
                # 处理 JSON 消息（如取消任务等）
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "cancel":
                        # 调用取消逻辑
                        from app.api.deploy import cancel_deploy_task

                        success = cancel_deploy_task(task_id)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "status",
                                    "level": "info" if success else "warn",
                                    "message": "取消请求已发送，将在当前步骤完成后终止"
                                    if success
                                    else "未找到运行中的部署任务或任务已完成",
                                    "step": "cancel",
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )
                        )
                except json.JSONDecodeError:
                    pass
    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: task_id={task_id}")
    except Exception as e:
        logger.error(f"WebSocket 异常: task_id={task_id}, error={e}")
    finally:
        await log_stream_manager.disconnect(task_id, websocket)
