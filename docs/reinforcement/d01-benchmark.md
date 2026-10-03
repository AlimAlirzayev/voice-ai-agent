# Divan — benchmark against current practice (d01)

Labels: **VERIFIED** = read in a source cited here during this work. **INFERRED** = reasoned from verified facts plus the repo. **UNKNOWN** = not established. Sources were retrieved by web search on 2026-10-03; search summaries, not full pages, were read, so claims are limited to what those summaries state.

## 1. Multi-agent topology (LangGraph)

| Practice | Divan today | Gap | Label |
|---|---|---|---|
| Supervisor: one agent talks to the user, delegates, control returns to it; makes few assumptions about sub-agents. Swarm: any agent talks to the user and hands off, each agent must know the others. | Supervisor with six personas, router is one LLM call, personas answer in their own voice. | Right choice for a roster the product controls and a single moderated entry point (crisis bypass, approval). Swarm would let personas address the user directly, which the product already simulates by composing their words. | VERIFIED ([LangChain benchmark post](https://www.langchain.com/blog/benchmarking-multi-agent-architectures)) |
| The same post benchmarks supervisor against swarm designs on a multi-agent task set. The swarm variant avoids the "translation" round trip through the supervisor. | Divan's supervisor is consulted twice per single-advisor turn (A4 in the audit). | Cost, not correctness: skip the second router call when the first answer is single-domain, or route to one persona by default. | VERIFIED that the benchmark exists; the specific numbers were not read (**UNKNOWN**). |

## 2. Interrupts, checkpointing, durable execution

| Practice | Divan today | Gap | Label |
|---|---|---|---|
| `interrupt()` surfaces a JSON value under `__interrupt__`, state is saved by the checkpointer, execution waits indefinitely; use a persistent, database-backed checkpointer in production; `thread_id` is the persistent cursor. ([LangGraph human-in-the-loop](https://docs.langchain.com/oss/python/langgraph/human-in-the-loop), [interrupts](https://docs.langchain.com/oss/langgraph/interrupts)) | Matches: `interrupt()` in `approval_gate`, SQLite checkpointer, thread id per chat. | Cursor ownership: any caller who knows a thread id can resume it (audit M1/H1). Wait is indefinite by design, so an abandoned pause blocks the chat (H3). | VERIFIED |
| Resume validity and decision schema are the application's job. | Was fail-open and replay-prone; fixed in d01 (409, closed decision set, fail-closed gate). | Closed. | VERIFIED (docs describe resume; the defects were measured locally). |
| Streaming (`astream`) to surface node progress and tokens. | Not used; the "narration" lines are returned after the whole run. | Sending narration and partial text as they happen would turn a 60 s wait into visible progress. | INFERRED (LangGraph streaming is a documented capability; its details were not fetched). |

## 3. Voice agent stack

Cited figures come from vendor and consultancy blogs, so treat them as industry claims, not measurements: [Twig latency budget](https://www.twig.so/blog/voice-ai-agents-latency-budget-800ms), [Retell](https://www.retellai.com/blog/how-real-time-voice-ai-actually-works), [Deepgram pipeline design](https://deepgram.com/learn/voice-agent-architecture-stt-llm-tts-pipeline-design), [Simba](https://simbavoice.ai/resources/the-engineering-behind-sub-second-voice-agents).

| Practice (as reported) | Divan today | Gap | Label |
|---|---|---|---|
| Whole loop under ~700–800 ms feels human; sub-1 s is table stakes in 2026. Budget: STT 50–150 ms, LLM 100–400 ms, TTS 100–250 ms. | Text turn ≈ 60 s measured (audit v5); voice adds whole-file Whisper and serial TTS. | Two orders of magnitude from the conversational target. The product is a council of long, literary replies, not a phone agent, so the right target is "first audible word within a few seconds", not 800 ms. | VERIFIED (claims as reported by the sources); target choice is INFERRED. |
| Pipelined streaming: partial STT, streamed LLM tokens, chunked TTS, so first audio plays before the reply is complete. | Strictly sequential; reply is base64 JSON after everything finishes. | Biggest perceived-latency lever: stream the first persona's text to TTS while the next persona is still generating. | VERIFIED (as reported) |
| Barge-in needs TTS that stops in <50 ms and echo-cancelled ASR. | Not applicable: push-to-talk voice notes (web and Telegram). | None while the interaction is voice-note based. | VERIFIED (as reported); applicability INFERRED. |
| Parallelize independent synthesis. | Segments synthesized serially (audit L2). | Cheap win: `asyncio.gather` over segments. | INFERRED |
| Provider fallback for TTS. | ElevenLabs → OpenAI/edge, with retry. | Matches practice. | INFERRED |
| Azerbaijani STT/TTS quality (Whisper `language="az"`, ElevenLabs v3). | Already pinned and measured by the owner (`voice_bench.py`). | Out of scope for d01; see the voice brief. | UNKNOWN beyond the repo's own measurements. |

## 4. Evaluation of persona fidelity and factual grounding

Source on judge practice: [Galtea](https://galtea.ai/blog/llm-as-a-judge-the-complete-guide), [Kinde](https://kinde.com/learn/ai-for-software-engineering/best-practice/llm-as-a-judge-done-right-calibrating-guarding-debiasing-your-evaluators/), [MLflow](https://mlflow.org/articles/tags/llm-as-a-judge/) (vendor and tooling blogs).

| Practice (as reported) | Divan today | Gap | Label |
|---|---|---|---|
| Rubric-based LLM judge returning a structured verdict, one rubric per dimension, binary pass/fail more consistent than Likert. | One judge prompt scoring five 1–5 dimensions at once (`audit.py:JUDGE_SYSTEM`). | The reported advice is separate binary rubrics; five correlated Likert scores in one prompt are the pattern it warns against. | VERIFIED (as reported) |
| Calibrate the judge against a human-labelled gold set (reported 200–500 traces, 2–3 labellers, Cohen's kappa); 80–90 % agreement on clear criteria, lower on tone. | No human labels, no agreement figure. The judge prompt role-plays a strict philologist and has never been checked against one. | The numbers behind "character 3.6/5" are uncalibrated. A 30–50 item set labelled by a native speaker would be the first step; the full 200+ is probably out of proportion for this product. | VERIFIED (as reported); sizing is INFERRED. |
| Deterministic checks for what can be checked mechanically; judge for the rest. | Live audit has both. d01 adds an offline deterministic layer (anachronism, calques, machine voice, unsupported quotation, foreign address) with labelled fixtures, run in CI. | Judge stage is wired (`--judge`) but not run in CI (needs the Claude CLI). | INFERRED |
| Grounding: retrieval hit rate plus citation faithfulness, with abstention when evidence is weak. | d01 measures hit@2 = 1.00 (lexical, 22 cases) and 1.00 (natural, 3 cases), citation faithfulness 1.00 over 49 citations; abstention is **0/2** on off-topic questions. | The abstention gate is the open grounding defect (audit A6). | INFERRED (metric choice) / measured locally |
| Persona-consistency benchmarks for role-play models. | None used. | The literature search returned mostly judge-practice blogs; no persona benchmark for Azerbaijani literary figures was found. | UNKNOWN |

## 5. Guardrails and security

Source: [OWASP Top 10 for LLM Applications 2025](https://opensourcesecurity.substack.com/p/a-deep-dive-into-the-owasp-top-10) (secondary summary; the OWASP page itself was not fetched).

| Practice | Divan today | Gap | Label |
|---|---|---|---|
| LLM01 Prompt Injection (#1 for the second edition running): crafted input can override instructions or redirect behaviour. | Router now treats only the first word as a decision; transcript role-forging closed; invisible characters stripped. No instruction-hierarchy statement in prompts, no injection cases in the golden set. | Add injection probes to the offline set and an explicit hierarchy line to the persona prompt (backlog). | VERIFIED (list entry); coverage gap is local fact. |
| LLM10 Unbounded Consumption: oversized prompts, high-volume requests and abusive automation drive cost. | Added input and upload caps and a turn timeout; per-IP rate limit exists; no per-key or global budget. | Daily budget per access key; verify that the limiter sees real client addresses behind Caddy (audit S4). | VERIFIED (list entry) |
| LLM07 System Prompt Leakage (new in 2025) | Persona prompts contain no secrets; leakage is a persona-quality issue, not a security one. | None for security. | INFERRED |
| LLM08 Vector and Embedding Weaknesses (new in 2025) | Corpus is committed and trusted; BM25 default. | Revisit if ingestion ever takes outside content. | INFERRED |
| Deterministic crisis path before the model, plus a moderation model. | Present and tested; fixed a zero-width evasion. | Keyword list is high-recall but unreviewed by a clinician; the crisis text is intentionally number-free. | INFERRED |

## 6. What the benchmark changes in the plan

1. Latency is the product gap that matters most (60 s against a "few seconds to first audio" target) and it is mostly graph shape: calls per turn and no streaming.
2. The evaluation gap is calibration, not volume: the existing judge is useful for trend but has no human anchor.
3. Security hygiene was weaker on bounds than on prompts; d01 closes the bounds.

## 7. Not established

Cost per answer in currency; the numbers inside the LangChain benchmark; any Azerbaijani-specific persona benchmark; real client IPs seen by the limiter in production; the sizing a human-labelled Azerbaijani gold set would need for acceptable judge agreement.
