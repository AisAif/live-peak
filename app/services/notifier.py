import logging
from typing import Any
import httpx

from app.core.config import settings
from app.models.domain import PeakEvent

logger = logging.getLogger("live_peak")
_SHARED_HTTP_CLIENT: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    global _SHARED_HTTP_CLIENT
    if _SHARED_HTTP_CLIENT is None or _SHARED_HTTP_CLIENT.is_closed:
        _SHARED_HTTP_CLIENT = httpx.AsyncClient(timeout=5.0)
    return _SHARED_HTTP_CLIENT


def _clamp_field(value: str, max_len: int = 1024) -> str:
    text = value.strip() or "-"
    return text if len(text) <= max_len else f"{text[: max_len - 3]}..."


def build_webhook_payload(peak: PeakEvent, webhook_url: str) -> dict[str, Any]:
    """Builds a Discord-compatible or generic JSON payload for a detected PeakEvent."""
    keywords_str = _clamp_field(", ".join(peak.highlight_keywords) if peak.highlight_keywords else "-")
    samples_str = _clamp_field(
        "\n".join(f"> {msg}" for msg in peak.sample_messages[:3]) if peak.sample_messages else "-"
    )
    time_range = (
        f"{peak.video_start_time} - {peak.video_end_time}"
        if peak.video_start_time and peak.video_end_time
        else f"{peak.padded_start_time.isoformat()} - {peak.padded_end_time.isoformat()}"
    )
    category = peak.moment_category or "General Spike"
    watch_url = f"https://www.youtube.com/watch?v={peak.video_id}"
    if peak.start_offset_seconds is not None:
        watch_url += f"&t={int(peak.start_offset_seconds)}s"

    lowered_url = webhook_url.lower()
    if "discord.com/api/webhooks" in lowered_url or "discordapp.com/api/webhooks" in lowered_url:
        return {
            "content": f"**[{category}]** Highlight Peak terdeteksi pada `{peak.video_id}` ({time_range})",
            "embeds": [
                {
                    "title": f"Highlight Score: {peak.highlight_score:.2f} | Max Z: {peak.max_z_score:.2f}",
                    "url": watch_url,
                    "color": 0x10B981,
                    "fields": [
                        {"name": "Kategori", "value": category, "inline": True},
                        {"name": "Range Video", "value": time_range, "inline": True},
                        {"name": "Chat / Authors", "value": f"{peak.total_messages} msg / {peak.unique_authors} user", "inline": True},
                        {"name": "Keywords", "value": keywords_str, "inline": False},
                        {"name": "Sample Chat", "value": samples_str, "inline": False},
                    ],
                }
            ],
        }

    return {
        "event": "peak_detected",
        "video_id": peak.video_id,
        "watch_url": watch_url,
        "moment_category": category,
        "highlight_score": peak.highlight_score,
        "max_z_score": peak.max_z_score,
        "max_chat_velocity": peak.max_chat_velocity,
        "total_messages": peak.total_messages,
        "unique_authors": peak.unique_authors,
        "video_start_time": peak.video_start_time,
        "video_end_time": peak.video_end_time,
        "start_offset_seconds": peak.start_offset_seconds,
        "end_offset_seconds": peak.end_offset_seconds,
        "highlight_keywords": peak.highlight_keywords,
        "sample_messages": peak.sample_messages,
    }


async def send_peak_webhook(
    peak: PeakEvent,
    webhook_url: str | None = None,
    min_highlight_score: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """
    Sends a non-blocking webhook notification for a newly persisted PeakEvent.
    Returns True if delivered (2xx), False if skipped or failed.
    """
    target_url = (webhook_url if webhook_url is not None else settings.WEBHOOK_URL).strip()
    threshold = min_highlight_score if min_highlight_score is not None else settings.WEBHOOK_MIN_HIGHLIGHT_SCORE
    if not target_url or peak.highlight_score < threshold:
        return False

    payload = build_webhook_payload(peak, target_url)
    try:
        target_client = client if client is not None else _get_shared_client()
        response = await target_client.post(target_url, json=payload)
        response.raise_for_status()
        logger.info(f"Webhook delivered for peak {peak.video_id} ({peak.moment_category}).")
        return True
    except Exception as e:
        logger.warning(f"Failed to deliver peak webhook for {peak.video_id}: {e}")
        return False
