"""Pronunciation dictionary: word-level respellings applied before TTS.

eleven_v3 speaks Azerbaijani but occasionally mis-stresses syllables. Words the
model gets wrong are stored here with a phonetic respelling that steers it
right (writing the word the way it should *sound*). The dictionary grows from
Voice Lab sessions (`/voicelab`), so the system learns from its own mistakes
instead of repeating them.
"""

import json
import re
import threading
from pathlib import Path

from app.core.config import settings

_lock = threading.Lock()


def _store_file() -> Path:
    path = settings.sqlite_file.parent / "voicelab" / "pronunciations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load() -> dict[str, str]:
    path = _store_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def add(word: str, respelling: str) -> dict[str, str]:
    with _lock:
        entries = load()
        entries[word.strip().lower()] = respelling.strip()
        _store_file().write_text(
            json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return entries


def apply(text: str) -> str:
    """Replace known-problem words with their phonetic respelling.

    The dictionary is re-read on every call: it is tiny, and freshness matters
    more than saving a file read - a word taught in the Voice Lab must take
    effect on the very next spoken reply.
    """
    entries = load()
    for word, respelling in entries.items():
        text = re.sub(
            rf"(?<!\w){re.escape(word)}(?!\w)", respelling, text, flags=re.IGNORECASE
        )
    return text
