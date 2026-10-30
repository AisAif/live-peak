import asyncio
import contextlib
import hashlib
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.core.logger import logger
from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.models.domain import ChatMessage, WindowStats, PeakEvent
from app.models.db import (
    ChatMessageModel,
    PeakEventModel,
    PeakKeywordModel,
    WindowStatsModel,
    StreamModel,
)
from app.services.ingestion import ChatIngestionService
from app.services.analytics import SlidingWindowAnalytics
from app.services.merger import PeakMerger
from app.services.notification import notification_service


def _insert_for(model):
    """Returns a dialect-specific INSERT builder supporting ON CONFLICT DO NOTHING."""
    if engine.dialect.name == "postgresql":
        return postgresql_insert(model)
    return sqlite_insert(model)


def build_peak_dedup_key(peak: PeakEvent) -> str:
    """Builds a stable idempotency key for a finalized peak event."""
    raw = "|".join([
        peak.video_id,
        peak.start_time.isoformat(),
        peak.peak_time.isoformat(),
        peak.end_time.isoformat(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


MAX_CHAT_BUFFER = 10_000


class ActiveStreamWorker:
    """Encapsulates active pipeline components for a single video stream."""

    def __init__(self, video_id: str, started_at: datetime | None = None):
        self.video_id = video_id
        self.started_at: datetime = started_at or datetime.now(timezone.utc)
        self.analytics = SlidingWindowAnalytics(video_id=video_id)
        self.merger = PeakMerger(video_id=video_id, stream_start=self.started_at)
        self.ingestion: ChatIngestionService | None = None
        self.task: asyncio.Task | None = None
        self.ticker_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.raw_chat_enabled = settings.ENABLE_RAW_CHAT_STORAGE
        self.chat_buffer: list[ChatMessage] = []

    async def handle_message(self, msg: ChatMessage) -> None:
        """Callback triggered for each incoming chat message."""
        async with self.lock:
            if self.raw_chat_enabled:
                self.chat_buffer.append(msg)
            completed_windows = self.analytics.process_message(msg)
            await self._process_stats(completed_windows)

    async def run_ticker(self) -> None:
        """Periodically finalizes windows so quiet periods still advance the baseline."""
        interval = max(1.0, self.analytics.window_duration / 5)
        try:
            while True:
                await asyncio.sleep(interval)
                async with self.lock:
                    await self._process_stats(self.analytics.tick())
                    await self._flush_chat_buffer()
        except asyncio.CancelledError:
            raise

    async def _process_stats(self, stats_list: list[WindowStats]) -> None:
        """Persists windows and forwards them to peak merging + notifications."""
        for stats in stats_list:
            await self._persist_window_stats(stats)
            peak_event = self.merger.process_window(stats)
            if peak_event is not None:
                saved = await self._persist_peak_event(peak_event)
                if saved:
                    notification_service.enqueue_peak_alert(peak_event)

    async def _persist_window_stats(self, stats: WindowStats) -> bool:
        """Saves periodic WindowStats to DB idempotently by (video_id, window_start)."""
        try:
            async with async_session_factory() as session:
                stmt = _insert_for(WindowStatsModel).values(
                    video_id=stats.video_id,
                    window_start=stats.window_start,
                    window_end=stats.window_end,
                    message_count=stats.message_count,
                    chat_velocity=stats.chat_velocity,
                    emoji_count=stats.emoji_count,
                    top_keywords=stats.top_keywords,
                    z_score=stats.z_score,
                    ewma_velocity=stats.ewma_velocity,
                    ewma_z_score=stats.ewma_z_score,
                    cusum_score=stats.cusum_score,
                    peak_source=stats.peak_source,
                    is_peak=stats.is_peak
                ).on_conflict_do_nothing(
                    index_elements=["video_id", "window_start"]
                )
                result = await session.execute(stmt)
                await session.commit()
                return (result.rowcount or 0) > 0
        except Exception as e:
            logger.error(f"Error persisting window stats for {self.video_id}: {e}")
            return False

    async def _persist_peak_event(self, peak: PeakEvent) -> bool:
        """Saves a finalized PeakEvent highlight to DB idempotently by dedup_key."""
        dedup_key = build_peak_dedup_key(peak)
        try:
            async with async_session_factory() as session:
                stmt = _insert_for(PeakEventModel).values(
                    video_id=peak.video_id,
                    start_time=peak.start_time,
                    peak_time=peak.peak_time,
                    end_time=peak.end_time,
                    padded_start_time=peak.padded_start_time,
                    padded_end_time=peak.padded_end_time,
                    video_start_time=peak.video_start_time,
                    video_end_time=peak.video_end_time,
                    start_offset_seconds=peak.start_offset_seconds,
                    end_offset_seconds=peak.end_offset_seconds,
                    max_z_score=peak.max_z_score,
                    max_chat_velocity=peak.max_chat_velocity,
                    total_messages=peak.total_messages,
                    highlight_keywords=peak.highlight_keywords,
                    dedup_key=dedup_key
                ).on_conflict_do_nothing(index_elements=["dedup_key"])
                result = await session.execute(stmt)
                saved = (result.rowcount or 0) > 0

                peak_id = (await session.execute(
                    select(PeakEventModel.id).where(
                        PeakEventModel.dedup_key == dedup_key
                    )
                )).scalar_one_or_none()
                if peak_id is not None:
                    await self._persist_peak_keywords(session, peak_id, peak)

                await session.commit()
                if saved:
                    logger.info(f"Successfully saved Peak Event for video {self.video_id} to DB.")
                return saved
        except Exception as e:
            logger.error(f"Error persisting peak event for {self.video_id}: {e}")
            return False

    async def _persist_peak_keywords(
        self,
        session,
        peak_id: int,
        peak: PeakEvent
    ) -> None:
        """Indexes a peak's keywords in the normalized search table."""
        keywords = []
        seen: set[str] = set()
        for keyword in peak.highlight_keywords or []:
            normalized = keyword.strip().lower()[:100]
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            keywords.append({
                "peak_id": peak_id,
                "video_id": peak.video_id,
                "keyword": normalized,
            })

        if not keywords:
            return

        stmt = _insert_for(PeakKeywordModel).values(keywords).on_conflict_do_nothing(
            index_elements=["peak_id", "keyword"]
        )
        await session.execute(stmt)

    async def _flush_chat_buffer(self) -> None:
        """Persists buffered raw chat messages in batches, ignoring duplicate IDs."""
        if not self.chat_buffer:
            return

        batch = self.chat_buffer
        self.chat_buffer = []
        batch_size = max(1, settings.CHAT_FLUSH_BATCH_SIZE)
        committed = 0

        try:
            for offset in range(0, len(batch), batch_size):
                chunk = batch[offset:offset + batch_size]
                async with async_session_factory() as session:
                    stmt = _insert_for(ChatMessageModel).values([
                        {
                            "video_id": msg.video_id,
                            "message_id": msg.message_id or None,
                            "author_name": msg.author_name,
                            "message": msg.message,
                            "amount_str": msg.amount_str,
                            "event_time": msg.timestamp,
                        }
                        for msg in chunk
                    ]).on_conflict_do_nothing(
                        index_elements=["video_id", "message_id"]
                    )
                    await session.execute(stmt)
                    await session.commit()
                committed = offset + len(chunk)
        except asyncio.CancelledError:
            self._restore_chat_buffer(batch[committed:])
            raise
        except Exception as e:
            logger.error(f"Error persisting raw chat messages for {self.video_id}: {e}")
            self._restore_chat_buffer(batch[committed:])

    def _restore_chat_buffer(self, batch: list[ChatMessage]) -> None:
        """Restores unpersisted messages, keeping memory bounded."""
        combined = batch + self.chat_buffer
        if len(combined) > MAX_CHAT_BUFFER:
            logger.warning(
                f"Raw chat buffer for {self.video_id} exceeded {MAX_CHAT_BUFFER} "
                "messages; dropping oldest entries."
            )
            combined = combined[-MAX_CHAT_BUFFER:]
        self.chat_buffer = combined


class StreamManager:
    """
    Central manager service controlling background worker tasks across multiple live streams.
    """

    def __init__(self):
        self.active_workers: dict[str, ActiveStreamWorker] = {}

    async def _upsert_stream(
        self,
        video_id: str,
        channel_id: str | None = None,
        title: str | None = None
    ) -> datetime:
        """Creates or refreshes stream metadata before monitoring starts."""
        now = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            stream = await session.get(StreamModel, video_id)
            if stream is None:
                stream_start = now
                session.add(StreamModel(
                    video_id=video_id,
                    channel_id=channel_id or "unknown",
                    title=title or f"Live Stream {video_id}",
                    is_live=True,
                    started_at=stream_start,
                    ended_at=None
                ))
            else:
                stream.is_live = True
                if not stream.started_at:
                    stream.started_at = now
                stream_start = stream.started_at
                stream.ended_at = None
                if channel_id:
                    stream.channel_id = channel_id
                if title:
                    stream.title = title
            await session.commit()
            return stream_start

    async def _mark_stream_offline(self, video_id: str) -> None:
        """Marks a stream as no longer live in the database."""
        async with async_session_factory() as session:
            stream = await session.get(StreamModel, video_id)
            if stream is not None:
                stream.is_live = False
                stream.ended_at = datetime.now(timezone.utc)
                await session.commit()

    async def start_monitoring_stream(
        self,
        video_id: str,
        channel_id: str | None = None,
        title: str | None = None
    ) -> bool:
        """Starts background pipeline worker for target video_id."""
        if video_id in self.active_workers:
            logger.warning(f"Stream {video_id} is already being monitored.")
            return False

        stream_start = await self._upsert_stream(video_id, channel_id=channel_id, title=title)

        worker = ActiveStreamWorker(video_id=video_id, started_at=stream_start)
        worker.ingestion = ChatIngestionService(
            video_id=video_id,
            message_callback=worker.handle_message
        )

        # Launch background ingestion + window timer tasks
        worker.task = asyncio.create_task(worker.ingestion.start_listening())
        worker.ticker_task = asyncio.create_task(worker.run_ticker())
        self.active_workers[video_id] = worker

        logger.info(f"Started monitoring pipeline for stream {video_id}")
        return True

    async def stop_monitoring_stream(self, video_id: str) -> bool:
        """Stops background pipeline worker for target video_id."""
        if video_id not in self.active_workers:
            return False

        worker = self.active_workers.pop(video_id)

        # Stop timer first so it no longer competes for the worker lock
        if worker.ticker_task and not worker.ticker_task.done():
            worker.ticker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker.ticker_task

        if worker.ingestion:
            worker.ingestion.stop()

        async with worker.lock:
            # Flush any partial window so the last messages are not lost
            if worker.analytics.current_messages:
                await worker._process_stats([
                    worker.analytics.finalize_window(use_actual_duration=True)
                ])

            # Flush any remaining active peak
            final_peak = worker.merger.flush(end_time=datetime.now(timezone.utc))
            if final_peak:
                saved = await worker._persist_peak_event(final_peak)
                if saved:
                    notification_service.enqueue_peak_alert(final_peak)

            # Persist any raw chat messages still waiting in the buffer
            await worker._flush_chat_buffer()

        if worker.task and not worker.task.done():
            worker.task.cancel()

        await self._mark_stream_offline(video_id)

        logger.info(f"Stopped monitoring pipeline for stream {video_id}")
        return True

    def list_active_streams(self) -> list[str]:
        """Returns list of video IDs currently monitored."""
        return list(self.active_workers.keys())


stream_manager = StreamManager()
