"""Offline latency harness: model calls and wall time with scripted fakes.

    python -m app.evals.latency [--delay 0.2] [--json out.json]

No network, no keys. Every model call sleeps `--delay` seconds and every TTS
clip sleeps the same, so wall time is (sequential steps) x delay and a change
in the *shape* of the graph shows up directly. It measures structure, not
provider speed: multiply the call counts by the live per-call time (about
20 s with the Claude CLI) to project a live turn.

Reported, "before" (`COUNCIL_ROUTING=iterative`, `TTS_CONCURRENCY=1`) against
"after" (the defaults):

  calls    model calls per turn for a greeting, a one-member and a two-member turn
  tts      wall time to synthesize the clips of a two-member reply
  stream   time to the first streamed event / first member's words vs the whole turn

Exit code 1 when a structural expectation is missed (see `check`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from langgraph.checkpoint.memory import InMemorySaver

import app.api.voice as voice_api
from app.core.config import settings
from app.evals.fakes import ScriptedCouncilModel
from app.graph import build_graph, run_turn, stream_turn

# (scenario, router script in each mode, expected model calls (before, after))
SCENARIOS = {
    "greeting": {"iterative": "YEKUN", "single_call": "YEKUN", "calls": (2, 2)},
    "one_member": {"iterative": ["NESIMI", "YEKUN"], "single_call": "NESIMI", "calls": (3, 2)},
    "two_members": {"iterative": ["NESIMI", "NIZAMI"], "single_call": "NESIMI NIZAMI", "calls": (4, 3)},
}


class TimedModel(ScriptedCouncilModel):
    """The scripted council model with a fixed latency per call and a call count."""

    def __init__(self, delay: float, **kwargs):
        super().__init__(**kwargs)
        self.delay = delay
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return await super().ainvoke(messages)


class _Settings:
    """Set `settings` fields for a block and restore them after."""

    def __init__(self, **values):
        self.values, self.saved = values, {}

    def __enter__(self):
        for key, value in self.values.items():
            self.saved[key] = getattr(settings, key)
            setattr(settings, key, value)

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            setattr(settings, key, value)


async def measure_calls(delay: float) -> dict:
    out = {}
    for name, spec in SCENARIOS.items():
        row = {}
        for mode in ("iterative", "single_call"):
            with _Settings(COUNCIL_ROUTING=mode):
                model = TimedModel(delay, route=spec[mode])
                graph = build_graph(InMemorySaver(), model)
                start = time.perf_counter()
                result = await run_turn(graph, "Sevgidə özümü itirirəm", f"lat-{name}-{mode}")
                row[mode] = {"calls": model.calls, "seconds": round(time.perf_counter() - start, 3),
                             "consulted": result.consulted}
        out[name] = row
    return out


async def measure_tts(delay: float) -> dict:
    async def fake_synthesize(text, advisor=None):
        await asyncio.sleep(delay)
        return b"OGG", "audio/ogg", "fake"

    real, voice_api.synthesize = voice_api.synthesize, fake_synthesize
    try:
        model = ScriptedCouncilModel(route="NESIMI NIZAMI")
        result = await run_turn(build_graph(InMemorySaver(), model), "Sevgidə özümü itirirəm", "lat-tts")
        out = {}
        for label, conc in (("serial", 1), ("parallel", settings.TTS_CONCURRENCY)):
            with _Settings(TTS_CONCURRENCY=conc):
                start = time.perf_counter()
                segments = await voice_api._speak_segments(result)
                out[label] = {"segments": len(segments), "seconds": round(time.perf_counter() - start, 3),
                              "order": [s.name for s in segments]}
        return out
    finally:
        voice_api.synthesize = real


async def measure_stream(delay: float) -> dict:
    out = {}
    for mode in ("iterative", "single_call"):
        with _Settings(COUNCIL_ROUTING=mode):
            route = SCENARIOS["two_members"][mode]
            graph = build_graph(InMemorySaver(), TimedModel(delay, route=route))
            start = time.perf_counter()
            first = first_opinion = None
            async for kind, _ in stream_turn(graph, "Sevgidə özümü itirirəm", f"lat-st-{mode}"):
                now = time.perf_counter() - start
                first = now if first is None else first
                first_opinion = now if first_opinion is None and kind == "opinion" else first_opinion
            total = time.perf_counter() - start
            out[mode] = {"first_event_seconds": round(first, 3),
                         "first_opinion_seconds": round(first_opinion, 3), "total_seconds": round(total, 3)}
    # A non-streaming client sees nothing until `total`.
    return out


def check(report: dict) -> list[str]:
    misses = []
    for name, spec in SCENARIOS.items():
        for mode, want in zip(("iterative", "single_call"), spec["calls"]):
            got = report["calls"][name][mode]["calls"]
            if got != want:
                misses.append(f"{name}/{mode}: {got} model calls, expected {want}")
    tts = report["tts"]
    if tts["parallel"]["order"] != tts["serial"]["order"]:
        misses.append("parallel TTS changed the segment order")
    if not tts["parallel"]["seconds"] < 0.75 * tts["serial"]["seconds"]:
        misses.append("parallel TTS is not faster than serial")
    st = report["stream"]["single_call"]
    if not st["first_event_seconds"] < 0.25 * st["total_seconds"]:
        misses.append("first streamed event came after 25% of the turn")
    return misses


async def run(delay: float) -> dict:
    report = {"delay_seconds": delay, "calls": await measure_calls(delay), "tts": await measure_tts(delay),
              "stream": await measure_stream(delay)}
    report["misses"] = check(report)
    return report


def print_report(report: dict) -> None:
    print(f"per-call and per-clip latency: {report['delay_seconds']}s (fake)\n")
    print(f"{'scenario':<12}{'calls before':>13}{'calls after':>12}{'secs before':>12}{'secs after':>11}")
    for name, row in report["calls"].items():
        b, a = row["iterative"], row["single_call"]
        print(f"{name:<12}{b['calls']:>13}{a['calls']:>12}{b['seconds']:>12}{a['seconds']:>11}")
    tts = report["tts"]
    print(f"\ntts, {tts['serial']['segments']} clips: serial {tts['serial']['seconds']}s, "
          f"parallel {tts['parallel']['seconds']}s")
    for mode, row in report["stream"].items():
        print(f"stream/{mode}: first event {row['first_event_seconds']}s, first member's words "
              f"{row['first_opinion_seconds']}s, whole turn {row['total_seconds']}s")
    print("\n" + ("STRUCTURE OK" if not report["misses"] else "MISSES:\n  " + "\n  ".join(report["misses"])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--json")
    args = parser.parse_args()
    report = asyncio.run(run(args.delay))
    print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    return 1 if report["misses"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
