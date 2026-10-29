from app.utils.text_helpers import extract_emojis, extract_top_keywords


def test_extract_top_keywords_ignores_urls_mentions_and_numbers():
    messages = [
        "GOAL!!! GOAL https://spam.example/abc @user123",
        "goal 2026",
        "🔥🔥",
    ]

    keywords = extract_top_keywords(messages, top_n=5)

    assert keywords[0] == "goal"
    assert "spam" not in keywords
    assert "user123" not in keywords
    assert "2026" not in keywords


def test_extract_top_keywords_keeps_hashtag_term():
    keywords = extract_top_keywords(["#Highlight mantap"], top_n=5)
    assert keywords[0] == "highlight"


def test_extract_emojis_returns_emoji_runs():
    assert extract_emojis("nice 🔥🔥 lol 😂") == ["🔥🔥", "😂"]
