from types import SimpleNamespace
import pytest

import app.services.discovery as discovery_module
from app.services.discovery import StreamDiscoveryService


def _mock_async_client(html: str, final_url: str = "https://www.youtube.com/watch?v=LIVEVID1234"):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return SimpleNamespace(status_code=200, text=html, url=final_url)

    return FakeClient


@pytest.mark.asyncio
async def test_discover_rejects_video_belonging_to_other_channel(monkeypatch):
    channel_a = "UCaaaaaaaaaaaaaaaaaaaaaa"
    channel_b = "UCbbbbbbbbbbbbbbbbbbbbbb"
    html = f'''
    <html>
      <head>
        <link rel="canonical" href="https://www.youtube.com/watch?v=OTHERVID123">
        <meta property="og:title" content="Channel B Stream">
      </head>
      <body>
        "externalChannelId":"{channel_b}"
        "isLive":true
      </body>
    </html>
    '''
    monkeypatch.setattr(
        discovery_module.httpx,
        "AsyncClient",
        _mock_async_client(html, "https://www.youtube.com/watch?v=OTHERVID123"),
    )

    service = StreamDiscoveryService()
    result = await service.discover_by_channel_id(channel_a)
    assert result is None


@pytest.mark.asyncio
async def test_discover_ignores_non_live_channel_page_with_featured_links(monkeypatch):
    channel_a = "UCaaaaaaaaaaaaaaaaaaaaaa"
    html = '''
    <html>
      <head>
        <link rel="canonical" href="https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa">
        <title>Channel A - YouTube</title>
      </head>
      <body>
        <a href="https://www.youtube.com/watch?v=RECOMMEN123">Watch LIVE now</a>
        "isLiveContent":true
      </body>
    </html>
    '''
    monkeypatch.setattr(
        discovery_module.httpx,
        "AsyncClient",
        _mock_async_client(html, f"https://www.youtube.com/channel/{channel_a}/live"),
    )

    service = StreamDiscoveryService()
    result = await service.discover_by_channel_id(channel_a)
    assert result is None


@pytest.mark.asyncio
async def test_discover_accepts_valid_live_stream_for_matching_channel(monkeypatch):
    channel_a = "UCaaaaaaaaaaaaaaaaaaaaaa"
    html = f'''
    <html>
      <head>
        <link rel="canonical" href="https://www.youtube.com/watch?v=LIVEVID1234">
        <meta property="og:title" content="Channel A Live">
      </head>
      <body>
        "externalChannelId":"{channel_a}"
        "isLive":true
      </body>
    </html>
    '''
    monkeypatch.setattr(
        discovery_module.httpx,
        "AsyncClient",
        _mock_async_client(html, "https://www.youtube.com/watch?v=LIVEVID1234"),
    )

    service = StreamDiscoveryService()
    result = await service.discover_by_channel_id(channel_a)
    assert result is not None
    assert result.video_id == "LIVEVID1234"
    assert result.channel_id == channel_a
    assert result.title == "Channel A Live"
    assert result.is_live is True
