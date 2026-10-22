from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FORBIDDEN_NAMES = {
    ".env", "app.db", "browser_profile", "browser_profile_edge", "chroma",
    "course_files", "logs", "node_modules", ".venv",
}
FORBIDDEN_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".pdf", ".ppt", ".pptx", ".mp4", ".mov",
    ".mp3", ".wav", ".log", ".pid",
}
FORBIDDEN_ROUTES = ("/crawl", "/interview", "/browser", "/imports", "/v2")
IGNORED_WORKING_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "chroma"}


def _release_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    files = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_WORKING_DIRS for part in relative.parts):
            continue
        if relative.parts and relative.parts[0] == "data":
            continue
        files.append(path)
    return files


def failures() -> list[str]:
    issues = []
    from scripts.check_curriculum import curriculum_failures
    from scripts.audit_release import audit

    issues.extend(curriculum_failures())
    for finding in audit()["findings"]:
        # The audit deliberately reports locations/types only, never credential values.
        issues.append(f"release privacy review: {finding['file']} ({finding['kind']})")
    for path in _release_files():
        relative = path.relative_to(ROOT)
        if any(part in FORBIDDEN_NAMES for part in relative.parts):
            issues.append(f"local/private path present: {relative}")
        elif path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            issues.append(f"private/media file present: {relative}")
    main_path = ROOT / "app" / "main.py"
    if main_path.exists():
        source = main_path.read_text(encoding="utf-8")
        for route in FORBIDDEN_ROUTES:
            if route in source:
                issues.append(f"private route reference in app/main.py: {route}")
    return issues


if __name__ == "__main__":
    problems = failures()
    if problems:
        print("Release check failed:")
        print("\n".join(f"- {problem}" for problem in problems))
        sys.exit(1)
    print("Release check passed: no known local data, media, or private routes found.")
