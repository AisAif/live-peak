import httpx
from app.core.logger import logger
from app.models.domain import PeakEvent


class NotificationService:
    """
    Service responsible for dispatching real-time peak event alerts
    to external Webhooks (Discord, Telegram, or generic HTTP Webhook endpoints).
    """

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url

    async def send_peak_alert(self, peak: PeakEvent, webhook_url: str | None = None) -> bool:
        """Dispatches peak alert payload to configured Webhook URL."""
        target_url = webhook_url or self.webhook_url
        if not target_url:
            return False

        # Format payload for generic Webhook or Discord
        payload = {
            "content": f"🚨 **HIGHLIGHT DETECTED!** (Video ID: `{peak.video_id}`)",
            "embeds": [
                {
                    "title": f"Peak Z-Score: {peak.max_z_score:.2f} 🚀",
                    "description": f"Peak Chat Velocity: **{peak.max_chat_velocity:.2f} msg/s**",
                    "fields": [
                        {"name": "Total Chat Messages", "value": str(peak.total_messages), "inline": True},
                        {"name": "Peak Keywords", "value": ", ".join(peak.highlight_keywords) or "N/A", "inline": True},
                        {"name": "Video Clip Start", "value": peak.padded_start_time.isoformat(), "inline": False},
                        {"name": "Video Clip End", "value": peak.padded_end_time.isoformat(), "inline": False},
                    ],
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


notification_service = NotificationService()
