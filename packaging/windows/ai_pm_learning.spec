# PyInstaller spec for the user-facing desktop executable.
from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path

root = Path(SPECPATH).resolve().parents[1]
datas = [
    (str(root / "app" / "static"), "app/static"),
    (str(root / "app" / "data" / "public_curriculum.json"), "app/data"),
    (str(root / "app" / "data" / "concept_library.json"), "app/data"),
    (str(root / "app" / "data" / "lesson102_teaching.json"), "app/data"),
    (str(root / "app" / "data" / "lesson102_feedback.json"), "app/data"),
    (str(root / "app" / "data" / "teaching"), "app/data/teaching"),
    (str(root / "app" / "config"), "app/config"),
    (str(root / "app" / "prompts" / "AI_PM_TUTOR_SKILL.md"), "app/prompts"),
    (str(root / "app_version.txt"), "."),
]
binaries = []
hiddenimports = ["app.desktop.launcher"]
for package in ("chromadb", "keyring", "webview", "uvicorn"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
hiddenimports += collect_submodules("app")

a = Analysis(
    [str(root / "app" / "desktop" / "launcher.py")], pathex=[str(root)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["pytest", "tests", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name="AI PM Learning Compass",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
