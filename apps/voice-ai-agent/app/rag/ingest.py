"""Chunk + embed the persona corpus into a JSON index.

Run inside the app environment (needs OPENAI_API_KEY):

    python -m app.rag.ingest

Poems chunk by bənd (blank-line groups, merged to a readable minimum) so a
citation never splits a couplet; prose packs paragraphs to ~700 characters.
Every chunk keeps provenance (work, ref, source URL) - the citation is the
receipt, and a receipt must point somewhere real. The index is a plain JSON
file: the corpus is a few hundred chunks, so a vector database would be pure
ceremony; cosine over lists is instant at this size.
"""

import json
import re
from pathlib import Path

from openai import OpenAI

from app.core.config import settings

CORPUS_DIR = Path(__file__).parent / "corpus"
EMBED_MODEL = "text-embedding-3-small"
MIN_POEM_CHUNK = 120
MAX_PROSE_CHUNK = 700


def parse_source(path: Path) -> tuple[dict, str]:
    """Split a corpus file into its `# key: value` header and body."""
    meta: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        m = re.match(r"#\s*([\w-]+)\s*:\s*(.+)", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
            body_start = i + 1
        elif line.strip():
            break
    return meta, "\n".join(lines[body_start:]).strip()


def chunk_poem(body: str) -> list[tuple[str, str]]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    for part in parts:
        if chunks and len(chunks[-1]) < MIN_POEM_CHUNK:
            chunks[-1] = chunks[-1] + "\n\n" + part
        else:
            chunks.append(part)
    return [(text, f"bənd {i + 1}") for i, text in enumerate(chunks)]


def _split_long(paragraph: str) -> list[str]:
    """Some sources use no blank lines at all, producing one giant 'paragraph'
    that would blow the embedding token limit - split those on sentence/line
    boundaries and pack back to chunk size."""
    if len(paragraph) <= MAX_PROSE_CHUNK * 2:
        return [paragraph]
    units = [u.strip() for u in re.split(r"(?<=[.!?…])\s+|\n", paragraph) if u.strip()]
    packed: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > MAX_PROSE_CHUNK:
            packed.append(current)
            current = unit
        else:
            current = f"{current} {unit}".strip()
    if current:
        packed.append(current)
    return packed


def chunk_prose(body: str) -> list[tuple[str, str]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    paragraphs = [piece for p in paragraphs for piece in _split_long(p)]
    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        if current and len(current) + len(p) > MAX_PROSE_CHUNK:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)
    return [(text, f"hissə {i + 1}") for i, text in enumerate(chunks)]


def is_usable(body: str) -> bool:
    """Guard against garbage entering the index.

    Wikimedia (and most sites) answer a failed fetch with an HTML error page
    under HTTP 200; the markup cleaner strips the tags and produces
    plausible-looking "text" that would be embedded and later quoted at a user
    as if it were Nizami. One such page reached the corpus on 2026-08-16
    before this check existed.

    Structural markers do the real work here. The length floor only catches
    redirect stubs and is deliberately low: a genuine ghazal can be six lines
    (two of Nəsimi's are), and a 200-char floor silently dropped them.
    """
    lowered = body[:2000].lower()
    if any(marker in lowered for marker in ("<!doctype html", "wikimedia error", "wikimedia foundation")):
        return False
    if "{" in body[:200] and "}" in body[:200]:  # unstripped template markup
        return False
    return len(body) >= 80


def collect_chunks() -> list[dict]:
    chunks = []
    for path in sorted(CORPUS_DIR.rglob("*.txt")):
        meta, body = parse_source(path)
        if not body or "advisor" not in meta:
            continue
        if not is_usable(body):
            print(f"SKIP (failed validation): {path.relative_to(CORPUS_DIR)}")
            continue
        chunker = chunk_poem if meta.get("type") == "poem" else chunk_prose
        for text, ref in chunker(body):
            chunks.append({
                "advisor": meta["advisor"],
                "work": meta.get("work", path.stem),
                "ref": ref,
                "source": meta.get("source", ""),
                "text": text,
            })
    return chunks


def main() -> None:
    chunks = collect_chunks()
    if not chunks:
        raise SystemExit("no corpus chunks found")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    for start in range(0, len(chunks), 64):
        batch = chunks[start:start + 64]
        response = client.embeddings.create(
            model=EMBED_MODEL, input=[c["text"] for c in batch]
        )
        for chunk, item in zip(batch, response.data):
            chunk["embedding"] = item.embedding

    out = settings.rag_index_file
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": EMBED_MODEL, "chunks": chunks}), encoding="utf-8")

    by_advisor: dict[str, int] = {}
    for c in chunks:
        by_advisor[c["advisor"]] = by_advisor.get(c["advisor"], 0) + 1
    print(f"indexed {len(chunks)} chunks -> {out}")
    for advisor, n in sorted(by_advisor.items()):
        print(f"  {advisor}: {n}")


if __name__ == "__main__":
    main()
