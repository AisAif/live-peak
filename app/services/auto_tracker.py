import asyncio
from sqlalchemy import select, delete
from app.core.logger import logger
from app.core.database import async_session_factory
from app.models.db import TrackedChannelModel
from app.services.discovery import StreamDiscoveryService
from app.services.manager import stream_manager


class AutoChannelTracker:
    """
    Service responsible for periodically polling a list of target YouTube Channel IDs or handles (@PUBGMOBILE),
    detecting when any of them go LIVE, and automatically launching real-time chat tracking.
    Persists target channels in SQLite DB ('tracked_channels' table).
    """

    def __init__(self, check_interval_seconds: int = 60):
        self.check_interval = check_interval_seconds
        self.discovery_service = StreamDiscoveryService()
        self.is_running = False
        self.task: asyncio.Task | None = None

    async def add_channel(self, channel_or_handle: str) -> dict | None:
        """
        Adds a YouTube Channel ID or Handle (@PUBGMOBILE) to auto-tracking list in SQLite DB.
        Returns dict with {"channel_id": str, "channel_name": str}, or None if duplicate/failed.
        """
        details = await self.discovery_service.resolve_channel_details(channel_or_handle)
        if not details:
            return None

        channel_id, channel_name = details

        async with async_session_factory() as session:
            # Check if already exists in DB
            stmt = select(TrackedChannelModel).where(TrackedChannelModel.channel_id == channel_id)
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing:
                # Update channel_name if it was previously saved with ID as fallback
                if existing.channel_name == channel_id and channel_name != channel_id:
                    existing.channel_name = channel_name
                    await session.commit()
                return {"channel_id": existing.channel_id, "channel_name": existing.channel_name}

            # Create new record in DB
            new_record = TrackedChannelModel(
                channel_id=channel_id,
                channel_name=channel_name
            )
            session.add(new_record)
            await session.commit()
            logger.info(f"Persisted Channel '{channel_name}' (ID: '{channel_id}') to SQLite DB.")
            return {"channel_id": channel_id, "channel_name": channel_name}

    async def remove_channel(self, channel_id: str) -> bool:
        """Removes a YouTube Channel ID from auto-tracking list in SQLite DB."""
        async with async_session_factory() as session:
            stmt = delete(TrackedChannelModel).where(TrackedChannelModel.channel_id == channel_id)
            result = await session.execute(stmt)
            await session.commit()
            if result.rowcount > 0:
                logger.info(f"Removed Channel ID '{channel_id}' from SQLite DB.")
                return True
            return False

    async def list_channels_enriched(self) -> list[dict]:
        """Returns list of tracked channels from SQLite DB, auto-enriching names if needed."""
        async with async_session_factory() as session:
            stmt = select(TrackedChannelModel).order_by(TrackedChannelModel.created_at.desc())
            result = await session.execute(stmt)
            records = result.scalars().all()

            channels = []
            for r in records:
                # Auto-enrich missing channel name if it matches channel_id
                if r.channel_name == r.channel_id:
                    details = await self.discovery_service.resolve_channel_details(r.channel_id)
                    if details and details[1] and details[1] != r.channel_id:
                        r.channel_name = details[1]
                        await session.commit()
                channels.append({"channel_id": r.channel_id, "channel_name": r.channel_name})

            return channels

    async def start(self) -> None:
        """Starts periodic background channel discovery loop."""
        self.is_running = True
        self.task = asyncio.create_task(self._periodic_loop())
        logger.info("Auto Channel Tracker service started.")

    async def stop(self) -> None:
        """Stops periodic background channel discovery loop."""
        self.is_running = False
        if self.task and not self.task.done():
            self.task.cancel()
        logger.info("Auto Channel Tracker service stopped.")

    async def _periodic_loop(self) -> None:
        """Periodic background task that checks all target channels in SQLite DB for live streams."""
        while self.is_running:
            try:
                channels = await self.list_channels_enriched()
                for ch in channels:
                    channel_id = ch["channel_id"]
                    stream_info = await self.discovery_service.discover_by_channel_id(channel_id)
                    if stream_info and stream_info.is_live:
                        video_id = stream_info.video_id
                        if video_id not in stream_manager.active_workers:
                            logger.info(
                                f"🎥 Auto-detected LIVE stream for channel {ch['channel_name']} ({channel_id})! "
                                f"Starting automatic tracking for video {video_id} ('{stream_info.title}')"
                            )
                            await stream_manager.start_monitoring_stream(video_id)
            except Exception as e:
                logger.error(f"Error in auto-tracker periodic check: {e}")

            await asyncio.sleep(self.check_interval)


auto_tracker = AutoChannelTracker()
