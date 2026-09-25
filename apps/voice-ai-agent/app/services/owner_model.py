"""Rung 0 of the owner voice: his OWN fine-tuned model (Piper/VITS, ONNX, CPU).

Trained on Kaggle from his Voice Lab recordings (ops/voice-train, approved by the
owner 2026-09-26). Once `data/voices/owner.onnx` (+ `.onnx.json`) is in place it
speaks every reply locally: no GPU quota, no network, no fee. Members keep their
pace and pitch through the same styles the clone uses.
"""
from __future__ import annotations

import asyncio
import tempfile
import wave
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.services.clone_voice import CloneUnavailable, _to_ogg, style_for


def model_file() -> Path:
    path = Path(settings.OWNER_MODEL_PATH)
    return path if path.is_absolute() else settings.clone_ref_file.parents[2] / path


def available() -> bool:
    f = model_file()
    return f.is_file() and f.with_suffix(".onnx.json").is_file()


@lru_cache(maxsize=1)
def _voice():
    from piper import PiperVoice

    return PiperVoice.load(str(model_file()))


def _synth(text: str, speed: float, out: str) -> None:
    from piper.config import SynthesisConfig

    with wave.open(out, "wb") as wav:
        _voice().synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1 / speed))


async def speak(text: str, advisor: str | None) -> bytes:
    if not available():
        raise CloneUnavailable(f"no owner model at {model_file()}")
    speed, semitones = style_for(advisor)
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        try:
            await asyncio.to_thread(_synth, text, speed, tmp.name)
        except Exception as exc:  # noqa: BLE001 - a broken model means: next rung
            raise CloneUnavailable(f"owner model failed: {exc}") from exc
        return await _to_ogg(tmp.name, semitones)
