"""Build the Windows desktop app and its per-user installer."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Windows packaging must run on Windows.")
    if not VERSION_RE.fullmatch(args.version):
        raise SystemExit("Version must use X.Y.Z format.")
    if not shutil.which("ISCC.exe"):
        raise SystemExit("Inno Setup 6 is required (ISCC.exe was not found).")

    output = args.output.resolve()
    allowed_output_root = (ROOT / "dist").resolve()
    try:
        output.relative_to(allowed_output_root)
    except ValueError as exc:
        raise SystemExit("Output must be inside this repository's dist directory.") from exc
    if output == allowed_output_root:
        raise SystemExit("Choose a dedicated output subdirectory under dist.")
    app_version = ROOT / "app_version.txt"
    if app_version.exists():
        raise SystemExit("A temporary app_version.txt already exists; inspect it before building.")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    stage = output / "payload"
    stage.mkdir()
    app_version.write_text(args.version + "\n", encoding="utf-8")
    try:
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
            "--distpath", str(stage / "dist"), "--workpath", str(stage / "work"),
            str(ROOT / "packaging" / "windows" / "ai_pm_learning.spec"),
        ], cwd=ROOT, check=True)
        app_exe = stage / "dist" / "AI PM Learning Compass.exe"
        if not app_exe.is_file():
            raise SystemExit("PyInstaller did not create the app executable.")
        shutil.copy2(app_exe, stage / "AI PM Learning Compass.exe")

        helper_build = stage / "helper-build"
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onefile", "--windowed",
            "--name", "AI PM Learning Compass Update", "--distpath", str(helper_build / "dist"),
            "--workpath", str(helper_build / "work"), str(ROOT / "app" / "desktop" / "update_helper.py"),
        ], cwd=ROOT, check=True)
        helper = helper_build / "dist" / "AI PM Learning Compass Update.exe"
        shutil.copy2(helper, stage / helper.name)
        shutil.rmtree(stage / "dist", ignore_errors=True)
        shutil.rmtree(helper_build, ignore_errors=True)
        shutil.rmtree(stage / "work", ignore_errors=True)

        iss = ROOT / "packaging" / "windows" / "installer.iss"
        subprocess.run([
            "ISCC.exe", f"/DAppVersion={args.version}", f"/DStageDir={stage}",
            f"/DOutputDir={output}", str(iss),
        ], cwd=ROOT, check=True)
        installer = output / f"AI-PM-Learning-Compass-Setup-{args.version}.exe"
        if not installer.is_file():
            raise SystemExit("Inno Setup did not create the installer.")
        digest = hashlib.sha256(installer.read_bytes()).hexdigest()
        (output / "SHA256SUMS.txt").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_installer_payload.py"), str(stage)], cwd=ROOT, check=True)
    finally:
        app_version.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
