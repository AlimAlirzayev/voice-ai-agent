"""Automated pronunciation-correction loop.

Closes the discover -> fix cycle end to end:

    scan_pronunciation.py  (discover problem words per persona voice)
            |
            v
    auto_tune_pronunciation.py   <-- this script
            |
            v
    POST /voicelab/dictionary    (winners become permanent)

For each problem word: an LLM proposes a handful of Azerbaijani phonetic
respellings (writing the word the way it should SOUND, e.g. "qırmadan" as
itself if fine, or breaking/adjusting spelling to steer the model), each
candidate is run through the real TTS voice -> Whisper loop, and a candidate
is only accepted after 2 CONSECUTIVE confirmations - eleven_v3 is stochastic,
so a single lucky pass proved unreliable in manual testing (2026-08-15
session). Winners are POSTed straight to /voicelab/dictionary, so the fix is
live immediately for every future reply.

Numeral-normalisation "diffs" (Whisper writing "otuz" as "30") are not
pronunciation problems and are filtered out before any word reaches the LLM.

Run inside the api container (needs OPENAI_API_KEY and, to save winners,
VOICELAB_TOKEN matching the running server's):

    docker compose exec api python scripts/auto_tune_pronunciation.py \
        --scan /tmp/scan_results.json --token "$VOICELAB_TOKEN"
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.voice import synthesize, transcribe  # noqa: E402

NUMERAL_RE = re.compile(r"^\d+$")
CANDIDATE_PROMPT = """Sən Azərbaycan dili fonetikası üzrə mütəxəssissən. Aşağıdakı söz/ifadə
mətn-səsə (TTS) modeli tərəfindən səhv tələffüz olunur. Onun DÜZGÜN səslənməsini təmin edəcək
3 fərqli yazılış variantı təklif et - sözün mənasını YOX, YALNIZ yazılışını dəyiş ki, model
onu doğru tələffüz etsin (məsələn defislə bölmək, bənzər səslənən hərflərlə əvəz etmək və s.).

Söz/ifadə: "{word}"
Bu, işləndiyi cümlə: "{sentence}"

Yalnız JSON massivi qaytar, başqa heç nə: ["variant1", "variant2", "variant3"]"""


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


async def propose_candidates(client: AsyncOpenAI, word: str, sentence: str) -> list[str]:
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": CANDIDATE_PROMPT.format(word=word, sentence=sentence)}],
        temperature=0.7,
    )
    raw = (response.choices[0].message.content or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        candidates = json.loads(raw)
        return [c for c in candidates if isinstance(c, str) and c.strip()][:3]
    except (json.JSONDecodeError, TypeError):
        return []


async def heard_target(sentence: str, target: str, advisor: str | None) -> tuple[bool, str]:
    audio, _, _ = await synthesize(sentence, advisor=advisor)
    transcript = await transcribe(audio, "probe.ogg")
    target_words = set(_words(target))
    heard_words = set(_words(transcript))
    return target_words <= heard_words, transcript


async def tune_word(
    client: AsyncOpenAI, word: str, sentence: str, advisor: str | None, confirm: int
) -> tuple[str, str] | None:
    """Returns (word, winning_respelling) or None if nothing survived confirmation."""
    ok, heard = await heard_target(sentence, word, advisor)
    if ok:
        print(f"  «{word}»: already fine ({heard.strip()[:60]})")
        return None

    candidates = await propose_candidates(client, word, sentence)
    if not candidates:
        print(f"  «{word}»: LLM proposed no candidates, skipping")
        return None

    for candidate in candidates:
        if candidate.lower() == word.lower():
            continue
        test_sentence = sentence.replace(word, candidate)
        passes = 0
        for run in range(1, confirm + 1):
            ok, heard = await heard_target(test_sentence, word, advisor)
            mark = "✅" if ok else "❌"
            print(f"  «{word}» -> «{candidate}» run {run}: {mark} {heard.strip()[:60]}")
            if not ok:
                break
            passes += 1
        if passes == confirm:
            print(f"  WINNER: «{word}» -> «{candidate}» ({confirm}/{confirm})")
            return word, candidate

    print(f"  no candidate for «{word}» survived confirmation")
    return None


async def save_to_dictionary(word: str, respelling: str, token: str) -> bool:
    import httpx

    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Voicelab-Token"] = token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:8000/voicelab/dictionary",
            headers=headers,
            json={"word": word, "respelling": respelling},
            timeout=30,
        )
    return response.status_code == 200


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", required=True, help="scan_pronunciation.py --json output")
    parser.add_argument("--confirm", type=int, default=2)
    parser.add_argument("--token", default="", help="VOICELAB_TOKEN; empty if the server has none set")
    parser.add_argument("--dry-run", action="store_true", help="find winners but do not save them")
    args = parser.parse_args()

    data = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # Build one (word, sentence, advisor) job per problem word, skipping pure
    # numeral-normalisation noise ("otuz" heard as "30" is not mispronounced).
    jobs: dict[str, tuple[str, str]] = {}
    for result in data["results"]:
        for d in result["diffs"]:
            word = d["expected"]
            if not word or NUMERAL_RE.match((d["heard"] or "").strip()):
                continue
            if word not in jobs:
                jobs[word] = (result["sentence"], result["advisor"])

    print(f"{len(jobs)} problem word(s) to tune (confirm={args.confirm})\n")

    winners: dict[str, str] = {}
    for word, (sentence, advisor) in jobs.items():
        print(f"=== {word!r} (advisor: {advisor}) ===")
        result = await tune_word(client, word, sentence, advisor, args.confirm)
        if result:
            winners[result[0]] = result[1]
        print()

    print(f"{'=' * 50}\n{len(winners)}/{len(jobs)} words fixed with a confirmed respelling\n")

    if args.dry_run:
        print(json.dumps(winners, ensure_ascii=False, indent=1))
        return 0

    saved = 0
    for word, respelling in winners.items():
        ok = await save_to_dictionary(word, respelling, args.token)
        print(f"{'saved' if ok else 'FAILED to save'}: «{word}» -> «{respelling}»")
        saved += ok

    print(f"\n{saved}/{len(winners)} saved to the live pronunciation dictionary")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
