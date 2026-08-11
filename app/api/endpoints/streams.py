from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db_session
from app.services.discovery import StreamDiscoveryService
from app.services.manager import stream_manager
from app.models.domain import StreamInfo

router = APIRouter(prefix="/streams", tags=["Streams"])
discovery_service = StreamDiscoveryService()


@router.get("/discover/{channel_id}", response_model=StreamInfo)
async def discover_channel_stream(channel_id: str):
    """Discovers active live stream for a given YouTube Channel ID."""
    info = await discovery_service.discover_by_channel_id(channel_id)
    if not info:
        raise HTTPException(status_code=44, detail="No active live stream found for this channel.")
    return info


@router.post("/start/{video_id}")
async def start_monitoring_stream(video_id: str):
    """Starts real-time chat monitoring pipeline for target YouTube video ID."""
    started = await stream_manager.start_monitoring_stream(video_id)
    if not started:
        raise HTTPException(status_code=400, detail="Stream is already being monitored.")
    return {"status": "success", "message": f"Started monitoring stream {video_id}"}


@router.post("/stop/{video_id}")
async def stop_monitoring_stream(video_id: str):
    """Stops real-time chat monitoring pipeline for target YouTube video ID."""
    stopped = await stream_manager.stop_monitoring_stream(video_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Stream is not currently monitored.")
    return {"status": "success", "message": f"Stopped monitoring stream {video_id}"}


@router.get("/active")
async def list_active_streams():
    """Lists all video IDs currently being monitored."""
    active = stream_manager.list_active_streams()
    return {"active_count": len(active), "video_ids": active}
