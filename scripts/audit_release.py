"""Inspect the exact Git index for private files and credential-like content.

Only locations and finding types are reported, never matched values.
This is a local leak check, not a copyright or factual-content certification.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {
    ".git", ".venv", "__pycache__", "sources", "attachments", "logs",
    "browser_profile", "browser_profile_edge", "course_files", "node_modules",
}
PRIVATE_SUFFIXES = {
    ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".log", ".pid",
    ".pdf", ".ppt", ".pptx", ".mp4", ".mov", ".mp3", ".wav",
    ".pem", ".p12", ".pfx", ".key", ".zip", ".7z",
}
PATTERNS = {
    "personal absolute path": re.compile(r"(?:[A-Za-z]:[\\/]+[U]sers[\\/]+|/[U]sers/|/[h]ome/)[^\s\"'<>]+", re.I),
    "private project identifier": re.compile(r"g-p-[a-f0-9]{32}|chatgpt[-]conversation://|conversationId\s*[\"']?\s*:", re.I),
    "provider credential format": re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b"),
    "private key material": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential embedded in URL": re.compile(r"https?://[^\s/:\"']+:[^\s/@\"']+@"),
    "credential URL query": re.compile(r"[?&](?:api_?key|access_token|token|secret|signature|password)=[^\s\"'&<>]+", re.I),
    "email address requiring review": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)


def local_secret_values():
    values = []
    candidates = dict(os.environ)
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, value = line.split("=", 1)
                candidates[name.strip()] = value.strip().strip("\"'")
    for name, value in candidates.items():
        if re.search(r"(?:API_KEY|ACCESS_TOKEN|PASSWORD|SECRET)$", name, re.I) and len(value) >= 12:
            values.append(value.encode())
    return set(values)


def inspect_blob(path, content, known_secrets=()):
    issues = []
    parts = Path(path).parts
    private_name = path == "MEMORY.md" or (parts and parts[0] == "data")
    private_name = private_name or any(part in PRIVATE_PARTS for part in parts)
    private_name = private_name or (Path(path).name.startswith(".env") and Path(path).name != ".env.example")
    if private_name or Path(path).suffix.lower() in PRIVATE_SUFFIXES:
        issues.append({"file": path, "kind": "private file type/path"})
    for secret in known_secrets:
        if secret in content:
            issues.append({"file": path, "kind": "matches a configured local secret"})
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        while offset + 12 <= len(content):
            size = int.from_bytes(content[offset:offset + 4], "big")
            kind = content[offset + 4:offset + 8]
            if kind in {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}:
                issues.append({"file": path, "kind": "image metadata requiring review"})
                break
            offset += size + 12
        return issues
    if b"\0" in content[:8192]:
        return issues
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return issues
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(source):
            line_number = source.count("\n", 0, match.start()) + 1
            line_text = source.splitlines()[line_number - 1]
            # This scanner's own deny-list deliberately contains a path pattern;
            # it is a rule being checked, not a machine-specific path to publish.
            if (path == "scripts/audit_installer_payload.py"
                    and kind == "personal absolute path"
                    and line_text.startswith("FORBIDDEN_TEXT = re.compile(")):
                continue
            # Exact, reviewed negative-test fixture using the reserved .example domain.
            fixtures = ("https://" + "user:" + "password@" + "model.example/v1",
                        "https://model.example/v1?" + "key=secret")
            if (path == "tests/test_model_settings.py"
                    and kind in {"credential embedded in URL", "email address requiring review", "credential URL query"}
                    and any(fixture in source and match.group() in fixture for fixture in fixtures)):
                continue
            issues.append({"file": path, "line": line_number, "kind": kind})
    if path == ".env.example":
        for line in source.splitlines():
            if re.match(r"\s*\w*(?:API_KEY|TOKEN|PASSWORD|SECRET)\s*=\s*\S+", line, re.I):
                issues.append({"file": path, "kind": "nonempty example credential"})
    return issues


def audit():
    index = git("ls-files", "--stage", "-z")
    if index.returncode:
        raise RuntimeError("Cannot read Git index")
    entries = [entry for entry in index.stdout.split(b"\0") if entry]
    known = local_secret_values()
    findings = []
    for entry in entries:
        metadata, encoded_path = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split()
        path = encoded_path.decode("utf-8")
        if stage != "0" or mode not in {"100644", "100755"}:
            findings.append({"file": path, "kind": "unmerged or non-regular Git entry"})
            continue
        content = git("cat-file", "blob", oid)
        if content.returncode:
            raise RuntimeError("Cannot read staged blob")
        findings.extend(inspect_blob(path, content.stdout, known))
    # Also inspect committed history: deleting a leaked file is not enough.
    history = git("rev-list", "--all", "--objects")
    history_blobs = 0
    if history.returncode == 0:
        seen = set()
        for item in history.stdout.splitlines():
            oid, separator, encoded_path = item.partition(b" ")
            if not separator or oid in seen:
                continue
            seen.add(oid)
            if git("cat-file", "-t", oid.decode()).stdout.strip() != b"blob":
                continue
            history_blobs += 1
            content = git("cat-file", "blob", oid.decode()).stdout
            for finding in inspect_blob(encoded_path.decode("utf-8"), content, known):
                findings.append({**finding, "scope": "committed history"})
    return {"staged_files": len(entries), "history_blobs": history_blobs,
            "configured_secret_values_checked": len(known), "findings": findings,
            "result": "review_required" if findings else "passed"}


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(1 if result["findings"] else 0)
