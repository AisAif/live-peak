import asyncio
import http.cookiejar
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Awaitable
import httpx
import pytchat
try:
    from chat_downloader import ChatDownloader
except ImportError:  # pragma: no cover - optional fallback in minimal test envs
    ChatDownloader = None
from app.core.config import settings
from app.core.logger import logger
from app.models.domain import ChatMessage

CHATDATA_RECONNECT_DELAY = 2.0
_SENTINEL = object()
_INNERTUBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_INNERTUBE_CLIENT = {
    "clientName": "WEB",
    "clientVersion": "2.20241101.00.00",
}
_API_KEY_RE = re.compile(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"')
_LIVE_CHAT_CONT_RE = re.compile(
    r'"liveChatRenderer"\s*:\s*\{.*?"continuation"\s*:\s*"([^"]+)"',
    re.DOTALL,
)
_ANY_CONT_RE = re.compile(r'"continuation"\s*:\s*"([^"]+)"')


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

    @staticmethod
    def _resolve_cookies_path() -> str | None:
        cookies_path = settings.YOUTUBE_COOKIES_FILE.strip()
        if not cookies_path:
            return None
        if not os.path.isfile(cookies_path):
            logger.warning(
                f"YOUTUBE_COOKIES_FILE '{cookies_path}' not found; "
                "continuing without cookies."
            )
            return None
        return cookies_path

    @staticmethod
    def _load_httpx_cookies(cookies_path: str | None) -> httpx.Cookies:
        cookies = httpx.Cookies()
        if cookies_path:
            jar = http.cookiejar.MozillaCookieJar(cookies_path)
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
                for cookie in jar:
                    cookies.set(cookie.name, cookie.value or "", domain=cookie.domain, path=cookie.path)
            except Exception as e:
                logger.warning(f"Failed to load cookies from '{cookies_path}': {e}")
        if "SOCS" not in cookies:
            cookies.set("SOCS", "CAI", domain=".youtube.com", path="/")
        return cookies

    @staticmethod
    def _extract_innertube_bootstrap(html: str) -> tuple[str | None, str | None]:
        """Extracts INNERTUBE_API_KEY and initial live-chat continuation token from YouTube HTML."""
        api_key_match = _API_KEY_RE.search(html)
        api_key = api_key_match.group(1) if api_key_match else None

        cont_match = _LIVE_CHAT_CONT_RE.search(html) or _ANY_CONT_RE.search(html)
        continuation = cont_match.group(1) if cont_match else None
        return api_key, continuation

    @staticmethod
    def _extract_runs_text(runs: list[dict] | None, simple_text: str | None = None) -> str:
        if simple_text:
            return simple_text
        if not runs:
            return ""
        parts: list[str] = []
        for run in runs:
            if not isinstance(run, dict):
                continue
            if "text" in run:
                parts.append(str(run["text"]))
            elif "emoji" in run and isinstance(run["emoji"], dict):
                emoji_obj = run["emoji"]
                shortcuts = emoji_obj.get("shortcuts") or []
                parts.append(str(shortcuts[0] if shortcuts else emoji_obj.get("emojiId", "")))
        return "".join(parts).strip()

    def _parse_innertube_actions(self, actions: list[dict]) -> list[ChatMessage]:
        """Converts InnerTube get_live_chat action items into deduplicated ChatMessage objects."""
        messages: list[ChatMessage] = []
        renderer_keys = (
            "liveChatTextMessageRenderer",
            "liveChatPaidMessageRenderer",
            "liveChatPaidStickerRenderer",
            "liveChatMembershipItemRenderer",
        )
        for action in actions:
            if not isinstance(action, dict):
                continue
            item = action.get("addChatItemAction", {}).get("item")
            if not isinstance(item, dict):
                continue
            renderer = None
            for key in renderer_keys:
                if key in item and isinstance(item[key], dict):
                    renderer = item[key]
                    break
            if renderer is None:
                continue

            message_id = renderer.get("id")
            if not self._is_new_message(message_id):
                continue

            author_name = (
                renderer.get("authorName", {}).get("simpleText")
                or self._extract_runs_text(renderer.get("authorName", {}).get("runs"))
                or "Unknown"
            )
            msg_obj = renderer.get("message") or renderer.get("headerSubtext") or {}
            text = self._extract_runs_text(msg_obj.get("runs"), msg_obj.get("simpleText"))
            amount_str = renderer.get("purchaseAmountText", {}).get("simpleText")

            ts = datetime.now(timezone.utc)
            ts_usec = renderer.get("timestampUsec")
            if ts_usec:
                try:
                    ts = datetime.fromtimestamp(int(ts_usec) / 1_000_000, tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    pass

            messages.append(
                ChatMessage(
                    video_id=self.video_id,
                    message_id=message_id,
                    author_name=author_name,
                    message=text,
                    timestamp=ts,
                    amount_str=amount_str,
                )
            )
        return messages

    async def _stream_with_innertube(self, cookies_path: str | None = None) -> None:
        """Native httpx YouTube InnerTube live chat poller (resilient fallback)."""
        cookies = self._load_httpx_cookies(cookies_path)
        bootstrap_urls = (
            f"https://www.youtube.com/live_chat?is_popout=1&v={self.video_id}",
            f"https://www.youtube.com/watch?v={self.video_id}",
        )

        async with httpx.AsyncClient(
            headers=_INNERTUBE_HEADERS,
            cookies=cookies,
            follow_redirects=True,
            timeout=15.0,
        ) as client:
            api_key: str | None = None
            continuation: str | None = None
            for url in bootstrap_urls:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                api_key, continuation = self._extract_innertube_bootstrap(resp.text)
                if api_key and continuation:
                    break

            if not api_key or not continuation:
                raise RuntimeError("Unable to extract InnerTube live chat continuation")

            logger.info(f"Connected to YouTube live chat via InnerTube API: {self.video_id}")

            endpoint = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}"
            while self.is_running and continuation:
                payload = {
                    "context": {"client": _INNERTUBE_CLIENT},
                    "continuation": continuation,
                }
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()

                live_cont = data.get("continuationContents", {}).get("liveChatContinuation", {})
                actions = live_cont.get("actions") or []
                for chat_msg in self._parse_innertube_actions(actions):
                    if self.message_callback:
                        await self.message_callback(chat_msg)

                next_cont: str | None = None
                timeout_ms = 2000
                for cont_entry in live_cont.get("continuations") or []:
                    if not isinstance(cont_entry, dict):
                        continue
                    for cont_key in (
                        "invalidationContinuationData",
                        "timedContinuationData",
                        "reloadContinuationData",
                    ):
                        if cont_key in cont_entry and isinstance(cont_entry[cont_key], dict):
                            cdata = cont_entry[cont_key]
                            next_cont = cdata.get("continuation")
                            timeout_ms = int(cdata.get("timeoutMs") or timeout_ms)
                            break
                    if next_cont:
                        break

                continuation = next_cont
                if continuation and self.is_running:
                    delay = max(0.5, min(timeout_ms / 1000.0, 5.0))
                    await asyncio.sleep(delay)

    async def _stream_with_chat_downloader(self) -> None:
        """Fallback live chat reader using chat-downloader when pytchat fails."""
        if ChatDownloader is None:
            raise RuntimeError("chat-downloader is not installed")

        url = f"https://www.youtube.com/watch?v={self.video_id}"
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
        stop_event = threading.Event()

        def _push(kind: str, payload: object) -> None:
            if loop.is_closed():
                return
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))
            except RuntimeError:
                pass

        def _worker() -> None:
            try:
                cookies_path = self._resolve_cookies_path()
                downloader = (
                    ChatDownloader(cookies=cookies_path)
                    if cookies_path
                    else ChatDownloader()
                )
                iterator = iter(downloader.get_chat(url))
                first_item = next(iterator, _SENTINEL)
                if first_item is _SENTINEL:
                    return
                _push("connected", None)
                _push("item", first_item)
                for item in iterator:
                    if stop_event.is_set() or not self.is_running:
                        break
                    _push("item", item)
            except Exception as exc:
                if not stop_event.is_set():
                    _push("error", exc)
            finally:
                _push("done", None)

        worker_thread = threading.Thread(
            target=_worker,
            name=f"chat-dl-{self.video_id}",
            daemon=True,
        )
        worker_thread.start()

        try:
            while self.is_running:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if kind == "connected":
                    logger.info(f"Connected to YouTube live chat via chat-downloader: {self.video_id}")
                    continue
                if kind == "done":
                    break
                if kind == "error":
                    raise payload  # type: ignore[misc]

                item = payload
                if not isinstance(item, dict):
                    continue
                message_id = item.get("message_id")
                if not self._is_new_message(message_id):
                    continue
                author_info = item.get("author")
                author_name = (
                    author_info.get("name")
                    if isinstance(author_info, dict)
                    else None
                ) or "Unknown"
                money_info = item.get("money")
                amount_str = money_info.get("text") if isinstance(money_info, dict) else None

                ts = datetime.now(timezone.utc)
                raw_ts = item.get("timestamp")
                if raw_ts:
                    try:
                        if isinstance(raw_ts, (int, float)):
                            if raw_ts > 1e14:
                                raw_ts = raw_ts / 1_000_000.0
                            elif raw_ts > 1e11:
                                raw_ts = raw_ts / 1_000.0
                            ts = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
                        elif isinstance(raw_ts, str):
                            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError, OSError):
                        pass

                chat_msg = ChatMessage(
                    video_id=self.video_id,
                    message_id=message_id,
                    author_name=author_name,
                    message=item.get("message") or "",
                    timestamp=ts,
                    amount_str=amount_str,
                )
                if self.message_callback:
                    await self.message_callback(chat_msg)
        finally:
            stop_event.set()

    async def _run_fallback_stream(self, cookies_path: str | None = None) -> None:
        """Tries chat-downloader first, then falls back to native InnerTube API poller."""
        if ChatDownloader is not None:
            try:
                await self._stream_with_chat_downloader()
                return
            except Exception as dl_err:
                logger.warning(
                    f"chat-downloader failed for {self.video_id} ({dl_err}); "
                    "falling back to native InnerTube API."
                )
        await self._stream_with_innertube(cookies_path=cookies_path)

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
                cookies_path = self._resolve_cookies_path()
                if cookies_path:
                    connected_at = time.monotonic()
                    await self._run_fallback_stream(cookies_path=cookies_path)
                    if not self.is_running:
                        break
                    if time.monotonic() - connected_at >= 10.0:
                        attempt = 0
                        backoff_delay = 2.0
                    logger.warning(
                        f"Fallback chat stream ended for {self.video_id}. Reconnecting..."
                    )
                    await asyncio.sleep(CHATDATA_RECONNECT_DELAY)
                    continue

                try:
                    chat = pytchat.create(video_id=self.video_id)
                except Exception as pytchat_err:
                    logger.warning(
                        f"pytchat failed for {self.video_id} ({pytchat_err}); "
                        "falling back to chat-downloader / InnerTube."
                    )
                    connected_at = time.monotonic()
                    await self._run_fallback_stream()
                    if not self.is_running:
                        break
                    if time.monotonic() - connected_at >= 10.0:
                        attempt = 0
                        backoff_delay = 2.0
                    logger.warning(
                        f"Fallback chat stream ended for {self.video_id}. Reconnecting..."
                    )
                    await asyncio.sleep(CHATDATA_RECONNECT_DELAY)
                    continue

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

                        ts = datetime.now(timezone.utc)
                        raw_ts = getattr(item, "timestamp", None)
                        if raw_ts:
                            try:
                                ts = datetime.fromtimestamp(float(raw_ts) / 1000.0, tz=timezone.utc)
                            except (ValueError, TypeError, OSError):
                                pass

                        chat_msg = ChatMessage(
                            video_id=self.video_id,
                            message_id=message_id,
                            author_name=item.author.name,
                            message=item.message,
                            timestamp=ts,
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
