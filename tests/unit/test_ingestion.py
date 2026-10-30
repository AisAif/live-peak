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
