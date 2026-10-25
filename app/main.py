from contextlib import asynccontextmanager
import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import secrets
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.staticfiles import StaticFiles

from app.api.routes import health, public_catalog, public_concepts, public_study, public_model_settings, public_progress
from app.db import models  # noqa: F401
from app.db.session import Base, engine, SessionLocal
from app.services.public_seed import seed_public_data
from app.services.public_concept_library import sync_public_concepts

STATIC_DIR = Path(__file__).parent / "static"
DESKTOP_RUNTIME = os.environ.get("AI_PM_DESKTOP") == "1"
DESKTOP_SESSION_TOKEN = secrets.token_urlsafe(32)
REQUEST_WINDOWS: dict[tuple[str, str], tuple[int, float]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_public_data()
    with SessionLocal() as db:
        sync_public_concepts(db)
    yield


app = FastAPI(
    title="AI PM Learning Copilot · Public Edition",
    version="0.1.0",
    docs_url=None if DESKTOP_RUNTIME else "/docs",
    redoc_url=None if DESKTOP_RUNTIME else "/redoc",
    openapi_url=None if DESKTOP_RUNTIME else "/openapi.json",
    lifespan=lifespan,
)


@app.middleware('http')
async def fresh_local_ui(request: Request, call_next):
    if DESKTOP_RUNTIME and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        try:
            local_client = request.client and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local_client = False
        if not local_client or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "此接口仅供本机应用使用。"}, status_code=403)

        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}".lower()
        if ((origin and origin.lower() != expected_origin)
                or request.headers.get("sec-fetch-site") == "cross-site"):
            return JSONResponse({"detail": "此请求来源不受支持。"}, status_code=403)

        supplied_token = request.cookies.get("ai_pm_session", "")
        if not hmac.compare_digest(supplied_token, DESKTOP_SESSION_TOKEN):
            return JSONResponse({"detail": "应用会话已更新，请刷新页面后重试。"}, status_code=403)

        try:
            content_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            content_length = 0
        if content_length > 1_048_576:
            return JSONResponse({"detail": "请求内容过大，请缩短后重试。"}, status_code=413)

        client_key = request.client.host if request.client else "local"
        limit_key = (client_key, "/api/concepts" if request.url.path == "/api/concepts" else
                     "/api/study/start" if request.url.path == "/api/study/start" else "/api")
        now = time.monotonic()
        count, window_start = REQUEST_WINDOWS.get(limit_key, (0, now))
        limit = 600 if limit_key[1] == "/api/concepts" else 60 if limit_key[1] == "/api/study/start" else 1200
        if now - window_start >= 60:
            count, window_start = 0, now
        if count >= limit:
            return JSONResponse({"detail": "操作稍快，请稍后再试。"}, status_code=429,
                                headers={"Retry-After": "2", "Cache-Control": "no-store"})
        REQUEST_WINDOWS[limit_key] = (count + 1, window_start)

    response = await call_next(request)
    if request.url.path == "/" and DESKTOP_RUNTIME:
        response.set_cookie("ai_pm_session", DESKTOP_SESSION_TOKEN, httponly=True, samesite="strict", path="/")
    if request.url.path in {'/', '/api/model-settings', '/api/catalog'} or request.url.path.startswith(('/static/', '/api/progress', '/api/catalog/')):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response

app.include_router(health.router, prefix="/api")
app.include_router(public_catalog.router, prefix="/api")
app.include_router(public_concepts.router, prefix="/api")
app.include_router(public_study.router, prefix="/api")
app.include_router(public_model_settings.router, prefix="/api")
app.include_router(public_progress.router, prefix="/api")
if os.environ.get("AI_PM_DESKTOP") == "1":
    from app.api.routes import desktop_updates

    app.include_router(desktop_updates.router, prefix="/api")


@app.exception_handler(RequestValidationError)
async def safe_configuration_errors(request: Request, exc: RequestValidationError):
    if request.url.path == '/api/model-settings':
        # FastAPI's default validation details can echo invalid input, including secrets.
        return JSONResponse({'detail': '模型配置格式不正确，请检查地址、模型名称与密钥。'}, status_code=422,
                            headers={'Cache-Control': 'no-store'})
    return await request_validation_exception_handler(request, exc)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    versions = {}
    for asset in ('app.js', 'styles.css', 'progress.js'):
        version = hashlib.sha256((STATIC_DIR / asset).read_bytes()).hexdigest()[:12]
        versions[asset] = version
        html = html.replace(f'/static/{asset}"', f'/static/{asset}?v={version}"')
    return HTMLResponse(html, headers={'X-Learning-UI-Version': versions['app.js']})
