import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, func, and_, cast, Text
from app.core.database import get_db_session
from app.models.db import PeakEventModel
from app.models.domain import PeakEvent, PaginatedPeakResponse

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
            video_start_time=r.video_start_time,
            video_end_time=r.video_end_time,
            start_offset_seconds=r.start_offset_seconds,
            end_offset_seconds=r.end_offset_seconds,
            max_z_score=r.max_z_score,
            max_chat_velocity=r.max_chat_velocity,
            total_messages=r.total_messages,
            highlight_keywords=r.highlight_keywords or [],
            created_at=r.created_at
        )
        for r in records
    ]


@router.get("/", response_model=PaginatedPeakResponse)
async def get_all_recent_peaks(
    video_id: str | None = None,
    min_z_score: float | None = None,
    min_velocity: float | None = None,
    keyword: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retrieves paginated and filtered peak highlight events across all streams.
    Supports filtering by video_id, min_z_score, min_velocity, keyword,
    and sorting by created_at, max_z_score, max_chat_velocity, total_messages.
    """
    conditions = []
    if video_id:
        conditions.append(PeakEventModel.video_id == video_id.strip())
    if min_z_score is not None:
        conditions.append(PeakEventModel.max_z_score >= min_z_score)
    if min_velocity is not None:
        conditions.append(PeakEventModel.max_chat_velocity >= min_velocity)
    if keyword:
        keyword_clean = f"%{keyword.strip().lower()}%"
        conditions.append(cast(PeakEventModel.highlight_keywords, Text).ilike(keyword_clean))

    count_stmt = select(func.count()).select_from(PeakEventModel)
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    total = (await db.execute(count_stmt)).scalar() or 0

    sort_map = {
        "created_at": PeakEventModel.created_at,
        "max_z_score": PeakEventModel.max_z_score,
        "max_chat_velocity": PeakEventModel.max_chat_velocity,
        "total_messages": PeakEventModel.total_messages,
    }
    col = sort_map.get(sort_by, PeakEventModel.created_at)
    order_func = desc(col) if sort_order.lower() == "desc" else asc(col)

    offset = (page - 1) * page_size
    stmt = select(PeakEventModel)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(order_func).offset(offset).limit(page_size)

    result = await db.execute(stmt)
    records = result.scalars().all()

    total_pages = math.ceil(total / page_size) if total > 0 else 1

    items = [
        PeakEvent(
            id=r.id,
            video_id=r.video_id,
            start_time=r.start_time,
            peak_time=r.peak_time,
            end_time=r.end_time,
            padded_start_time=r.padded_start_time,
            padded_end_time=r.padded_end_time,
            video_start_time=r.video_start_time,
            video_end_time=r.video_end_time,
            start_offset_seconds=r.start_offset_seconds,
            end_offset_seconds=r.end_offset_seconds,
            max_z_score=r.max_z_score,
            max_chat_velocity=r.max_chat_velocity,
            total_messages=r.total_messages,
            highlight_keywords=r.highlight_keywords or [],
            created_at=r.created_at
        )
        for r in records
    ]

    return PaginatedPeakResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )
