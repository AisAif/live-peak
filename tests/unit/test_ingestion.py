import pytest

from app.services.ingestion import ChatIngestionService


class _ChatData:
    def __init__(self, items):
        self.items = items

    def sync_items(self):
        raise AssertionError("sync_items() paces playback and must not be used")


class _Chat:
    def __init__(self, chatdata):
        self._chatdata = chatdata

    def get(self):
        return self._chatdata


def test_collect_items_uses_chatdata_items_without_playback_pacing():
    expected = [object(), object()]

    assert ChatIngestionService._collect_items(_Chat(_ChatData(expected))) == expected


def test_collect_items_handles_dead_chat():
    assert ChatIngestionService._collect_items(_Chat(None)) == []
    assert ChatIngestionService._collect_items(_Chat([])) == []


def test_is_new_message_deduplicates_and_allows_missing_ids():
    service = ChatIngestionService("video")

    assert service._is_new_message("m1") is True
    assert service._is_new_message("m1") is False
    assert service._is_new_message(None) is True
    assert service._is_new_message(None) is True


def test_is_new_message_evicts_oldest_id_when_full():
    service = ChatIngestionService("video")
    service._seen_message_ids = __import__("collections").deque(maxlen=2)

    assert service._is_new_message("m1") is True
    assert service._is_new_message("m2") is True
    assert service._is_new_message("m3") is True
    assert service._is_new_message("m1") is True
    assert service._is_new_message("m3") is False


@pytest.mark.asyncio
async def test_chatdata_finished_reconnects_without_duplicate_messages(monkeypatch):
    import app.services.ingestion as ingestion_module
    from app.services.ingestion import ChatIngestionService
    from types import SimpleNamespace

    service = ChatIngestionService("video")
    seen: list[str | None] = []

    async def callback(message):
        seen.append(message.message_id)

    service.message_callback = callback
    creates = 0

    class FakeData:
        def __init__(self):
            self.items = [
                SimpleNamespace(
                    id="m1",
                    author=SimpleNamespace(name="tester"),
                    message="hello",
                )
            ]

    class FakeChat:
        def __init__(self):
            self._alive = True

        def is_alive(self):
            alive = self._alive
            self._alive = False
            return alive

        def get(self):
            return FakeData()

        def raise_for_status(self):
            raise ingestion_module.pytchat.ChatDataFinished()

        def terminate(self):
            pass

    def fake_create(video_id):
        nonlocal creates
        creates += 1
        if creates >= 3:
            service.is_running = False
        return FakeChat()

    monkeypatch.setattr(ingestion_module.pytchat, "create", fake_create)
    monkeypatch.setattr(ingestion_module, "CHATDATA_RECONNECT_DELAY", 0.0)

    await service.start_listening()

    assert creates == 3
    assert seen == ["m1"]


@pytest.mark.asyncio
async def test_falls_back_to_chat_downloader_when_pytchat_fails(monkeypatch):
    import app.services.ingestion as ingestion_module

    service = ChatIngestionService("vid_fallback", max_reconnect_attempts=2)
    received = []

    async def callback(message):
        received.append(message)
        if len(received) >= 2:
            service.is_running = False

    service.message_callback = callback

    def failing_pytchat(video_id):
        raise ValueError("Cannot find channel id for video id")

    class FakeDownloader:
        def get_chat(self, url):
            yield {"message_id": "c1", "author": {"name": "alice"}, "message": "GILA CLUTCH!"}
            yield {"message_id": "c1", "author": {"name": "alice"}, "message": "duplicate"}
            yield {
                "message_id": "c2",
                "author": {"name": "bob"},
                "message": "gg",
                "money": {"text": "IDR 50,000"},
            }

    monkeypatch.setattr(ingestion_module.pytchat, "create", failing_pytchat)
    monkeypatch.setattr(ingestion_module, "ChatDownloader", FakeDownloader)

    await service.start_listening()

    assert len(received) == 2
    assert received[0].author_name == "alice"
    assert received[0].message == "GILA CLUTCH!"
    assert received[1].author_name == "bob"
    assert received[1].amount_str == "IDR 50,000"


@pytest.mark.asyncio
async def test_chat_downloader_uses_cookies_file_when_configured(monkeypatch, tmp_path):
    import app.services.ingestion as ingestion_module

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    service = ChatIngestionService("vid_cookie", max_reconnect_attempts=1)
    received = []
    init_kwargs = {}

    async def callback(message):
        received.append(message)
        service.is_running = False

    service.message_callback = callback

    class FakeCookieDownloader:
        def __init__(self, **kwargs):
            init_kwargs.update(kwargs)

        def get_chat(self, url):
            yield {"message_id": "ck1", "author": {"name": "alice"}, "message": "mantap"}

    def fail_if_pytchat_called(video_id):
        raise AssertionError("pytchat must be skipped when YOUTUBE_COOKIES_FILE exists")

    monkeypatch.setattr(ingestion_module.settings, "YOUTUBE_COOKIES_FILE", str(cookie_file))
    monkeypatch.setattr(ingestion_module.pytchat, "create", fail_if_pytchat_called)
    monkeypatch.setattr(ingestion_module, "ChatDownloader", FakeCookieDownloader)

    await service.start_listening()

    assert init_kwargs == {"cookies": str(cookie_file)}
    assert len(received) == 1
    assert received[0].message == "mantap"
