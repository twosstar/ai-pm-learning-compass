import json
import logging
from dataclasses import dataclass
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlparse

from openai import AsyncOpenAI
import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.model_credentials import CredentialStorageError, load_api_key, load_model_preferences

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)
logger = logging.getLogger(__name__)


@dataclass(frozen=True, repr=False)
class RuntimeModel:
    client: AsyncOpenAI | None
    model: str
    base_url: str
    source: str


class LLMService:
    def __init__(self) -> None:
        settings = get_settings()
        try:
            preferences = load_model_preferences()
            saved_key = load_api_key()
        except (CredentialStorageError, RuntimeError):
            preferences, saved_key = {}, None
        api_key = settings.llm_api_key or saved_key or ""
        base_url = preferences.get("base_url", settings.llm_base_url)
        model = preferences.get("model", settings.llm_chat_model)
        source = "environment" if settings.llm_api_key else "credential-manager" if saved_key else "none"
        self._runtime = RuntimeModel(
            self._make_client(api_key, base_url) if api_key else None,
            model, base_url, source,
        )
        self._remembered = source == "credential-manager"
        self.last_error = ''
        self._verified = False

    @staticmethod
    def _make_client(api_key: str, base_url: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=0, timeout=30.0,
            http_client=httpx.AsyncClient(follow_redirects=False, timeout=30.0),
        )

    @property
    def _configured(self) -> bool:
        return self._runtime.client is not None

    def configure_runtime(self, api_key: str, base_url: str, model: str, remembered: bool = False) -> None:
        # One atomic reference change; in-flight requests keep their own snapshot.
        source = "credential-manager" if remembered else "session"
        self._runtime = RuntimeModel(self._make_client(api_key, base_url), model, base_url, source)
        self._remembered = remembered
        self.last_error = ''
        self._verified = False

    def clear_runtime(self) -> None:
        current = self._runtime
        self._runtime = RuntimeModel(None, current.model, current.base_url, 'none')
        self._remembered = False
        self.last_error = ''
        self._verified = False

    def public_status(self) -> dict:
        runtime = self._runtime
        parsed = urlparse(runtime.base_url)
        # Never echo credentials/query parameters, even from legacy environment URLs.
        host = parsed.hostname or ''
        if ':' in host:
            host = f'[{host}]'
        port = f':{parsed.port}' if parsed.port else ''
        safe_url = f'{parsed.scheme}://{host}{port}{parsed.path}'
        return {'configured': runtime.client is not None, 'base_url': safe_url,
                'model': runtime.model, 'source': runtime.source, 'last_error': self.last_error,
                'verified': self._verified, 'storage': runtime.source,
                'remembered': self._remembered}

    @staticmethod
    def _options(runtime: RuntimeModel) -> dict:
        return (
            {"extra_body": {"thinking": {"type": "disabled"}}}
            if urlparse(runtime.base_url).hostname == "api.deepseek.com"
            else {}
        )

    def _record_error(self, exc: Exception) -> None:
        self._verified = False
        name = type(exc).__name__
        messages = {
            'AuthenticationError': '认证失败：请检查密钥与供应商是否匹配。',
            'PermissionDeniedError': '没有该模型的访问权限，请核对供应商账户。',
            'NotFoundError': '接口或模型不存在，请核对 API 地址与模型名称。',
            'RateLimitError': '请求受限或额度不足，请到供应商后台核对。',
            'APITimeoutError': '模型响应超时，请稍后重新评价。',
            'APIConnectionError': '无法连接模型服务，请核对 API 地址与网络。',
            'JSONDecodeError': '模型返回的内容不是有效 JSON，当前接口可能不兼容。',
            'ValidationError': '模型返回格式不符合评分要求，请换用支持结构化输出的模型。',
        }
        self.last_error = messages.get(name, '模型调用失败，请核对供应商、模型与账户状态。')
        # Provider errors may echo request secrets. Never log their body or repr.
        logger.warning('Model request failed (%s)', name)

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
    ) -> str:
        runtime = self._runtime
        if runtime.client is None:
            raise RuntimeError('尚未配置模型，请打开页面中的“模型设置”。')
        token_limit = {"max_tokens": max_tokens} if max_tokens is not None else {}
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await runtime.client.chat.completions.create(
                    model=runtime.model,
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    **token_limit,
                )
                content = (response.choices[0].message.content or "").strip()
                if content:
                    self.last_error = ''
                    self._verified = True
                    return content
                last_error = RuntimeError("模型返回了空答案。")
                logger.warning("LLM returned an empty answer; retrying")
            except Exception as exc:
                last_error = exc
                self._record_error(exc)
                break
        raise RuntimeError("模型连续返回空答案或调用失败，请稍后重试。") from last_error

    async def complete_json(self, system: str, user: str) -> dict:
        runtime = self._runtime
        if runtime.client is None:
            raise RuntimeError('尚未配置模型，请打开页面中的“模型设置”。')
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await runtime.client.chat.completions.create(
                    model=runtime.model,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": f"{system}\n只输出一个合法 JSON 对象。",
                        },
                        {"role": "user", "content": user},
                    ],
                    **self._options(runtime),
                )
                value = json.loads(response.choices[0].message.content or "")
                if not isinstance(value, dict):
                    raise TypeError("模型返回的不是 JSON 对象。")
                self.last_error = ''
                self._verified = True
                return value
            except Exception as exc:
                last_error = exc
                self._record_error(exc)
                break
        raise RuntimeError("模型没有返回可解析的结构化结果，请重试。") from last_error

    async def complete_structured(
        self,
        schema: type[StructuredOutput],
        system: str,
        user: str,
        fallback: Callable[[], StructuredOutput],
        retries: int = 2,
        max_tokens: int | None = None,
        on_api_call: Callable[[], None] | None = None,
        on_usage: Callable[[int, int], None] | None = None,
        on_fallback: Callable[[], None] | None = None,
    ) -> StructuredOutput:
        """Request a JSON object, validate it against a Pydantic schema, then fall back safely."""
        runtime = self._runtime
        if runtime.client is None:
            if on_fallback:
                on_fallback()
            return fallback()
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        token_limit = {"max_tokens": max_tokens} if max_tokens is not None else {}
        for _ in range(min(retries, 1) + 1):
            try:
                if on_api_call:
                    on_api_call()
                response = await runtime.client.chat.completions.create(
                    model=runtime.model,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"{system}\n输出必须严格符合以下 JSON Schema，不得输出额外文本："
                                f"\n{schema_json}"
                            ),
                        },
                        {"role": "user", "content": user},
                    ],
                    **token_limit,
                    **self._options(runtime),
                )
                usage = getattr(response, "usage", None)
                if usage and on_usage:
                    on_usage(
                        int(getattr(usage, "prompt_tokens", 0) or 0),
                        int(getattr(usage, "completion_tokens", 0) or 0),
                    )
                raw = json.loads(response.choices[0].message.content or "")
                result = schema.model_validate(raw)
                self.last_error = ''
                self._verified = True
                return result
            except Exception as exc:
                self._record_error(exc)
                if type(exc).__name__ not in {'JSONDecodeError', 'ValidationError'}:
                    break
        if on_fallback:
            on_fallback()
        return fallback()


llm_service = LLMService()
