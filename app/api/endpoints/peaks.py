from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.core.database import get_db_session
from app.models.db import PeakEventModel
from app.models.domain import PeakEvent

router = APIRouter(prefix="/peaks", tags=["Peak Highlights"])


@router.get("/{video_id}", response_model=list[PeakEvent])
async def get_video_peaks(video_id: str, db: AsyncSession = Depends(get_db_session)):
    """Retrieves all detected peak highlight events for a given video ID."""
    stmt = select(PeakEventModel).where(PeakEventModel.video_id == video_id).order_by(desc(PeakEventModel.max_z_score))
    result = await db.execute(stmt)
    records = result.scalars().all()
    
    return [
        PeakEvent(
            id=r.id,
            video_id=r.video_id,
            start_time=r.start_time,
            peak_time=r.peak_time,
            end_time=r.end_time,
            padded_start_time=r.padded_start_time,
            padded_end_time=r.padded_end_time,
            max_z_score=r.max_z_score,
            max_chat_velocity=r.max_chat_velocity,
            total_messages=r.total_messages,
            highlight_keywords=r.highlight_keywords or [],
            created_at=r.created_at
        )
        for r in records
    ]


@router.get("/", response_model=list[PeakEvent])
async def get_all_recent_peaks(limit: int = 20, db: AsyncSession = Depends(get_db_session)):
    """Retrieves recent peak highlight events across all streams."""
    stmt = select(PeakEventModel).order_by(desc(PeakEventModel.created_at)).limit(limit)
    result = await db.execute(stmt)
    records = result.scalars().all()

    return [
        PeakEvent(
            id=r.id,
            video_id=r.video_id,
            start_time=r.start_time,
            peak_time=r.peak_time,
            end_time=r.end_time,
            padded_start_time=r.padded_start_time,
            padded_end_time=r.padded_end_time,
            max_z_score=r.max_z_score,
            max_chat_velocity=r.max_chat_velocity,
            total_messages=r.total_messages,
            highlight_keywords=r.highlight_keywords or [],
            created_at=r.created_at
        )
        for r in records
    ]
