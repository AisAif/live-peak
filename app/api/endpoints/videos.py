import math
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models.db import PeakEventModel, StreamModel
from app.models.domain import (
    PaginatedVideoResponse,
    PeakEvent,
    PeakMinuteGroup,
    VideoDetailResponse,
    VideoSummary,
)
from app.utils.stats_helpers import format_seconds_to_timestamp

router = APIRouter(prefix="/videos", tags=["Video Highlights"])


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalizes a datetime returned by SQLite (naive) to UTC-aware."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _day_start(value: date) -> datetime:
    """Returns the UTC start-of-day for a date filter."""
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _to_peak_event(record: PeakEventModel) -> PeakEvent:
    """Converts a peak ORM record into the API domain model."""
    return PeakEvent(
        id=record.id,
        video_id=record.video_id,
        start_time=record.start_time,
        peak_time=record.peak_time,
        end_time=record.end_time,
        padded_start_time=record.padded_start_time,
        padded_end_time=record.padded_end_time,
        video_start_time=record.video_start_time,
        video_end_time=record.video_end_time,
        start_offset_seconds=record.start_offset_seconds,
        end_offset_seconds=record.end_offset_seconds,
        max_z_score=record.max_z_score,
        max_chat_velocity=record.max_chat_velocity,
        total_messages=record.total_messages,
        highlight_keywords=record.highlight_keywords or [],
        created_at=record.created_at,
    )


def _peak_offset(peak: PeakEventModel, stream: StreamModel | None) -> float:
    """Resolves a peak's offset in seconds from the start of the video."""
    if peak.start_offset_seconds is not None:
        return float(peak.start_offset_seconds)

    started_at = _as_utc(stream.started_at) if stream else None
    peak_start = _as_utc(peak.start_time)
    if started_at is not None and peak_start is not None:
        return max(0.0, (peak_start - started_at).total_seconds())
    return 0.0


@router.get("/", response_model=PaginatedVideoResponse)
async def list_videos(
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = None,
    sort_by: str = "video_date",
    sort_order: str = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Lists videos that have detected highlight peaks, newest first by default.

    Date filters apply to the stream start time, falling back to the first
    peak detection time when a stream row is unavailable.
    """
    video_date = func.coalesce(
        StreamModel.started_at, func.min(PeakEventModel.created_at)
    ).label("video_date")

    grouped = (
        select(
            PeakEventModel.video_id.label("video_id"),
            StreamModel.title.label("title"),
            StreamModel.channel_id.label("channel_id"),
            StreamModel.is_live.label("is_live"),
            StreamModel.started_at.label("started_at"),
            StreamModel.ended_at.label("ended_at"),
            func.count(PeakEventModel.id).label("peak_count"),
            func.max(PeakEventModel.max_z_score).label("max_z_score"),
            func.sum(PeakEventModel.total_messages).label("total_messages"),
            func.max(PeakEventModel.peak_time).label("last_peak_at"),
            video_date,
        )
        .outerjoin(StreamModel, StreamModel.video_id == PeakEventModel.video_id)
        .group_by(
            PeakEventModel.video_id,
            StreamModel.title,
            StreamModel.channel_id,
            StreamModel.is_live,
            StreamModel.started_at,
            StreamModel.ended_at,
        )
        .subquery()
    )

    conditions = []
    if start_date is not None:
        conditions.append(grouped.c.video_date >= _day_start(start_date))
    if end_date is not None:
        conditions.append(
            grouped.c.video_date < _day_start(end_date + timedelta(days=1))
        )
    if search:
        conditions.append(grouped.c.title.ilike(f"%{search.strip()}%"))

    count_stmt = select(func.count()).select_from(grouped)
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    total = (await db.execute(count_stmt)).scalar() or 0

    sort_map = {
        "video_date": grouped.c.video_date,
        "started_at": grouped.c.video_date,
        "peak_count": grouped.c.peak_count,
        "max_z_score": grouped.c.max_z_score,
        "total_messages": grouped.c.total_messages,
        "last_peak_at": grouped.c.last_peak_at,
    }
    col = sort_map.get(sort_by, grouped.c.video_date)
    order_func = desc(col) if sort_order.lower() == "desc" else asc(col)

    stmt = select(grouped)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(order_func).offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).all()
    items = [
        VideoSummary(
            video_id=row.video_id,
            title=row.title or f"Video {row.video_id}",
            channel_id=row.channel_id,
            is_live=bool(row.is_live),
            started_at=row.started_at,
            ended_at=row.ended_at,
            peak_count=int(row.peak_count or 0),
            max_z_score=float(row.max_z_score or 0.0),
            total_messages=int(row.total_messages or 0),
            last_peak_at=row.last_peak_at,
        )
        for row in rows
    ]

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return PaginatedVideoResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{video_id}", response_model=VideoDetailResponse)
async def get_video_detail(
    video_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """Returns video metadata plus its peaks grouped by video minute."""
    stream = await db.get(StreamModel, video_id)
    stmt = (
        select(PeakEventModel)
        .where(PeakEventModel.video_id == video_id)
        .order_by(
            asc(PeakEventModel.start_offset_seconds),
            asc(PeakEventModel.peak_time),
        )
    )
    records = (await db.execute(stmt)).scalars().all()

    groups: dict[int, list[tuple[float, PeakEventModel]]] = {}
    for record in records:
        offset = _peak_offset(record, stream)
        groups.setdefault(int(offset // 60), []).append((offset, record))

    minutes: list[PeakMinuteGroup] = []
    for minute_index in sorted(groups):
        entries = sorted(groups[minute_index], key=lambda item: item[0])
        peak_records = [record for _, record in entries]
        start_offset = entries[0][0]
        end_offset = max(
            (
                record.end_offset_seconds
                if record.end_offset_seconds is not None
                else offset
            )
            for offset, record in entries
        )

        keywords: list[str] = []
        for record in peak_records:
            for keyword in record.highlight_keywords or []:
                if keyword not in keywords:
                    keywords.append(keyword)

        minutes.append(PeakMinuteGroup(
            minute_index=minute_index,
            minute_label=format_seconds_to_timestamp(minute_index * 60),
            start_offset_seconds=round(start_offset, 2),
            end_offset_seconds=round(float(end_offset), 2),
            peak_count=len(peak_records),
            max_z_score=max(record.max_z_score for record in peak_records),
            max_chat_velocity=max(
                record.max_chat_velocity for record in peak_records
            ),
            total_messages=sum(record.total_messages for record in peak_records),
            highlight_keywords=keywords[:7],
            peaks=[_to_peak_event(record) for _, record in entries],
        ))

    return VideoDetailResponse(
        video_id=video_id,
        title=(stream.title if stream else None) or f"Video {video_id}",
        channel_id=stream.channel_id if stream else None,
        is_live=bool(stream.is_live) if stream else False,
        started_at=stream.started_at if stream else None,
        ended_at=stream.ended_at if stream else None,
        peak_count=len(records),
        max_z_score=(
            max(record.max_z_score for record in records) if records else 0.0
        ),
        total_messages=sum(record.total_messages for record in records),
        last_peak_at=(
            max(record.peak_time for record in records) if records else None
        ),
        minutes=minutes,
    )
