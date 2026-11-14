import math
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, func, and_
from app.core.database import get_db_session
from app.models.db import PeakEventModel, PeakKeywordModel
from app.models.domain import PeakEvent, PaginatedPeakResponse, PeakReviewUpdate

router = APIRouter(prefix="/peaks", tags=["Peak Highlights"])


def _to_peak_event(r: PeakEventModel) -> PeakEvent:
    """Maps a PeakEventModel ORM row to the PeakEvent domain schema."""
    return PeakEvent(
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
        highlight_score=r.highlight_score,
        unique_authors=r.unique_authors,
        diversity_ratio=r.diversity_ratio,
        emoji_count=r.emoji_count,
        superchat_count=r.superchat_count,
        peak_sources=r.peak_sources or [],
        highlight_keywords=r.highlight_keywords or [],
        sample_messages=r.sample_messages or [],
        moment_category=r.moment_category,
        review_status=r.review_status,
        review_note=r.review_note,
        created_at=r.created_at,
    )


@router.get("/{video_id}", response_model=list[PeakEvent])
async def get_video_peaks(video_id: str, db: AsyncSession = Depends(get_db_session)):
    """Retrieves all detected peak highlight events for a given video ID."""
    stmt = (
        select(PeakEventModel)
        .where(PeakEventModel.video_id == video_id)
        .order_by(desc(PeakEventModel.highlight_score), desc(PeakEventModel.max_z_score))
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    return [_to_peak_event(r) for r in records]


@router.get("/", response_model=PaginatedPeakResponse)
async def get_all_recent_peaks(
    video_id: str | None = None,
    min_z_score: float | None = None,
    min_highlight_score: float | None = None,
    min_velocity: float | None = None,
    keyword: str | None = None,
    category: str | None = None,
    review_status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retrieves paginated and filtered peak highlight events across all streams.
    Supports filtering by video_id, min_z_score, min_highlight_score, min_velocity, keyword,
    and sorting by created_at, highlight_score, max_z_score, max_chat_velocity, total_messages.
    """
    conditions = []
    if video_id:
        conditions.append(PeakEventModel.video_id == video_id.strip())
    if min_z_score is not None:
        conditions.append(PeakEventModel.max_z_score >= min_z_score)
    if min_highlight_score is not None:
        conditions.append(PeakEventModel.highlight_score >= min_highlight_score)
    if min_velocity is not None:
        conditions.append(PeakEventModel.max_chat_velocity >= min_velocity)
    if keyword and keyword.strip():
        keyword_clean = f"%{keyword.strip().lower()}%"
        keyword_peak_ids = select(PeakKeywordModel.peak_id).where(
            PeakKeywordModel.keyword.like(keyword_clean)
        )
        conditions.append(PeakEventModel.id.in_(keyword_peak_ids))
    if category and category.strip():
        conditions.append(PeakEventModel.moment_category == category.strip())
    if review_status and review_status.strip():
        conditions.append(PeakEventModel.review_status == review_status.strip())

    count_stmt = select(func.count()).select_from(PeakEventModel)
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    total = (await db.execute(count_stmt)).scalar() or 0

    sort_map = {
        "created_at": PeakEventModel.created_at,
        "highlight_score": PeakEventModel.highlight_score,
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

    items = [_to_peak_event(r) for r in records]

    return PaginatedPeakResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.patch("/{peak_id}/review", response_model=PeakEvent)
async def update_peak_review(
    peak_id: int,
    payload: PeakReviewUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    """Updates the human review status/bookmark and optional note for a peak."""
    record = await db.get(PeakEventModel, peak_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Peak event not found")

    record.review_status = payload.review_status
    if payload.review_note is not None:
        record.review_note = payload.review_note.strip() or None
    await db.commit()
    await db.refresh(record)
    return _to_peak_event(record)
