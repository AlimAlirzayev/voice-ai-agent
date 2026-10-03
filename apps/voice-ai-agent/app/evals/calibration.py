"""Judge-vs-human calibration for the persona-fidelity judge.

Two commands, no network and no Claude call:

  pack   build a blind labelling pack from audit report(s): a CSV for the native
         speaker (no judge scores in it) and a key JSON that maps each pack row
         back to the judge's scores.
  score  read the filled CSV plus the key and print, per rubric dimension, the
         percent agreement, within-one agreement, Cohen's kappa (unweighted and
         quadratic-weighted) and the pass/fail kappa at the pass threshold.

usage: .venv/bin/python -m app.evals.calibration pack --reports output/audit-v5.json --out output/calibration
       .venv/bin/python -m app.evals.calibration score --labels output/calibration/labels.csv \
           --key output/calibration/key.json
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

DIMENSIONS = ("xarakter", "mentalitet", "dil", "bedii", "fayda")
SCALE = (1, 2, 3, 4, 5)
PASS_THRESHOLD = 4  # a score >= 4 counts as "acceptable" for the binary view
PACK_FIELDS = ["item_id", "question", "speakers", "reply", *DIMENSIONS, "defects", "comment"]


def build_pack(reports: list[dict], seed: int = 20260101, limit: int | None = None) -> tuple[list[dict], list[dict]]:
    """Return (rows, key). Rows carry no judge output; the order is shuffled by `seed`
    so the rater cannot infer the audit version or the question group from position."""
    pool: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for rep in reports:
        for r in rep.get("results", []):
            judge = r.get("judge") or {}
            if "checks" not in r or "error" in judge or not r.get("reply"):
                continue
            if any(d not in judge for d in DIMENSIONS):
                continue
            ident = (r["id"], r["reply"])
            if ident in seen:
                continue
            seen.add(ident)
            pool.append(r)
    random.Random(seed).shuffle(pool)
    if limit:
        pool = pool[:limit]
    rows, key = [], []
    for n, r in enumerate(pool, 1):
        item_id = f"P{n:03d}"
        rows.append({"item_id": item_id, "question": r["q"], "speakers": ", ".join(r.get("consulted") or []),
                     "reply": r["reply"], **{d: "" for d in DIMENSIONS}, "defects": "", "comment": ""})
        key.append({"item_id": item_id, "source_id": r["id"],
                    "judge": {d: int(float(r["judge"][d])) for d in DIMENSIONS},
                    "judge_defects": r["judge"].get("qusurlar") or []})
    return rows, key


def write_pack(rows: list[dict], key: list[dict], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "labels.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=PACK_FIELDS)
        w.writeheader()
        w.writerows(rows)
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")


def read_labels(path: Path) -> dict[str, dict[str, int]]:
    """item_id -> {dimension: score}. Blank cells are skipped; a value outside 1-5 is an error."""
    labels: dict[str, dict[str, int]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            scores: dict[str, int] = {}
            for d in DIMENSIONS:
                cell = (row.get(d) or "").strip()
                if not cell:
                    continue
                try:
                    value = int(cell)
                except ValueError as exc:
                    raise ValueError(f"{row['item_id']}.{d}: {cell!r} is not an integer 1-5") from exc
                if value not in SCALE:
                    raise ValueError(f"{row['item_id']}.{d}: {value} is outside 1-5")
                scores[d] = value
            labels[row["item_id"]] = scores
    return labels


def cohen_kappa(a: list[int], b: list[int], weights: str | None = None, categories: tuple[int, ...] = SCALE) -> float | None:
    """Cohen's kappa for two raters. `weights` is None or "quadratic".
    None when undefined (no pairs, or both raters constant on one category)."""
    n = len(a)
    if n == 0:
        return None
    k = len(categories)
    idx = {c: i for i, c in enumerate(categories)}
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[idx[x]][idx[y]] += 1
    row = [sum(r) for r in obs]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i: int, j: int) -> float:  # disagreement weight
        if weights == "quadratic":
            return ((i - j) / (k - 1)) ** 2
        return 0.0 if i == j else 1.0

    d_obs = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    d_exp = sum(w(i, j) * row[i] * col[j] for i in range(k) for j in range(k)) / (n * n)
    if d_exp == 0:
        return None
    return 1 - d_obs / d_exp


def agreement(human: dict[str, dict[str, int]], key: list[dict]) -> dict:
    """Per-dimension judge-vs-human agreement over the items both rated."""
    out: dict[str, dict] = {}
    for d in DIMENSIONS:
        h, j = [], []
        for k in key:
            hv = human.get(k["item_id"], {}).get(d)
            if hv is not None:
                h.append(hv)
                j.append(k["judge"][d])
        n = len(h)
        if n == 0:
            out[d] = {"n": 0, "exact": None, "within_one": None, "kappa": None,
                      "kappa_weighted": None, "kappa_pass": None, "mean_bias": None}
            continue
        hb = [int(x >= PASS_THRESHOLD) for x in h]
        jb = [int(x >= PASS_THRESHOLD) for x in j]
        out[d] = {
            "n": n,
            "exact": sum(x == y for x, y in zip(h, j)) / n,
            "within_one": sum(abs(x - y) <= 1 for x, y in zip(h, j)) / n,
            "kappa": cohen_kappa(h, j),
            "kappa_weighted": cohen_kappa(h, j, "quadratic"),
            "kappa_pass": cohen_kappa(hb, jb, categories=(0, 1)),
            "mean_bias": sum(y - x for x, y in zip(h, j)) / n,  # judge minus human; > 0 = judge is lenient
        }
    return out


def _fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.0f}%" if pct else f"{v:.2f}"


def render(result: dict) -> str:
    head = f"{'dimension':<11}{'n':>4}{'exact':>8}{'±1':>7}{'kappa':>8}{'k(quad)':>9}{'k(pass)':>9}{'bias':>7}"
    lines = [head, "-" * len(head)]
    for d, r in result.items():
        lines.append(f"{d:<11}{r['n']:>4}{_fmt(r['exact'], True):>8}{_fmt(r['within_one'], True):>7}"
                     f"{_fmt(r['kappa']):>8}{_fmt(r['kappa_weighted']):>9}{_fmt(r['kappa_pass']):>9}{_fmt(r['mean_bias']):>7}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("--reports", nargs="+", required=True, help="audit report JSON file(s) with judge scores")
    p.add_argument("--out", default="output/calibration")
    p.add_argument("--seed", type=int, default=20260101)
    p.add_argument("--limit", type=int, default=0)
    s = sub.add_parser("score")
    s.add_argument("--labels", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--json", default="")
    a = ap.parse_args(argv)

    if a.cmd == "pack":
        reports = [json.loads(Path(f).read_text(encoding="utf-8")) for f in a.reports]
        rows, key = build_pack(reports, a.seed, a.limit or None)
        write_pack(rows, key, Path(a.out))
        print(f"{len(rows)} items -> {a.out}/labels.csv (give to the rater), {a.out}/key.json (keep back)")
        return 0

    human = read_labels(Path(a.labels))
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    result = agreement(human, key)
    print(render(result))
    if a.json:
        Path(a.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
