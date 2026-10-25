"""Reject private or machine-specific files from a staged public installer."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

FORBIDDEN_NAMES = {"app.db", "learning.db", "chroma.sqlite3"}
FORBIDDEN_PARTS = {".git", ".venv", "tests", "logs", "browser-profile", "userdata", "__pycache__"}
FORBIDDEN_TEXT = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|AIzaSy[A-Za-z0-9_-]{30,}|C:\\Users\\[^\\]+\\)", re.I)
ALLOWED_FILES = {"AI PM Learning Compass.exe", "AI PM Learning Compass Update.exe"}


def audit(root: Path) -> list[str]:
    findings: list[str] = []
    if not root.is_dir():
        return [f"staging directory not found: {root}"]
    top_level_files = {path.name for path in root.iterdir() if path.is_file()}
    if top_level_files != ALLOWED_FILES:
        findings.append(f"unexpected staged files: {sorted(top_level_files)}")
    if any(path.is_dir() for path in root.iterdir()):
        findings.append("unexpected directory in installer staging area")
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part.lower() in FORBIDDEN_PARTS for part in relative.parts):
            findings.append(f"forbidden path: {relative}")
            continue
        if path.name.lower().startswith(".env") or path.name.lower() in FORBIDDEN_NAMES:
            findings.append(f"forbidden file: {relative}")
            continue
        if path.is_file() and path.suffix.lower() in {".json", ".txt", ".ini", ".cfg", ".yaml", ".yml", ".toml", ".py"}:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                findings.append(f"unreadable file: {relative}")
                continue
            if FORBIDDEN_TEXT.search(content):
                findings.append(f"possible credential or user path: {relative}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("staging_directory", type=Path)
    args = parser.parse_args()
    findings = audit(args.staging_directory.resolve())
    if findings:
        print("Installer payload audit failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Installer payload audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
