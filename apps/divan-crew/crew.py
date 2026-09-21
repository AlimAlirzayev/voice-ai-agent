"""Divan as a CrewAI crew — Lesson #41 (Agent · Task · Tool · Crew · Process).

The LangGraph app stays the production door. This is a second, thin front
over the SAME council: the six members are built from the roster and the
hand-written character prompts already in `app/prompts/divan.py`, imported
rather than copied, so there is exactly one place where Koroğlu is defined.

What this adds that the graph does not have:
  * members OWN their tools — each one searches its own corpus itself,
    instead of a node fetching evidence and pasting it into the prompt;
  * a deterministic metre tool the poets can call on their own verse;
  * a structured verdict (`output_pydantic=DivanVerdict`) with strict routing,
    replacing a bare-token parse that silently picks the wrong member;
  * a hierarchical manager (Divanbəyi) that delegates and validates.

COST AND TIME, the two things that can ruin this run:
  * every member thinks on the operator's Claude subscription via
    `gateway.studio_crew.ClaudeSubscriptionLLM` — reused, not rewritten. No
    metered API key is read anywhere in this module.
  * that class was measured spiralling to 20+ minutes when workers run on
    `claude -p` unbounded, so two walls are mandatory here: the per-run LLM
    budget the class already enforces (CREW_LLM_BUDGET, default 240 s) and
    the roster cap below. At most two members answer any one question, which
    is the same cap the LangGraph supervisor applies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Both trees on the path: the course app (roster, prompts, corpus) and the OS
# (the Claude subscription client). Neither is copied into the other.
DIVAN_APP = os.getenv("DIVAN_APP_DIR", "/opt/divan/apps/voice-ai-agent")
HUB = os.getenv("HUB_DIR", "/opt/marketing-hub-os")
for path in (os.path.dirname(os.path.abspath(__file__)), DIVAN_APP, HUB):
    if path not in sys.path:
        sys.path.insert(0, path)

from crewai import Agent, Crew, Process, Task  # noqa: E402
from crewai.tools import tool  # noqa: E402

import corpus  # noqa: E402
import heca  # noqa: E402
from app.prompts.divan import ROSTER, advisor_prompt  # noqa: E402
from schemas import MAX_CONSULTED, Citation, DivanVerdict  # noqa: E402

RESULT_BEGIN = "<<<DIVAN_RESULT_BEGIN>>>"
RESULT_END = "<<<DIVAN_RESULT_END>>>"

# Wall-clock ceiling for one council run, checked by the caller. The LLM
# budget inside ClaudeSubscriptionLLM stops NEW expensive calls; this is the
# outer number the operator is promised.
RUN_CEILING_S = float(os.getenv("DIVAN_RUN_CEILING", "600"))

POETS = ("nesimi", "nizami", "koroglu")

# Appended LAST to every task, after the instructions, because a rule placed
# early gets outvoted by the grounding text that follows it - measured in this
# house on 2026-08-11 and re-confirmed here on the second live run.
VOICE_CONTRACT = (
    "SƏS QAYDASI (hamıdan üstündür): cavab səslə oxunacaq. Maşın sözü işlətmə — "
    "«BM25», «retrieval», «uyğunluq balı», «hissə 1», «ref:», bal, faiz, "
    "fayl adı, link YOX. Mənbənin adını demə. Alətin tapdığı parçanı olduğu "
    "kimi sitat gətirmə: onu öz dilinlə danış. Tapmadınsa, tapmadığını deyil, "
    "sadəcə öz sözünü de. Hər üzv ən çox 2 qısa cümlə."
)

# The deterministic half of the same rule: what the guard catches, the run
# reports. A prompt is a request; this is the meter.
MACHINE_LEAKS = (
    "bm25", "retrieval", "uyğunluq bal", "uygunluq bal", "embedding",
    "ref:", "hissə 1", "hisse 1", "bənd 1", "http", "json", "tool",
)


def is_hollow(telemetry: dict, consulted: list[str]) -> str | None:
    """Did the council actually sit, or did the manager improvise it alone?

    This is the check that caught the first live run, and it is a function
    rather than a thing someone remembers to eyeball. A hierarchical run must
    cost at least one model call per member consulted plus the manager's own,
    and a member that never opened its own texts cited nothing it read.

    Returns the reason it looks hollow, or None when the run is real.
    """
    calls = (telemetry.get("brain") or {}).get("claude_calls", 0)
    calls += (telemetry.get("brain") or {}).get("fallback_calls", 0)
    if not consulted:
        return "heç bir üzv seçilməyib"
    if calls < len(consulted) + 1:
        return (
            f"{len(consulted)} üzv göstərilir, amma cəmi {calls} model çağırışı "
            "var — menecer cavabı özü yazıb"
        )
    if telemetry.get("tool_calls", {}).get("corpus", 0) == 0:
        return "heç bir üzv öz mətninə baxmayıb — sitat iddiası əsassızdır"
    return None


def voice_leaks(text: str) -> list[str]:
    """Machine vocabulary found in text meant to be spoken to a person."""
    low = text.lower()
    return sorted({marker for marker in MACHINE_LEAKS if marker in low})


def build_llm():
    """The members' brain: the operator's Claude subscription, reused.

    Imported from the OS rather than reconstructed, so the cap-latch, the
    account rotation and the per-run budget all behave exactly as they do in
    production. `CREW_WORKER_BRAIN=fast` still forces the free floor, which
    is the escape hatch when the subscription is capped.
    """
    from gateway.studio_crew import _make_llm

    return _make_llm()


# --- tools: deterministic, LLM-free, owned by the agents -----------------
#
# The ledger below is not bookkeeping, it is the anti-fabrication rule. The
# FIRST live run of this crew produced a citation reading «Nəsimi, Seçilmiş
# əsərləri / Divan, qəzəl, mətlə beyti» — a real line of verse under a source
# that does not exist in our corpus, emitted by a model that had called no
# tool at all. A citation is a receipt; a receipt written by the person
# claiming the expense is not one. So citations are taken from what the
# retrieval layer ACTUALLY returned, and whatever the model wrote is dropped.

_CITATION_LEDGER: list[dict] = []
_TOOL_CALLS: dict[str, int] = {"corpus": 0, "metre": 0, "corpus_hits": 0}


def reset_ledger() -> None:
    _CITATION_LEDGER.clear()
    _TOOL_CALLS.update({"corpus": 0, "metre": 0, "corpus_hits": 0})


@tool("oz_metnimde_axtar")
def corpus_tool(advisor: str, query: str) -> str:
    """Bir Divan üzvünün ÖZ mətnlərində (dastan, qəzəl, poema) sualla
    səsləşən parçanı tapır. advisor: nesreddin|koroglu|simurg|nesimi|
    dedeqorqud|nizami. Tapılmazsa bunu açıq deyir — uydurma sitat yoxdur."""
    _TOOL_CALLS["corpus"] += 1
    hits = corpus.search(advisor, query)
    _TOOL_CALLS["corpus_hits"] += len(hits)
    for hit in hits:
        _CITATION_LEDGER.append({
            "advisor": hit.advisor,
            "work": hit.work,
            "ref": hit.ref,
            "quote": hit.text.strip()[:200],
            "source": hit.source,
            "retrieval": "bm25",
        })
    if not hits:
        return (
            "Bu sualla səsləşən parça öz mətnlərində tapılmadı — "
            "sitatsız, öz xarakterinlə cavab ver."
        )
    # The score is deliberately NOT shown to the agent. In the second live run
    # the members read it out loud - «uyğunluq balı 6.415», «retrieval: BM25» -
    # turning a spoken answer from a 15th-century poet into a retrieval log.
    # What a tool shows its caller is what the caller may repeat.
    return "\n".join(
        f"[{i + 1}] «{h.text.strip()}» — {h.work}, {h.ref}"
        for i, h in enumerate(hits)
    )


@tool("heca_vezni_yoxla")
def metre_tool(text: str) -> str:
    """Şeir mətninin heca vəznini ölçür: hər misrada heca sayı, bölgü
    (6+5, 4+4+3, 4+4, 4+3), qafiyə sxemi və forma adı. Model işlətmir,
    sayır. Öz yazdığın şeiri buraya ver və qüsuru düzəlt."""
    _TOOL_CALLS["metre"] += 1
    return heca.render(text)


def build_members(llm) -> dict[str, Agent]:
    """One Agent per roster entry. role/goal/backstory come from the product's
    own prompts — the lesson's 'give the agent a role, a goal and a backstory'
    is satisfied by real, already-written character work, not by new filler."""
    members: dict[str, Agent] = {}
    for key, info in ROSTER.items():
        tools = [corpus_tool, metre_tool] if key in POETS else [corpus_tool]
        members[key] = Agent(
            role=info["name"],
            goal=info["domain"],
            backstory=advisor_prompt(key),
            tools=tools,
            llm=llm,
            allow_delegation=False,
            verbose=False,
            max_iter=3,
        )
    return members


def build_manager(llm) -> Agent:
    roster_lines = "\n".join(f"- {k}: {v['name']} — {v['domain']}" for k, v in ROSTER.items())
    return Agent(
        role="Divanbəyi",
        goal=(
            "Sualı ən çox İKİ uyğun üzvə yönəlt, fikirlərini topla və şuranın "
            "yekun sözünü ver."
        ),
        backstory=(
            "Sən Divanın başısan. Özün məsləhət vermirsən — kimin danışacağını "
            "seçirsən, cavabları yoxlayırsan və yekunu bağlayırsan.\n"
            f"Şuranın üzvləri:\n{roster_lines}\n"
            "Qayda: ən çox iki üzv. Sual heç bir üzvün sahəsinə aid deyilsə, "
            "bir üzv seç və qısa saxla."
        ),
        llm=llm,
        allow_delegation=True,
        verbose=False,
        max_iter=4,
    )


def build_crew(question: str, llm=None) -> Crew:
    llm = llm or build_llm()
    members = build_members(llm)
    manager = build_manager(llm)

    # NOTE: no `agent=` here, deliberately. Assigning the task to the manager
    # made the FIRST live run answer in a single LLM call with zero delegation
    # and zero tool use - the manager simply wrote what the members "would"
    # have said. In Process.hierarchical the task must stay unassigned so the
    # manager has to delegate it to the coworkers.
    task = Task(
        description=(
            f"İstifadəçinin sualı: «{question}»\n\n"
            f"Ən çox {MAX_CONSULTED} üzvə müraciət et — cavabı ÖZÜN yazma, "
            "üzvlərdən al. Hər üzv əvvəlcə `oz_metnimde_axtar` aləti ilə öz "
            "mətnlərinə baxsın, sonra öz sahəsindən və öz xarakteri ilə "
            "danışsın; şeir yazan üzv `heca_vezni_yoxla` ilə vəznini "
            "yoxlasın. Sonra fikirləri BİR cavaba birləşdir: ən çox üç qısa "
            "cümlə, markdown və emoji olmadan, istifadəçinin dilində.\n\n"
            + VOICE_CONTRACT
        ),
        expected_output=(
            "DivanVerdict JSON: question, consulted (ən çox 2 açar), opinions "
            "(advisor, name, text — üzvlərin öz sözləri), verdict (yekun cavab), "
            "needs_approval, citations, metre. Sitatları özündən yazma: onlar "
            "alətin qaytardığı parçalardan götürülür."
        ),
        output_pydantic=DivanVerdict,
    )

    return Crew(
        agents=list(members.values()),
        tasks=[task],
        process=Process.hierarchical,
        manager_agent=manager,
        memory=False,
        verbose=False,
    )


def run(question: str) -> tuple[DivanVerdict | None, dict]:
    """One council run. Returns (verdict, telemetry). Never raises on a model
    failure: the caller gets a telemetry record saying what happened."""
    started = time.monotonic()
    reset_ledger()
    telemetry: dict = {"question": question, "ceiling_s": RUN_CEILING_S}
    try:
        crew = build_crew(question)
        result = crew.kickoff()
        verdict = getattr(result, "pydantic", None)
        if verdict is None:
            telemetry["error"] = "crew returned no structured verdict"
        else:
            telemetry["model_citations_dropped"] = len(verdict.citations)
            verdict.citations = [Citation(**c) for c in _CITATION_LEDGER]
            verdict = verdict.with_approval_rule()
        telemetry["raw"] = str(getattr(result, "raw", ""))[:1200]
    except Exception as exc:  # noqa: BLE001 - a run must report, not crash
        verdict, telemetry["error"] = None, f"{type(exc).__name__}: {exc}"

    telemetry["seconds"] = round(time.monotonic() - started, 1)
    telemetry["over_ceiling"] = telemetry["seconds"] > RUN_CEILING_S
    telemetry["tool_calls"] = dict(_TOOL_CALLS)
    # The honesty meter of this whole build: a run where the members never
    # touched their own texts is a run the manager improvised, no matter how
    # good the Azerbaijani reads.
    telemetry["grounded"] = _TOOL_CALLS["corpus"] > 0
    if verdict is not None:
        spoken = " ".join([verdict.verdict] + [o.text for o in verdict.opinions])
        telemetry["voice_leaks"] = voice_leaks(spoken)
        telemetry["hollow"] = is_hollow(telemetry, verdict.consulted)
    try:
        from gateway.studio_crew import _BRAIN_STATE

        telemetry["brain"] = {
            "claude_calls": _BRAIN_STATE["claude"],
            "fallback_calls": _BRAIN_STATE["fallback"],
            "llm_seconds": round(_BRAIN_STATE["llm_seconds"], 1),
            "budget_hit": _BRAIN_STATE["budget_hit"],
        }
    except Exception:  # noqa: BLE001
        pass
    return verdict, telemetry


def main() -> int:
    parser = argparse.ArgumentParser(description="Divan council as a CrewAI crew")
    parser.add_argument("question", help="the question to put to the council")
    args = parser.parse_args()

    verdict, telemetry = run(args.question)
    print(RESULT_BEGIN)
    print(json.dumps(
        {"verdict": verdict.model_dump() if verdict else None, "telemetry": telemetry},
        ensure_ascii=False, indent=2,
    ))
    print(RESULT_END)
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
