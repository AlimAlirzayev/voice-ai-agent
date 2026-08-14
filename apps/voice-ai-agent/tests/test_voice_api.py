"""Regression test for a real bug: `VoiceResponse` used to have no
`status`/`approval` fields at all, so a paused (HITL) voice turn silently
looked identical to a completed one to any caller - including `bot.py`,
which checks `payload["status"] == "pending_approval"` to decide whether to
show Təsdiqlə/İmtina buttons. That check could never fire over `/voice`.
"""

import pytest

import app.api.voice as voice_api
from app.api.voice import _build_voice_response, _speak_segments
from app.graph import TurnResult
from app.models.schemas import VoiceSegment


def _segment(text: str) -> VoiceSegment:
    return VoiceSegment(
        advisor="koroglu",
        name="Koroğlu",
        text=text,
        audio_base64="AA==",
        audio_mime="audio/ogg",
        tts_provider="elevenlabs",
    )


def test_pending_voice_turn_surfaces_status_and_approval():
    result = TurnResult(
        status="pending_approval",
        reply="Bu, Koroğlunun cəsarətli tövsiyəsidir. Onu son cavab kimi təsdiqləyirsiniz?",
        history_length=0,
        approval={"advisor": "Koroğlu", "advisor_key": "koroglu", "draft": "İrəli addımla."},
        consulted=["koroglu"],
        turn_id="abc123",
    )

    response = _build_voice_response(
        thread_id="t-1", transcript="Riskli addım atmalıyammı?", result=result, segments=[_segment(result.reply)]
    )

    assert response.status == "pending_approval"
    assert response.approval == result.approval
    assert response.consulted == ["koroglu"]
    assert response.turn_id == "abc123"


def test_completed_voice_turn_reports_ok_status():
    result = TurnResult(
        status="ok",
        reply="Salam!",
        history_length=2,
        consulted=[],
        turn_id="xyz789",
    )

    response = _build_voice_response(
        thread_id="t-2", transcript="Salam", result=result, segments=[_segment(result.reply)]
    )

    assert response.status == "ok"
    assert response.approval is None
    assert response.consulted == []


@pytest.mark.asyncio
async def test_narration_becomes_a_spoken_divanbeyi_segment_first(monkeypatch):
    """The narrator's own explanation must be heard before the advisor -
    same "MC introduces, then the guest speaks" order as the text field."""

    async def fake_synthesize(text, advisor=None):
        return (b"fake-audio", "audio/ogg", "elevenlabs")

    monkeypatch.setattr(voice_api, "synthesize", fake_synthesize)

    result = TurnResult(
        status="ok",
        reply="Qorxma, qərarını ver.",
        history_length=2,
        consulted=["koroglu"],
        opinions=[{"advisor": "koroglu", "name": "Koroğlu", "text": "Qorxma, qərarını ver."}],
        turn_id="n-1",
        narration=["Divanbəyi sualını dinləyir...", "Sözü indi Koroğluya verirəm..."],
    )

    segments = await _speak_segments(result)

    assert len(segments) == 2
    assert segments[0].name == "Divanbəyi"
    assert segments[0].advisor == ""
    assert "Sözü indi Koroğluya verirəm" in segments[0].text
    assert segments[1].name == "Koroğlu"
