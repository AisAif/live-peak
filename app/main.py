from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.core.logger import logger
from app.core.database import init_db
from app.utils.text_helpers import fetch_remote_stopwords
from app.api.router import main_router


from app.services.auto_tracker import auto_tracker
from app.services.retention import retention_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Handles startup tasks (DB initialization, fetching dynamic stopwords, starting auto channel tracker)
    and graceful shutdown cleanup.
    """
    logger.info(f"Starting {settings.PROJECT_NAME}...")
    
    # 1. Initialize SQLite database tables automatically
    await init_db()
    
    # 2. Dynamically fetch remote open-source stopwords (free)
    try:
        await fetch_remote_stopwords()
    except Exception as e:
        logger.warning(f"Error fetching remote stopwords: {e}")
    
    # 3. Start Auto Channel Tracker Service
    await auto_tracker.start()

    # 4. Start Data Retention & Rollup worker
    await retention_service.start()

    yield
    
    # Shut-down cleanup
    await retention_service.stop()
    await auto_tracker.stop()
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Real-time YouTube Live chat velocity analytics & Z-score peak detection pipeline.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Register API & WebSocket routers
app.include_router(main_router)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "database": settings.DATABASE_URL
    }
