"""
MVP AI部署助手 - 启动入口

用法:
    python run.py                 # 启动服务
    python run.py --init-db       # 初始化数据库并退出
    python run.py --host 0.0.0.0 --port 8080

默认监听 0.0.0.0:8080
"""
import argparse
import os
import sys

# 确保项目根目录在 sys.path 中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def init_database():
    """初始化数据库：建表 + 种子数据"""
    from app.models.database import init_database as _init
    print("[init-db] 开始初始化数据库...")
    _init()
    print("[init-db] 数据库初始化完成。")


def main():
    parser = argparse.ArgumentParser(description="MVP AI部署助手后端服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8080, help="监听端口，默认 8080")
    parser.add_argument("--init-db", action="store_true", help="初始化数据库后退出")
    parser.add_argument("--reload", action="store_true", help="开启热重载（开发模式）")
    args = parser.parse_args()

    if args.init_db:
        init_database()
        return

    import uvicorn

    print(f"[run] 启动服务: http://{args.host}:{args.port}")
    print(f"[run] Swagger 文档: http://{args.host}:{args.port}/docs")
    print(f"[run] ReDoc 文档: http://{args.host}:{args.port}/redoc")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,  # SQLite 限制，单 worker
        log_level="info",
    )


if __name__ == "__main__":
    main()
