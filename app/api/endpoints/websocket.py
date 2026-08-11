import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.logger import logger
from app.services.manager import stream_manager

router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws/live/{video_id}")
async def websocket_live_analytics(websocket: WebSocket, video_id: str):
    """
    WebSocket endpoint streaming real-time chat velocity stats & Z-score peak alerts
    for a monitored video ID directly to frontend client dashboards.
    """
    await websocket.accept()
    logger.info(f"WebSocket client connected for video {video_id}")

    try:
        while True:
            worker = stream_manager.active_workers.get(video_id)
            if worker and worker.analytics.history:
                latest_stats = worker.analytics.history[-1]
                data = {
                    "video_id": latest_stats.video_id,
                    "window_start": latest_stats.window_start.isoformat(),
                    "window_end": latest_stats.window_end.isoformat(),
                    "message_count": latest_stats.message_count,
                    "chat_velocity": latest_stats.chat_velocity,
                    "emoji_count": latest_stats.emoji_count,
                    "top_keywords": latest_stats.top_keywords,
                    "z_score": latest_stats.z_score,
                    "is_peak": latest_stats.is_peak
                }
                await websocket.send_json(data)
            else:
                await websocket.send_json({"status": "waiting", "video_id": video_id})

            await asyncio.sleep(2.0)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for video {video_id}")
    except Exception as e:
        logger.error(f"WebSocket error for video {video_id}: {e}")
