"""Offline tests for the Voice Lab loop: word diffing, sentence rotation and
the pronunciation dictionary (no network, no providers)."""

import json

from app.core.config import settings
from app.services import pronounce, voicelab


def _isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))


def test_word_diffs_flags_replaced_and_dropped_words():
    diffs = voicelab.word_diffs(
        "Qarabağın dağlarında qartallar qanad çalır",
        "Qarabağın dağlarında kartallar çalır",
    )
    assert {"expected": "qartallar qanad", "heard": "kartallar"} in diffs


def test_word_diffs_clean_read_has_no_diffs():
    text = "Göygölün gözəlliyi görənləri heyran qoyur"
    assert voicelab.word_diffs(text, text.upper()) == []


def test_next_sentence_advances_and_cycles(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)

    first = voicelab.next_sentence()
    voicelab.mark_done(first["index"])
    second = voicelab.next_sentence()
    assert second["index"] != first["index"]

    for i in range(len(voicelab.SENTENCES)):
        voicelab.mark_done(i)
    assert voicelab.next_sentence()["index"] == 0  # cycles from the top


def test_sample_is_stored_with_expected_text(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)

    stored = voicelab.save_sample(b"fake-audio", "Salam dünya", extension="ogg")
    assert stored.read_bytes() == b"fake-audio"
    assert stored.with_suffix(".txt").read_text(encoding="utf-8") == "Salam dünya"
    assert stored in voicelab.sample_files()


def test_pronounce_apply_respells_whole_words_only(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)

    pronounce.add("Nəsimi", "Nə-si-mi")
    assert pronounce.apply("Nəsimi dedi") == "Nə-si-mi dedi"
    # substrings of longer words must stay untouched
    pronounce.add("ad", "add")
    assert "adamlar" in pronounce.apply("adamlar gəldi")

    raw = json.loads(
        (tmp_path / "voicelab" / "pronunciations.json").read_text(encoding="utf-8")
    )
    assert raw["nəsimi"] == "Nə-si-mi"
