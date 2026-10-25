"""Install a previously verified update after the learner confirms it."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path
from ctypes import wintypes

_INSTALLER_NAME = re.compile(r"^AI-PM-Learning-Compass-Setup-\d+\.\d+\.\d+\.exe$")
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF
_SYNCHRONIZE = 0x00100000


def _wait_for_process(process_id: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, process_id)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the app process has already exited.
            return
        raise OSError(error, "无法确认应用已退出，已取消安装。")
    try:
        result = kernel32.WaitForSingleObject(handle, _INFINITE)
        if result != _WAIT_OBJECT_0:
            raise OSError(ctypes.get_last_error(), "等待应用退出失败。")
    finally:
        kernel32.CloseHandle(handle)


def _validated_installer(value: str) -> Path:
    installer = Path(value).resolve(strict=True)
    local_app_data = Path(os.environ["LOCALAPPDATA"]).resolve(strict=True)
    expected_parent = (local_app_data / "AI PM Learning Compass" / "updates").resolve(strict=True)
    if installer.parent != expected_parent or not _INSTALLER_NAME.fullmatch(installer.name):
        raise ValueError("更新安装包路径不正确。")
    if not installer.is_file() or installer.stat().st_size <= 0:
        raise ValueError("更新安装包不存在。")
    return installer


def main(argv: list[str] | None = None) -> int:
    if os.name != "nt":
        return 2
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        return 2
    try:
        installer = _validated_installer(args[0])
        parent_id = int(args[1])
        if parent_id <= 0:
            raise ValueError("应用进程标识不正确。")
        _wait_for_process(parent_id)
    except (KeyError, OSError, ValueError):
        return 3

    result = subprocess.run([str(installer), "/UPDATE"], cwd=str(installer.parent), check=False)
    if result.returncode != 0:
        return result.returncode or 4
    installed_app = Path(sys.executable).with_name("AI PM Learning Compass.exe")
    if not installed_app.is_file():
        return 5
    installer.unlink(missing_ok=True)
    subprocess.Popen(
        [str(installed_app)],
        cwd=str(installed_app.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x00000008),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
