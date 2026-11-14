from datetime import datetime, timedelta, timezone
import httpx
import pytest

from app.models.domain import PeakEvent
from app.services.notifier import build_webhook_payload, send_peak_webhook


def _sample_peak(highlight_score: float = 7.5) -> PeakEvent:
    now = datetime.now(timezone.utc)
    return PeakEvent(
        video_id="vid_notify_1",
        start_time=now,
        peak_time=now + timedelta(seconds=10),
        end_time=now + timedelta(seconds=20),
        padded_start_time=now,
        padded_end_time=now + timedelta(seconds=35),
        video_start_time="05:00",
        video_end_time="05:35",
        start_offset_seconds=300.0,
        end_offset_seconds=335.0,
        max_z_score=4.2,
        max_chat_velocity=3.5,
        total_messages=40,
        highlight_score=highlight_score,
        unique_authors=22,
        highlight_keywords=["clutch", "gg"],
        sample_messages=["u1: GILA CLUTCH!"],
        moment_category="Hype / Clutch",
    )


def test_build_webhook_payload_discord_vs_generic():
    peak = _sample_peak()

    discord_payload = build_webhook_payload(peak, "https://discord.com/api/webhooks/123/abc")
    assert "embeds" in discord_payload
    assert "[Hype / Clutch]" in discord_payload["content"]
    assert "clutch, gg" in str(discord_payload["embeds"][0]["fields"])

    generic_payload = build_webhook_payload(peak, "https://example.com/hook")
    assert generic_payload["event"] == "peak_detected"
    assert generic_payload["moment_category"] == "Hype / Clutch"
    assert generic_payload["watch_url"].endswith("&t=300s")


@pytest.mark.asyncio
async def test_send_peak_webhook_threshold_and_delivery():
    peak = _sample_peak(highlight_score=6.0)
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        # Below min score -> skipped
        skipped = await send_peak_webhook(
            peak,
            webhook_url="https://example.com/hook",
            min_highlight_score=8.0,
            client=client,
        )
        assert skipped is False
        assert len(sent_requests) == 0

        # Meets min score -> delivered
        delivered = await send_peak_webhook(
            peak,
            webhook_url="https://example.com/hook",
            min_highlight_score=5.0,
            client=client,
        )
        assert delivered is True
        assert len(sent_requests) == 1
