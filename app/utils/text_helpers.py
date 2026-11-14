import math
import re
import logging
from collections import Counter
import httpx
try:
    import emoji as _emoji_pkg
except ImportError:  # pragma: no cover - optional fallback in minimal test envs
    _emoji_pkg = None

logger = logging.getLogger("live_peak")

# Default local fallback stopwords (Indonesian & English)
DEFAULT_STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "sama", "dengan", "untuk",
    "ada", "bisa", "gak", "ga", "ngga", "nggak", "tak", "tidak", "ya", "yah",
    "iya", "dong", "deh", "kan", "lah", "sih", "kok", "apa", "siapa", "bagaimana",
    "gua", "lu", "gw", "eloe", "cuy", "nih", "tuh", "doang", "yg", "dg", "ok", "si", "ku", "mu",
    "the", "is", "a", "an", "and", "or", "to", "in", "on", "at", "for", "with",
    "this", "that", "it", "you", "me", "he", "she", "they", "we", "my", "your"
}

# In-memory dynamic stopwords cache
ACTIVE_STOPWORDS: set[str] = set(DEFAULT_STOPWORDS)

# Noise patterns commonly found in live chat messages
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@\w+")
PUNCTUATION_PATTERN = re.compile(r"[^\w\s]|_")

# Free open-source GitHub raw endpoints for comprehensive stopwords
INDONESIAN_STOPWORDS_URL = "https://raw.githubusercontent.com/stopwords-iso/stopwords-id/master/stopwords-id.json"
ENGLISH_STOPWORDS_URL = "https://raw.githubusercontent.com/stopwords-iso/stopwords-en/master/stopwords-en.json"

# Emoji Regex matcher pattern (8-digit hex for \U escapes)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
    "\U0001F680-\U0001F6FF"  # Transport & Map Symbols
    "\U0001F700-\U0001F77F"  # Alchemical Symbols
    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002600-\U000026FF"  # Miscellaneous Symbols
    "\U00002700-\U000027BF"  # Dingbats
    "]+",
    flags=re.UNICODE
)


async def fetch_remote_stopwords() -> set[str]:
    """
    Dynamically fetches comprehensive stopwords from free public open-source repositories (GitHub Raw).
    Falls back gracefully to DEFAULT_STOPWORDS if offline or request fails.
    """
    global ACTIVE_STOPWORDS
    collected_words: set[str] = set(DEFAULT_STOPWORDS)

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Fetch Indonesian stopwords
        try:
            res_id = await client.get(INDONESIAN_STOPWORDS_URL)
            if res_id.status_code == 200:
                id_words = res_id.json()
                collected_words.update(id_words)
                logger.info(f"Loaded {len(id_words)} Indonesian stopwords from remote repository.")
        except Exception as e:
            logger.warning(f"Could not fetch remote ID stopwords (using fallback): {e}")

        # Fetch English stopwords
        try:
            res_en = await client.get(ENGLISH_STOPWORDS_URL)
            if res_en.status_code == 200:
                en_words = res_en.json()
                collected_words.update(en_words)
                logger.info(f"Loaded {len(en_words)} English stopwords from remote repository.")
        except Exception as e:
            logger.warning(f"Could not fetch remote EN stopwords (using fallback): {e}")

    ACTIVE_STOPWORDS = collected_words
    return ACTIVE_STOPWORDS


def extract_emojis(text: str) -> list[str]:
    """Extracts all emojis (grouped into contiguous runs) present in a text string."""
    if _emoji_pkg is not None:
        matches = _emoji_pkg.emoji_list(text)
        if not matches:
            return []
        runs: list[str] = []
        cur_start = matches[0]["match_start"]
        cur_end = matches[0]["match_end"]
        for item in matches[1:]:
            if item["match_start"] == cur_end:
                cur_end = item["match_end"]
            else:
                runs.append(text[cur_start:cur_end])
                cur_start = item["match_start"]
                cur_end = item["match_end"]
        runs.append(text[cur_start:cur_end])
        return runs
    return EMOJI_PATTERN.findall(text)


def tokenize_keywords_and_emojis(messages: list[str]) -> tuple[Counter[str], int]:
    """
    Tokenizes messages into meaningful keywords and emojis, returning term counts
    and the total emoji count in a single pass.
    """
    words: list[str] = []
    emoji_count = 0
    for msg in messages:
        emojis = extract_emojis(msg)
        emoji_count += len(emojis)
        words.extend(emojis)

        clean_text = URL_PATTERN.sub(" ", msg)
        clean_text = MENTION_PATTERN.sub(" ", clean_text)
        clean_text = PUNCTUATION_PATTERN.sub(" ", clean_text).lower()
        for token in clean_text.split():
            if (
                len(token) >= 2
                and not token.isdigit()
                and token not in ACTIVE_STOPWORDS
            ):
                words.append(token)

    return Counter(words), emoji_count


def extract_keywords_and_emojis(
    messages: list[str], top_n: int = 5
) -> tuple[list[str], int]:
    """
    Extracts top N meaningful keywords/emojis and the total emoji count in one pass.

    Filters out active stopwords and short words (< 2 characters).
    """
    counts, emoji_count = tokenize_keywords_and_emojis(messages)
    if not counts:
        return [], emoji_count
    return [word for word, _ in counts.most_common(top_n)], emoji_count


def extract_contrastive_keywords(
    fg_counts: Counter[str],
    bg_counts: Counter[str] | None = None,
    top_n: int = 5,
) -> list[str]:
    """
    Ranks foreground keywords by how strongly they burst relative to background
    chat history, suppressing terms that are constantly present in normal chat.
    """
    if not fg_counts:
        return []
    if not bg_counts:
        return [word for word, _ in fg_counts.most_common(top_n)]

    fg_total = max(1, sum(fg_counts.values()))
    bg_total = max(1, sum(bg_counts.values()))

    scored: list[tuple[float, int, str]] = []
    for word, fg_count in fg_counts.items():
        fg_prob = (fg_count + 0.5) / (fg_total + 1.0)
        bg_prob = (bg_counts.get(word, 0) + 0.5) / (bg_total + 1.0)
        burst_score = fg_count * math.log1p(fg_prob / bg_prob)
        scored.append((burst_score, fg_count, word))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [word for _, _, word in scored[:top_n]]


def select_sample_messages(
    messages: list[tuple[str, str, bool]],
    top_keywords: list[str],
    limit: int = 5,
) -> list[str]:
    """
    Selects up to `limit` representative, deduplicated chat quotes for a window/peak.
    Each input tuple is (author_name, message_text, has_superchat).
    """
    if not messages or limit <= 0:
        return []

    kw_set = {k.lower() for k in top_keywords}
    candidates: list[tuple[int, int, str, str, str]] = []
    for idx, (author, text, has_superchat) in enumerate(messages):
        clean = " ".join(text.split())
        without_noise = MENTION_PATTERN.sub("", URL_PATTERN.sub("", clean)).strip()
        if len(without_noise) < 2 and not extract_emojis(clean):
            continue
        lowered = clean.lower()
        norm_key = " ".join(PUNCTUATION_PATTERN.sub(" ", without_noise.lower()).split()) or lowered
        score = 0
        if has_superchat:
            score += 3
        score += sum(2 for kw in kw_set if kw in lowered)
        if extract_emojis(clean):
            score += 1
        if 4 <= len(clean) <= 140:
            score += 1
        display_text = clean if len(clean) <= 140 else f"{clean[:137]}..."
        candidates.append((score, -idx, author, norm_key, f"{author}: {display_text}"))

    candidates.sort(reverse=True)
    selected: list[str] = []
    seen_authors: set[str] = set()
    seen_texts: set[str] = set()
    for _, _, author, lowered, formatted in candidates:
        if lowered in seen_texts or author in seen_authors:
            continue
        selected.append(formatted)
        seen_authors.add(author)
        seen_texts.add(lowered)
        if len(selected) >= limit:
            break

    # If distinct authors were fewer than `limit`, allow additional unique texts
    if len(selected) < limit:
        for _, _, _, lowered, formatted in candidates:
            if lowered in seen_texts:
                continue
            selected.append(formatted)
            seen_texts.add(lowered)
            if len(selected) >= limit:
                break

    return selected


_COMEDY_WORD_RE = re.compile(
    r"\b(?:wkwk\w*|haha\w*|ngakak\w*|lol|lmao|kocak\w*|lucu\w*)\b",
    re.IGNORECASE,
)
_COMEDY_EMOJIS = ("😂", "🤣")

_SHOCK_WORD_RE = re.compile(
    r"\b(?:anjay\w*|waduh|mati|fail\w*|oof|rip|monkas|kaget|wtf)\b",
    re.IGNORECASE,
)
_SHOCK_EMOJIS = ("😱", "💀", "😭")

_HYPE_WORD_RE = re.compile(
    r"\b(?:gg\w*|pog\w*|mantap\w*|gila|keren|clutch|ace|goal|gol|win|menang)\b",
    re.IGNORECASE,
)
_HYPE_EMOJIS = ("🔥", "🚀", "👏", "⚡")

_TECH_ISSUE_WORD_RE = re.compile(
    r"\b(?:lag\w*|buffering|freeze|mute\w*|nosound|blackscreen|putus|patah|delay|dc)\b",
    re.IGNORECASE,
)
_TECH_ISSUE_EMOJIS: tuple[str, ...] = ()


def _score_category_hits(text: str, word_re: re.Pattern[str], emojis: tuple[str, ...]) -> int:
    return len(word_re.findall(text)) + sum(text.count(e) for e in emojis)


def classify_moment_category(
    keywords: list[str],
    sample_messages: list[str] | None = None,
    superchat_count: int = 0,
) -> str:
    """Classifies a highlight moment using word-boundary weighted scoring."""
    kw_text = " ".join(keywords)
    sample_text = " ".join(sample_messages or [])

    scores = {
        "Comedy / Ngakak": (
            2 * _score_category_hits(kw_text, _COMEDY_WORD_RE, _COMEDY_EMOJIS)
            + _score_category_hits(sample_text, _COMEDY_WORD_RE, _COMEDY_EMOJIS)
        ),
        "Shock / Fail": (
            2 * _score_category_hits(kw_text, _SHOCK_WORD_RE, _SHOCK_EMOJIS)
            + _score_category_hits(sample_text, _SHOCK_WORD_RE, _SHOCK_EMOJIS)
        ),
        "Hype / Clutch": (
            2 * _score_category_hits(kw_text, _HYPE_WORD_RE, _HYPE_EMOJIS)
            + _score_category_hits(sample_text, _HYPE_WORD_RE, _HYPE_EMOJIS)
        ),
        "Technical Issue": (
            2 * _score_category_hits(kw_text, _TECH_ISSUE_WORD_RE, _TECH_ISSUE_EMOJIS)
            + _score_category_hits(sample_text, _TECH_ISSUE_WORD_RE, _TECH_ISSUE_EMOJIS)
        ),
        "Support / Donate": superchat_count * 2,
    }

    best_category, best_score = max(scores.items(), key=lambda item: item[1])
    return best_category if best_score > 0 else "General Spike"


def extract_top_keywords(messages: list[str], top_n: int = 5) -> list[str]:
    """
    Extracts top N most frequent meaningful keywords or emojis from a list of chat messages.
    Filters out active stopwords and short words (< 2 characters).
    """
    keywords, _ = extract_keywords_and_emojis(messages, top_n=top_n)
    return keywords
