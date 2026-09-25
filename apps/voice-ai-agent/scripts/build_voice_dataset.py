"""Build an LJSpeech-style dataset of the owner's voice from Voice Lab recordings.

    .venv/bin/python scripts/build_voice_dataset.py --out /opt/divan/voice-dataset

Output: wavs/<id>.wav (22.05 kHz mono, trimmed, -20 LUFS) + metadata.csv (`id|text`),
the format Piper / VITS fine-tuning expects, plus report.json.

Two kinds of recording exist and are treated differently:
* one sentence per sample (the normal Voice Lab loop): kept when Whisper heard at
  most `--max-diffs` word differences from the sentence; the TEXT is the sentence
  he was asked to read, never Whisper's guess.
* long takes (several sentences or free talk in one file): cut at Whisper's
  segment boundaries; a segment is kept only when it matches a known practice
  sentence closely (difflib ratio >= 0.9), and then that sentence is the text.
  Free talk is dropped, because an unverified transcript would teach wrong words.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from app.services import voicelab  # noqa: E402

FILTER = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1," \
         "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse," \
         "highpass=f=60,loudnorm=I=-20:TP=-2:LRA=11"


def norm(s: str) -> str:
    return " ".join(re.findall(r"\w+", s.lower().replace("i̇", "i")))


def cut(src: Path, dst: Path, start: float | None = None, end: float | None = None) -> float:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.2f}", "-to", f"{end:.2f}"]
    cmd += ["-i", str(src), "-af", FILTER, "-ac", "1", "-ar", "22050", str(dst)]
    subprocess.run(cmd, check=True)
    return voicelab.audio_seconds(dst)


def segments(path: Path) -> list[dict]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.STT_API_KEY, base_url=settings.STT_BASE_URL)
    with path.open("rb") as fh:
        r = client.audio.transcriptions.create(model=settings.stt_model, file=(path.name, fh),
                                               language="az", response_format="verbose_json")
    return r.model_dump().get("segments", [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/opt/divan/voice-dataset")
    ap.add_argument("--max-diffs", type=int, default=1)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "wavs").mkdir(parents=True, exist_ok=True)
    known = {norm(t): t for t, _ in voicelab.SENTENCES}
    rows, dropped = [], []
    for src in voicelab.sample_files():
        meta_path = src.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        seconds = meta.get("seconds") or voicelab.audio_seconds(src)
        if meta and seconds <= 20:
            if meta.get("diffs", 99) > args.max_diffs:
                dropped.append({"file": src.name, "why": f"{meta['diffs']} word slips"})
                continue
            sid = src.stem
            dur = cut(src, out / "wavs" / f"{sid}.wav")
            rows.append((sid, meta["expected"], dur))
            continue
        for i, seg in enumerate(segments(src)):
            heard = norm(seg["text"])
            best = max(known, key=lambda k: difflib.SequenceMatcher(None, k, heard).ratio())
            ratio = difflib.SequenceMatcher(None, best, heard).ratio()
            if ratio < 0.9 or seg["end"] - seg["start"] < 1.0:
                dropped.append({"file": src.name, "seg": i, "why": f"no known sentence ({ratio:.2f})",
                                "heard": seg["text"].strip()[:80]})
                continue
            sid = f"{src.stem}_{i:02d}"
            dur = cut(src, out / "wavs" / f"{sid}.wav", seg["start"], seg["end"])
            rows.append((sid, known[best], dur))
    (out / "metadata.csv").write_text("".join(f"{sid}.wav|{text}\n" for sid, text, _ in rows), encoding="utf-8")
    report = {"clips": len(rows), "minutes": round(sum(d for *_, d in rows) / 60, 2),
              "goal_minutes": voicelab.GOAL_MINUTES, "dropped": dropped}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "dropped"}), f"dropped={len(dropped)}")


if __name__ == "__main__":
    main()
