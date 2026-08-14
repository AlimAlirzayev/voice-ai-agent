# Architecture landscape notes (researched 2026-08-14)

Time-sensitive: re-verify vendors/prices before committing. The patterns are durable.

## Agentic RAG (Phase 2 design basis)

LangGraph's official agentic-RAG pattern (docs.langchain.com/oss/python/langgraph/agentic-rag):
retrieval is a **tool** the model may call, not a fixed pre-step. Loop:
`generate_query_or_respond → retrieve (tool) → grade_documents → (relevant? answer :
rewrite_question → retry)`. Fits Divan as a per-advisor subgraph: each council member
gets its own corpus (public-domain: Xəmsə, Kitabi-Dədə Qorqud, Koroğlu dastanı,
Nəsimi divanı, Molla Nəsrəddin lətifələri, Məntiqüt-Teyr) and answers with citations.

Citation grounding practice: a citation is a verifiable link from a claim to the
supporting passage — "the receipt"; grounding happens at retrieval/prompt-assembly
time. Watch for citation-shaped hallucinations (quotes/links present, claim
unsupported); test citation faithfulness explicitly in evals.

Vector RAG vs knowledge graph (Alim asked): start vector (chunk+embed, easy, gives
citations); GraphRAG (entities/relations: Koroğlu—Çənlibel—Alı kişi) is a Phase 2.5
add-on for multi-hop relation questions — build it ON TOP of working vector RAG,
never instead.

## Eval discipline (2026 state)

LangChain State of Agent Engineering: 89% of production-agent teams have
observability, only 52% have evals — the gap is where quality dies. Converging
practice: fast checks on every PR + nightly LLM-as-judge regressions + online checks
on production traces. Divan already has the offline golden suite + LangSmith; add
LLM-as-judge tier and groundedness/citation-faithfulness checks in Phase 3.

## Talking-avatar landscape (Phase 5)

Two vendor classes — the decision that matters:
1. **Full-stack avatar platforms** (do their own TTS): HeyGen LiveAvatar (realism,
   175+ languages, ~1–2 s), Tavus Phoenix-4 (real-time leader: <600 ms, full-duplex,
   WebRTC), D-ID (cheap fast clips from one photo).
2. **Audio-in avatar layers** (accept YOUR audio): Simli-type speech-to-video APIs.

Divan's moat is the native cloned AZ voice, so the avatar layer MUST accept our audio
stream — class 2 (or class-1 vendors in audio-passthrough mode). First "shock demo"
cheaply: generated historical portrait + our native v3/cloned audio → D-ID-style
offline clip = museum-screen feel from one video.

Style depth (Zəngin vision): few-shot + RAG first; SFT/LoRA on the literary corpus
later, trained on rented GPU (never the CPU-only VPS).

## Sources

- https://docs.langchain.com/oss/python/langgraph/agentic-rag
- https://www.langchain.com/state-of-agent-engineering
- https://app.ailog.fr/en/blog/guides/citation-sourcing-rag
- https://www.toughtongueai.com/blog/best-virtual-avatar-solutions-2026
- https://www.docket.io/blog/heygen-vs-tavus-vs-anam-vs-simli-how-we-chose-dockets-ai-avatar-provider
- https://www.d-id.com/blog/best-tavus-alternatives-real-time-ai-avatars/
