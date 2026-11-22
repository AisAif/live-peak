import re
import httpx
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from app.core.logger import logger
from app.models.domain import StreamInfo


def parse_youtube_iso_datetime(value: str) -> datetime | None:
    """Parses ISO 8601 datetime strings from YouTube HTML/JSON into timezone-aware UTC datetime."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def extract_stream_start_time(html: str) -> datetime | None:
    """
    Extracts the official YouTube live broadcast start time from watch page HTML.
    Looks for startTimestamp, actualStartTime, or schema.org startDate meta tags.
    """
    patterns = [
        r'"startTimestamp"\s*:\s*"([^"]+)"',
        r'"actualStartTime"\s*:\s*"([^"]+)"',
        r'<meta\s+itemprop="startDate"\s+content="([^"]+)"',
        r'<meta\s+property="og:video:release_date"\s+content="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            dt = parse_youtube_iso_datetime(match.group(1))
            if dt:
                return dt
    return None


class StreamDiscoveryService:
    """
    Service responsible for detecting active YouTube Live streams
    via passive RSS feeds or HTTP polling without needing expensive Selenium/Official API quotas.
    Supports Channel IDs (UC...), handles (@PUBGMOBILE), and full channel URLs.
    """

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout = timeout_seconds
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }

    async def resolve_channel_details(self, input_str: str) -> tuple[str, str] | None:
        """
        Resolves (channel_id, channel_name) from input string which can be:
        1. Direct Channel ID: 'UCX6OQ3DkcsbYNE6H8uQQuVA'
        2. Channel Handle: '@PUBGMOBILE' or 'PUBGMOBILE'
        3. Channel URL: 'https://www.youtube.com/@PUBGMOBILE'
        """
        clean_input = input_str.strip()

        # Handle URL or @handle or direct UC
        handle = clean_input
        if "youtube.com/channel/" in handle:
            handle = handle.split("youtube.com/channel/")[-1]
        elif "youtube.com/" in handle:
            handle = handle.split("youtube.com/")[-1]

        if handle.startswith("UC") and len(handle) == 24:
            url = f"https://www.youtube.com/channel/{handle}"
        else:
            if not handle.startswith("@"):
                handle = f"@{handle}"
            url = f"https://www.youtube.com/{handle}"

        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    html = response.text
                    
                    # Extract Channel ID (prefer canonical/externalId over generic browseId)
                    id_match = re.search(
                        r'<link\s+rel="canonical"\s+href="https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})"',
                        html,
                    )
                    if not id_match:
                        id_match = re.search(r'"externalId":"(UC[a-zA-Z0-9_-]{22})"', html)
                    if not id_match:
                        id_match = re.search(r'"browseId":"(UC[a-zA-Z0-9_-]{22})"', html)
                    if not id_match:
                        id_match = re.search(r'href="https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})"', html)
                    
                    # Extract Channel Name / Title
                    name_match = re.search(r'<meta property="og:title" content="(.*?)">', html)
                    if not name_match:
                        name_match = re.search(r'<title>(.*?)</title>', html)
                    
                    channel_name = name_match.group(1).replace(" - YouTube", "").strip() if name_match else handle
                    channel_id = id_match.group(1) if id_match else (clean_input if clean_input.startswith("UC") else handle)
                    
                    logger.info(f"Resolved input '{input_str}' -> Name: '{channel_name}', ID: '{channel_id}'")
                    return channel_id, channel_name
            except Exception as e:
                logger.error(f"Error resolving channel details for '{input_str}': {e}")

        # Fallback if request fails
        fallback_id = clean_input if (clean_input.startswith("UC") and len(clean_input) == 24) else clean_input
        return fallback_id, clean_input

    async def resolve_channel_id(self, input_str: str) -> str | None:
        """Helper method returning just the Channel ID."""
        details = await self.resolve_channel_details(input_str)
        return details[0] if details else None

    async def discover_by_channel_id(self, channel_or_handle: str) -> StreamInfo | None:
        """
        Polls target channel's /live page to detect active live stream video ID and title.
        Supports Channel IDs (UC...) or handles (@PUBGMOBILE).
        """
        channel_id = channel_or_handle
        if not (channel_id.startswith("UC") and len(channel_id) == 24):
            resolved = await self.resolve_channel_id(channel_or_handle)
            if resolved:
                channel_id = resolved

        live_url = f"https://www.youtube.com/channel/{channel_id}/live"
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
            try:
                response = await client.get(live_url)
                if response.status_code != 200:
                    logger.warning(f"Discovery failed for channel {channel_id}: HTTP {response.status_code}")
                    return None

                html = response.text

                # Extract canonical watch video_id (avoid matching sidebar/featured links)
                video_id_match = re.search(
                    r'<link\s+rel="canonical"\s+href="https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})"',
                    html,
                )
                if not video_id_match:
                    video_id_match = re.search(r"watch\?v=([a-zA-Z0-9_-]{11})", str(response.url))

                if not video_id_match:
                    logger.info(f"No active live stream detected for channel {channel_id}")
                    return None

                video_id = video_id_match.group(1)

                # Verify the discovered video actually belongs to this channel
                owner_match = (
                    re.search(r'<meta\s+itemprop="identifier"\s+content="(UC[a-zA-Z0-9_-]{22})"', html)
                    or re.search(r'"externalChannelId":"(UC[a-zA-Z0-9_-]{22})"', html)
                    or re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
                )
                if owner_match and owner_match.group(1) != channel_id:
                    logger.warning(
                        f"Discovered video {video_id} belongs to channel {owner_match.group(1)}, "
                        f"not requested channel {channel_id}; ignoring."
                    )
                    return None

                # Strict live check (do not match generic 'LIVE' text or ended VOD 'isLiveContent')
                is_live = '"isLive":true' in html or '"isLiveNow":true' in html
                if not is_live:
                    logger.info(f"Video {video_id} for channel {channel_id} is not currently live.")
                    return None

                # Extract video title
                title_match = re.search(r'<meta\s+property="og:title"\s+content="(.*?)"', html)
                if not title_match:
                    title_match = re.search(r'<title>(.*?)</title>', html)
                title = title_match.group(1).replace(" - YouTube", "").strip() if title_match else f"Live Stream {video_id}"

                actual_start = extract_stream_start_time(html)

                return StreamInfo(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    is_live=is_live,
                    started_at=actual_start or datetime.now(timezone.utc)
                )

            except Exception as e:
                logger.error(f"Error discovering stream for channel {channel_id}: {e}")
                return None

    async def fetch_video_start_time(self, video_id: str) -> datetime | None:
        """Fetches YouTube watch page HTML to extract the actual stream start time."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return extract_stream_start_time(resp.text)
        except Exception as e:
            logger.warning(f"Could not fetch stream start time for {video_id}: {e}")
        return None
