import re
import logging
from collections import Counter
import httpx

logger = logging.getLogger("live_peak")

# Default local fallback stopwords (Indonesian & English)
DEFAULT_STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "sama", "dengan", "untuk",
    "ada", "bisa", "gak", "ga", "ngga", "nggak", "tak", "tidak", "ya", "yah",
    "iya", "dong", "deh", "kan", "lah", "sih", "kok", "apa", "siapa", "bagaimana",
    "gua", "lu", "gw", "eloe", "gw", "wkwk", "wkwkwk", "wkwkwkwk",
    "the", "is", "a", "an", "and", "or", "to", "in", "on", "at", "for", "with",
    "this", "that", "it", "you", "me", "he", "she", "they", "we", "my", "your"
}

# In-memory dynamic stopwords cache
ACTIVE_STOPWORDS: set[str] = set(DEFAULT_STOPWORDS)

# Noise patterns commonly found in live chat messages
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@\w+")

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
    """Extracts all emojis present in a text string."""
    return EMOJI_PATTERN.findall(text)


def extract_top_keywords(messages: list[str], top_n: int = 5) -> list[str]:
    """
    Extracts top N most frequent meaningful keywords or emojis from a list of chat messages.
    Filters out active stopwords and short words (< 2 characters).
    """
    words: list[str] = []
    for msg in messages:
        # Extract emojis
        emojis = extract_emojis(msg)
        words.extend(emojis)

        # Remove URLs, mentions, and punctuation before tokenizing
        clean_text = URL_PATTERN.sub(" ", msg)
        clean_text = MENTION_PATTERN.sub(" ", clean_text)
        clean_text = re.sub(r"[^\w\s]|_", " ", clean_text).lower()
        tokens = clean_text.split()
        for token in tokens:
            if (
                len(token) > 2
                and not token.isdigit()
                and token not in ACTIVE_STOPWORDS
            ):
                words.append(token)

    if not words:
        return []

    counts = Counter(words)
    return [word for word, _ in counts.most_common(top_n)]
