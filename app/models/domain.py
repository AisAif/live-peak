from datetime import datetime, timezone
from pydantic import BaseModel, Field


def get_utc_now() -> datetime:
    """Helper function returning current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class ChatMessage(BaseModel):
    """Represents a single chat message received from YouTube live chat."""
    video_id: str
    message_id: str | None = None
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
    ewma_velocity: float = 0.0
    ewma_z_score: float = 0.0
    cusum_score: float = 0.0
    peak_source: str | None = None
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
    video_start_time: str | None = None
    video_end_time: str | None = None
    start_offset_seconds: float | None = None
    end_offset_seconds: float | None = None
    max_z_score: float
    max_chat_velocity: float
    total_messages: int
    highlight_keywords: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=get_utc_now)


class PaginatedPeakResponse(BaseModel):
    """Paginated envelope for peak highlight events list."""
    items: list[PeakEvent]
    total: int
    page: int
    page_size: int
    total_pages: int



class StreamInfo(BaseModel):
    """Represents a YouTube live stream target."""
    video_id: str
    channel_id: str
    title: str
    is_live: bool = True
    started_at: datetime | None = None
