from pathlib import Path
import sys

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if settings.database_url.startswith("sqlite:///"):
    db_path = Path(settings.database_url.removeprefix("sqlite:///"))
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        if getattr(sys, "frozen", False):
            raise RuntimeError("无法写入本机学习数据目录，请检查用户配置文件夹权限。")
        # Sandboxed/dev environments may not expose D:. Keep the configured
        # D: location as the production default, but remain runnable locally.
        fallback = Path(__file__).resolve().parents[2] / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        settings.storage_dir = fallback
        settings.chroma_path = fallback / "chroma"
        settings.database_url = f"sqlite:///{fallback / 'app.db'}"

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session
