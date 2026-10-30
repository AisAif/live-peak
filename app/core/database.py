import os
from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
from app.core.logger import logger


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


# Ensure directory exists if using local SQLite with a path like ./data/live_peak.db
if "sqlite" in settings.DATABASE_URL:
    parts = settings.DATABASE_URL.split(":///")
    if len(parts) > 1:
        db_file_path = parts[1]
        dir_name = os.path.dirname(db_file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

# Create async engine for local SQLite or PostgreSQL
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# Apply high-concurrency PRAGMAs for SQLite connections (WAL mode & busy timeout)
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA cache_size=-64000;")
        cursor.execute("PRAGMA temp_store=MEMORY;")
        cursor.execute("PRAGMA mmap_size=268435456;")
        cursor.close()

# Async session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


def _run_sqlite_migrations(conn) -> None:
    """
    Lightweight additive migrations for existing local SQLite databases.

    SQLAlchemy's create_all() does not alter existing tables, so new columns and
    unique indexes must be added explicitly to keep old databases compatible.
    """
    conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
    conn.exec_driver_sql("PRAGMA busy_timeout=5000;")
    conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
    logger.info("SQLite configuration: WAL mode, busy_timeout=5000ms, synchronous=NORMAL active.")

    def table_columns(table_name: str) -> set[str]:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
        return {row[1] for row in rows}

    if "ended_at" not in table_columns("streams"):
        conn.exec_driver_sql("ALTER TABLE streams ADD COLUMN ended_at DATETIME")
        logger.info("Migration: added streams.ended_at column.")

    if "dedup_key" not in table_columns("peak_events"):
        conn.exec_driver_sql("ALTER TABLE peak_events ADD COLUMN dedup_key VARCHAR(255)")
        logger.info("Migration: added peak_events.dedup_key column.")

    peak_columns = table_columns("peak_events")
    peak_additions = {
        "video_start_time": "VARCHAR(50)",
        "video_end_time": "VARCHAR(50)",
        "start_offset_seconds": "FLOAT",
        "end_offset_seconds": "FLOAT",
    }
    for col_name, col_type in peak_additions.items():
        if col_name not in peak_columns:
            conn.exec_driver_sql(f"ALTER TABLE peak_events ADD COLUMN {col_name} {col_type}")
            logger.info(f"Migration: added peak_events.{col_name} column.")

    window_columns = table_columns("window_stats")
    window_additions = {
        "ewma_velocity": "FLOAT NOT NULL DEFAULT 0",
        "ewma_z_score": "FLOAT NOT NULL DEFAULT 0",
        "cusum_score": "FLOAT NOT NULL DEFAULT 0",
        "peak_source": "VARCHAR(50)",
    }
    for column_name, column_type in window_additions.items():
        if column_name not in window_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE window_stats ADD COLUMN {column_name} {column_type}"
            )
            logger.info(f"Migration: added window_stats.{column_name} column.")

    conn.exec_driver_sql(
        "UPDATE peak_events SET dedup_key = 'legacy-' || id WHERE dedup_key IS NULL"
    )

    # Backfill the normalized keyword index once for pre-existing peaks.
    try:
        keyword_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM peak_keywords"
        ).scalar() or 0
        if keyword_count == 0:
            conn.exec_driver_sql(
                "INSERT OR IGNORE INTO peak_keywords (peak_id, video_id, keyword) "
                "SELECT p.id, p.video_id, lower(trim(j.value)) "
                "FROM peak_events p, json_each(p.highlight_keywords) j "
                "WHERE j.value IS NOT NULL AND trim(j.value) != ''"
            )
            logger.info("Migration: backfilled peak_keywords from existing peaks.")
    except Exception as e:
        logger.warning(f"Peak keyword backfill skipped: {e}")

    migrations = [
        "CREATE INDEX IF NOT EXISTS ix_peak_keywords_keyword "
        "ON peak_keywords(keyword)",
        "CREATE INDEX IF NOT EXISTS ix_peak_keywords_video_keyword "
        "ON peak_keywords(video_id, keyword)",
        "CREATE INDEX IF NOT EXISTS ix_peak_keywords_peak_id "
        "ON peak_keywords(peak_id)",
        "CREATE INDEX IF NOT EXISTS ix_streams_started_at "
        "ON streams(started_at)",
        "CREATE INDEX IF NOT EXISTS ix_peak_events_video_offset "
        "ON peak_events(video_id, start_offset_seconds)",
        "CREATE INDEX IF NOT EXISTS ix_peak_events_video_peak_time "
        "ON peak_events(video_id, peak_time)",
        "CREATE INDEX IF NOT EXISTS ix_peak_events_video_max_z "
        "ON peak_events(video_id, max_z_score)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_window_stats_video_start "
        "ON window_stats(video_id, window_start)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_peak_events_dedup_key "
        "ON peak_events(dedup_key)",
        "CREATE INDEX IF NOT EXISTS ix_peak_events_created_at "
        "ON peak_events(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_peak_events_max_z_score "
        "ON peak_events(max_z_score)",
        "CREATE INDEX IF NOT EXISTS ix_window_stats_video_end "
        "ON window_stats(video_id, window_end)",
        "CREATE INDEX IF NOT EXISTS ix_window_stats_window_end "
        "ON window_stats(window_end)",
    ]
    for statement in migrations:
        try:
            conn.exec_driver_sql(statement)
        except Exception as e:
            logger.warning(f"Migration skipped ({statement}): {e}")


async def init_db() -> None:
    """Initialize database tables and run additive SQLite migrations."""
    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            await conn.run_sync(_run_sqlite_migrations)
    logger.info("Database tables initialized successfully.")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for FastAPI endpoint DB sessions."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error, rolled back: {e}")
            raise
        finally:
            await session.close()
