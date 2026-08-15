"""Pronunciation auto-tune harness: find a respelling the clone pronounces right.

For a word the TTS mispronounces, propose candidate respellings and run each
through the full TTS -> Whisper loop. A candidate only counts as a WINNER if
Whisper hears the ORIGINAL word in `--confirm` consecutive runs — eleven_v3 is
stochastic, and a single lucky pass is not a fix (measured 2026-08-15: a
candidate that passed once failed both confirmation runs).

Run inside the api container, where the app package and provider keys live:

    docker compose exec api python scripts/tune_pronunciation.py \
        --word "Koroğluyam" \
        --carrier "Salam, mən Koroğluyam." \
        --candidates "Koroğlu-yam" "Kor-oğluyam"

A confirmed winner can then be saved:

    curl -X POST http://127.0.0.1:8000/voicelab/dictionary \
        -H "Content-Type: application/json" \
        -H "X-Voicelab-Token: $VOICELAB_TOKEN" \
        -d '{"word": "...", "respelling": "..."}'
"""

import argparse
import asyncio
import re
import sys

from app.services.voice import synthesize, transcribe


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


async def heard_target(sentence: str, target: str) -> tuple[bool, str]:
    audio, _, _ = await synthesize(sentence, advisor=None)
    transcript = await transcribe(audio, "probe.ogg")
    return _words(target)[0] in _words(transcript), transcript


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--word", required=True, help="the word as it should be heard")
    parser.add_argument("--carrier", required=True, help="short sentence containing the word")
    parser.add_argument("--candidates", nargs="+", required=True, help="respellings to try")
    parser.add_argument("--confirm", type=int, default=2, help="consecutive passes required")
    args = parser.parse_args()

    if args.word not in args.carrier:
        parser.error("--carrier must contain --word")

    ok, heard = await heard_target(args.carrier, args.word)
    print(f"baseline «{args.word}»: {'✅ already fine' if ok else '❌'} | heard: {heard.strip()}")
    if ok:
        return 0

    for candidate in args.candidates:
        sentence = args.carrier.replace(args.word, candidate)
        passes = 0
        for run in range(1, args.confirm + 1):
            ok, heard = await heard_target(sentence, args.word)
            print(f"  «{candidate}» run {run}: {'✅' if ok else '❌'} | {heard.strip()}")
            if not ok:
                break
            passes += 1
        if passes == args.confirm:
            print(f"WINNER: «{candidate}» ({args.confirm}/{args.confirm} confirmed) — save it via /voicelab/dictionary")
            return 0

    print("no candidate survived confirmation — try new respellings, or fix at the voice level")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
