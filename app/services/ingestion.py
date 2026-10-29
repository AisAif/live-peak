import asyncio
from datetime import datetime, timezone
from typing import Callable, Awaitable
import pytchat
from app.core.logger import logger
from app.models.domain import ChatMessage


class ChatIngestionService:
    """
    Service responsible for streaming real-time YouTube live chat messages via pytchat,
    featuring resilient reconnection logic with exponential backoff.
    """

    def __init__(
        self,
        video_id: str,
        message_callback: Callable[[ChatMessage], Awaitable[None]] | None = None,
        max_reconnect_attempts: int = 10
    ):
        self.video_id = video_id
        self.message_callback = message_callback
        self.max_reconnect_attempts = max_reconnect_attempts
        self.is_running = False

    async def start_listening(self) -> None:
        """
        Starts live chat ingestion loop. Handles automatic reconnection if stream drops.
        """
        self.is_running = True
        attempt = 0
        backoff_delay = 2.0

        logger.info(f"Starting chat ingestion listener for video {self.video_id}...")

        while self.is_running and attempt < self.max_reconnect_attempts:
            try:
                # Create pytchat async listener
                chat = pytchat.create(video_id=self.video_id)
                attempt = 0  # Reset attempt counter on successful connection
                backoff_delay = 2.0

                logger.info(f"Connected to YouTube live chat stream: {self.video_id}")

                while self.is_running and chat.is_alive():
                    # Process incoming chat messages asynchronously
                    for item in chat.get().sync_items():
                        chat_msg = ChatMessage(
                            video_id=self.video_id,
                            message_id=getattr(item, "id", None),
                            author_name=item.author.name,
                            message=item.message,
                            timestamp=datetime.now(timezone.utc),
                            amount_str=item.amountString if hasattr(item, "amountString") else None
                        )

                        if self.message_callback:
                            await self.message_callback(chat_msg)

                    await asyncio.sleep(0.5)

                if not chat.is_alive():
                    logger.warning(f"Live chat connection died for video {self.video_id}. Reconnecting...")

            except Exception as e:
                attempt += 1
                logger.error(
                    f"Chat ingestion error for video {self.video_id} (Attempt {attempt}/{self.max_reconnect_attempts}): {e}"
                )
                if not self.is_running:
                    break

                # Exponential backoff retry (2s, 4s, 8s, 16s, max 30s)
                await asyncio.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, 30.0)

        self.is_running = False
        logger.info(f"Chat ingestion listener stopped for video {self.video_id}.")

    def stop(self) -> None:
        """Stops live chat ingestion loop."""
        self.is_running = False
