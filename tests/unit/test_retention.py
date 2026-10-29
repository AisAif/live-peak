from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models.db import (
    ChatMessageModel,
    PeakEventModel,
    WindowRollupModel,
    WindowStatsModel,
)
from app.services.retention import RetentionService

VIDEO_ID = "retention_test_video"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
OLD_START = NOW - timedelta(days=40)
OLD_BUCKET = OLD_START.replace(minute=0, second=0, microsecond=0)
RECENT_START = NOW - timedelta(days=1)


async def _build_service(db_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory, RetentionService(
        session_factory=session_factory,
        db_engine=engine
    )


def _window(start: datetime, count: int, velocity: float, z_score: float, peak: bool) -> WindowStatsModel:
    return WindowStatsModel(
        video_id=VIDEO_ID,
        window_start=start,
        window_end=start + timedelta(seconds=10),
        message_count=count,
        chat_velocity=velocity,
        emoji_count=count - 2,
        top_keywords=[],
        z_score=z_score,
        is_peak=peak
    )


def _peak(created_at: datetime, dedup_key: str) -> PeakEventModel:
    return PeakEventModel(
        video_id=VIDEO_ID,
        start_time=created_at,
        peak_time=created_at,
        end_time=created_at,
        padded_start_time=created_at,
        padded_end_time=created_at,
        max_z_score=3.0,
        max_chat_velocity=1.0,
        total_messages=5,
        highlight_keywords=[],
        dedup_key=dedup_key,
        created_at=created_at
    )


def _chat(event_time: datetime, message_id: str) -> ChatMessageModel:
    return ChatMessageModel(
        video_id=VIDEO_ID,
        message_id=message_id,
        author_name="tester",
        message="hello",
        event_time=event_time,
    )


@pytest.mark.asyncio
async def test_retention_rolls_up_then_deletes_expired_data(tmp_path, monkeypatch):
    engine, session_factory, service = await _build_service(tmp_path / "retention.db")
    monkeypatch.setattr(settings, "ENABLE_DATA_RETENTION", True)
    monkeypatch.setattr(settings, "WINDOW_STATS_RETENTION_DAYS", 30)
    monkeypatch.setattr(settings, "PEAK_EVENTS_RETENTION_DAYS", 30)
    monkeypatch.setattr(settings, "CHAT_MESSAGE_RETENTION_DAYS", 7)

    async with session_factory() as session:
        session.add_all([
            WindowRollupModel(
                video_id=VIDEO_ID,
                bucket_start=OLD_BUCKET,
                window_count=1,
                message_count=1,
                peak_count=0,
                emoji_count=0,
                avg_chat_velocity=0.1,
                max_chat_velocity=0.1,
                avg_z_score=0.5,
                max_z_score=0.5
            ),
            _window(OLD_START, count=3, velocity=0.3, z_score=1.0, peak=False),
            _window(
                OLD_START + timedelta(seconds=20),
                count=5,
                velocity=0.5,
                z_score=3.0,
                peak=True
            ),
            _window(RECENT_START, count=2, velocity=0.2, z_score=0.2, peak=False),
            _peak(NOW - timedelta(days=400), "retention-old-peak"),
            _peak(RECENT_START, "retention-recent-peak"),
            _chat(NOW - timedelta(days=40), "old-chat"),
            _chat(NOW - timedelta(days=1), "recent-chat"),
        ])
        await session.commit()

    result = await service.run_cleanup(now=NOW)

    assert result["windows_deleted"] == 2
    assert result["peaks_deleted"] == 1
    assert result["messages_deleted"] == 1
    assert result["rollups"] == 1

    async with session_factory() as session:
        rollup = (await session.execute(
            select(WindowRollupModel).where(WindowRollupModel.video_id == VIDEO_ID)
        )).scalars().one()
        assert rollup.window_count == 3
        assert rollup.message_count == 9
        assert rollup.peak_count == 1
        assert rollup.emoji_count == 4
        assert rollup.avg_chat_velocity == pytest.approx(0.3)
        assert rollup.max_chat_velocity == pytest.approx(0.5)
        assert rollup.avg_z_score == pytest.approx(1.5)
        assert rollup.max_z_score == pytest.approx(3.0)

        window_count = (await session.execute(
            select(func.count()).select_from(WindowStatsModel)
        )).scalar_one()
        peak_count = (await session.execute(
            select(func.count()).select_from(PeakEventModel)
        )).scalar_one()
        message_count = (await session.execute(
            select(func.count()).select_from(ChatMessageModel)
        )).scalar_one()
        assert window_count == 1
        assert peak_count == 1
        assert message_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_zero_retention_days_keeps_data_forever(tmp_path, monkeypatch):
    engine, session_factory, service = await _build_service(tmp_path / "retention-zero.db")
    monkeypatch.setattr(settings, "ENABLE_DATA_RETENTION", True)
    monkeypatch.setattr(settings, "WINDOW_STATS_RETENTION_DAYS", 0)
    monkeypatch.setattr(settings, "PEAK_EVENTS_RETENTION_DAYS", 0)
    monkeypatch.setattr(settings, "CHAT_MESSAGE_RETENTION_DAYS", 0)

    async with session_factory() as session:
        session.add_all([
            _window(OLD_START, count=3, velocity=0.3, z_score=1.0, peak=False),
            _chat(OLD_START, "zero-retention-chat"),
        ])
        await session.commit()

    result = await service.run_cleanup(now=NOW)

    assert result == {
        "rollups": 0,
        "windows_deleted": 0,
        "peaks_deleted": 0,
        "messages_deleted": 0,
    }
    async with session_factory() as session:
        count = (await session.execute(
            select(func.count()).select_from(WindowStatsModel)
        )).scalar_one()
        message_count = (await session.execute(
            select(func.count()).select_from(ChatMessageModel)
        )).scalar_one()
        assert count == 1
        assert message_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_disabled_keeps_all_data(tmp_path, monkeypatch):
    engine, session_factory, service = await _build_service(tmp_path / "retention-off.db")
    monkeypatch.setattr(settings, "ENABLE_DATA_RETENTION", False)

    async with session_factory() as session:
        session.add_all([
            _window(OLD_START, count=3, velocity=0.3, z_score=1.0, peak=False),
            _chat(OLD_START, "disabled-retention-chat"),
        ])
        await session.commit()

    result = await service.run_cleanup(now=NOW)

    assert result == {
        "rollups": 0,
        "windows_deleted": 0,
        "peaks_deleted": 0,
        "messages_deleted": 0,
    }
    async with session_factory() as session:
        count = (await session.execute(
            select(func.count()).select_from(WindowStatsModel)
        )).scalar_one()
        message_count = (await session.execute(
            select(func.count()).select_from(ChatMessageModel)
        )).scalar_one()
        assert count == 1
        assert message_count == 1

    await engine.dispose()


