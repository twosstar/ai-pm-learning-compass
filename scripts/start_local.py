"""Run the public edition locally and open the browser when it is ready."""

from __future__ import annotations

import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 8001
URL = f"http://{HOST}:{PORT}/"
HEALTH_URL = f"{URL}api/health"


def health_check() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1) as response:
            return response.status == 200 and response.read() == b'{"status":"ok"}'
    except (OSError, urllib.error.URLError):
        return False


def port_is_in_use() -> bool:
    with socket.socket() as connection:
        return connection.connect_ex((HOST, PORT)) == 0


def main() -> int:
    import uvicorn

    if health_check():
        print(f"The app is already running. Opening {URL}")
        webbrowser.open(URL)
        return 0
    if port_is_in_use():
        print(f"Port {PORT} is already in use. Close the other app and try again.")
        return 1

    server = threading.Thread(
        target=uvicorn.run,
        kwargs={"app": "app.main:app", "host": HOST, "port": PORT, "log_level": "info"},
        daemon=True,
        name="learning-copilot-server",
    )
    server.start()
    print("Waiting for the app to finish starting...")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and server.is_alive():
        if health_check():
            print(f"Ready: {URL}")
            webbrowser.open(URL)
            print("Keep this window open. Press Ctrl+C here to stop the app.")
            try:
                while server.is_alive():
                    server.join(timeout=0.5)
            except KeyboardInterrupt:
                print("Stopping the app...")
            return 0
        time.sleep(0.5)

    print("The app did not become ready. Check the startup error above and try again.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
