import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.core.config import settings
from app.core.database import async_session_factory, engine as default_engine
from app.core.logger import logger
from app.models.db import (
    ChatMessageModel,
    PeakEventModel,
    WindowRollupModel,
    WindowStatsModel,
)


class RetentionService:
    """
    Periodically rolls old window stats into hourly aggregates and deletes data
    that has exceeded its configured retention period.
    """

    def __init__(
        self,
        session_factory=async_session_factory,
        db_engine=default_engine
    ):
        self._session_factory = session_factory
        self._engine = db_engine
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Starts the periodic retention worker when enabled."""
        if not settings.ENABLE_DATA_RETENTION:
            logger.info("Data retention is disabled.")
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run_periodic(), name="retention-cleanup"
        )
        logger.info("Data retention worker started.")

    async def stop(self) -> None:
        """Stops the periodic retention worker gracefully."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _run_periodic(self) -> None:
        interval_seconds = max(
            60.0, settings.RETENTION_CHECK_INTERVAL_HOURS * 3600.0
        )
        while True:
            try:
                await self.run_cleanup()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Data retention cleanup failed: {e}")
            await asyncio.sleep(interval_seconds)

    async def run_cleanup(self, now: datetime | None = None) -> dict[str, int]:
        """
        Rolls up expired window stats, then deletes expired windows, peaks,
        and raw chat messages.

        A retention value of 0 (or negative) keeps that data type forever.
        """
        empty_result = {
            "rollups": 0,
            "windows_deleted": 0,
            "peaks_deleted": 0,
            "messages_deleted": 0,
        }
        if not settings.ENABLE_DATA_RETENTION:
            return empty_result

        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        window_cutoff = self._cutoff(now, settings.WINDOW_STATS_RETENTION_DAYS)
        peak_cutoff = self._cutoff(now, settings.PEAK_EVENTS_RETENTION_DAYS)
        chat_cutoff = self._cutoff(now, settings.CHAT_MESSAGE_RETENTION_DAYS)
        if window_cutoff is None and peak_cutoff is None and chat_cutoff is None:
            return empty_result

        async with self._lock:
            async with self._session_factory() as session:
                rollups = 0
                windows_deleted = 0
                peaks_deleted = 0
                messages_deleted = 0

                if window_cutoff is not None:
                    rollups = await self._rollup_windows(session, window_cutoff)
                    result = await session.execute(
                        delete(WindowStatsModel).where(
                            WindowStatsModel.window_end < window_cutoff
                        )
                    )
                    windows_deleted = self._affected_rows(result)

                if peak_cutoff is not None:
                    result = await session.execute(
                        delete(PeakEventModel).where(
                            PeakEventModel.created_at < peak_cutoff
                        )
                    )
                    peaks_deleted = self._affected_rows(result)

                if chat_cutoff is not None:
                    result = await session.execute(
                        delete(ChatMessageModel).where(
                            ChatMessageModel.event_time < chat_cutoff
                        )
                    )
                    messages_deleted = self._affected_rows(result)

                await session.commit()

        if rollups or windows_deleted or peaks_deleted or messages_deleted:
            logger.info(
                f"Retention cleanup: {rollups} rollup bucket(s), "
                f"{windows_deleted} window(s), {peaks_deleted} peak(s), "
                f"{messages_deleted} chat message(s) removed."
            )

        return {
            "rollups": rollups,
            "windows_deleted": windows_deleted,
            "peaks_deleted": peaks_deleted,
            "messages_deleted": messages_deleted,
        }

    @staticmethod
    def _cutoff(now: datetime, days: int) -> datetime | None:
        if days <= 0:
            return None
        return now - timedelta(days=days)

    async def _rollup_windows(self, session, cutoff: datetime) -> int:
        bucket_expr = self._bucket_expression()
        statement = (
            select(
                WindowStatsModel.video_id.label("video_id"),
                bucket_expr.label("bucket_start"),
                func.count(WindowStatsModel.id).label("window_count"),
                func.sum(WindowStatsModel.message_count).label("message_count"),
                func.sum(
                    case((WindowStatsModel.is_peak.is_(True), 1), else_=0)
                ).label("peak_count"),
                func.sum(WindowStatsModel.emoji_count).label("emoji_count"),
                func.avg(WindowStatsModel.chat_velocity).label("avg_chat_velocity"),
                func.max(WindowStatsModel.chat_velocity).label("max_chat_velocity"),
                func.avg(WindowStatsModel.z_score).label("avg_z_score"),
                func.max(WindowStatsModel.z_score).label("max_z_score"),
            )
            .where(WindowStatsModel.window_end < cutoff)
            .group_by(WindowStatsModel.video_id, bucket_expr)
        )
        rows = (await session.execute(statement)).all()
        if not rows:
            return 0

        values = [
            {
                "video_id": row.video_id,
                "bucket_start": self._to_utc_datetime(row.bucket_start),
                "window_count": int(row.window_count),
                "message_count": int(row.message_count or 0),
                "peak_count": int(row.peak_count or 0),
                "emoji_count": int(row.emoji_count or 0),
                "avg_chat_velocity": float(row.avg_chat_velocity or 0.0),
                "max_chat_velocity": float(row.max_chat_velocity or 0.0),
                "avg_z_score": float(row.avg_z_score or 0.0),
                "max_z_score": float(row.max_z_score or 0.0),
            }
            for row in rows
        ]

        insert_stmt = self._insert_for(WindowRollupModel).values(values)
        update_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["video_id", "bucket_start"],
            set_={
                "window_count": (
                    WindowRollupModel.window_count
                    + insert_stmt.excluded.window_count
                ),
                "message_count": (
                    WindowRollupModel.message_count
                    + insert_stmt.excluded.message_count
                ),
                "peak_count": (
                    WindowRollupModel.peak_count
                    + insert_stmt.excluded.peak_count
                ),
                "emoji_count": (
                    WindowRollupModel.emoji_count
                    + insert_stmt.excluded.emoji_count
                ),
                "avg_chat_velocity": (
                    (
                        WindowRollupModel.avg_chat_velocity
                        * WindowRollupModel.window_count
                        + insert_stmt.excluded.avg_chat_velocity
                        * insert_stmt.excluded.window_count
                    )
                    / (
                        WindowRollupModel.window_count
                        + insert_stmt.excluded.window_count
                    )
                ),
                "max_chat_velocity": self._max_expression(
                    WindowRollupModel.max_chat_velocity,
                    insert_stmt.excluded.max_chat_velocity
                ),
                "avg_z_score": (
                    (
                        WindowRollupModel.avg_z_score
                        * WindowRollupModel.window_count
                        + insert_stmt.excluded.avg_z_score
                        * insert_stmt.excluded.window_count
                    )
                    / (
                        WindowRollupModel.window_count
                        + insert_stmt.excluded.window_count
                    )
                ),
                "max_z_score": self._max_expression(
                    WindowRollupModel.max_z_score,
                    insert_stmt.excluded.max_z_score
                ),
            }
        )
        result = await session.execute(update_stmt)
        affected = self._affected_rows(result)
        return affected if affected > 0 else len(values)

    def _bucket_expression(self):
        if self._engine.dialect.name == "postgresql":
            return func.date_trunc("hour", WindowStatsModel.window_start)
        return func.strftime("%Y-%m-%d %H:00:00", WindowStatsModel.window_start)

    def _insert_for(self, model):
        if self._engine.dialect.name == "postgresql":
            return postgresql_insert(model)
        return sqlite_insert(model)

    @staticmethod
    def _affected_rows(result) -> int:
        count = result.rowcount
        return count if count is not None and count > 0 else 0

    @staticmethod
    def _max_expression(existing, incoming):
        return case((incoming > existing, incoming), else_=existing)

    @staticmethod
    def _to_utc_datetime(value) -> datetime:
        if isinstance(value, str):
            value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


retention_service = RetentionService()
