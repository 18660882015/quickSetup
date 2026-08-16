"""
系统托盘入口（pystray 为可选依赖）

- 后台线程运行 FastAPI 服务（uvicorn）
- pystray + PIL 可用时：常驻系统托盘，右键菜单操作
- 未安装时：降级为普通前台服务运行

安装托盘支持：
    pip install pystray pillow
"""
import threading
import webbrowser

import uvicorn

from app.config.settings import get_settings


def _make_icon_image():
    """用 PIL 生成一个简单的托盘图标（蓝底白色三角）"""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(64, 158, 255, 255))
    draw.polygon(
        [(20, 18), (46, 32), (20, 46)],
        fill=(255, 255, 255, 255),
    )
    return img


def main():
    settings = get_settings()
    url = f"http://localhost:{settings.app_port}"

    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=settings.app_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    # 服务线程
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    print(f"[tray] Service running at {url}")

    # 尝试启动托盘
    try:
        import pystray
    except ImportError:
        print(
            "[tray] pystray not installed, running without tray icon. "
            "Install with: pip install pystray pillow"
        )
        print("[tray] Press Ctrl+C to stop.")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            server.should_exit = True
        return

    def open_ui(icon, item):
        webbrowser.open(url)

    def quit_app(icon, item):
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("打开 Web 界面 / Open Web UI", open_ui, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出 / Quit", quit_app),
    )

    icon = pystray.Icon(
        "MVP AI部署助手",
        _make_icon_image(),
        "MVP AI部署助手 - 双击打开",
        menu,
    )
    print("[tray] Tray icon started. Right-click the tray icon for options.")
    icon.run()

    server.should_exit = True
    print("[tray] Stopped.")


if __name__ == "__main__":
    main()
