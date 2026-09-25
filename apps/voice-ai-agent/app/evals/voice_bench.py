"""Voice benchmark: every engine on the same 20 held-out sentences (never recorded,
never trained on) -> intelligibility, likeness to the owner, speed.

    .venv/bin/python -m app.evals.voice_bench [--engines edge,owner-vc,clone,owner-model]

Method (checked on known cases before any number is quoted, 2026-09-26):
* intelligibility = word error rate of Whisper large-v3 (language pinned to az)
  against the sentence. Known case: the owner's own reading scores near 0.
* likeness = cosine of Resemblyzer speaker embeddings (an encoder independent of
  every engine under test) to the owner's reference recordings. Known cases:
  his held-out recording 0.86, the Microsoft voice 0.59.
* speed = real-time factor (seconds to synthesize / seconds of audio).
Gate for the owner's fine-tuned model to take rung 0: WER no worse than the
Microsoft voice + 0.05 AND likeness >= 0.80.
"""
from __future__ import annotations

import argparse, asyncio, difflib, json, re, subprocess, tempfile, time
from pathlib import Path

from app.core.config import settings
from app.services import clone_voice, owner_model, voice

HELDOUT = json.loads(Path(__file__).with_name("voice_heldout.json").read_text(encoding="utf-8"))
REFS = ["data/voices/owner_ref.wav", "data/voices/owner_ref_conversational.wav"]
SIM = "/opt/divan/vc/.venv/bin/python"


def wer(ref: str, hyp: str) -> float:
    n = lambda s: re.findall(r"\w+", s.lower().replace("i̇", "i"))
    a, b = n(ref), n(hyp)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    errors = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
    return errors / max(1, len(a))


async def engine_audio(engine: str, text: str) -> bytes:
    if engine == "edge":
        return await voice._edge_tts(voice.pronounce.apply(text), None)
    if engine == "owner-vc":
        return await voice._edge_tts(voice.pronounce.apply(text), None, owner=True)
    if engine == "clone":
        return await clone_voice.speak(voice.pronounce.apply(text), None)
    if engine == "owner-model":
        return await owner_model.speak(voice.pronounce.apply(text), None)
    raise ValueError(engine)


def seconds(ogg: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(ogg)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def likeness(files: list[Path]) -> list[float]:
    code = ("import sys,json,numpy as np\nfrom resemblyzer import VoiceEncoder, preprocess_wav\n"
            "e=VoiceEncoder('cpu',verbose=False); E=lambda p:e.embed_utterance(preprocess_wav(p))\n"
            "refs,files=json.loads(sys.argv[1]),json.loads(sys.argv[2])\n"
            "o=np.mean([E(r) for r in refs],axis=0)\n"
            "print(json.dumps([float(np.dot(o,v)/np.linalg.norm(o)/np.linalg.norm(v)) for v in map(E,files)]))")
    refs = [str(settings.clone_ref_file.parents[2] / r) for r in REFS]
    out = subprocess.run([SIM, "-c", code, json.dumps(refs), json.dumps([str(f) for f in files])],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


async def run(engines: list[str], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for engine in engines:
        rows, files = [], []
        for i, text in enumerate(HELDOUT):
            t0 = time.time()
            try:
                audio = await engine_audio(engine, text)
            except Exception as exc:  # noqa: BLE001
                rows.append({"i": i, "error": str(exc)[:120]})
                continue
            took = time.time() - t0
            f = out_dir / f"{engine}_{i:02d}.ogg"
            f.write_bytes(audio)
            heard = await voice.transcribe(audio, f.name)
            rows.append({"i": i, "wer": round(wer(text, heard), 3), "rtf": round(took / max(0.1, seconds(f)), 2),
                         "heard": heard})
            files.append(f)
        sims = likeness(files) if files else []
        ok = [r for r in rows if "wer" in r]
        for r, s in zip(ok, sims):
            r["likeness"] = round(s, 3)
        mean = lambda k: round(sum(r[k] for r in ok) / len(ok), 3) if ok else None
        report[engine] = {"n": len(ok), "failed": len(rows) - len(ok), "wer": mean("wer"),
                          "likeness": mean("likeness"), "rtf": mean("rtf"), "rows": rows}
        print(engine, {k: v for k, v in report[engine].items() if k != "rows"}, flush=True)
    edge = report.get("edge", {}).get("wer")
    own = report.get("owner-model")
    if own and own["n"] and edge is not None:
        report["gate_owner_model"] = bool(own["wer"] <= edge + 0.05 and own["likeness"] >= 0.80)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="edge,owner-vc,owner-model")
    ap.add_argument("--out", default="output/voice-bench")
    args = ap.parse_args()
    out = Path(args.out)
    report = asyncio.run(run(args.engines.split(","), out))
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("gate_owner_model:", report.get("gate_owner_model"))


if __name__ == "__main__":
    main()
