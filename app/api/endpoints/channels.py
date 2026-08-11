from fastapi import APIRouter, HTTPException
from app.services.auto_tracker import auto_tracker

router = APIRouter(prefix="/channels", tags=["Auto Channel Tracker"])


@router.post("/track/{channel_input:path}")
async def add_channel_to_tracker(channel_input: str):
    """
    Adds a YouTube Channel ID, Handle (@PUBGMOBILE), or URL to the auto-tracking monitoring list in SQLite DB.
    Automatically resolves channel name and canonical Channel ID (UC...).
    """
    entry = await auto_tracker.add_channel(channel_input)
    if not entry:
        raise HTTPException(status_code=400, detail="Channel is already in auto-tracker list or could not be resolved.")
    return {
        "status": "success",
        "message": f"Added channel '{entry['channel_name']}' ({entry['channel_id']}) to auto-tracker.",
        "channel": entry,
        "tracked_channels": await auto_tracker.list_channels_enriched()
    }


@router.delete("/untrack/{channel_id:path}")
async def remove_channel_from_tracker(channel_id: str):
    """Removes a YouTube Channel ID from the auto-tracking monitoring list in SQLite DB."""
    removed = await auto_tracker.remove_channel(channel_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Channel ID not found in auto-tracker list.")
    return {
        "status": "success",
        "message": f"Removed channel {channel_id} from auto-tracker.",
        "tracked_channels": await auto_tracker.list_channels_enriched()
    }


@router.get("/")
async def list_tracked_channels():
    """Lists all YouTube Channels (Name & ID) currently being auto-tracked from SQLite DB."""
    channels = await auto_tracker.list_channels_enriched()
    return {"count": len(channels), "channels": channels}
