from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    JSON,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TrackedChannelModel(Base):
    """Database ORM model for auto-tracked YouTube channels."""
    __tablename__ = "tracked_channels"

    channel_id: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    channel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class StreamModel(Base):
    """Database ORM model for live stream targets."""
    __tablename__ = "streams"

    video_id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    channel_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    is_live: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class PeakEventModel(Base):
    """Database ORM model for detected peak/highlight events."""
    __tablename__ = "peak_events"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_peak_events_dedup_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    peak_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    padded_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    padded_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    video_start_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    video_end_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_offset_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_offset_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_z_score: Mapped[float] = mapped_column(Float, nullable=False)
    max_chat_velocity: Mapped[float] = mapped_column(Float, nullable=False)
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    highlight_keywords: Mapped[list] = mapped_column(JSON, default=list)
    dedup_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, index=True
    )


class WindowStatsModel(Base):
    """Database ORM model for storing periodic sliding window chat statistics."""
    __tablename__ = "window_stats"
    __table_args__ = (
        UniqueConstraint("video_id", "window_start", name="uq_window_stats_video_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_velocity: Mapped[float] = mapped_column(Float, nullable=False)
    emoji_count: Mapped[int] = mapped_column(Integer, default=0)
    top_keywords: Mapped[list] = mapped_column(JSON, default=list)
    z_score: Mapped[float] = mapped_column(Float, default=0.0)
    ewma_velocity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ewma_z_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cusum_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_peak: Mapped[bool] = mapped_column(Boolean, default=False)


class WindowRollupModel(Base):
    """Hourly aggregate of window statistics retained after raw windows expire."""
    __tablename__ = "window_rollups"
    __table_args__ = (
        UniqueConstraint(
            "video_id", "bucket_start", name="uq_window_rollups_video_bucket"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    window_count: Mapped[int] = mapped_column(Integer, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_count: Mapped[int] = mapped_column(Integer, nullable=False)
    emoji_count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_chat_velocity: Mapped[float] = mapped_column(Float, nullable=False)
    max_chat_velocity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_z_score: Mapped[float] = mapped_column(Float, nullable=False)
    max_z_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class ChatMessageModel(Base):
    """Database ORM model for raw chat messages (opt-in storage)."""
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "video_id", "message_id", name="uq_chat_messages_video_message"
        ),
        Index("ix_chat_messages_video_event_time", "video_id", "event_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    amount_str: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
