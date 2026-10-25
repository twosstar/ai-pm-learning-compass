"""Application version shared by desktop startup and release checks."""

from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _read_build_version() -> str | None:
    if not getattr(sys, "frozen", False):
        return None
    resource_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    version_file = resource_root / "app_version.txt"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if _SEMVER.fullmatch(value) else None


def get_version() -> str:
    """Return a strict X.Y.Z release version, with a safe source-run fallback."""
    packaged = _read_build_version()
    if packaged:
        return packaged
    try:
        candidate = version("ai-pm-learning-copilot")
    except PackageNotFoundError:
        candidate = "0.1.0"
    return candidate if _SEMVER.fullmatch(candidate) else "0.1.0"


def version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER.fullmatch(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())
