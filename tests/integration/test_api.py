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


@pytest.mark.asyncio
async def test_peak_review_and_video_export_endpoints():
    import uuid
    from datetime import datetime, timedelta, timezone
    from app.core.database import async_session_factory
    from app.models.db import PeakEventModel, StreamModel

    now = datetime.now(timezone.utc)
    test_video_id = f"vid_export_{uuid.uuid4().hex[:6]}"

    async with async_session_factory() as session:
        session.add(StreamModel(
            video_id=test_video_id,
            title="Exportable Stream",
            channel_id="UC_EXPORT",
            is_live=False,
            started_at=now,
        ))
        p1 = PeakEventModel(
            video_id=test_video_id,
            start_time=now + timedelta(seconds=70),
            peak_time=now + timedelta(seconds=75),
            end_time=now + timedelta(seconds=80),
            padded_start_time=now + timedelta(seconds=60),
            padded_end_time=now + timedelta(seconds=95),
            video_start_time="01:00",
            video_end_time="01:35",
            start_offset_seconds=60.0,
            end_offset_seconds=95.0,
            max_z_score=4.5,
            max_chat_velocity=3.0,
            total_messages=45,
            highlight_score=7.5,
            highlight_keywords=["clutch", "gg"],
            sample_messages=["u1: GILA CLUTCH!"],
            moment_category="Hype / Clutch",
            dedup_key=f"exp_{uuid.uuid4().hex}",
        )
        p2 = PeakEventModel(
            video_id=test_video_id,
            start_time=now + timedelta(seconds=130),
            peak_time=now + timedelta(seconds=135),
            end_time=now + timedelta(seconds=140),
            padded_start_time=now + timedelta(seconds=120),
            padded_end_time=now + timedelta(seconds=155),
            video_start_time="02:00",
            video_end_time="02:35",
            start_offset_seconds=120.0,
            end_offset_seconds=155.0,
            max_z_score=3.0,
            max_chat_velocity=1.8,
            total_messages=20,
            highlight_score=4.2,
            highlight_keywords=["spam"],
            moment_category="General Spike",
            dedup_key=f"exp_{uuid.uuid4().hex}",
        )
        session.add_all([p1, p2])
        await session.commit()
        await session.refresh(p1)
        await session.refresh(p2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Mark p1 as bookmarked and p2 as false_positive
        r1 = await client.patch(
            f"/api/v1/peaks/{p1.id}/review",
            json={"review_status": "bookmarked", "review_note": "Best clip"},
        )
        assert r1.status_code == 200
        assert r1.json()["review_status"] == "bookmarked"
        assert r1.json()["review_note"] == "Best clip"

        r2 = await client.patch(
            f"/api/v1/peaks/{p2.id}/review",
            json={"review_status": "false_positive"},
        )
        assert r2.status_code == 200

        # Filter peaks by review_status
        res_bm = await client.get(f"/api/v1/peaks/?video_id={test_video_id}&review_status=bookmarked")
        assert res_bm.status_code == 200
        assert res_bm.json()["total"] == 1
        assert res_bm.json()["items"][0]["id"] == p1.id

        # Export chapters (excludes false_positive by default)
        res_chap = await client.get(f"/api/v1/videos/{test_video_id}/export?format=chapters")
        assert res_chap.status_code == 200
        assert "00:00:00 Stream Start" in res_chap.text
        assert "01:00 [Hype / Clutch] clutch, gg" in res_chap.text
        assert "02:00" not in res_chap.text

        # Export CSV
        res_csv = await client.get(f"/api/v1/videos/{test_video_id}/export?format=csv&only_valid=true")
        assert res_csv.status_code == 200
        assert "text/csv" in res_csv.headers["content-type"]
        assert "Hype / Clutch" in res_csv.text
        assert "General Spike" not in res_csv.text

        # Export JSON
        res_json = await client.get(f"/api/v1/videos/{test_video_id}/export?format=json")
        assert res_json.status_code == 200
        exported = res_json.json()
        assert len(exported) == 1
        assert exported[0]["id"] == p1.id
