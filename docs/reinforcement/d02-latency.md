# Divan latency (d02): migration notes

Everything below is additive or switchable; no route, response field or env var was removed or renamed.

## What changed

| Item | Change | Switch |
|---|---|---|
| B1 | One router call names up to two members ("SIMURG KOROGLU"); they speak in turn and the router is not asked again. Model calls per turn: one member 3 → 2, two members 4 → 3, greeting 2 → 2. | `COUNCIL_ROUTING=single_call` (default) or `iterative` (previous behaviour) |
| B2 | The clips of one reply are synthesized concurrently; order of `segments` is unchanged; a failing clip still fails the reply (502) and cancels the rest. | `TTS_CONCURRENCY` (default 4; 1 = serial) |
| B5 | New `POST /chat/stream` and `POST /voice/stream` (SSE). `/chat`, `/chat/resume`, `/voice`, `/voice/resume` are unchanged. | none; clients opt in by calling the new routes |

## Stream contract

Request bodies are those of `/chat` and `/voice`. Response is `text/event-stream`; each frame is `event: <name>` plus one line `data: <json>`.

| Event | Data | When |
|---|---|---|
| `transcript` (voice only) | string | after speech-to-text |
| `narration` | string | the opening line immediately, the rest once the router has chosen |
| `opinion` | `{advisor, name, text}` | each member, as soon as that member has finished |
| `segment` (voice only) | `VoiceSegment` | as soon as that member's clip is ready; TTS for member 1 runs while member 2 is written |
| `done` | the body `/chat` or `/voice` would return | last frame |
| `error` | `{status, detail}` | a failure after the stream opened (503 model, 502 voice) |

Failures before the stream opens (upload size, no speech, 422 validation, rate limit) are the same HTTP errors as the non-streaming routes. A paused thread answers with a single `done` carrying `status: pending_approval`; resolve it with the existing resume routes. A client that played the `segment` events may ignore `done.segments`.

## Behaviour a client can see

- With `single_call`, the router prompt allows two names; a router that answers in prose still ends the council (first-word rule is unchanged).
- Routing narration lines for both members are added at once, before either speaks; the final `narration` list is the same as before.

## Rollback

`COUNCIL_ROUTING=iterative` and `TTS_CONCURRENCY=1` restore the previous call pattern. Tests that script the old router loop set `iterative` explicitly.
