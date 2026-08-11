import pytest_asyncio
from app.core.database import init_db
from app.utils.text_helpers import fetch_remote_stopwords


@pytest_asyncio.fixture(autouse=True)
async def setup_test_database():
    """Initializes SQLite database tables before running test cases."""
    await init_db()
