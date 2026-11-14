from datetime import datetime, timezone
from typing import Literal
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
    unique_authors: int = 0
    diversity_ratio: float = 0.0
    superchat_count: int = 0
    author_names: list[str] = Field(default_factory=list, exclude=True)
    sample_messages: list[str] = Field(default_factory=list, exclude=True)
    chat_velocity: float  # Messages per second
    emoji_count: int = 0
    top_keywords: list[str] = Field(default_factory=list)
    z_score: float = 0.0
    ewma_velocity: float = 0.0
    ewma_z_score: float = 0.0
    cusum_score: float = 0.0
    river_score: float = 0.0
    semantic_convergence: float = 0.0
    is_tech_issue: bool = False
    peak_source: str | None = None
    is_peak: bool = False


class PeakEvent(BaseModel):
    """Represents a detected highlight/peak moment in a live stream."""
    id: int | None = None
    video_id: str
    channel_id: str | None = None
    channel_name: str | None = None
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
    highlight_score: float = 0.0
    unique_authors: int = 0
    diversity_ratio: float = 0.0
    emoji_count: int = 0
    superchat_count: int = 0
    peak_sources: list[str] = Field(default_factory=list)
    highlight_keywords: list[str] = Field(default_factory=list)
    sample_messages: list[str] = Field(default_factory=list)
    moment_category: str | None = None
    review_status: Literal["valid", "false_positive", "bookmarked"] | None = None
    review_note: str | None = None
    created_at: datetime = Field(default_factory=get_utc_now)


class PeakReviewUpdate(BaseModel):
    """Payload for updating a peak's human review status / bookmark."""
    review_status: Literal["valid", "false_positive", "bookmarked"] | None = None
    review_note: str | None = Field(default=None, max_length=500)


class PaginatedPeakResponse(BaseModel):
    """Paginated envelope for peak highlight events list."""
    items: list[PeakEvent]
    total: int
    page: int
    page_size: int
    total_pages: int


class VideoSummary(BaseModel):
    """Aggregated highlight summary for a single video/stream."""
    video_id: str
    title: str
    channel_id: str | None = None
    channel_name: str | None = None
    is_live: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    peak_count: int = 0
    max_z_score: float = 0.0
    total_messages: int = 0
    last_peak_at: datetime | None = None


class PaginatedVideoResponse(BaseModel):
    """Paginated envelope for the video highlight list."""
    items: list[VideoSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class PeakMinuteGroup(BaseModel):
    """Peaks grouped into the video minute they occurred in."""
    minute_index: int
    minute_label: str
    start_offset_seconds: float
    end_offset_seconds: float
    peak_count: int
    max_z_score: float
    max_chat_velocity: float
    total_messages: int
    highlight_keywords: list[str] = Field(default_factory=list)
    peaks: list[PeakEvent] = Field(default_factory=list)


class VideoDetailResponse(VideoSummary):
    """Video metadata plus its peaks grouped per minute."""
    minutes: list[PeakMinuteGroup] = Field(default_factory=list)


class RegimeShiftPoint(BaseModel):
    """Timestamp and offset where stream chat rhythm structurally shifted."""
    window_index: int
    timestamp: datetime
    offset_seconds: float
    time_label: str


class ShapeDiscordWindow(BaseModel):
    """Most structurally unusual chat waveform interval across the stream."""
    start_index: int
    end_index: int
    start_offset_seconds: float
    end_offset_seconds: float
    time_label: str
    discord_distance: float
    matched_peak_id: int | None = None


class RetrospectiveAuditResponse(BaseModel):
    """Post-stream / retrospective PELT regime-shift and Matrix Profile audit."""
    video_id: str
    total_windows: int
    ruptures_active: bool
    stumpy_active: bool
    regime_shifts: list[RegimeShiftPoint] = Field(default_factory=list)
    shape_discords: list[ShapeDiscordWindow] = Field(default_factory=list)


class StreamInfo(BaseModel):
    """Represents a YouTube live stream target."""
    video_id: str
    channel_id: str
    title: str
    is_live: bool = True
    started_at: datetime | None = None
