import asyncio
import contextlib

import httpx

from app.core.config import settings
from app.core.logger import logger
from app.models.domain import PeakEvent


class NotificationService:
    """
    Service responsible for dispatching real-time peak event alerts
    to external Webhooks (Discord, Telegram, or generic HTTP Webhook endpoints).

    Alerts are queued and delivered by a background worker so slow webhook
    endpoints never block chat ingestion or window persistence.
    """

    def __init__(self, webhook_url: str | None = None, queue_size: int = 1000):
        self.webhook_url = webhook_url
        self.queue_size = queue_size
        self._queue: asyncio.Queue[PeakEvent] | None = None
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Starts the background webhook delivery worker when configured."""
        if not self.webhook_url:
            return
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._queue = asyncio.Queue(maxsize=self.queue_size)
        self._worker_task = asyncio.create_task(
            self._worker(), name="notification-worker"
        )
        logger.info("Notification worker started.")

    async def stop(self) -> None:
        """Stops the delivery worker gracefully."""
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        self._worker_task = None
        self._queue = None

    def enqueue_peak_alert(self, peak: PeakEvent) -> bool:
        """
        Queues a peak alert without blocking the caller.

        Returns False when notifications are disabled or the queue is full.
        """
        if not self.webhook_url or self._queue is None:
            return False
        try:
            self._queue.put_nowait(peak)
            return True
        except asyncio.QueueFull:
            logger.warning(
                f"Notification queue is full; dropping peak alert for {peak.video_id}."
            )
            return False

    async def _worker(self) -> None:
        """Delivers queued alerts sequentially until cancelled."""
        assert self._queue is not None
        while True:
            peak = await self._queue.get()
            try:
                await self.send_peak_alert(peak)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error delivering queued peak alert: {e}")
            finally:
                self._queue.task_done()

    async def send_peak_alert(self, peak: PeakEvent, webhook_url: str | None = None) -> bool:
        """Dispatches peak alert payload to configured Webhook URL."""
        target_url = webhook_url or self.webhook_url
        if not target_url:
            return False

        fields = [
            {"name": "Total Chat Messages", "value": str(peak.total_messages), "inline": True},
            {"name": "Peak Keywords", "value": ", ".join(peak.highlight_keywords) or "N/A", "inline": True},
        ]
        if peak.video_start_time and peak.video_end_time:
            fields.append({
                "name": "Video Timestamp",
                "value": f"`{peak.video_start_time}` - `{peak.video_end_time}`",
                "inline": False
            })
        fields.extend([
            {"name": "Clip Start (Jam Asli)", "value": peak.padded_start_time.isoformat(), "inline": True},
            {"name": "Clip End (Jam Asli)", "value": peak.padded_end_time.isoformat(), "inline": True},
        ])

        # Format payload for generic Webhook or Discord
        payload = {
            "content": f"🚨 **HIGHLIGHT DETECTED!** (Video ID: `{peak.video_id}`)",
            "embeds": [
                {
                    "title": f"Peak Z-Score: {peak.max_z_score:.2f} 🚀",
                    "description": f"Peak Chat Velocity: **{peak.max_chat_velocity:.2f} msg/s**",
                    "fields": fields,
                    "color": 15158332  # Red color embed
                }
            ]
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(target_url, json=payload)
                if response.status_code in (200, 204):
                    logger.info(f"Successfully dispatched peak alert webhook for {peak.video_id}")
                    return True
                else:
                    logger.warning(f"Webhook dispatch failed with HTTP {response.status_code}: {response.text}")
                    return False
            except Exception as e:
                logger.error(f"Error dispatching webhook notification: {e}")
                return False


notification_service = NotificationService(webhook_url=settings.WEBHOOK_URL or None)
