from contextlib import asynccontextmanager
import hashlib
from pathlib import Path

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
    lifespan=lifespan,
)


@app.middleware('http')
async def fresh_local_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {'/', '/api/model-settings', '/api/catalog'} or request.url.path.startswith(('/static/', '/api/progress')):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    return response

app.include_router(health.router, prefix="/api")
app.include_router(public_catalog.router, prefix="/api")
app.include_router(public_concepts.router, prefix="/api")
app.include_router(public_study.router, prefix="/api")
app.include_router(public_model_settings.router, prefix="/api")
app.include_router(public_progress.router, prefix="/api")


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
