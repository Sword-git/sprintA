import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# SQLite for local dev (no PostgreSQL required)
APP_DB_PATH = os.environ.get("APP_DB_PATH", os.path.join(os.path.dirname(__file__), "mem0_app.db"))

engine = create_engine(f"sqlite:///{APP_DB_PATH}", pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
