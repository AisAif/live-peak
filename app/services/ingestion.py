import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Awaitable
import pytchat
from app.core.logger import logger
from app.models.domain import ChatMessage

CHATDATA_RECONNECT_DELAY = 2.0


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
        self._chat = None
        self._seen_message_ids: deque[str] = deque(maxlen=10_000)
        self._seen_message_id_set: set[str] = set()

    def _is_new_message(self, message_id: str | None) -> bool:
        """Returns True once per message ID, evicting the oldest ID when full."""
        if message_id is None:
            return True
        if message_id in self._seen_message_id_set:
            return False
        if len(self._seen_message_ids) == self._seen_message_ids.maxlen:
            self._seen_message_id_set.discard(self._seen_message_ids.popleft())
        self._seen_message_ids.append(message_id)
        self._seen_message_id_set.add(message_id)
        return True

    @staticmethod
    def _collect_items(chat) -> list:
        """
        Drains available chat items; runs in a worker thread to avoid blocking.

        Uses ``Chatdata.items`` directly instead of ``sync_items()`` because the
        latter paces messages to the original broadcast timeline and can sleep
        for days on long-running 24/7 streams.
        """
        chatdata = chat.get()
        if chatdata is None:
            return []
        items = getattr(chatdata, "items", None)
        return list(items) if items is not None else list(chatdata)

    async def start_listening(self) -> None:
        """
        Starts live chat ingestion loop. Handles automatic reconnection if stream drops.
        """
        self.is_running = True
        attempt = 0
        backoff_delay = 2.0

        logger.info(f"Starting chat ingestion listener for video {self.video_id}...")

        while self.is_running and attempt < self.max_reconnect_attempts:
            chat = None
            connected_at = None
            try:
                chat = pytchat.create(video_id=self.video_id)
                self._chat = chat
                connected_at = time.monotonic()

                logger.info(f"Connected to YouTube live chat stream: {self.video_id}")

                while self.is_running and chat.is_alive():
                    # pytchat is synchronous and may block; drain it off the event loop.
                    items = await asyncio.to_thread(self._collect_items, chat)

                    if time.monotonic() - connected_at >= 10.0:
                        attempt = 0
                        backoff_delay = 2.0

                    for item in items:
                        message_id = getattr(item, "id", None)
                        if not self._is_new_message(message_id):
                            continue

                        chat_msg = ChatMessage(
                            video_id=self.video_id,
                            message_id=message_id,
                            author_name=item.author.name,
                            message=item.message,
                            timestamp=datetime.now(timezone.utc),
                            amount_str=item.amountString if hasattr(item, "amountString") else None
                        )

                        if self.message_callback:
                            await self.message_callback(chat_msg)

                if not self.is_running:
                    break

                chat.raise_for_status()
                logger.warning(
                    f"Live chat connection ended for video {self.video_id}. Reconnecting..."
                )

            except pytchat.ChatDataFinished:
                if not self.is_running:
                    break
                # Continuation boundaries are normal on long-running streams;
                # reconnect promptly without consuming the error retry budget.
                logger.warning(
                    f"Chat continuation ended for video {self.video_id}. Reconnecting..."
                )
                await asyncio.sleep(CHATDATA_RECONNECT_DELAY)
                continue
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
        """Stops live chat ingestion loop and unblocks any pending thread read."""
        self.is_running = False
        chat = self._chat
        self._chat = None
        if chat is not None:
            try:
                chat.terminate()
            except Exception as e:
                logger.warning(f"Error terminating chat listener for {self.video_id}: {e}")
