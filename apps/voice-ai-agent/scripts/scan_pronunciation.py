"""Systematic pronunciation scan across all six persona voices.

For each advisor, synthesizes a handful of representative sentences in their
OWN voice (not the narrator), transcribes with Whisper, and reports every
word-level mismatch. This is the discovery half of the pronunciation loop;
`auto_tune_pronunciation.py` is the fix half.

Run inside the api container:

    docker compose exec api python scripts/scan_pronunciation.py [--json out.json]
"""

import argparse
import asyncio
import json
import re
import sys

from app.services.voice import synthesize, transcribe

# A few sentences per advisor, drawn from their real register (short, in the
# spirit of what synthesize() actually says in a turn) so the scan reflects
# real production text, not artificial test strings.
PROBES: dict[str, list[str]] = {
    "nesreddin": [
        "Bir gün padşah məndən soruşdu, sən niyə heç vaxt ciddi danışmırsan?",
        "Əncirin mükafatı zindan oldu, amma baltanı da unutmadım.",
        "Qazı evdə yoxdur deyirsən, bəs pəncərədəki kim idi?",
    ],
    "koroglu": [
        "Mərd dayanın, qoç igidlər, Çənlibelin başı qardır!",
        "Haqsızlığın qalası nə qədər uca olsa da, igidin nərəsi ondan ucadır.",
        "Qıratım yel kimi uçar, qılıncım şimşək kimi çaxar.",
    ],
    "simurg": [
        "Sən uzun yol qət etdin, ey yolçu, axtardığın quş elə özün idi.",
        "Həqiqət hər zaman ən uzaq deyil, ən yaxın yerdədir.",
        "Otuz quş yeddi vadidən keçib öz daxilində müdrikliyi tapdı.",
    ],
    "nesimi": [
        "Məndə sığar iki cahan, mən bu cahanə sığmazam.",
        "Həqiqəti kənarda yox, öz daxilində axtar.",
        "Gərçi bu gün Nəsimiyəm, haşimiyəm, qureyşiyəm.",
    ],
    "dedeqorqud": [
        "Oğul, bu dünyada hər şeyin öz vaxtı var.",
        "Atalar demiş, dağ dağa qovuşmaz, insan insana qovuşar.",
        "Qopuzumu sinəmə basıb sənə bir alqış deyim.",
    ],
    "nizami": [
        "Sevgi ilə ədalət eyni kökdən bəslənir.",
        "Kim başqasının qəlbini qırmadan öz yolunu tapırsa, müdrikliyə çatmışdır.",
        "Xəmsəmdə yazdığım hər beyt ağıl ilə ehtirasın tarazlığıdır.",
    ],
}


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def diff(expected: str, heard: str) -> list[dict]:
    exp, got = _words(expected), _words(heard)
    out = []
    # simple positional-ish diff via difflib, mirroring app/services/voicelab.py
    import difflib
    matcher = difflib.SequenceMatcher(a=exp, b=got, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            out.append({"expected": " ".join(exp[i1:i2]), "heard": " ".join(got[j1:j2]) or None})
    return out


async def scan_advisor(key: str, sentences: list[str]) -> list[dict]:
    findings = []
    for sentence in sentences:
        audio, _, engine = await synthesize(sentence, advisor=key)
        transcript = await transcribe(audio, "probe.ogg")
        diffs = diff(sentence, transcript)
        findings.append({
            "advisor": key, "sentence": sentence, "heard": transcript,
            "engine": engine, "diffs": diffs,
        })
    return findings


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", help="write full results to this path")
    parser.add_argument("--advisor", help="scan only this advisor key")
    args = parser.parse_args()

    advisors = {args.advisor: PROBES[args.advisor]} if args.advisor else PROBES
    all_results = []
    problem_words: dict[str, set[str]] = {}

    for key, sentences in advisors.items():
        print(f"\n=== {key} ===")
        results = await scan_advisor(key, sentences)
        all_results.extend(results)
        for r in results:
            status = "✅" if not r["diffs"] else "❌"
            print(f"{status} «{r['sentence'][:55]}»")
            if r["diffs"]:
                print(f"   heard: {r['heard'][:80]}")
                for d in r["diffs"]:
                    print(f"   «{d['expected']}» -> «{d['heard'] or '(düşüb)'}»")
                    problem_words.setdefault(d["expected"], set()).add(key)

    print(f"\n{'=' * 50}")
    print(f"TOPLAM: {len(problem_words)} fərqli problem söz/ifadə tapıldı")
    for word, advisors_hit in sorted(problem_words.items()):
        print(f"  «{word}» ({', '.join(sorted(advisors_hit))})")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({
                "results": all_results,
                "problem_words": {w: sorted(a) for w, a in problem_words.items()},
            }, f, ensure_ascii=False, indent=1)
        print(f"\nSaved -> {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
