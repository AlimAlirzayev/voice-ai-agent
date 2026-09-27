"""maybe_start_training: fires once at the goal, never below it, never twice."""
import subprocess

from app.services import voicelab


def _setup(monkeypatch, tmp_path, minutes, active=False, last=0.0):
    monkeypatch.setattr(voicelab, "progress", lambda: {"recorded_minutes": minutes, "goal_minutes": 30.0})
    monkeypatch.setattr(voicelab, "TRAIN_DIR", tmp_path)
    (tmp_path / ".last_minutes").write_text(str(last))
    monkeypatch.setattr(voicelab, "_training_active", lambda: active)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_below_goal_does_nothing(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, 12.5)
    r = voicelab.maybe_start_training()
    assert r["training_started"] is False and "12.5" in r["reason"] and calls == []


def test_at_goal_starts_one_detached_unit(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, 31.0)
    r = voicelab.maybe_start_training()
    assert r["training_started"] is True
    assert calls[0][0] == "systemd-run" and calls[0][1].startswith("--unit=divan-voice-train")
    assert calls[0][-1] == voicelab.TRAIN_CMD


def test_idempotent_while_a_run_is_active(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, 31.0, active=True)
    assert voicelab.maybe_start_training()["training_started"] is False and calls == []


def test_not_again_for_the_same_recordings(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, 31.0, last=30.6)
    r = voicelab.maybe_start_training()
    assert r["training_started"] is False and "already trained" in r["reason"] and calls == []
