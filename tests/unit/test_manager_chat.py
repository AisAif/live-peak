from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models.db import ChatMessageModel
from app.models.domain import ChatMessage
from app.services.manager import ActiveStreamWorker
import app.services.manager as manager_module

VIDEO_ID = "chat_flush_test_video"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _message(message_id: str | None, text: str) -> ChatMessage:
    return ChatMessage(
        video_id=VIDEO_ID,
        message_id=message_id,
        author_name="tester",
        message=text,
        timestamp=NOW,
    )


@pytest.mark.asyncio
async def test_flush_chat_buffer_persists_batches_and_deduplicates(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'chat-flush.db').as_posix()}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(manager_module, "async_session_factory", session_factory)
    monkeypatch.setattr(settings, "CHAT_FLUSH_BATCH_SIZE", 2)

    worker = ActiveStreamWorker(VIDEO_ID)
    worker.raw_chat_enabled = True
    worker.chat_buffer = [
        _message("m1", "first"),
        _message("m1", "duplicate"),
        _message("m2", "second"),
        _message(None, "no-id"),
    ]

    await worker._flush_chat_buffer()

    assert worker.chat_buffer == []
    async with session_factory() as session:
        total = (await session.execute(
            select(func.count()).select_from(ChatMessageModel)
        )).scalar_one()
        message_ids = (await session.execute(
            select(ChatMessageModel.message_id).where(
                ChatMessageModel.message_id.is_not(None)
            )
        )).scalars().all()

    assert total == 3
    assert sorted(message_ids) == ["m1", "m2"]

    await engine.dispose()
