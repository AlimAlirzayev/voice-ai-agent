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

## Audit results (same 20 questions, same judge, 2026-09-25)

| | v1 (as found) | v2 | v4 (delivered) |
|---|---|---|---|
| Deterministic pass | 18/20 | 8/20 | **19/20** |
| Judge: character | 1.95 | 3.11 | **3.53** |
| Judge: mentality/values | 2.84 | 3.84 | **4.00** |
| Judge: language | 3.26 | 3.37 | **3.58** |
| Judge: literary style | 2.47 | 3.26 | **3.47** |
| Judge: usefulness | 2.58 | 3.84 | **3.42** |
| Nəsrəddin as 2nd voice | 16 | 17 | **1** |
| Turkish question answered in | Turkish | Azerbaijani | Azerbaijani |

What moved the numbers, in order of effect:
1. **Routing defect in the original graph** (not a model habit): on the second hop the
   router never saw who had spoken, repeated its first pick, and the fallback
   `remaining[0]` then summoned the first roster key — Molla Nəsrəddin — on 17 of 18
   questions. The router now sees the speakers; an unusable answer ends the council.
2. **Voices kept, not merged**: the old synthesis step blended two members into one
   nameless paragraph. Members now speak under their own names; no summary on top
   (v2 showed a closing line only repeated them).
3. **Council rules + authentic anchors** per member (values, calque list, no invented
   folklore, per-member address). The Dədə Qorqud blessing was checked word by word
   against the corpus; two lines the builder first wrote were not in it and were removed.
4. **Operational**: the CLI self-update window (FileNotFoundError) is waited out; an
   exhausted subscription window returns a polite Azerbaijani 503 instead of a 500.

Open, measured, not fixed here: 12 of 56 citations still carry Vikimənbə OCR/apparatus
debris (page marks, digits) — cleaning the corpus is its own pass. The judge is one
Claude call per answer; it is a graded opinion, not a native-speaker panel.
