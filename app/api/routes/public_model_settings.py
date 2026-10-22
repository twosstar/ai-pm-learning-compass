"""Loopback-only, same-origin model configuration. No credential persistence."""
import hmac
import ipaddress
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, SecretStr

from app.services.llm import llm_service

router = APIRouter(prefix='/model-settings', tags=['local-model-settings'])
_LOCAL_TOKEN = secrets.token_urlsafe(32)
_LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def require_local_access(request: Request) -> None:
    try:
        local_client = request.client and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local_client = False
    if not local_client or request.url.hostname not in _LOCAL_HOSTS:
        raise HTTPException(403, '模型设置只允许本机访问。')
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.headers.get("host", "")}'.lower()
    if origin and origin.lower() != expected:
        raise HTTPException(403, '模型设置不接受跨站请求。')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, '模型设置不接受跨站请求。')
    if request.method != 'GET':
        token = request.headers.get('x-local-settings-token', '')
        if not hmac.compare_digest(token, _LOCAL_TOKEN):
            raise HTTPException(403, '请重新打开模型设置后再操作。')


class LocalModelConfiguration(BaseModel):
    base_url: str
    model: str
    api_key: SecretStr
    allow_provider_requests: bool = False


def validate_configuration(payload: LocalModelConfiguration) -> tuple[str, str, str]:
    if not payload.allow_provider_requests:
        raise HTTPException(400, '请确认信任该供应商，并知晓调用模型可能产生费用。')
    base_url, model, key = payload.base_url.strip(), payload.model.strip(), payload.api_key.get_secret_value().strip()
    if not 1 <= len(key) <= 4096 or any(char.isspace() for char in key):
        raise HTTPException(400, '请填写有效密钥，不要包含空格或换行。')
    if not 1 <= len(model) <= 200 or any(ord(char) < 33 for char in model):
        raise HTTPException(400, '请填写供应商提供的模型名称，不要包含空格或换行。')
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        parsed.port  # Validate malformed ports without sending a request.
        safe = (len(base_url) <= 2048 and parsed.scheme == 'https' and hostname
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and not any(char.isspace() for char in base_url) and '\\' not in base_url)
        if not safe or hostname in _LOCAL_HOSTS or hostname.endswith(('.localhost', '.local')):
            raise ValueError
        try:
            if not ipaddress.ip_address(hostname).is_global:
                raise ValueError
        except ValueError:
            # A valid domain need not be an IP literal. An invalid IP literal is rejected below.
            if ':' in hostname or all(char in '0123456789.' for char in hostname):
                raise HTTPException(400, '不支持私有或本机 API 地址。')
    except (ValueError, AttributeError):
        raise HTTPException(400, 'API 地址须为可信供应商的 HTTPS 基础地址，不能包含账号、密钥参数或片段。')
    return key, base_url.rstrip('/'), model


def public_state(response: Response) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    return dict(llm_service.public_status(), settings_token=_LOCAL_TOKEN)


@router.get('', dependencies=[Depends(require_local_access)])
async def status(response: Response) -> dict:
    return public_state(response)


@router.put('', dependencies=[Depends(require_local_access)])
async def configure(payload: LocalModelConfiguration, request: Request, response: Response) -> dict:
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, '请使用页面中的模型设置表单。')
    key, base_url, model = validate_configuration(payload)
    llm_service.configure_runtime(key, base_url, model)
    return public_state(response)


@router.delete('', dependencies=[Depends(require_local_access)])
async def clear(response: Response) -> dict:
    llm_service.clear_runtime()
    return public_state(response)
