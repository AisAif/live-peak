from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, DateTime, JSON, Text
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class PeakEventModel(Base):
    """Database ORM model for detected peak/highlight events."""
    __tablename__ = "peak_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    peak_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    padded_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    padded_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_z_score: Mapped[float] = mapped_column(Float, nullable=False)
    max_chat_velocity: Mapped[float] = mapped_column(Float, nullable=False)
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    highlight_keywords: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class WindowStatsModel(Base):
    """Database ORM model for storing periodic sliding window chat statistics."""
    __tablename__ = "window_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_velocity: Mapped[float] = mapped_column(Float, nullable=False)
    emoji_count: Mapped[int] = mapped_column(Integer, default=0)
    top_keywords: Mapped[list] = mapped_column(JSON, default=list)
    z_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_peak: Mapped[bool] = mapped_column(Boolean, default=False)
