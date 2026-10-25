"""Run the local FastAPI learning app inside a standalone Windows window."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import ctypes


def _application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def _configure_user_paths() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Windows 未提供本机应用数据目录，暂时无法启动。")
    user_root = Path(local_app_data) / "AI PM Learning Compass"
    data_dir = user_root / "data"
    config_dir = user_root / "config"
    (data_dir / "chroma").mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    webview_dir = config_dir / "webview"
    webview_dir.mkdir(parents=True, exist_ok=True)

    database_url = f"sqlite:///{(data_dir / 'app.db').as_posix()}"
    os.environ.update({
        "APP_ENV": "desktop",
        "AI_PM_DESKTOP": "1",
        "APP_HOST": "127.0.0.1",
        "STORAGE_DIR": str(data_dir),
        "DATABASE_URL": database_url,
        "CHROMA_PATH": str(data_dir / "chroma"),
        # Desktop users configure keys in the app; don't inherit a machine-wide key.
        "LLM_API_KEY": "",
        "AI_PM_USER_CONFIG_DIR": str(config_dir),
        "AI_PM_WEBVIEW_STORAGE": str(webview_dir),
    })
    return user_root


def _health_check(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status == 200 and response.read() == b'{"status":"ok"}'
    except (OSError, urllib.error.URLError):
        return False


def _show_startup_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "AI PM 学习罗盘", 0x10)
    except Exception:
        print(message)


def main() -> int:
    try:
        user_root = _configure_user_paths()
    except Exception as exc:
        _show_startup_error(f"AI PM 学习罗盘无法初始化本机数据目录。请检查用户文件夹权限后重试。\n（{type(exc).__name__}）")
        return 1
    sys.path.insert(0, str(_application_root()))

    try:
        import webview
        import uvicorn
    except Exception as exc:
        _show_startup_error(f"AI PM 学习罗盘启动失败：{type(exc).__name__}。请重新安装应用后重试。")
        return 1

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    host_url = f"http://127.0.0.1:{port}/"
    os.environ["APP_PORT"] = str(port)

    try:
        from app.main import app
    except Exception as exc:
        listener.close()
        _show_startup_error(f"AI PM 学习罗盘启动失败：{type(exc).__name__}。请重新安装应用后重试。")
        return 1

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
        name="learning-copilot-server",
    )
    server_thread.start()

    deadline = time.monotonic() + 60
    health_url = f"{host_url}api/health"
    while time.monotonic() < deadline and server_thread.is_alive():
        if _health_check(health_url):
            break
        time.sleep(0.25)
    else:
        server.should_exit = True
        listener.close()
        server_thread.join(timeout=5)
        _show_startup_error("AI PM 学习罗盘启动超时，请检查本机安全软件后重试。")
        return 1

    try:
        class DesktopApi:
            def close_app(self) -> None:
                window.destroy()

        window = webview.create_window(
            "AI PM 学习罗盘",
            f"{host_url}?desktop=1",
            width=1440,
            height=940,
            min_size=(980, 680),
            text_select=True,
            js_api=DesktopApi(),
        )

        def request_server_shutdown() -> None:
            server.should_exit = True

        window.events.closed += request_server_shutdown
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(user_root / "config" / "webview"),
        )
    except Exception as exc:
        _show_startup_error(
            "无法打开桌面窗口。请确认 Microsoft Edge WebView2 Runtime 已安装，"
            f"然后重试（{type(exc).__name__}）。"
        )
        return 1
    finally:
        server.should_exit = True
        listener.close()
        server_thread.join(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
