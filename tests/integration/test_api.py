import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_health_check_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"


@pytest.mark.asyncio
async def test_streams_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Check active streams list
        response = await client.get("/api/v1/streams/active")
        assert response.status_code == 200
        assert "active_count" in response.json()


@pytest.mark.asyncio
async def test_peaks_api_endpoints():
    import uuid
    from datetime import datetime, timezone
    from app.core.database import async_session_factory
    from app.models.db import PeakEventModel

    test_video_id = f"test_vid_{uuid.uuid4().hex[:8]}"
    test_key = f"key_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        session.add(PeakEventModel(
            video_id=test_video_id,
            start_time=now,
            peak_time=now,
            end_time=now,
            padded_start_time=now,
            padded_end_time=now,
            video_start_time="01:15",
            video_end_time="01:45",
            start_offset_seconds=75.0,
            end_offset_seconds=105.0,
            max_z_score=3.5,
            max_chat_velocity=5.0,
            total_messages=50,
            highlight_keywords=["gg", "mantap"],
            dedup_key=test_key
        ))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Query recent peaks (paginated envelope)
        response = await client.get("/api/v1/peaks/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "total_pages" in data
        matching = [p for p in data["items"] if p["video_id"] == test_video_id]
        assert len(matching) >= 1
        assert matching[0]["video_start_time"] == "01:15"
        assert matching[0]["video_end_time"] == "01:45"
        assert matching[0]["start_offset_seconds"] == 75.0
        assert matching[0]["end_offset_seconds"] == 105.0

        # Query with filtering and sorting
        res_filter = await client.get(
            f"/api/v1/peaks/?video_id={test_video_id}&min_z_score=3.0&keyword=mantap&sort_by=max_z_score&sort_order=desc&page=1&page_size=10"
        )
        assert res_filter.status_code == 200
        f_data = res_filter.json()
        assert f_data["total"] >= 1
        assert f_data["items"][0]["video_id"] == test_video_id

        # Query filter with no match returns empty envelope cleanly
        res_empty = await client.get("/api/v1/peaks/?keyword=nonexistent_keyword_xyz_123")
        assert res_empty.status_code == 200
        e_data = res_empty.json()
        assert e_data["total"] == 0
        assert e_data["items"] == []
        assert e_data["total_pages"] == 1

        # Query video-specific peaks
        res_vid = await client.get(f"/api/v1/peaks/{test_video_id}")
        assert res_vid.status_code == 200
        vid_data = res_vid.json()
        assert len(vid_data) >= 1
        assert vid_data[0]["video_start_time"] == "01:15"
        assert vid_data[0]["video_end_time"] == "01:45"


@pytest.mark.asyncio
async def test_channels_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Add channel
        res_add = await client.post("/api/v1/channels/track/UC123456789")
        assert res_add.status_code == 200
        tracked = res_add.json()["tracked_channels"]
        assert any(c["channel_id"] == "UC123456789" for c in tracked)

        # List channels
        res_list = await client.get("/api/v1/channels/")
        assert res_list.status_code == 200
        assert res_list.json()["count"] >= 1

        # Untrack channel
        res_del = await client.delete("/api/v1/channels/untrack/UC123456789")
        assert res_del.status_code == 200
