"""d02: fewer model calls, parallel TTS, streaming - all with scripted fakes."""

import asyncio
import json
import time

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.api.voice as voice_api
from app.core.config import settings
from app.evals import latency
from app.evals.fakes import ScriptedCouncilModel
from app.graph import TurnResult, build_graph, run_turn, stream_turn
from app.graph.builder import resolve_routes
from app.services.voice import VoiceError
from tests.test_council_e2e import _voice


class Counting(ScriptedCouncilModel):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return await super().ainvoke(messages)


def sse(text: str) -> list[tuple[str, object]]:
    frames = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n")
        frames.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return frames


# ---------------------------------------------------------------- B1: model calls
@pytest.mark.parametrize(
    "route, calls, consulted",
    [
        ("YEKUN", 2, []),                       # router + host greeting
        ("NESIMI", 2, ["nesimi"]),              # router + 1 advisor
        ("NESIMI NIZAMI", 3, ["nesimi", "nizami"]),
        ("NESIMI NIZAMI SIMURG", 3, ["nesimi", "nizami"]),  # capped at two members
    ],
)
async def test_single_call_routing_model_calls(route, calls, consulted):
    model = Counting(route=route)
    result = await run_turn(build_graph(InMemorySaver(), model), "Sevgidə özümü itirirəm", "calls")
    assert (model.calls, result.consulted) == (calls, consulted)
    assert model.router_calls == 1  # the router is never asked a second time


@pytest.mark.parametrize("route, calls", [(["NESIMI", "YEKUN"], 3), (["NESIMI", "NIZAMI"], 4)])
async def test_iterative_routing_is_kept_as_a_rollback(monkeypatch, route, calls):
    monkeypatch.setattr(settings, "COUNCIL_ROUTING", "iterative")
    model = Counting(route=route)
    await run_turn(build_graph(InMemorySaver(), model), "Sevgidə özümü itirirəm", "calls")
    assert model.calls == calls


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("NESIMI", ["nesimi"]),
        ("NESIMI NIZAMI", ["nesimi", "nizami"]),
        ("Koroğlu, Simurğ", ["koroglu", "simurg"]),
        ("NESIMI + NIZAMI", ["nesimi", "nizami"]),
        ("NESIMI NESIMI", ["nesimi"]),                      # no repeats
        ("NESIMI və NIZAMI", ["nesimi"]),                   # only a directly following name counts
        ("Mən deyirəm NESIMI NIZAMI", []),                  # first word rule
        ("YEKUN", []),
        ("", []),
    ],
)
def test_resolve_routes(raw, expected):
    assert resolve_routes(raw, ["koroglu", "simurg", "nesimi", "nizami"]) == expected


async def test_plan_does_not_leak_into_the_next_turn():
    graph = build_graph(InMemorySaver(), ScriptedCouncilModel(route=["NESIMI NIZAMI", "YEKUN"]))
    await run_turn(graph, "bir", "leak")
    second = await run_turn(graph, "Sağ ol", "leak")
    assert second.consulted == []


# ---------------------------------------------------------------- B2: parallel TTS
def _result(n_opinions=3) -> TurnResult:
    names = [("nesimi", "Nəsimi"), ("nizami", "Nizami Gəncəvi"), ("simurg", "Simurğ")][:n_opinions]
    opinions = [{"advisor": k, "name": n, "text": f"söz {k}"} for k, n in names]
    return TurnResult(status="ok", reply="x", history_length=1, consulted=[k for k, _ in names],
                      opinions=opinions, narration=["Divanbəyi dinləyir."])


@pytest.fixture
def slow_tts(monkeypatch):
    log = {"in_flight": 0, "peak": 0, "started": []}

    async def synth(text, advisor=None):
        log["started"].append((text, time.perf_counter()))
        log["in_flight"] += 1
        log["peak"] = max(log["peak"], log["in_flight"])
        await asyncio.sleep(0.2)
        log["in_flight"] -= 1
        return text.encode(), "audio/ogg", "fake"

    monkeypatch.setattr(voice_api, "synthesize", synth)
    return log


async def test_four_segments_are_synthesized_in_parallel_and_stay_in_order(slow_tts):
    start = time.perf_counter()
    segments = await voice_api._speak_segments(_result(3))  # narration + 3 members
    elapsed = time.perf_counter() - start
    assert len(segments) == 4 and elapsed < 0.5  # serial would be 0.8 s
    assert [s.name for s in segments] == ["Divanbəyi", "Nəsimi", "Nizami Gəncəvi", "Simurğ"]
    assert [s.advisor for s in segments] == ["", "nesimi", "nizami", "simurg"]


async def test_tts_concurrency_is_bounded_and_one_means_serial(slow_tts, monkeypatch):
    monkeypatch.setattr(settings, "TTS_CONCURRENCY", 2)
    await voice_api._speak_segments(_result(3))
    assert slow_tts["peak"] == 2

    monkeypatch.setattr(settings, "TTS_CONCURRENCY", 1)
    slow_tts["peak"] = 0
    start = time.perf_counter()
    await voice_api._speak_segments(_result(3))
    assert slow_tts["peak"] == 1 and time.perf_counter() - start >= 0.8


async def test_a_failing_clip_fails_the_reply_and_cancels_the_rest(monkeypatch):
    done = []

    async def synth(text, advisor=None):
        if advisor == "nizami":
            raise VoiceError("tts down")
        await asyncio.sleep(0.3)
        done.append(text)
        return b"x", "audio/ogg", "fake"

    monkeypatch.setattr(voice_api, "synthesize", synth)
    with pytest.raises(VoiceError):
        await voice_api._speak_segments(_result(3))
    await asyncio.sleep(0.4)
    assert done == []  # the other clips were cancelled, not left running


def test_voice_endpoint_still_answers_502_when_a_clip_fails(make_client, monkeypatch):
    async def stt(audio, filename):
        return audio.decode()

    async def synth(text, advisor=None):
        raise VoiceError("tts down")

    monkeypatch.setattr(voice_api, "transcribe", stt)
    monkeypatch.setattr(voice_api, "synthesize", synth)
    client = make_client(ScriptedCouncilModel(route="NESIMI NIZAMI"))
    assert _voice(client, "salam").status_code == 502


# ---------------------------------------------------------------- B5: streaming
async def test_stream_turn_yields_members_as_they_finish_and_ends_with_the_result():
    graph = build_graph(InMemorySaver(), ScriptedCouncilModel(route="NESIMI NIZAMI"))
    events = [e async for e in stream_turn(graph, "Sevgidə özümü itirirəm", "s1")]
    kinds = [k for k, _ in events]
    assert kinds[0] == "narration" and kinds[-1] == "result"
    assert [v["advisor"] for k, v in events if k == "opinion"] == ["nesimi", "nizami"]
    # streamed narration is exactly the narration of the final result
    assert [v for k, v in events if k == "narration"] == events[-1][1].narration
    # and the result matches what the non-streaming path produces
    plain = await run_turn(build_graph(InMemorySaver(), ScriptedCouncilModel(route="NESIMI NIZAMI")),
                           "Sevgidə özümü itirirəm", "s2")
    assert events[-1][1].reply == plain.reply


async def test_stream_turn_reports_the_hitl_pause_and_the_crisis_path():
    graph = build_graph(InMemorySaver(), ScriptedCouncilModel(route="KOROGLU"))
    last = [e async for e in stream_turn(graph, "Riskli addım atım?", "s3")][-1][1]
    assert last.status == "pending_approval" and last.approval["advisor_key"] == "koroglu"

    crisis = [e async for e in stream_turn(graph, "özümü öldürmək istəyirəm", "s4")]
    assert [k for k, _ in crisis] == ["result"] and crisis[0][1].consulted == []


async def test_first_streamed_event_arrives_before_a_quarter_of_the_turn():
    report = await latency.measure_stream(0.2)
    row = report["single_call"]
    assert row["first_event_seconds"] < 0.25 * row["total_seconds"]


def _strip(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "turn_id"}


def test_chat_stream_done_is_byte_identical_to_chat(make_client):
    client = make_client(ScriptedCouncilModel(route=["NESIMI NIZAMI"] * 2))
    plain = client.post("/chat", json={"message": "Sevgidə özümü itirirəm", "thread_id": "a"}).json()
    r = client.post("/chat/stream", json={"message": "Sevgidə özümü itirirəm", "thread_id": "b"})
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = sse(r.text)
    names = [n for n, _ in frames]
    assert names[-1] == "done" and names.count("opinion") == 2 and "narration" in names
    done = dict(frames[-1][1], thread_id="a")
    assert _strip(done) == _strip(plain)
    assert [d["advisor"] for n, d in frames if n == "opinion"] == ["nesimi", "nizami"]


def test_chat_stream_pause_resume_and_errors(make_client):
    client = make_client(ScriptedCouncilModel(route=["KOROGLU"] * 2, reply="Qalx."))
    frames = sse(client.post("/chat/stream", json={"message": "Riskli?", "thread_id": "p"}).text)
    assert frames[-1][0] == "done" and frames[-1][1]["status"] == "pending_approval"
    # a second message on the paused thread returns the pause, no new run
    again = sse(client.post("/chat/stream", json={"message": "Salam", "thread_id": "p"}).text)
    assert [n for n, _ in again] == ["done"] and again[0][1]["status"] == "pending_approval"
    # the existing resume route settles it
    assert client.post("/chat/resume", json={"thread_id": "p", "decision": "approve"}).json()["status"] == "ok"

    class Broken:
        async def ainvoke(self, messages):
            from app.services.llm import LLMError
            raise LLMError("the model is down")

    broken = make_client(Broken())
    frames = sse(broken.post("/chat/stream", json={"message": "Salam", "thread_id": "x"}).text)
    assert frames[-1] == ("error", {"status": 503, "detail": "the model is down"})
    assert client.post("/chat/stream", json={"message": "", "thread_id": "x"}).status_code == 422


def test_voice_stream_done_matches_voice_and_clips_are_not_synthesized_twice(make_client, spoken):
    client = make_client(ScriptedCouncilModel(route=["NESIMI NIZAMI"] * 2, reply="Bir söz."))
    plain = _voice(client, "Sevgidə özümü itirirəm", thread="v1").json()
    spoken.clear()
    r = client.post("/voice/stream", files={"file": ("a.ogg", "Sevgidə özümü itirirəm".encode())},
                    data={"thread_id": "v2"})
    frames = sse(r.text)
    names = [n for n, _ in frames]
    assert names[0] == "transcript" and names[-1] == "done"
    assert names.count("segment") == len(plain["segments"]) == len(spoken)
    done = dict(frames[-1][1], thread_id="v1")
    assert _strip(done) == _strip(plain)
    assert [d["name"] for n, d in frames if n == "segment"].count("Nəsimi") == 1


def test_voice_stream_stt_errors_are_plain_http_errors(make_client, spoken):
    client = make_client(ScriptedCouncilModel(route="YEKUN"))
    r = client.post("/voice/stream", files={"file": ("a.ogg", b"")}, data={"thread_id": "v"})
    assert r.status_code == 422  # same as /voice: no speech detected


def test_voice_stream_starts_a_members_tts_while_the_next_one_is_writing(make_client, monkeypatch):
    t0 = time.perf_counter()
    stamps = {}

    class Slow(ScriptedCouncilModel):
        async def ainvoke(self, messages):
            out = await super().ainvoke(messages)
            await asyncio.sleep(0.3)
            stamps.setdefault("model_done", []).append(time.perf_counter() - t0)
            return out

    async def stt(audio, filename):
        return audio.decode()

    async def synth(text, advisor=None):
        stamps.setdefault("tts_start", {})[advisor] = time.perf_counter() - t0
        await asyncio.sleep(0.3)
        return b"x", "audio/ogg", "fake"

    monkeypatch.setattr(voice_api, "transcribe", stt)
    monkeypatch.setattr(voice_api, "synthesize", synth)
    client = make_client(Slow(route="NESIMI NIZAMI"))
    sse(client.post("/voice/stream", files={"file": ("a.ogg", b"salam")}, data={"thread_id": "v"}).text)
    router, first, second = stamps["model_done"]
    assert stamps["tts_start"]["nesimi"] < second  # started before member 2 finished writing


# ---------------------------------------------------------------- harness
async def test_latency_harness_structure_holds():
    report = await latency.run(0.02)
    assert report["misses"] == []
    assert report["calls"]["one_member"]["iterative"]["calls"] == 3
    assert report["calls"]["one_member"]["single_call"]["calls"] == 2
