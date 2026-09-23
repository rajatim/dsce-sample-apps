import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLITE_FALLBACK_URL = "sqlite:///./loan_app.db"


def resolve_database_url() -> str:
    return os.getenv("DATABASE_URL", SQLITE_FALLBACK_URL)


def build_engine(database_url: str) -> Engine:
    options = {"pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options.update(
            pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "90")),
            pool_recycle=300,
        )
    return create_engine(database_url, **options)


engine = build_engine(resolve_database_url())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency to get a DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
