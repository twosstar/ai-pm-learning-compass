"""Per-user model preferences and opt-in Windows Credential Manager storage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

_SERVICE_NAME = "AI PM Learning Compass"
_CREDENTIAL_NAME = "model-provider-api-key"
_PREFERENCE_NAME = "model.json"
_ALLOWED_PREFERENCES = {"base_url", "model"}


def _desktop_storage_enabled() -> bool:
    return os.environ.get("AI_PM_DESKTOP") == "1"


class CredentialStorageError(RuntimeError):
    """Credential Manager is unavailable or failed to store the requested key."""


def _config_dir() -> Path:
    configured = os.environ.get("AI_PM_USER_CONFIG_DIR")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AI PM Learning Compass" / "config"
    return Path.home() / ".config" / "ai-pm-learning-compass"


def _credential_backend():
    if os.name != "nt":
        raise CredentialStorageError("此设备不支持 Windows 凭据保险库。")
    try:
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    except Exception as exc:
        raise CredentialStorageError("Windows 凭据保险库暂不可用。") from exc


def load_api_key() -> str | None:
    """Read the app's per-user Windows credential, if one was saved."""
    if os.name != "nt" or not _desktop_storage_enabled():
        return None
    try:
        return _credential_backend().get_password(_SERVICE_NAME, _CREDENTIAL_NAME)
    except CredentialStorageError:
        raise
    except Exception as exc:
        raise CredentialStorageError("读取 Windows 凭据失败。") from exc


def save_api_key(api_key: str) -> None:
    """Store an API key only in the current Windows user's Credential Manager."""
    if not _desktop_storage_enabled():
        raise CredentialStorageError("只有桌面版可以记住此设备的密钥。")
    try:
        _credential_backend().set_password(_SERVICE_NAME, _CREDENTIAL_NAME, api_key)
    except CredentialStorageError:
        raise
    except Exception as exc:
        raise CredentialStorageError("保存到 Windows 凭据保险库失败。") from exc


def delete_api_key() -> None:
    """Delete the saved key; deleting a missing credential is successful."""
    if not _desktop_storage_enabled():
        return
    try:
        _credential_backend().delete_password(_SERVICE_NAME, _CREDENTIAL_NAME)
    except CredentialStorageError:
        raise
    except Exception as exc:
        # keyring uses PasswordDeleteError for a missing item on some versions.
        if type(exc).__name__ not in {"PasswordDeleteError", "CredentialNotFoundError"}:
            raise CredentialStorageError("删除 Windows 凭据失败。") from exc


def api_key_is_saved() -> bool:
    return bool(load_api_key())


def load_model_preferences() -> dict[str, str]:
    if not _desktop_storage_enabled():
        return {}
    path = _config_dir() / _PREFERENCE_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("读取本机模型设置失败。") from exc
    if not isinstance(payload, dict) or set(payload) - _ALLOWED_PREFERENCES:
        raise RuntimeError("本机模型设置格式不正确。")
    return {key: value for key, value in payload.items() if isinstance(value, str)}


def save_model_preferences(base_url: str, model: str) -> None:
    if not _desktop_storage_enabled():
        return
    path = _config_dir() / _PREFERENCE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"base_url": base_url, "model": model}, ensure_ascii=False)
    temporary_name: str | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix="model-", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise RuntimeError("保存本机模型设置失败。") from exc


def clear_model_preferences() -> None:
    if not _desktop_storage_enabled():
        return
    try:
        (_config_dir() / _PREFERENCE_NAME).unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError("删除本机模型设置失败。") from exc


def clear_model_credentials() -> None:
    delete_api_key()
    clear_model_preferences()
