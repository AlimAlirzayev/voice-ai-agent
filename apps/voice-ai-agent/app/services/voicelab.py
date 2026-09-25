"""Voice Lab: the live loop where the trainer teaches the system his voice and
pronunciation, sentence by sentence (Telegram `/ses` mode or the API directly).

Per sample: the trainer reads a target sentence aloud -> Whisper transcribes it
(sanity signal); the current narrator voice (the trainer's clone) speaks the
same sentence -> Whisper transcribes that too. Words that the clone's audio
loses in transcription are the clone's pronunciation failures - that is the
real training signal. Raw recordings accumulate on disk so they can later be
pushed back into the ElevenLabs voice (see `/voicelab/retrain`).
"""

import difflib
import json
import re
import time
from pathlib import Path

from app.core.config import settings

# Each sentence targets a specific Azerbaijani phonetic trap; "focus" is shown
# to the trainer so the reading emphasises the right thing.
SENTENCES: list[tuple[str, str]] = [
    ("Bəs sən heç düşünmüsənmi, sözün qüdrəti hardan gəlir?", "ə saitləri və sual intonasiyası"),
    ("Qarabağın dağlarında qartallar qanad çalır.", "q samiti"),
    ("Göygölün gözəlliyi görənləri heyran qoyur.", "ö və ü saitləri"),
    ("Xəzərin xəfif xışıltısı sahilə xoş gəlir.", "x samiti"),
    ("Şuşanın şirin şəlaləsi daşlardan süzülür.", "ş samiti"),
    ("Ağacların yarpaqları payızda saralıb tökülür.", "ğ samiti"),
    ("Cəsarətli igidlər Çənlibeldə cəm olublar.", "c və ç samitləri"),
    ("Min doqquz yüz doxsan birinci ildə tarix yazıldı.", "rəqəmlərin oxunuşu"),
    ("Heydər Əliyev prospekti ilə Nizami küçəsi kəsişir.", "xüsusi adlar"),
    ("Ürəyimdə ümid, gözümdə işıq, dilimdə dua var.", "ritmik sadalama"),
    ("Ehtiyatlı ol! Yol sürüşkəndir, yavaş sür!", "nida intonasiyası"),
    ("Kitabxanada sükut hökm sürür, hamı mütaliəyə dalıb.", "uzun sözlər"),
]

# The fine-tune set (approved by the owner 2026-09-26): 288 more sentences so
# the recordings reach ~30 minutes, enough to fine-tune a voice model of his
# own. Picked from the council's own replies and users' questions (modern
# literary Azerbaijani, the register Divan speaks in) plus Nizami, Simurğ and
# Nəsrəddin prose, greedily for letter-pair coverage. Archaic Dədə Qorqud and
# Nəsimi text and the dialect-heavy Koroğlu corpus are left out on purpose.
_EXTRA = json.loads((Path(__file__).with_name("voicelab_sentences.json")).read_text(encoding="utf-8"))
_SEEN = {t for t, _ in SENTENCES}
SENTENCES += [(t, "təbii danışıq tonu — səs modeli üçün") for t in _EXTRA if t not in _SEEN]

# Minutes of clean reading needed before the fine-tune run is worth starting.
GOAL_MINUTES = 30.0
# Compare against the current clone only every Nth sample: each comparison
# costs a synthesis (GPU quota) and slows the reading loop.
COMPARE_EVERY = 10


def _lab_dir() -> Path:
    path = settings.sqlite_file.parent / "voicelab"
    (path / "samples").mkdir(parents=True, exist_ok=True)
    return path


def _progress_file() -> Path:
    return _lab_dir() / "progress.json"


def _load_done() -> list[int]:
    path = _progress_file()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("done", [])
    except (OSError, json.JSONDecodeError):
        return []


def next_sentence() -> dict:
    """First sentence not yet practised; cycles from the top when all done."""
    done = _load_done()
    remaining = [i for i in range(len(SENTENCES)) if i not in done]
    index = remaining[0] if remaining else 0
    if not remaining:
        _progress_file().write_text(json.dumps({"done": []}), encoding="utf-8")
    text, focus = SENTENCES[index]
    return {"index": index, "text": text, "focus": focus,
            "remaining": len(remaining) or len(SENTENCES), **progress()}


def mark_done(index: int) -> None:
    done = _load_done()
    if index not in done:
        done.append(index)
    _progress_file().write_text(json.dumps({"done": done}), encoding="utf-8")


def save_sample(audio: bytes, expected_text: str, extension: str = "ogg") -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = _lab_dir() / "samples" / f"{stamp}.{extension}"
    path.write_bytes(audio)
    path.with_suffix(".txt").write_text(expected_text, encoding="utf-8")
    return path


def record_meta(path: Path, heard: str, diffs: list[dict]) -> None:
    """Keep what Whisper heard next to the sample: the dataset builder drops
    readings that drifted from the sentence, so the model never learns a slip."""
    meta = {"expected": path.with_suffix(".txt").read_text(encoding="utf-8"),
            "heard": heard, "diffs": len(diffs), "seconds": audio_seconds(path)}
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def audio_seconds(path: Path) -> float:
    import subprocess

    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=20)
        return round(float(out.stdout.strip() or 0), 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def progress() -> dict:
    """Recorded minutes toward the fine-tune goal (cached per sample in .json)."""
    total = 0.0
    for path in sample_files():
        meta = path.with_suffix(".json")
        if meta.exists():
            try:
                total += float(json.loads(meta.read_text(encoding="utf-8")).get("seconds", 0))
                continue
            except (OSError, ValueError):
                pass
        total += audio_seconds(path)
    return {"recorded_minutes": round(total / 60, 1), "goal_minutes": GOAL_MINUTES}


def should_compare() -> bool:
    return len(sample_files()) % COMPARE_EVERY == 1


def sample_files() -> list[Path]:
    """Every stored recording (Telegram ogg, browser webm, uploads), not the sidecars."""
    return sorted(p for p in (_lab_dir() / "samples").iterdir()
                  if p.suffix.lower() in {".ogg", ".oga", ".webm", ".m4a", ".mp3", ".wav", ".opus"})


def _norm_words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def word_diffs(expected: str, heard: str) -> list[dict]:
    """Word-level mismatches between what was expected and what Whisper heard.

    Whisper itself is imperfect on Azerbaijani, so treat these as signals to
    investigate, not verdicts.
    """
    exp, got = _norm_words(expected), _norm_words(heard)
    diffs = []
    matcher = difflib.SequenceMatcher(a=exp, b=got, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            diffs.append({
                "expected": " ".join(exp[i1:i2]),
                "heard": " ".join(got[j1:j2]) or None,
            })
    return diffs[:8]
