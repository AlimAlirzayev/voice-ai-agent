"""Voice Lab collects the fine-tune set: 300 sentences, minutes toward the goal,
browser webm counted, and the clone comparison only every Nth sample."""
from app.services import voicelab


def test_sentence_set_is_large_and_unique():
    texts = [t for t, _ in voicelab.SENTENCES]
    assert len(texts) >= 290 and len(set(texts)) == len(texts)


def test_progress_counts_every_format(monkeypatch, tmp_path):
    (tmp_path / "samples").mkdir()
    for name in ["a.webm", "b.ogg", "a.txt", "a.json"]:
        (tmp_path / "samples" / name).write_bytes(b"x")
    monkeypatch.setattr(voicelab, "_lab_dir", lambda: tmp_path)
    monkeypatch.setattr(voicelab, "audio_seconds", lambda p: 30.0)
    assert [p.name for p in voicelab.sample_files()] == ["a.webm", "b.ogg"]
    (tmp_path / "samples" / "a.json").write_text("{\"seconds\": 90}")
    assert voicelab.progress() == {"recorded_minutes": 2.0, "goal_minutes": voicelab.GOAL_MINUTES}


def test_compare_is_sparse(monkeypatch):
    for n, want in [(1, True), (2, False), (10, False), (11, True)]:
        monkeypatch.setattr(voicelab, "sample_files", lambda n=n: [0] * n)
        assert voicelab.should_compare() is want
