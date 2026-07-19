from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# Get the backend directory path
BACKEND_DIR = Path(__file__).parent.parent
DATABASE_PATH = BACKEND_DIR / "hedge_fund.db"

# Database configuration - use absolute path
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Create SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # Needed for SQLite
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models
Base = declarative_base()

# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(eng=None) -> None:
    """
    Safe column-addition migrations for SQLite (no Alembic).
    Each ALTER TABLE is wrapped in try/except so re-runs are idempotent.
    Call this after Base.metadata.create_all() on startup.
    """
    from sqlalchemy import text
    target = eng or engine

    migrations = [
        # screener_runs — weight_profile and run_date added after initial schema
        "ALTER TABLE screener_runs ADD COLUMN weight_profile VARCHAR(30) DEFAULT 'medium_long'",
        "ALTER TABLE screener_runs ADD COLUMN run_date VARCHAR(10)",
        # screener_results — technical_score added when weight profiles spec was added
        "ALTER TABLE screener_results ADD COLUMN technical_score REAL",
    ]

    with target.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                # Column already exists or table doesn't exist yet — both are fine
                pass