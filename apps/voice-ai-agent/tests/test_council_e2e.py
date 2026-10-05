"""End to end over HTTP with the model, STT and TTS replaced by fakes: the
whole council path (routing -> advisors -> HITL -> memory -> voice segments)
runs for real, only the paid providers are scripted."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

import app.api.voice as voice_api
import app.graph.builder as builder
from app.core.config import settings
from app.evals.fakes import ScriptedCouncilModel
from app.graph import build_graph, run_turn
from app.main import app
from app.memory.sqlite import Checkpointer
from app.services.llm import LLMError
from app.services.voice import VoiceError


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    """Factory: `make_client(model)` -> a TestClient whose council uses `model`."""
    stack = []

    def _make(model, **settings_overrides):
        monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "c.sqlite"))
        monkeypatch.setattr(settings, "FEEDBACK_PATH", str(tmp_path / "f.sqlite"))
        for key, value in settings_overrides.items():
            monkeypatch.setattr(settings, key, value)
        monkeypatch.setattr(builder, "build_llm", lambda: model)
        client = TestClient(app)
        client.__enter__()
        stack.append(client)
        return client

    yield _make
    for client in stack:
        client.__exit__(None, None, None)


@pytest.fixture
def spoken(monkeypatch):
    """Replace STT/TTS; `spoken` records (text, advisor) for every synthesized clip."""
    clips: list[tuple[str, str | None]] = []

    async def fake_transcribe(audio, filename):
        return audio.decode()

    async def fake_synthesize(text, advisor=None):
        clips.append((text, advisor))
        return b"OGG", "audio/ogg", "fake"

    monkeypatch.setattr(voice_api, "transcribe", fake_transcribe)
    monkeypatch.setattr(voice_api, "synthesize", fake_synthesize)
    return clips


def _voice(client, text, thread="v1"):
    return client.post("/voice", files={"file": ("a.ogg", text.encode())}, data={"thread_id": thread})


# ---------------------------------------------------------------- chat
def test_chat_hitl_approve_edit_and_reject_over_http(make_client):
    # one router script per turn: Koroğlu, then the council is done (x3 threads)
    client = make_client(ScriptedCouncilModel(route=["KOROGLU", "YEKUN"] * 3, reply="Qalx, irəli get."))

    paused = client.post("/chat", json={"message": "Riskli addım atım?", "thread_id": "a"}).json()
    assert paused["status"] == "pending_approval"
    assert paused["approval"]["advisor_key"] == "koroglu"
    assert "Qalx, irəli get." in paused["approval"]["draft"]

    approved = client.post("/chat/resume", json={"thread_id": "a", "decision": "approve"}).json()
    assert approved["status"] == "ok" and "Qalx, irəli get." in approved["reply"]

    client.post("/chat", json={"message": "Yenə riskli?", "thread_id": "b"})
    edited = client.post("/chat/resume", json={"thread_id": "b", "decision": "edit", "text": "Əvvəlcə ağsaqqala danış."}).json()
    assert edited["reply"] == "Əvvəlcə ağsaqqala danış."

    client.post("/chat", json={"message": "Bir də riskli?", "thread_id": "c"})
    rejected = client.post("/chat/resume", json={"thread_id": "c", "decision": "reject"}).json()
    assert "Qalx" not in rejected["reply"]


def test_new_message_on_a_paused_thread_returns_the_pending_approval_not_a_new_run(make_client):
    model = ScriptedCouncilModel(route="KOROGLU")
    client = make_client(model)
    client.post("/chat", json={"message": "Riskli?", "thread_id": "p"})
    calls = model.router_calls
    again = client.post("/chat", json={"message": "Salam?", "thread_id": "p"}).json()
    assert again["status"] == "pending_approval"
    assert model.router_calls == calls  # the council was not consulted again


def test_two_advisors_speak_in_order_and_the_second_hears_the_first(make_client):
    model = ScriptedCouncilModel(route=["NESIMI", "NIZAMI"], reply="Söz.")
    client = make_client(model)
    body = client.post("/chat", json={"message": "Sevgidə özümü itirirəm", "thread_id": "two"}).json()
    assert body["consulted"] == ["nesimi", "nizami"]
    assert body["reply"].index("Nəsimi:") < body["reply"].index("Nizami Gəncəvi:")
    assert "Sənin xaricində" not in body["reply"]
    assert "Səndən əvvəl məclisdə bu söz deyildi" in model.advisor_systems[1]
    assert "Səndən əvvəl məclisdə bu söz deyildi" not in model.advisor_systems[0]


def test_council_never_exceeds_two_advisors(make_client):
    model = ScriptedCouncilModel(route=["NESIMI", "NIZAMI", "SIMURG", "KOROGLU"])
    client = make_client(model)
    body = client.post("/chat", json={"message": "Çox mövzulu sual", "thread_id": "cap"}).json()
    assert len(body["consulted"]) == 2


def test_llm_failure_is_a_clean_503(make_client):
    class Broken:
        async def ainvoke(self, messages):
            raise LLMError("the model is down")

    client = make_client(Broken())
    r = client.post("/chat", json={"message": "Salam", "thread_id": "x"})
    assert r.status_code == 503 and r.json()["detail"] == "the model is down"


# ---------------------------------------------------------------- voice
def test_voice_round_trip_speaks_each_member_in_their_own_voice(make_client, spoken):
    client = make_client(ScriptedCouncilModel(route=["NESIMI", "NIZAMI"], reply="Bir söz."))
    body = _voice(client, "Sevgidə özümü itirirəm").json()
    assert body["transcript"] == "Sevgidə özümü itirirəm"
    voices = [(s["advisor"], s["name"]) for s in body["segments"]]
    assert voices[0] == ("", "Divanbəyi")  # narration opens
    assert [a for a, _ in voices if a] == ["nesimi", "nizami"]
    assert {advisor for _, advisor in spoken if advisor} == {"nesimi", "nizami"}
    assert body["audio_base64"] == body["segments"][-1]["audio_base64"]  # back-compat field


def test_voice_hitl_pause_then_resume_speaks_the_final_answer(make_client, spoken):
    client = make_client(ScriptedCouncilModel(route="KOROGLU", reply="İrəli addımla."))
    paused = _voice(client, "Riskli addım atım?", "vh").json()
    assert paused["status"] == "pending_approval"
    assert any("İrəli addımla." in text and advisor == "koroglu" for text, advisor in spoken)  # the draft, in Koroğlu's voice

    spoken.clear()
    resumed = client.post("/voice/resume", data={"thread_id": "vh", "decision": "approve"}).json()
    assert resumed["status"] == "ok"
    assert any(advisor == "koroglu" for _, advisor in spoken)


def test_voice_error_mapping(make_client, monkeypatch):
    client = make_client(ScriptedCouncilModel())

    async def deaf(audio, filename):
        raise VoiceError("bad audio")

    async def silent(audio, filename):
        return ""

    monkeypatch.setattr(voice_api, "transcribe", deaf)
    assert _voice(client, "x").status_code == 400
    monkeypatch.setattr(voice_api, "transcribe", silent)
    assert _voice(client, "x").status_code == 422

    async def hear(audio, filename):
        return "Salam"

    async def mute(text, advisor=None):
        raise VoiceError("tts down")

    monkeypatch.setattr(voice_api, "transcribe", hear)
    monkeypatch.setattr(voice_api, "synthesize", mute)
    assert _voice(client, "x").status_code == 502


# ---------------------------------------------------------------- memory
async def test_memory_survives_a_restart_and_threads_stay_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "mem.sqlite"))
    model = ScriptedCouncilModel(route="YEKUN")

    first = Checkpointer()
    graph = build_graph(await first.open(), model)
    await run_turn(graph, "Mənim adım Alimdir.", "alice")
    await run_turn(graph, "Salam", "bob")
    await first.close()

    second = Checkpointer()  # a new process, same file
    graph = build_graph(await second.open(), model)
    state = await graph.aget_state({"configurable": {"thread_id": "alice"}})
    texts = [m.content for m in state.values["messages"] if isinstance(m, HumanMessage)]
    assert texts == ["Mənim adım Alimdir."]
    result = await run_turn(graph, "Adım nədir?", "alice")
    assert result.history_length == 4
    bob = await graph.aget_state({"configurable": {"thread_id": "bob"}})
    assert all("Alim" not in m.content for m in bob.values["messages"])
    await second.close()


async def test_history_is_trimmed_to_the_configured_window(monkeypatch):
    monkeypatch.setattr(settings, "MAX_HISTORY_MESSAGES", 4)
    graph = build_graph(InMemorySaver(), ScriptedCouncilModel(route="YEKUN"))
    last = None
    for i in range(6):
        last = await run_turn(graph, f"sual {i}", "trim")
    assert last.history_length <= 4
    state = await graph.aget_state({"configurable": {"thread_id": "trim"}})
    assert "sual 5" in [m.content for m in state.values["messages"]]


async def test_per_turn_scratch_does_not_leak_into_the_next_turn():
    graph = build_graph(InMemorySaver(), ScriptedCouncilModel(route=["NESIMI", "YEKUN"]))
    first = await run_turn(graph, "Dəyərsizəm", "leak")
    assert first.consulted == ["nesimi"]
    second = await run_turn(graph, "Sağ ol", "leak")  # router: YEKUN
    assert second.consulted == [] and second.citations == []
