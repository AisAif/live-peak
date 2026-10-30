from fastapi import APIRouter
from app.api.endpoints import streams, peaks, videos, websocket, dashboard, channels

api_router = APIRouter(prefix="/api/v1")

# Include sub-routers
api_router.include_router(streams.router)
api_router.include_router(peaks.router)
api_router.include_router(videos.router)
api_router.include_router(channels.router)

# Root level WebSocket & Dashboard routers
main_router = APIRouter()
main_router.include_router(api_router)
main_router.include_router(websocket.router)
main_router.include_router(dashboard.router)
