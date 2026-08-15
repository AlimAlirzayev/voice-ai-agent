"""Grounded personas (roadmap Phase 2): each council member reads from their
own real, public-domain corpus and answers with citations.

- `corpus/<advisor>/*.txt` - curated source texts with provenance headers
- `ingest.py`  - chunk + embed the corpus into a JSON index (run once per host)
- `retriever.py` - load the index and serve per-advisor top-k retrieval

The retrieval layer feeds advisors EVIDENCE; it never replaces their voice -
character prompts stay in charge of how the answer sounds.
"""
