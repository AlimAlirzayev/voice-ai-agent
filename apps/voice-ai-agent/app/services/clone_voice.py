"""The owner's own cloned voice for the council (OmniVoice, zero cost).

Alim recorded his own Azerbaijani voice for the system (audio-studio
`voices/ramin_ref.wav`, 36 s, 2026-07-17). OmniVoice (k2-fsa, a free Hugging
Face Space that lists Azerbaijani) clones any text in that voice from the
reference clip plus its transcript. Measured from the VPS 2026-09-25: one
sentence in about 8.5 s.

Every member speaks in that one voice; they are told apart by pace and pitch,
the same way the free Microsoft voices are. When the reference clip is absent
or the Space fails, `voice.synthesize` falls back to those Microsoft voices so
a live turn never ends in silence.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from app.core.config import settings

log = logging.getLogger(__name__)


class CloneUnavailable(RuntimeError):
    """The cloned voice cannot speak this turn (no reference, Space down, timeout)."""


# The free Hugging Face tier gives a few minutes of GPU a day (measured 2026-09-25:
# dry after about seven clips). Once it says so, stop knocking until it refills,
# so every turn does not pay a failed round trip before the converter speaks.
QUOTA_COOLDOWN = 3600.0
_resting_until = 0.0


def _note_quota(exc: Exception) -> None:
    global _resting_until
    if "quota" in str(exc).lower():
        _resting_until = time.time() + QUOTA_COOLDOWN


def style_for(advisor: str | None) -> tuple[float, float]:
    """(speed, semitones) per member on the owner's voice."""
    return {
        "nesreddin": (1.06, 1.0),
        "koroglu": (1.0, -1.5),
        "simurg": (0.94, 3.0),
        "nesimi": (0.97, 0.0),
        "dedeqorqud": (0.9, -2.0),
        "nizami": (0.97, -0.7),
    }.get(advisor or "", (1.0, 0.0))


def ref_text() -> str:
    if settings.CLONE_REF_TEXT:
        return settings.CLONE_REF_TEXT
    sidecar = settings.clone_ref_file.with_suffix(".txt")
    return sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else ""


def available() -> bool:
    return settings.clone_ref_file.is_file() and bool(ref_text())


@lru_cache(maxsize=1)
def _client():
    from gradio_client import Client

    token = settings.HF_TOKEN or None
    try:
        return Client(settings.CLONE_SPACE, hf_token=token) if token else Client(settings.CLONE_SPACE)
    except TypeError:  # older gradio_client without hf_token
        return Client(settings.CLONE_SPACE)


def _predict(text: str, speed: float) -> str:
    from gradio_client import handle_file

    words = max(1, len(text.split()))
    res = _client().predict(
        text=text, lang="Azerbaijani", ref_aud=handle_file(str(settings.clone_ref_file)),
        ref_text=ref_text(), instruct="", ns=48.0, gs=2.0, dn=True, sp=speed,
        du=max(3.5, round(words * 0.75 + 1.5, 1)), pp=True, po=True, api_name="/_clone_fn",
    )
    src = res[0] if isinstance(res, (list, tuple)) else res
    if isinstance(src, dict):
        src = src.get("value") or src.get("path") or src.get("name")
    if not src or not Path(str(src)).is_file():
        raise CloneUnavailable(f"OmniVoice returned no audio: {str(res)[:200]}")
    return str(src)


async def _to_ogg(wav: str, semitones: float) -> bytes:
    """Shift pitch by `semitones` (duration kept) and encode OGG/Opus."""
    f = 2 ** (semitones / 12)
    chain = f"aresample=24000,asetrate={24000 * f:.0f},aresample=48000,atempo={1 / f:.4f}"
    with tempfile.NamedTemporaryFile(suffix=".ogg") as out:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-af", chain,
            "-ac", "1", "-c:a", "libopus", "-b:a", "48k", out.name,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise CloneUnavailable(f"ffmpeg failed: {err.decode('utf-8', 'replace')[:200]}")
        return Path(out.name).read_bytes()


async def speak(text: str, advisor: str | None) -> bytes:
    if not available():
        raise CloneUnavailable(f"no reference voice at {settings.clone_ref_file}")
    if time.time() < _resting_until:
        raise CloneUnavailable("OmniVoice GPU quota is resting")
    speed, semitones = style_for(advisor)
    try:
        wav = await asyncio.wait_for(asyncio.to_thread(_predict, text, speed),
                                     timeout=settings.CLONE_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise CloneUnavailable(f"OmniVoice took longer than {settings.CLONE_TIMEOUT:.0f}s") from exc
    except CloneUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - any Space failure means: fall back
        _client.cache_clear()
        _note_quota(exc)
        raise CloneUnavailable(f"OmniVoice failed: {exc}") from exc
    return await _to_ogg(wav, semitones)


async def to_owner(mp3: bytes) -> bytes:
    """Second rung: any Azerbaijani speech (the Microsoft voice) re-timbred into the
    owner's voice by the local converter (`divan-vc`, OpenVoice v2 on CPU, ~5 s per
    6 s clip). Used when OmniVoice is out of free GPU quota - measured 2026-09-25:
    the free Hugging Face tier ran dry after about seven clips."""
    import httpx

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "22050", "-f", "wav", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    wav, err = await proc.communicate(mp3)
    if proc.returncode != 0 or not wav:
        raise CloneUnavailable(f"ffmpeg mp3->wav failed: {err.decode('utf-8', 'replace')[:200]}")
    try:
        async with httpx.AsyncClient(timeout=settings.VC_TIMEOUT) as client:
            r = await client.post(f"{settings.VC_URL}/convert", content=wav)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - converter down means: plain voice
        raise CloneUnavailable(f"timbre converter failed: {exc}") from exc
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        tmp.write(r.content)
        tmp.flush()
        return await _to_ogg(tmp.name, 0.0)
