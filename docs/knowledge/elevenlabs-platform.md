# ElevenLabs platform — verified facts (2026-08-14)

All items marked ✓ were tested live against the API with the project account, not
taken from docs or marketing.

## Models and Azerbaijani

✓ `GET /v1/models` on 2026-08-14:

| Model | Languages | Azerbaijani | Notes |
|---|---|---|---|
| `eleven_v3` | 74 | **✓ yes (`aze`)** | the ONLY model with AZ; expressive, higher latency |
| `eleven_multilingual_v2` | 29 | no | previous project default — root cause of the "artificial" AZ speech |
| `eleven_flash_v2_5` / `eleven_turbo_v2_5` | 32 | no | low-latency tier — **no AZ**, so real-time AZ speech is impossible on ElevenLabs today |
| `eleven_english_sts_v2` / `eleven_multilingual_sts_v2` | 1 / 29 | no | speech-to-speech (voice changer) |

Consequence: any real-time (sub-second) conversational product in Azerbaijani cannot
use ElevenLabs flash/turbo models yet. Either accept v3 latency, or watch for AZ
landing in the flash tier, or use Azure `az-AZ-BabekNeural`/`BanuNeural` (native,
low-latency, only 2 voices) for the real-time path.

## Voice library gap = our moat

✓ `GET /v1/shared-voices?language=az|aze` → **0 results**. Search "azerbaijani" → 2
professional voices by Azerbaijani-named creators, both English-language. There is no
native Azerbaijani voice in the ElevenLabs community library. Whoever clones good
native AZ voices first has something the library simply does not offer.

## Cloning (the plan for native voices)

✓ Account tier: Starter. Instant Voice Cloning: enabled. Voice slots: 10 (0 used as
of 2026-08-14) — enough for 6 council personas + narrator. Professional Voice
Cloning: not on this tier.

- IVC needs ~1–2 min of clean speech; the clone inherits the source speaker's accent
  and intonation — so a native AZ speaker recording produces native AZ output even
  though the model itself is language-agnostic.
- Premade voices (George, Arnold, Rachel…) are English-accented; with AZ text even on
  v3 they sound foreign (confirmed by ear, A/B v2 vs v3, 2026-08-14 — both rejected).
- Recording script for cloning sessions: phonetically rich AZ text incl. ə-heavy
  words, questions, emotional range, numbers (see git history / session notes).

## API keys are scoped

✓ Keys carry a `permissions` list ("all" or per-scope: `text_to_speech`,
`voices_read`, `voices_write`, `models_read`, `user_read`, …). The project key was
originally TTS-only — every other endpoint returned 401 `missing_permissions`; fixed
2026-08-14 by editing the key's scopes in the dashboard. When an ElevenLabs call
fails with 401 despite a valid key, check scopes first.

## Agents platform (ConvAI)

✓ `GET /v1/convai/agents` works on this tier; 1 agent already exists in the account.
ElevenLabs Agents = hosted real-time conversation stack (STT + LLM + TTS + turn
taking, WebRTC/WebSocket). Relevant to the museum-kiosk vision, BUT: its low-latency
TTS models exclude AZ (see above), and our differentiators (Divan LangGraph brain,
native cloned voices) argue for keeping the brain ours and treating any avatar/voice
platform as an output layer that accepts OUR audio.

## CORRECTION (2026-08-14, from Alim): the AZ voice market is alive

Alim pushed back on the "artificial AZ is inevitable" reading — correctly. Local
practice already produces commercial AZ voice content and even LIVE agents:

- **Autocalls.ai** sells Azerbaijani AI phone agents (inbound/outbound call centers,
  lead qualification, booking) — real-time AZ conversation is commercially shipped.
- **Soniox** offers streaming Azerbaijani STT built for voice agents (candidate to
  replace/augment Whisper for a live AZ pipeline).
- **LOVO, SpeechGen, Speechify, Narakeet** list AZ TTS voices (mostly Azure-backed).
- Local practitioners publish AZ voice-over guides (anarrustamli.com); social teams
  produce AZ ads/podcasts/radio with ElevenLabs today.

Reading: my flash-tier limitation note stands for ElevenLabs specifically, but the
market solves real-time AZ with other stacks (Azure voices, Soniox STT, custom
pipelines). Lesson: verify against what practitioners ship, not only against model
capability tables. TODO: scrape/study concrete AZ social examples (YouTube/LinkedIn)
to learn their exact settings and pre-processing tricks.

## Also seen in the dashboard (not yet used)

Voice Isolator, Voice Changer (STS), Dubbing, Music, Sound Effects, Speech to Text,
Studio/Flows/Templates. Voice Changer + a cloned native voice could convert an actor
recording into a persona voice while keeping the actor's native prosody — worth a
Phase 5 experiment.
