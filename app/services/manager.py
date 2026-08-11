import asyncio
from datetime import datetime, timezone
from app.core.logger import logger
from app.core.database import async_session_factory
from app.models.domain import ChatMessage, WindowStats, PeakEvent
from app.models.db import PeakEventModel, WindowStatsModel, StreamModel
from app.services.ingestion import ChatIngestionService
from app.services.analytics import SlidingWindowAnalytics
from app.services.merger import PeakMerger


class ActiveStreamWorker:
    """Encapsulates active pipeline components for a single video stream."""

    def __init__(self, video_id: str):
        self.video_id = video_id
        self.analytics = SlidingWindowAnalytics(video_id=video_id)
        self.merger = PeakMerger(video_id=video_id)
        self.ingestion: ChatIngestionService | None = None
        self.task: asyncio.Task | None = None
        self.started_at: datetime = datetime.now(timezone.utc)

    async def handle_message(self, msg: ChatMessage) -> None:
        """Callback triggered for each incoming chat message."""
        stats = self.analytics.process_message(msg)
        if stats is not None:
            await self._persist_window_stats(stats)
            peak_event = self.merger.process_window(stats)
            if peak_event is not None:
                await self._persist_peak_event(peak_event)

    async def _persist_window_stats(self, stats: WindowStats) -> None:
        """Saves periodic 10-second WindowStats to local SQLite DB."""
        try:
            async with async_session_factory() as session:
                db_model = WindowStatsModel(
                    video_id=stats.video_id,
                    window_start=stats.window_start,
                    window_end=stats.window_end,
                    message_count=stats.message_count,
                    chat_velocity=stats.chat_velocity,
                    emoji_count=stats.emoji_count,
                    top_keywords=stats.top_keywords,
                    z_score=stats.z_score,
                    is_peak=stats.is_peak
                )
                session.add(db_model)
                await session.commit()
        except Exception as e:
            logger.error(f"Error persisting window stats for {self.video_id}: {e}")

    async def _persist_peak_event(self, peak: PeakEvent) -> None:
        """Saves finalized PeakEvent highlight to local SQLite DB."""
        try:
            async with async_session_factory() as session:
                db_model = PeakEventModel(
                    video_id=peak.video_id,
                    start_time=peak.start_time,
                    peak_time=peak.peak_time,
                    end_time=peak.end_time,
                    padded_start_time=peak.padded_start_time,
                    padded_end_time=peak.padded_end_time,
                    max_z_score=peak.max_z_score,
                    max_chat_velocity=peak.max_chat_velocity,
                    total_messages=peak.total_messages,
                    highlight_keywords=peak.highlight_keywords
                )
                session.add(db_model)
                await session.commit()
                logger.info(f"Successfully saved Peak Event ID for video {self.video_id} to DB.")
        except Exception as e:
            logger.error(f"Error persisting peak event for {self.video_id}: {e}")


class StreamManager:
    """
    Central manager service controlling background worker tasks across multiple live streams.
    """

    def __init__(self):
        self.active_workers: dict[str, ActiveStreamWorker] = {}

    async def start_monitoring_stream(self, video_id: str) -> bool:
        """Starts background pipeline worker for target video_id."""
        if video_id in self.active_workers:
            logger.warning(f"Stream {video_id} is already being monitored.")
            return False

        worker = ActiveStreamWorker(video_id=video_id)
        worker.ingestion = ChatIngestionService(
            video_id=video_id,
            message_callback=worker.handle_message
        )

        # Launch background ingestion task
        worker.task = asyncio.create_task(worker.ingestion.start_listening())
        self.active_workers[video_id] = worker

        logger.info(f"Started monitoring pipeline for stream {video_id}")
        return True

    async def stop_monitoring_stream(self, video_id: str) -> bool:
        """Stops background pipeline worker for target video_id."""
        if video_id not in self.active_workers:
            return False

        worker = self.active_workers.pop(video_id)
        if worker.ingestion:
            worker.ingestion.stop()

        # Flush any remaining active peak
        final_peak = worker.merger.flush()
        if final_peak:
            await worker._persist_peak_event(final_peak)

        if worker.task and not worker.task.done():
            worker.task.cancel()

        logger.info(f"Stopped monitoring pipeline for stream {video_id}")
        return True

    def list_active_streams(self) -> list[str]:
        """Returns list of video IDs currently monitored."""
        return list(self.active_workers.keys())


stream_manager = StreamManager()
