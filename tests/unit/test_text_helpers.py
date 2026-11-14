from collections import Counter

from app.utils.text_helpers import (
    classify_moment_category,
    extract_contrastive_keywords,
    extract_emojis,
    extract_top_keywords,
    select_sample_messages,
)


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


def test_extract_contrastive_keywords_suppresses_background_terms():
    fg = Counter({"halo": 5, "clutch": 4, "gg": 3})
    bg = Counter({"halo": 80, "selamat": 10})

    keywords = extract_contrastive_keywords(fg, bg, top_n=3)

    assert keywords[0] == "clutch"
    assert keywords.index("clutch") < keywords.index("halo")


def test_select_sample_messages_deduplicates_and_prefers_distinct_authors():
    items = [
        ("alice", "GILA CLUTCH BANGET BRO!!", False),
        ("alice", "GILA CLUTCH BANGET BRO!!", False),
        ("bob", "gila clutch banget bro!!", False),
        ("bob", "wkwkwk ngakak parah", False),
        ("charlie", "GGWP MANTAP JIWA", True),
        ("dave", "x", False),  # too short (<2 chars)
    ]

    samples = select_sample_messages(items, top_keywords=["clutch", "ngakak"], limit=3)

    assert len(samples) == 3
    assert "charlie: GGWP MANTAP JIWA" in samples
    assert "alice: GILA CLUTCH BANGET BRO!!" in samples
    assert "bob: wkwkwk ngakak parah" in samples


def test_classify_moment_category_rules():
    assert classify_moment_category(["halo"], superchat_count=1) == "Support / Donate"
    assert classify_moment_category(["wkwkwk", "ngakak"]) == "Comedy / Ngakak"
    assert classify_moment_category(["kaget", "wtf"]) == "Shock / Fail"
    assert classify_moment_category(["clutch", "ggwp"]) == "Hype / Clutch"
    assert classify_moment_category(["obrolan", "santai"]) == "General Spike"
    assert classify_moment_category([], superchat_count=0) == "General Spike"
    # Substring false positives must not trigger category hints
    assert classify_moment_category(["nanggung", "window", "script", "face"]) == "General Spike"
    # Dominant comedy flood outweighs a single superchat
    assert classify_moment_category(
        ["wkwkwk", "ngakak"],
        sample_messages=["u1: wkwkwk kocak", "u2: ngakak lucu"],
        superchat_count=1,
    ) == "Comedy / Ngakak"


def test_select_sample_messages_filters_pure_url_and_punctuation_duplicates():
    items = [
        ("spammer", "https://spam.example/abc @someone", True),
        ("alice", "GILA CLUTCH!!", False),
        ("bob", "gila clutch", False),
        ("charlie", "mantap jiwa 🔥", False),
    ]

    samples = select_sample_messages(items, top_keywords=["clutch"], limit=3)

    assert len(samples) == 2
    assert "spammer" not in " ".join(samples)
    assert "alice: GILA CLUTCH!!" in samples
    assert "charlie: mantap jiwa 🔥" in samples
