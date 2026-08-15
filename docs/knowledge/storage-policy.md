# Storage policy (2026-08-15)

Where Divan's data lives, by tier. Rule of thumb: **git for curated sources,
Drive for raw/irreplaceable assets, server volume for derived data only.**
Measured 2026-08-15: RAG index 2.8MB, whole /data volume 5.2MB, server disk
3% used — the policy exists for where we're going, not where we are.

| Tier | What | Where | Why |
|---|---|---|---|
| Curated corpus | `app/rag/corpus/*.txt` (54KB) | **git** (this repo) | Small, versioned, reviewed — the source of truth for ingest |
| Vector index | `/data/rag/index.json` (2.8MB) | server/local volume | DERIVED — never backed up; rebuild: `docker compose exec api python -m app.rag.ingest` (per host) |
| Raw big assets | dictionaries, official PDFs, source recordings | **Google Drive** "Divan — Bilik Anbarı" + `/root/divan-archive/` on the server | Not in git (size/licence); Drive holds manifests with fetch commands for re-downloadable files and real copies of irreplaceable ones |
| Voice Lab samples | `/data/voicelab/samples/` | server/local volume | Working set for clone retraining; promote keepers to Drive "Səs materialları" |
| Conversation state | `/data/*.sqlite` | server volume | Operational; not archived (privacy + rebuildable UX) |

Drive warehouse: folder "Divan — Bilik Anbarı" (Ədəbi korpus / Dil resursları /
Səs materialları), each with a MANIFEST doc carrying provenance, licences and
fetch commands.

## Language resources decision (Alim asked to load dictionaries into the vector DB)

Collected, latest versions:
- **Orfoqrafiya Normaları 2019** (Cabinet decision 174, official 12-page PDF;
  2020 amendments noted) — archived.
- **Hunspell az dictionary** — 42,937 words + affix rules, MPL-2.0
  (github.com/mozillaz/spellchecker) — the open, machine-readable alternative
  to the copyrighted 2021 print lüğət.

They deliberately do NOT go into the embedding index: orthography is an
exact-match problem, not a semantic-search problem. Embedding 42k dictionary
entries (~500MB+) would bloat the index and retrieval quality would still be
wrong-tool-for-the-job. Planned use instead:
1. deterministic spell layer (hunspell wordlist) for Voice Lab diff
   normalisation and TTS pre-checks;
2. rule-based checks from the 2019 normaları in evals;
3. if a feature ever needs *citable* rules, ingest selected sections as their
   own RAG source — selectively, never wholesale.
