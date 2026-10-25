"""Check and download verified public Windows releases from GitHub."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.version import get_version, version_tuple

OWNER = "twosstar"
REPOSITORY = "ai-pm-learning-compass"
RELEASE_API = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/latest"
CHECKSUM_NAME = "SHA256SUMS.txt"
MAX_INSTALLER_BYTES = 350 * 1024 * 1024
_verified_installer: Path | None = None
_verified_version: str | None = None
_verified_sha256: str | None = None
_check_lock = asyncio.Lock()


def _trusted_release_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _update_dir() -> Path:
    configured = os.environ.get("AI_PM_USER_CONFIG_DIR")
    if configured:
        root = Path(configured).parent
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home()))
        root = Path(local_app_data) / "AI PM Learning Compass"
    folder = root / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def _read_text(client: httpx.AsyncClient, url: str, limit: int = 128_000) -> str:
    if not _trusted_release_url(url):
        raise ValueError("untrusted_release_url")
    response = await client.get(url, headers={"Accept": "application/octet-stream"}, follow_redirects=True)
    response.raise_for_status()
    if response.url.scheme != "https" or response.url.host not in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
        raise ValueError("untrusted_asset_host")
    if len(response.content) > limit:
        raise ValueError("release_metadata_too_large")
    return response.text


async def _download_verified(
    client: httpx.AsyncClient,
    url: str,
    destination: Path,
    expected_sha256: str,
) -> Path:
    if not _trusted_release_url(url):
        raise ValueError("untrusted_release_url")
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            final_host = response.url.host
            if response.url.scheme != "https" or final_host not in {
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }:
                raise ValueError("untrusted_asset_host")
            announced_size = int(response.headers.get("content-length", "0") or 0)
            if announced_size > MAX_INSTALLER_BYTES:
                raise ValueError("asset_too_large")
            with temporary.open("wb") as output:
                async for chunk in response.aiter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > MAX_INSTALLER_BYTES:
                        raise ValueError("asset_too_large")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if size == 0 or digest.hexdigest().lower() != expected_sha256.lower():
            raise ValueError("checksum_mismatch")
        os.replace(temporary, destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


async def _release_asset(client: httpx.AsyncClient, current_version: str) -> dict:
    response = await client.get(RELEASE_API, headers={"Accept": "application/vnd.github+json"})
    response.raise_for_status()
    release = response.json()
    if not isinstance(release, dict):
        raise ValueError("invalid_release_metadata")
    tag = release.get("tag_name", "")
    candidate_version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else ""
    if release.get("draft") or release.get("prerelease") or not version_tuple(candidate_version):
        return {"available": False, "state": "no_update"}
    current_tuple = version_tuple(current_version)
    candidate_tuple = version_tuple(candidate_version)
    if not current_tuple or not candidate_tuple or candidate_tuple <= current_tuple:
        return {"available": False, "state": "no_update"}

    expected_name = f"AI-PM-Learning-Compass-Setup-{candidate_version}.exe"
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("invalid_release_assets")
    by_name = {item.get("name"): item for item in assets if isinstance(item, dict)}
    installer = by_name.get(expected_name)
    checksum = by_name.get(CHECKSUM_NAME)
    if not installer or not checksum:
        raise ValueError("release_asset_missing")
    installer_url = installer.get("browser_download_url", "")
    checksum_url = checksum.get("browser_download_url", "")
    if not _trusted_release_url(installer_url) or not _trusted_release_url(checksum_url):
        raise ValueError("untrusted_release_url")

    manifest = await _read_text(client, checksum_url)
    matches = []
    for line in manifest.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == expected_name and re.fullmatch(r"[a-fA-F0-9]{64}", parts[0]):
            matches.append(parts[0])
    if len(matches) != 1:
        raise ValueError("invalid_checksum_manifest")
    return {
        "available": True,
        "state": "downloading",
        "version": candidate_version,
        "installer_url": installer_url,
        "sha256": matches[0],
        "installer_name": expected_name,
    }


async def check_for_update(current_version: str | None = None) -> dict:
    """Check the latest stable release and download it before offering installation."""
    global _verified_installer, _verified_version, _verified_sha256
    current_version = current_version or get_version()
    if not version_tuple(current_version):
        return {"available": False, "state": "invalid_current_version"}
    async with _check_lock:
        timeout = httpx.Timeout(20.0, connect=8.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                release = await _release_asset(client, current_version)
                if not release["available"]:
                    _verified_installer = None
                    _verified_version = None
                    _verified_sha256 = None
                    return release
                if _verified_installer and _verified_version == release["version"] and _verified_installer.is_file():
                    if _file_sha256(_verified_installer) == release["sha256"].lower():
                        return {"available": True, "state": "ready", "version": _verified_version}
                installer_path = _update_dir() / release["installer_name"]
                await _download_verified(client, release["installer_url"], installer_path, release["sha256"])
                _verified_installer = installer_path
                _verified_version = release["version"]
                _verified_sha256 = release["sha256"].lower()
                return {"available": True, "state": "ready", "version": _verified_version}
        except (httpx.HTTPError, OSError, ValueError):
            return {"available": False, "state": "check_failed"}


def launch_verified_installer() -> None:
    """Start the bundled helper for the already verified installer only."""
    global _verified_installer
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("自动安装只适用于已安装的 Windows 桌面版。")
    if not _verified_installer or not _verified_installer.is_file() or not _verified_sha256:
        raise RuntimeError("尚未准备好经过校验的更新安装包。")
    if _file_sha256(_verified_installer) != _verified_sha256:
        _verified_installer.unlink(missing_ok=True)
        _verified_installer = None
        raise RuntimeError("更新安装包校验失败，请重新检查更新。")
    helper = Path(sys.executable).with_name("AI PM Learning Compass Update.exe")
    if not helper.is_file():
        raise RuntimeError("更新组件不完整，请从 GitHub Releases 下载新版安装包。")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    try:
        subprocess.Popen(
            [str(helper), str(_verified_installer), str(os.getpid())],
            cwd=str(Path(sys.executable).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        raise RuntimeError("无法启动更新组件，请重新安装应用后再试。") from exc
