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
    from app.models.db import PeakEventModel, PeakKeywordModel

    test_video_id = f"test_vid_{uuid.uuid4().hex[:8]}"
    test_key = f"key_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        peak = PeakEventModel(
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
        )
        session.add(peak)
        await session.flush()
        session.add_all([
            PeakKeywordModel(
                peak_id=peak.id,
                video_id=test_video_id,
                keyword=keyword,
            )
            for keyword in ("gg", "mantap")
        ])
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
async def test_videos_api_endpoints():
    import uuid
    from datetime import datetime, timedelta, timezone
    from app.core.database import async_session_factory
    from app.models.db import PeakEventModel, StreamModel

    test_video_id = f"vid_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        session.add(StreamModel(
            video_id=test_video_id,
            channel_id="UC_VIDEO_TEST",
            title="Grand Finals Highlights",
            is_live=False,
            started_at=now,
            ended_at=now + timedelta(hours=1),
        ))
        for offset, z_score in ((75.0, 3.2), (130.0, 4.8)):
            session.add(PeakEventModel(
                video_id=test_video_id,
                start_time=now + timedelta(seconds=offset),
                peak_time=now + timedelta(seconds=offset),
                end_time=now + timedelta(seconds=offset + 10),
                padded_start_time=now + timedelta(seconds=offset - 15),
                padded_end_time=now + timedelta(seconds=offset + 25),
                video_start_time="01:15",
                video_end_time="01:45",
                start_offset_seconds=offset,
                end_offset_seconds=offset + 30,
                max_z_score=z_score,
                max_chat_velocity=5.0 + z_score,
                total_messages=50,
                highlight_keywords=["gg", "clutch"],
                dedup_key=f"key_{uuid.uuid4().hex}",
            ))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        today = now.date().isoformat()
        res_list = await client.get(
            f"/api/v1/videos/?search=Grand%20Finals&start_date={today}&end_date={today}"
        )
        assert res_list.status_code == 200
        data = res_list.json()
        assert data["total"] >= 1
        matching = [v for v in data["items"] if v["video_id"] == test_video_id]
        assert len(matching) == 1
        assert matching[0]["title"] == "Grand Finals Highlights"
        assert matching[0]["peak_count"] == 2
        assert matching[0]["max_z_score"] == 4.8
        assert matching[0]["total_messages"] == 100

        res_detail = await client.get(f"/api/v1/videos/{test_video_id}")
        assert res_detail.status_code == 200
        detail = res_detail.json()
        assert detail["title"] == "Grand Finals Highlights"
        assert detail["peak_count"] == 2
        assert len(detail["minutes"]) == 2
        assert detail["minutes"][0]["minute_label"] == "01:00"
        assert detail["minutes"][1]["minute_label"] == "02:00"
        assert detail["minutes"][0]["peak_count"] == 1
        assert detail["minutes"][1]["max_z_score"] == 4.8


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
