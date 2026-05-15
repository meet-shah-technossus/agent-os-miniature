from __future__ import annotations
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from sqlalchemy.engine import Engine

Base = declarative_base()
_engine: Engine | None = None
SessionLocal: scoped_session | None = None


def init_db(app: Flask) -> None:
    """Initialize SQLAlchemy engine, session factory, and database tables."""
    global _engine, SessionLocal

    database_url = app.config.get("DATABASE_URL", "sqlite:///appointments.db")
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, future=True, connect_args=connect_args)
    session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    SessionLocal = scoped_session(session_factory)
    Base.metadata.create_all(bind=_engine)

    @app.teardown_appcontext
    def teardown_session(exception: Exception | None = None) -> None:
        SessionLocal.remove()


def get_session() -> scoped_session:
    """Return the scoped session bound to the current engine."""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db(app) first.")
    return SessionLocal
