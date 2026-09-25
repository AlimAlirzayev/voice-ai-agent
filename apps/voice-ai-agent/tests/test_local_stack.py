"""The zero-cost stack: Claude CLI brain, BM25 citations, free Azerbaijani voice.

None of these tests touch the network or spawn the real CLI; they pin the
contracts the live council depends on when every paid key is absent.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import Settings
from app.rag.bm25 import BM25Retriever, az_lower, stems
from app.services.claude_cli import ClaudeCLIChat, ClaudeCLIError, render_transcript


# ------------------------------------------------------------------ settings
def test_auto_provider_falls_back_to_claude_when_no_key_but_the_cli_exists(monkeypatch):
    import app.core.config as config_module

    monkeypatch.setattr(config_module.shutil, "which", lambda _n: "/usr/local/bin/claude")
    s = Settings(LLM_PROVIDER="auto", OPENAI_API_KEY="", GROQ_API_KEY="", _env_file=None)
    assert s.chat_provider == "claude"
    assert s.chat_model == s.CLAUDE_MODEL
    monkeypatch.setattr(config_module.shutil, "which", lambda _n: None)
    assert s.chat_provider == "openai"  # the original no-key behaviour, unchanged


def test_explicit_claude_provider_survives_a_groq_key_meant_for_stt():
    s = Settings(LLM_PROVIDER="claude", GROQ_API_KEY="gsk_x", _env_file=None)
    assert s.chat_provider == "claude"


def test_tts_prefers_elevenlabs_then_edge_never_silence():
    assert Settings(ELEVENLABS_API_KEY="k", _env_file=None).tts_provider == "elevenlabs"
    assert Settings(ELEVENLABS_API_KEY="", OPENAI_API_KEY="", _env_file=None).tts_provider == "edge"
    assert Settings(TTS_PROVIDER="edge", ELEVENLABS_API_KEY="k", _env_file=None).tts_provider == "edge"


def test_every_member_has_a_distinct_edge_voice_setting():
    s = Settings(_env_file=None)
    members = ["nesreddin", "koroglu", "simurg", "nesimi", "dedeqorqud", "nizami"]
    settings_seen = {s.edge_voice_for(m) for m in members}
    assert len(settings_seen) == len(members)
    assert all(v[0].startswith("az-AZ-") for v in settings_seen)


# ------------------------------------------------------------------ narration
def test_narration_registers_cover_the_same_moments_and_product_has_no_jargon():
    from app.prompts.divan import _NARRATION

    course, product = _NARRATION["course"], _NARRATION["product"]
    assert set(course) == set(product) == {"opening", "routing", "hitl", "synthesis"}
    assert set(course["routing"]) == set(product["routing"])
    spoken = " ".join([product["opening"], product["hitl"], product["synthesis"], *product["routing"].values()]).lower()
    for word in ("langgraph", "supervisor", "interrupt", "synthesis", "human-in-the-loop", "mexanizm"):
        assert word not in spoken, word


# ------------------------------------------------------------------ composed reply
def test_reply_keeps_every_member_in_their_own_words_and_one_closing():
    from app.graph.builder import closing_of, compose_reply

    opinions = [
        {"advisor": "dedeqorqud", "name": "Dədə Qorqud", "text": "Qardaş qardaşa yağı olmaz. "},
        {"advisor": "nesreddin", "name": "Molla Nəsrəddin", "text": "Mirası bölərsən, qardaşı bölməzsən."},
    ]
    reply = compose_reply(opinions, " Əvvəl salamı ver, sonra malı böl. ")
    assert reply.startswith("Dədə Qorqud: Qardaş qardaşa yağı olmaz.")
    assert "\n\nMolla Nəsrəddin: Mirası bölərsən" in reply
    assert reply.endswith("Divanbəyi: Əvvəl salamı ver, sonra malı böl.")
    assert closing_of(reply) == "Əvvəl salamı ver, sonra malı böl."
    # one member alone: their voice, no closing, nothing to re-speak
    solo = compose_reply(opinions[:1], "")
    assert solo == "Dədə Qorqud: Qardaş qardaşa yağı olmaz." and closing_of(solo) == ""


def test_advisor_prompt_carries_the_council_rules_and_the_language_rule(monkeypatch):
    from app.core.config import settings
    from app.prompts.divan import DIVAN_QAYDALARI, advisor_prompt

    monkeypatch.setattr(settings, "REPLY_LANGUAGE", "az")
    p = advisor_prompt("dedeqorqud")
    assert DIVAN_QAYDALARI in p and "Həmişə Azərbaycan dilində" in p
    assert "Öz adını çəkmə" in p
    monkeypatch.setattr(settings, "REPLY_LANGUAGE", "user")
    assert "İstifadəçinin dilində" in advisor_prompt("nizami")


# ------------------------------------------------------------------ claude cli
def test_transcript_keeps_system_apart_and_labels_turns():
    system, transcript = render_transcript([
        SystemMessage(content="Sən Koroğlusan."),
        HumanMessage(content="Nə edim?"),
        AIMessage(content="Cəsarətli ol."),
        HumanMessage(content="Bəs sonra?"),
    ])
    assert system == "Sən Koroğlusan."
    assert transcript.startswith("User: Nə edim?\n\nAssistant: Cəsarətli ol.\n\nUser: Bəs sonra?")
    assert transcript.endswith("do not add a label.")


def test_cli_command_disables_tools_sessions_and_settings():
    cmd = ClaudeCLIChat(model="claude-x")._command("SYS")
    assert cmd[:2] == ["claude", "-p"]
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--no-session-persistence" in cmd and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-x"
    assert cmd[-2:] == ["--system-prompt", "SYS"]


def test_cli_json_is_parsed_and_errors_surface():
    llm = ClaudeCLIChat()
    payload = json.dumps({"result": "  Salam, oğul.  ", "usage": {"input_tokens": 3}, "duration_ms": 12}).encode()
    text, meta = llm._parse(payload, b"", 0)
    assert text == "Salam, oğul." and meta["usage"] == {"input_tokens": 3}
    with pytest.raises(ClaudeCLIError):
        llm._parse(json.dumps({"is_error": True, "result": "limit"}).encode(), b"", 0)
    with pytest.raises(ClaudeCLIError):
        llm._parse(b"not json", b"", 0)
    with pytest.raises(ClaudeCLIError):
        llm._parse(b"", b"boom", 1)


# ------------------------------------------------------------------ bm25
def test_azerbaijani_lowercasing_and_stems():
    assert az_lower("SIĞMAZAM İNSAN") == "sığmazam insan"
    # words of 3+ letters survive, cut to a 5-letter stem: "cahana" and "cahan" meet
    assert stems("Məndə sığar iki cahan, mən bu cahana sığmazam") == [
        "məndə", "sığar", "iki", "cahan", "mən", "cahan", "sığma",
    ]


@pytest.mark.asyncio
async def test_bm25_finds_the_known_passage_and_labels_it():
    chunks = [
        {"advisor": "nesimi", "work": "Divan", "ref": "qəzəl", "source": "vikimənbə",
         "text": "Məndə sığar iki cahan, mən bu cahana sığmazam"},
        {"advisor": "nesimi", "work": "Divan", "ref": "rübai", "source": "vikimənbə",
         "text": "Ey könül, sən bu dünyada nə axtarırsan"},
        {"advisor": "koroglu", "work": "Dastan", "ref": "qol 1", "source": "vikimənbə",
         "text": "Cahana sığmayan igid Koroğlu"},
    ]
    r = BM25Retriever(chunks)
    hits = await r.retrieve("nesimi", "cahana sığmazam")
    assert hits and hits[0]["ref"] == "qəzəl" and hits[0]["retrieval"] == "bm25"
    # a member never quotes another member's text, even when it matches better
    assert all(h["advisor"] == "nesimi" for h in hits)
    assert await r.retrieve("nizami", "cahana sığmazam") == []
    assert await r.retrieve("nesimi", "xx") == []
