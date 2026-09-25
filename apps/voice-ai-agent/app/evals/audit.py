"""Council quality audit: known-answer questions, deterministic checks, a separate judge.

What it measures, per question:
  * routing   - did Divanbəyi call the member whose domain the question belongs to
  * language  - Turkish/colloquial loans, Cyrillic, missing Azerbaijani letters,
                machine vocabulary (framework names, retrieval jargon), markdown/emoji
  * form      - sentence count of the spoken reply
  * citations - are the quoted passages clean text or OCR debris (digits, footnote marks)
  * culture   - presence of native markers: address forms, blessings, proverbs (informative)
  * judge     - a separate Claude call in the role of a strict Azerbaijani philologist
                scores character fidelity, mentality/values, language purity, literary
                style and usefulness 1-5 with named defects

The deterministic checks decide pass/fail; the judge only adds a graded opinion.
Nothing here edits prompts: the audit reports, the human decides.

usage: .venv/bin/python -m app.evals.audit [--base http://127.0.0.1:8940] [--out report.html]
       [--only nesreddin,koroglu] [--no-judge]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

AUDIT_SET = Path(__file__).with_name("audit_set.json")

MACHINE_LEAKS = (
    "langgraph", "supervisor", "interrupt", "synthesis", "bm25", "retrieval", "embedding",
    "uyğunluq bal", "json", "http", "tool", "prompt", "llm", "model", "süni intellekt",
    "ai ", "agent",
)

# Turkish / colloquial / calque forms an Azerbaijani reader hears as foreign.
# Word-boundary matched on the lowercased text; each maps to the native form.
LOANWORDS = {
    "önəmli": "vacib", "zatən": "onsuz da", "falan": "filan", "burda": "burada",
    "orda": "orada", "gələcəm": "gələcəyəm", "edəcəm": "edəcəyəm", "sağol": "sağ ol",
    "çok": "çox", "değil": "deyil", "ile": "ilə", "için": "üçün", "evet": "bəli",
    "hayır": "xeyr", "şimdi": "indi", "nasıl": "necə", "neden": "niyə", "kadar": "qədər",
    "ama": "amma", "ve": "və", "belki": "bəlkə", "hiç": "heç", "kendi": "öz",
    "ben": "mən", "yapmak": "etmək", "yap": "et", "gibi": "kimi", "dükkan": "dükan",
    "şey": "şey (məqbul)", "bir şeyler": "bir şeylər", "olsun ki": "olsun", "bence": "məncə",
    "sence": "səncə", "işte": "bax", "artık": "artıq", "sadece": "sadəcə", "tamamen": "tamamilə",
    "herkes": "hamı", "herşey": "hər şey", "değişmek": "dəyişmək", "güzel": "gözəl",
    "iyi": "yaxşı", "kötü": "pis", "zaman": "vaxt (məqbul)", "şu an": "indi",
}
# "şey" and "zaman" are valid Azerbaijani; kept in the table for completeness but
# excluded from failures.
_LOAN_INFO_ONLY = {"şey", "zaman", "ve"}

CULTURE_MARKERS = {
    "xitab": ("oğul", "bala", "qardaş", "qızım", "əzizim", "ay bala", "övladım", "ay oğul", "igid"),
    "alqış": ("allah", "xeyir-dua", "yolun açıq", "qismət", "xeyir", "nə mutlu", "alqış", "amin"),
    "məsəl": ("deyiblər", "el məsəli", "atalar", "demişkən", "məsəl", "deyərlər", "el deyib"),
}

_UPPER_MAP = str.maketrans({"İ": "i", "I": "ı"})
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_WORD = re.compile(r"[a-zəğışçöüA-ZƏĞIİŞÇÖÜ]+")


def az_lower(text: str) -> str:
    return text.translate(_UPPER_MAP).lower()


def sentences(text: str) -> int:
    return len([p for p in re.split(r"[.!?…]+", text) if p.strip()])


def loanwords_in(text: str) -> list[str]:
    words = {az_lower(w) for w in _WORD.findall(text)}
    return sorted(w for w in words if w in LOANWORDS and w not in _LOAN_INFO_ONLY)


def leaks_in(text: str) -> list[str]:
    """Machine vocabulary as whole words: audit v1 flagged «ictimai» for "ai "."""
    low = az_lower(text)
    found = set()
    for marker in MACHINE_LEAKS:
        m = marker.strip()
        pattern = r"(?<![a-zəğışçöü])" + re.escape(m) + r"(?![a-zəğışçöü])"
        if re.search(pattern, low):
            found.add(m)
    return sorted(found)


def culture_markers_in(text: str) -> dict[str, list[str]]:
    low = az_lower(text)
    return {kind: [m for m in markers if m in low] for kind, markers in CULTURE_MARKERS.items()}


def citation_noise(quote: str) -> list[str]:
    """OCR / apparatus debris that must never be read aloud as a classic's words."""
    problems = []
    if re.search(r"\d", quote):
        problems.append("rəqəm")
    if re.search(r"\b[A-Z]\d+", quote):
        problems.append("səhifə/qeyd işarəsi")
    letters = len(_WORD.findall(quote))
    if letters and len(quote) / max(letters, 1) > 12:
        problems.append("hərf-söz nisbəti pozuq")
    return problems


def deterministic_checks(item: dict, reply: str, consulted: list[str], citations: list[dict]) -> dict:
    fails: list[str] = []
    warns: list[str] = []
    expected = item.get("expect")
    if expected and expected not in consulted:
        fails.append(f"marşrut: {expected} gözlənilirdi, çağırılan {consulted or '—'}")
    if not reply.strip():
        fails.append("boş cavab")
    if _CYRILLIC.search(reply):
        fails.append("kiril hərfi")
    if len(reply) > 60 and "ə" not in az_lower(reply):
        fails.append("«ə» yoxdur — türkcəyə meyl")
    loans = loanwords_in(reply)
    if loans:
        fails.append("kalka/türk sözü: " + ", ".join(f"{w}→{LOANWORDS[w]}" for w in loans))
    leaks = leaks_in(reply)
    if leaks:
        fails.append("maşın sözü: " + ", ".join(leaks))
    # Since v2 the reply carries every member's own words plus one closing line:
    # up to 3 sentences per member and 1 for the Divanbəyi.
    limit = item.get("max_sentences") or (3 * max(len(consulted), 1) + 1)
    n = sentences(reply)
    if n > limit:
        fails.append(f"cümlə sayı {n} > {limit}")
    if any(tok in reply for tok in ("```", "###", "**")) or _EMOJI.search(reply):
        fails.append("markdown/emoji")
    if item.get("lang") == "az" and re.search(r"\b(the|and|you|is)\b", az_lower(reply)):
        warns.append("ingilis sözü")
    noisy = [c for c in citations if citation_noise(c.get("quote", ""))]
    if noisy:
        warns.append(f"sitat zibili: {len(noisy)}/{len(citations)} sitat OCR/rəqəm daşıyır")
    markers = culture_markers_in(reply)
    return {"fails": fails, "warns": warns, "sentences": n, "culture": markers}


JUDGE_SYSTEM = """Sən otuz illik Azərbaycan filoloqu, folklorşünas və ədəbiyyatşünassan; Kitabi-Dədə Qorqudu,
Koroğlu dastanını, Nəsimini, Nizamini, Molla Nəsrəddin lətifələrini əslindən oxumusan. Sərtsən, xoşagəlməzsən,
tərif etmirsən. Sənə bir istifadəçi sualı və «Divan» adlı əfsanəvi şuranın cavabı verilir; şuranın hansı
üzvlərinin danışdığı deyilir. Cavabı 1–5 şkalası ilə qiymətləndir:
- xarakter: cavab həmin üzv(lər)in tarixi/ədəbi şəxsiyyətinə sadiqdirmi (üslub, düşüncə tərzi, mənbə ruhu)?
- mentalitet: Azərbaycan dəyərləri (ailə, ağsaqqal, halallıq, böyüyə hörmət, səbir, qonaqpərvərlik, qeyrət) təbii
  hiss olunurmu, yoxsa ümumi «qərb self-help» tonu var?
- dil: təmiz ədəbi Azərbaycan dili — türk/rus kalkası, tərcümə qoxusu, yad sintaksis varmı?
- bədii: mətn canlıdır, ritmi, obrazı, xalq ifadəsi varmı, yoxsa quru nəsihətdir?
- fayda: real insan bu cavabla nə edəcəyini bilirmi?
YALNIZ bu JSON-u qaytar, başqa heç nə:
{"xarakter":1-5,"mentalitet":1-5,"dil":1-5,"bedii":1-5,"fayda":1-5,"qusurlar":["…"],"en_yaxsi":"…","bir_cumle":"…"}"""


def judge(question: str, reply: str, consulted: list[str], model: str, timeout: float = 150.0) -> dict:
    prompt = (f"SUAL: {question}\n\nDANIŞANLAR: {', '.join(consulted) or 'heç kim'}\n\nDİVANIN CAVABI:\n{reply}")
    cmd = ["claude", "-p", "--output-format", "json", "--model", model, "--tools", "",
           "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
           "--permission-mode", "default", "--system-prompt", JUDGE_SYSTEM]
    env = {"PYTHONIOENCODING": "utf-8", "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/root"}
    try:
        proc = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, timeout=timeout, env=env, check=False)
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
        text = data.get("result", "") if isinstance(data, dict) else ""
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {"error": f"hakim JSON vermədi: {text[:120]}"}
    except Exception as exc:  # noqa: BLE001 - the audit must finish even if the judge does not
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def ask(client: httpx.Client, base: str, question: str, thread_id: str) -> tuple[dict, bool]:
    """POST /chat; approve a pending HITL step so the audit sees the final reply."""
    r = client.post(f"{base}/chat", json={"message": question, "thread_id": thread_id}, timeout=300)
    r.raise_for_status()
    data = r.json()
    hitl = data.get("status") == "pending_approval"
    if hitl:
        r = client.post(f"{base}/chat/resume", json={"thread_id": thread_id, "decision": "approve"}, timeout=300)
        r.raise_for_status()
        resumed = r.json()
        resumed["consulted"] = data.get("consulted") or resumed.get("consulted")
        resumed["citations"] = data.get("citations") or resumed.get("citations")
        data = resumed
    return data, hitl


def run(base: str, only: set[str] | None, use_judge: bool, judge_model: str,
        partial: Path | None = None, resume: dict | None = None) -> dict:
    """Ask every question; after each one the partial report is written to
    `partial`, so a killed run loses one answer, not twenty. `resume` (a
    previous partial/final report) skips the ids it already holds."""
    items = json.loads(AUDIT_SET.read_text(encoding="utf-8"))
    if only:
        items = [i for i in items if i.get("expect") in only or i.get("id") in only]
    done = {r["id"]: r for r in (resume or {}).get("results", []) if "checks" in r}
    results = [done[i["id"]] for i in items if i["id"] in done]
    items = [i for i in items if i["id"] not in done]
    if done:
        print(f"resuming: {len(done)} already answered, {len(items)} to go", flush=True)

    def save() -> None:
        if partial:
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text(json.dumps({"base": base, "judge_model": judge_model if use_judge else None,
                                           "when": datetime.now().isoformat(timespec="seconds"),
                                           "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")

    with httpx.Client() as client:
        for i, item in enumerate(items, 1):
            t0 = time.time()
            thread_id = f"audit-{datetime.now():%Y%m%d%H%M%S}-{i}"
            try:
                data, hitl = ask(client, base, item["q"], thread_id)
            except Exception as exc:  # noqa: BLE001
                results.append({**item, "error": f"{type(exc).__name__}: {exc}"})
                print(f"[{i}/{len(items)}] {item['id']} ERROR {exc}", flush=True)
                continue
            reply = data.get("reply", "")
            consulted = data.get("consulted") or []
            citations = data.get("citations") or []
            checks = deterministic_checks(item, reply, consulted, citations)
            verdict = judge(item["q"], reply, consulted, judge_model) if use_judge else {}
            results.append({**item, "reply": reply, "consulted": consulted, "citations": citations,
                            "hitl": hitl, "seconds": round(time.time() - t0, 1), "checks": checks,
                            "judge": verdict})
            save()
            state = "PASS" if not checks["fails"] else "FAIL"
            print(f"[{i}/{len(items)}] {item['id']} {state} {consulted}"
                  f" {round(time.time() - t0)}s {'HITL' if hitl else ''} {checks['fails']}", flush=True)
    return {"base": base, "when": datetime.now().isoformat(timespec="seconds"), "judge_model": judge_model if use_judge else None,
            "results": results}


def summarise(report: dict) -> dict:
    rs = [r for r in report["results"] if "checks" in r]
    n = len(rs)
    passed = sum(1 for r in rs if not r["checks"]["fails"])
    routing_ok = sum(1 for r in rs if r.get("expect") and r["expect"] in r["consulted"])
    routing_n = sum(1 for r in rs if r.get("expect"))
    judged = [r["judge"] for r in rs if r.get("judge") and "error" not in r["judge"]]
    keys = ("xarakter", "mentalitet", "dil", "bedii", "fayda")
    avg = {k: round(sum(float(j.get(k, 0)) for j in judged) / len(judged), 2) for k in keys} if judged else {}
    warns = sum(len(r["checks"]["warns"]) for r in rs)
    cites = sum(len(r["citations"]) for r in rs)
    noisy = sum(1 for r in rs for c in r["citations"] if citation_noise(c.get("quote", "")))
    return {"n": n, "passed": passed, "routing": f"{routing_ok}/{routing_n}", "judge_avg": avg,
            "judged": len(judged), "warnings": warns, "citations": cites, "noisy_citations": noisy,
            "mean_seconds": round(sum(r["seconds"] for r in rs) / n, 1) if n else 0}


def render_html(report: dict, summary: dict) -> str:
    def esc(s: object) -> str:
        return html.escape(str(s))

    rows = []
    for r in report["results"]:
        if "checks" not in r:
            rows.append(f"<tr class=err><td colspan=6>{esc(r['id'])}: {esc(r.get('error'))}</td></tr>")
            continue
        c = r["checks"]
        j = r.get("judge") or {}
        state = "PASS" if not c["fails"] else "FAIL"
        scores = " · ".join(f"{k[:3]} {j.get(k, '–')}" for k in ("xarakter", "mentalitet", "dil", "bedii", "fayda")) if j and "error" not in j else esc(j.get("error", ""))
        cites = "".join(f"<li>{esc(ci.get('name'))} — {esc(ci.get('work'))}, {esc(ci.get('ref'))}: «{esc(ci.get('quote', '')[:110])}»"
                        f"{' <b class=w>[' + ', '.join(citation_noise(ci.get('quote',''))) + ']</b>' if citation_noise(ci.get('quote','')) else ''}</li>"
                        for ci in r["citations"])
        culture = ", ".join(f"{k}: {', '.join(v)}" for k, v in c["culture"].items() if v) or "—"
        rows.append(f"""<tr class={state.lower()}>
<td><b>{esc(r['id'])}</b><br><small>{esc(r.get('expect') or '—')} · {r['seconds']} s{' · HITL' if r['hitl'] else ''}</small></td>
<td>{esc(r['q'])}</td>
<td class=reply>{esc(r['reply'])}<br><small>danışanlar: {esc(', '.join(r['consulted']) or '—')} · {c['sentences']} cümlə · mədəni işarə: {esc(culture)}</small>
<ul class=cites>{cites}</ul></td>
<td><b>{state}</b><ul>{''.join(f'<li class=f>{esc(x)}</li>' for x in c['fails'])}{''.join(f'<li class=w>{esc(x)}</li>' for x in c['warns'])}</ul></td>
<td>{scores}<ul>{''.join(f'<li>{esc(x)}</li>' for x in (j.get('qusurlar') or []))}</ul><small>{esc(j.get('bir_cumle', ''))}</small></td>
</tr>""")
    avg = summary["judge_avg"]
    avg_html = " · ".join(f"{k} <b>{v}</b>" for k, v in avg.items()) if avg else "hakim işləmədi"
    return f"""<!doctype html><html lang=az><head><meta charset=utf-8><title>Divan audit</title>
<style>:root{{--bg:#fbfaf6;--fg:#1c1b18;--card:#fff;--line:#e4e0d6;--pass:#1d7a3a;--fail:#b3261e;--warn:#9a6700}}
@media(prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#151412;--fg:#ece9e1;--card:#1e1c19;--line:#33302a}}}}
:root[data-theme=dark]{{--bg:#151412;--fg:#ece9e1;--card:#1e1c19;--line:#33302a}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,Inter,sans-serif}}
h1{{font-size:1.4rem;margin:0 0 4px}} .sum{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0 18px}}
.sum div{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}}
table{{width:100%;border-collapse:collapse;background:var(--card)}} td{{border-top:1px solid var(--line);padding:10px;vertical-align:top}}
tr.pass td:first-child{{border-left:4px solid var(--pass)}} tr.fail td:first-child{{border-left:4px solid var(--fail)}}
.f{{color:var(--fail)}} .w{{color:var(--warn)}} .reply{{max-width:46ch}} ul{{margin:4px 0 0 16px;padding:0}} .cites{{font-size:.85em;opacity:.85}}
@media(max-width:700px){{table,tbody,tr,td{{display:block}} td{{border:0}} tr{{border-top:1px solid var(--line);padding:8px 0}}}}</style></head>
<body><h1>Divan — mentalitet, dil və üslub auditi</h1>
<div><small>{esc(report['when'])} · {esc(report['base'])} · hakim: {esc(report.get('judge_model') or '—')}</small></div>
<div class=sum><div>Keçdi <b>{summary['passed']}/{summary['n']}</b></div><div>Marşrut <b>{summary['routing']}</b></div>
<div>Hakim (1–5): {avg_html} <small>({summary['judged']} qiymət)</small></div>
<div>Sitat <b>{summary['citations']}</b>, zibilli <b class=w>{summary['noisy_citations']}</b></div>
<div>Xəbərdarlıq <b>{summary['warnings']}</b></div><div>Orta vaxt <b>{summary['mean_seconds']} s</b></div></div>
<table><tr><th>Hal</th><th>Sual</th><th>Divanın cavabı</th><th>Deterministik</th><th>Hakim</th></tr>{''.join(rows)}</table>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8940")
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--judge-model", default="claude-fable-5-1")
    ap.add_argument("--resume", default="", help="a previous (partial) report JSON to continue from")
    a = ap.parse_args()
    only = {s.strip() for s in a.only.split(",") if s.strip()} or None
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    resume = json.loads(Path(a.resume).read_text(encoding="utf-8")) if a.resume else None
    partial = Path(a.json or f"output/audit-{stamp}.json").with_suffix(".partial.json")
    report = run(a.base, only, not a.no_judge, a.judge_model, partial=partial, resume=resume)
    summary = summarise(report)
    report["summary"] = summary
    out_json = Path(a.json or f"output/audit-{stamp}.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out_html = Path(a.out or f"output/audit-{stamp}.html")
    out_html.write_text(render_html(report, summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"json: {out_json}\nhtml: {out_html}")
    return 0 if summary["passed"] == summary["n"] else 1


if __name__ == "__main__":
    sys.exit(main())
