# Divan on the VPS — zero-cost stack (2026-09-25)

The DigitalOcean droplet is gone; the council runs inside our own server as a
systemd service. Every paid key was dead on the day this was built (OpenAI 429,
Gemini 402, ElevenLabs 401), so the stack was rebuilt around what costs nothing
and is measured to work — without touching the LangGraph graph itself.

| Organ | Was | Now | Where |
|---|---|---|---|
| Brain (all members + Divanbəyi) | OpenAI `gpt-4.1-mini` / Groq Llama | **Claude** through the operator's subscription (`claude -p`, one stateless child per call, no tools/MCP/CLAUDE.md) | `app/services/claude_cli.py`, `LLM_PROVIDER=claude` |
| Citations | OpenAI embeddings index | **BM25** over the same `ingest.collect_chunks()` corpus, per member, `retrieval: "bm25"` on every hit | `app/rag/bm25.py`, `RAG_BACKEND=auto` |
| Speech → text | OpenAI Whisper | **Groq `whisper-large-v3`** (OpenAI-compatible endpoint, `language="az"` kept) | `STT_BASE_URL`, `STT_API_KEY`, `STT_MODEL` |
| Text → speech | ElevenLabs v3 (dead key) | **Microsoft neural Azerbaijani** (`edge-tts`: Babek/Banu, per-member pace and pitch) → ffmpeg → OGG/Opus | `app/services/voice.py::_edge_tts`, `settings.edge_voice_for` |
| Moderation | OpenAI omni-moderation | off (no key); the deterministic `graph/guardrails.py` stays | `MODERATION_ENABLED=false` |

Provider order is a setting, not a rewrite: when an ElevenLabs key appears in
`.env` the members get their designed voices again; when an OpenAI key appears
the embedding index is used again. Nothing else changes.

## Run

```bash
cd /opt/divan/apps/voice-ai-agent
uv sync --extra dev && uv pip install edge-tts      # once
cp .env.example .env                                 # then set LLM_PROVIDER=claude, GROQ key for STT
.venv/bin/python -m pytest -q                        # 88 tests, no network, no CLI
systemctl enable --now divan                         # /etc/systemd/system/divan.service → 127.0.0.1:8940
```

From a laptop: `ssh -f -N -L 8940:127.0.0.1:8940 hetzner-agents` → http://127.0.0.1:8940/demo
(`kurs-demo`-style helper: `divan-demo` on the Mac).

Health: `curl 127.0.0.1:8940/` → `llm: claude-fable-5-1`, `stt: whisper-large-v3`, `tts: edge`.

## Measured

- One question, two members consulted, four citations: **37 s** wall (Claude ×4).
- TTS: 6–8 s of speech in 1.0–1.5 s, OGG/Opus, no key.
- Tests: 79 → 88 (new: provider selection, CLI transcript/command/parse contracts, BM25 known-answer, per-member voice settings).
- Tests are isolated from the live `.env` (`tests/conftest.py`): measured once that a real `.env` on the box made a test post fake audio to Groq.

## Quality audit

```bash
.venv/bin/python -m app.evals.audit --out output/audit.html --json output/audit.json
```

20 known-answer questions (3 per member + 2 edge cases). Deterministic checks decide
pass/fail: routing, Turkish/colloquial loans, Cyrillic, missing «ə», machine vocabulary,
sentence count, markdown/emoji, citation debris. A separate Claude call in the role of
a strict Azerbaijani philologist scores character / mentality / language / literary
style / usefulness 1–5 with named defects. The report is HTML; the builder does not
grade its own output by hand.

## Known limits (decisions, not bugs)

- Two Azerbaijani timbres exist for free; six distinct voices need an ElevenLabs key.
- The demo page has one (dark) theme by design.
- The Vikimənbə corpus carries OCR/apparatus debris in some chunks (page marks, digits) — the
  audit counts it per citation; cleaning the corpus is a separate pass.
