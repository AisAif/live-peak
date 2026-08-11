from datetime import datetime, timezone
from pydantic import BaseModel, Field


def get_utc_now() -> datetime:
    """Helper function returning current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class ChatMessage(BaseModel):
    """Represents a single chat message received from YouTube live chat."""
    video_id: str
    author_name: str
    message: str
    timestamp: datetime = Field(default_factory=get_utc_now)
    amount_str: str | None = None  # For SuperChats if present


class WindowStats(BaseModel):
    """Aggregated stats for a single time window (e.g. 10 seconds)."""
    video_id: str
    window_start: datetime
    window_end: datetime
    message_count: int
    chat_velocity: float  # Messages per second
    emoji_count: int = 0
    top_keywords: list[str] = Field(default_factory=list)
    z_score: float = 0.0
    is_peak: bool = False


class PeakEvent(BaseModel):
    """Represents a detected highlight/peak moment in a live stream."""
    id: int | None = None
    video_id: str
    start_time: datetime
    peak_time: datetime
    end_time: datetime
    padded_start_time: datetime
    padded_end_time: datetime
    max_z_score: float
    max_chat_velocity: float
    total_messages: int
    highlight_keywords: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=get_utc_now)


class StreamInfo(BaseModel):
    """Represents a YouTube live stream target."""
    video_id: str
    channel_id: str
    title: str
    is_live: bool = True
    started_at: datetime | None = None
