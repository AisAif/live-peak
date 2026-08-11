import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_health_check_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"


@pytest.mark.asyncio
async def test_streams_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Check active streams list
        response = await client.get("/api/v1/streams/active")
        assert response.status_code == 200
        assert "active_count" in response.json()


@pytest.mark.asyncio
async def test_peaks_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Query recent peaks
        response = await client.get("/api/v1/peaks/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_channels_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Add channel
        res_add = await client.post("/api/v1/channels/track/UC123456789")
        assert res_add.status_code == 200
        tracked = res_add.json()["tracked_channels"]
        assert any(c["channel_id"] == "UC123456789" for c in tracked)

        # List channels
        res_list = await client.get("/api/v1/channels/")
        assert res_list.status_code == 200
        assert res_list.json()["count"] >= 1

        # Untrack channel
        res_del = await client.delete("/api/v1/channels/untrack/UC123456789")
        assert res_del.status_code == 200
