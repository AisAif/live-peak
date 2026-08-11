import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from app.models.domain import ChatMessage

MOCK_USERS = ["Budi", "Siti", "Andi", "Rian", "GamerPro99", "Bagas", "User123", "Nabila", "Rico", "Deni"]

NORMAL_MESSAGES = [
    "Halo kawan", "Mantap bang", "Lanjut tarung", "Siapa yang menang?", "Mabar yuk",
    "Semangat bro", "Streaming jam berapa?", "Hi all", "Wkwk lumayan", "Keren cuy"
]

PEAK_MESSAGES = [
    "WKWKWKWK ANJAYYY 😂😂😂", "GOOOOOLLLL!!!!! 🔥🔥🔥", "PENALTY GUYS!!!",
    "GILA KEREEN BANGET GG!", "WKWKWK NGAKAK BERSAMA 🔥", "WHAT A SAVE!", "POGGGGG", "GG WP BANGBANG!"
]


async def generate_mock_chat_stream(
    video_id: str = "mock_video_123",
    total_duration_seconds: int = 120,
    peak_start_second: int = 40,
    peak_duration_seconds: int = 20,
    delay_between_messages: float = 0.1
) -> AsyncGenerator[ChatMessage, None]:
    """
    Simulates a live chat stream with baseline chat velocity and an artificial peak burst interval.
    Yields ChatMessage objects asynchronously.
    """
    start_time = datetime.now(timezone.utc)
    current_time = start_time

    while (current_time - start_time).total_seconds() < total_duration_seconds:
        elapsed = (current_time - start_time).total_seconds()
        is_peak_period = peak_start_second <= elapsed <= (peak_start_second + peak_duration_seconds)

        # Higher message frequency during peak
        msg_pool = PEAK_MESSAGES if is_peak_period else NORMAL_MESSAGES
        msg_text = random.choice(msg_pool)
        user = random.choice(MOCK_USERS)

        yield ChatMessage(
            video_id=video_id,
            author_name=user,
            message=msg_text,
            timestamp=current_time
        )

        # Sleep interval: short during peak (high velocity), longer during normal
        sleep_dur = random.uniform(0.05, 0.15) if is_peak_period else random.uniform(0.5, 1.2)
        await asyncio.sleep(delay_between_messages)
        current_time += timedelta(seconds=sleep_dur)
