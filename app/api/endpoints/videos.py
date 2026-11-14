import asyncio
import csv
import io
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.peaks import _to_peak_event
from app.core.database import get_db_session
from app.models.db import PeakEventModel, StreamModel, TrackedChannelModel, WindowStatsModel
from app.models.domain import (
    PaginatedVideoResponse,
    PeakMinuteGroup,
    RetrospectiveAuditResponse,
    VideoDetailResponse,
    VideoSummary,
)
from app.services.retrospective import run_retrospective_audit
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
            TrackedChannelModel.channel_name.label("channel_name"),
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
        .outerjoin(TrackedChannelModel, TrackedChannelModel.channel_id == StreamModel.channel_id)
        .group_by(
            PeakEventModel.video_id,
            StreamModel.title,
            StreamModel.channel_id,
            TrackedChannelModel.channel_name,
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
            channel_name=row.channel_name,
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
    channel_id = stream.channel_id if stream else None
    channel_name = None
    if channel_id:
        tracked_ch = await db.get(TrackedChannelModel, channel_id)
        if tracked_ch:
            channel_name = tracked_ch.channel_name
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
            peaks=[
                _to_peak_event(record, channel_id=channel_id, channel_name=channel_name)
                for _, record in entries
            ],
        ))

    return VideoDetailResponse(
        video_id=video_id,
        title=(stream.title if stream else None) or f"Video {video_id}",
        channel_id=channel_id,
        channel_name=channel_name,
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


def _sanitize_csv_cell(value: object) -> object:
    """Prefixes potentially dangerous formula prefixes to prevent CSV injection."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


@router.get("/{video_id}/export")
async def export_video_highlights(
    video_id: str,
    format: Literal["chapters", "csv", "json"] = "chapters",
    only_valid: bool = False,
    exclude_false_positive: bool = True,
    db: AsyncSession = Depends(get_db_session),
):
    """Exports detected highlight peaks for a video as YouTube Chapters, CSV, or JSON."""
    stream = await db.get(StreamModel, video_id)
    channel_id = stream.channel_id if stream else None
    channel_name = None
    if channel_id:
        tracked_ch = await db.get(TrackedChannelModel, channel_id)
        if tracked_ch:
            channel_name = tracked_ch.channel_name
    stmt = (
        select(PeakEventModel)
        .where(PeakEventModel.video_id == video_id)
        .order_by(
            asc(PeakEventModel.start_offset_seconds),
            asc(PeakEventModel.peak_time),
        )
    )
    records = list((await db.execute(stmt)).scalars().all())
    if only_valid:
        records = [r for r in records if r.review_status in ("valid", "bookmarked")]
    elif exclude_false_positive:
        records = [r for r in records if r.review_status != "false_positive"]

    if format == "chapters":
        lines = ["00:00:00 Stream Start"]
        last_offset = 0.0
        for r in records:
            offset_sec = _peak_offset(r, stream)
            if offset_sec - last_offset < 10.0:
                continue
            ts = format_seconds_to_timestamp(offset_sec)
            cat = r.moment_category or "Highlight"
            kws = ", ".join((r.highlight_keywords or [])[:4]) or "Chat Spike"
            lines.append(f"{ts} [{cat}] {kws} (Score: {r.highlight_score:.2f})")
            last_offset = offset_sec
        return PlainTextResponse("\n".join(lines))

    events = [_to_peak_event(r) for r in records]
    if format == "json":
        payload = json.dumps([e.model_dump(mode="json") for e in events], indent=2)
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{video_id}_highlights.json"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "video_id", "video_start_time", "video_end_time",
        "start_offset_seconds", "end_offset_seconds", "moment_category",
        "highlight_score", "max_z_score", "max_chat_velocity",
        "total_messages", "unique_authors", "review_status",
        "highlight_keywords", "sample_messages",
    ])
    for e in events:
        writer.writerow([
            _sanitize_csv_cell(v)
            for v in (
                e.id,
                e.video_id,
                e.video_start_time or "",
                e.video_end_time or "",
                e.start_offset_seconds if e.start_offset_seconds is not None else "",
                e.end_offset_seconds if e.end_offset_seconds is not None else "",
                e.moment_category or "",
                e.highlight_score,
                e.max_z_score,
                e.max_chat_velocity,
                e.total_messages,
                e.unique_authors,
                e.review_status or "",
                "; ".join(e.highlight_keywords),
                " | ".join(e.sample_messages),
            )
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{video_id}_highlights.csv"'},
    )


@router.get("/{video_id}/audit", response_model=RetrospectiveAuditResponse)
async def audit_video_patterns(
    video_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Runs retrospective PELT regime-shift and Matrix Profile discord audit for a video."""
    stream = await db.get(StreamModel, video_id)
    channel_id = stream.channel_id if stream else None
    channel_name = None
    if channel_id:
        tracked_ch = await db.get(TrackedChannelModel, channel_id)
        if tracked_ch:
            channel_name = tracked_ch.channel_name
    win_stmt = (
        select(WindowStatsModel)
        .where(WindowStatsModel.video_id == video_id)
        .order_by(asc(WindowStatsModel.window_start))
    )
    peak_stmt = (
        select(PeakEventModel)
        .where(PeakEventModel.video_id == video_id)
        .order_by(asc(PeakEventModel.start_time))
    )
    window_rows = list((await db.execute(win_stmt)).scalars().all())
    peak_rows = list((await db.execute(peak_stmt)).scalars().all())

    return await asyncio.to_thread(
        run_retrospective_audit,
        video_id,
        window_rows,
        peak_rows,
        stream.started_at if stream else None,
    )
