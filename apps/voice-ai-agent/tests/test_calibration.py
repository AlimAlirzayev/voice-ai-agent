import csv
import json

import pytest

from app.evals import calibration as cal

DIMS = cal.DIMENSIONS


def _key(judge_rows):
    return [{"item_id": f"P{i:03d}", "source_id": f"s{i}", "judge": dict(zip(DIMS, row)), "judge_defects": []}
            for i, row in enumerate(judge_rows, 1)]


def _human(human_rows):
    return {f"P{i:03d}": dict(zip(DIMS, row)) for i, row in enumerate(human_rows, 1)}


def test_perfect_agreement():
    rows = [(1, 2, 3, 4, 5), (5, 4, 3, 2, 1), (3, 3, 4, 4, 2), (2, 5, 1, 3, 4)]
    res = cal.agreement(_human(rows), _key(rows))
    for d in DIMS:
        assert res[d]["exact"] == 1.0
        assert res[d]["kappa"] == pytest.approx(1.0)
        assert res[d]["kappa_weighted"] == pytest.approx(1.0)
        assert res[d]["mean_bias"] == 0


def test_kappa_known_value():
    # 2x2 textbook case: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> kappa 0.4
    a = [1] * 20 + [1] * 5 + [0] * 10 + [0] * 15
    b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    assert cal.cohen_kappa(a, b, categories=(0, 1)) == pytest.approx(0.4)


def test_weighted_kappa_penalises_far_misses_more():
    human = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
    near = [2, 3, 4, 5, 4, 2, 3, 4, 5, 4]
    far = [5, 4, 1, 2, 1, 5, 4, 1, 2, 1]
    assert cal.cohen_kappa(human, near, "quadratic") > cal.cohen_kappa(human, far, "quadratic")
    assert cal.cohen_kappa(human, far, "quadratic") < 0


def test_undefined_kappa_returns_none():
    assert cal.cohen_kappa([], []) is None
    assert cal.cohen_kappa([4, 4, 4], [4, 4, 4]) is None  # no variance on either side


def test_lenient_judge_shows_positive_bias_and_within_one():
    human = [[2, 2, 2, 2, 2], [3, 3, 3, 3, 3], [1, 2, 3, 2, 1], [3, 2, 3, 3, 2]]
    judge = [[4, 4, 4, 4, 4], [4, 4, 4, 4, 4], [2, 3, 4, 3, 2], [4, 3, 4, 4, 3]]
    res = cal.agreement(_human(human), _key(judge))
    assert res["xarakter"]["mean_bias"] == pytest.approx(1.25)
    assert res["xarakter"]["exact"] == 0.0
    assert res["xarakter"]["within_one"] == 0.75
    # humans never reach 4, judge always does: pass/fail kappa is 0 or undefined, never high
    assert res["xarakter"]["kappa_pass"] in (None, 0.0)


def test_missing_human_cells_are_skipped_per_dimension():
    key = _key([(3, 3, 3, 3, 3), (4, 4, 4, 4, 4)])
    human = {"P001": {"xarakter": 3}, "P002": {"xarakter": 4, "dil": 2}}
    res = cal.agreement(human, key)
    assert res["xarakter"]["n"] == 2 and res["dil"]["n"] == 1 and res["fayda"]["n"] == 0
    assert res["fayda"]["exact"] is None


def test_read_labels_validates_range(tmp_path):
    path = tmp_path / "labels.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cal.PACK_FIELDS)
        w.writeheader()
        w.writerow({"item_id": "P001", "xarakter": "4", "dil": "", "bedii": " 2 "})
    assert cal.read_labels(path) == {"P001": {"xarakter": 4, "bedii": 2}}
    path.write_text("item_id,xarakter\nP001,6\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cal.read_labels(path)
    path.write_text("item_id,xarakter\nP001,abc\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cal.read_labels(path)


def _report():
    good = {"xarakter": 3, "mentalitet": 5, "dil": 4, "bedii": 4, "fayda": 4, "qusurlar": ["x"]}
    return {"results": [
        {"id": "a", "q": "Sual a?", "reply": "Cavab a.", "consulted": ["koroglu"], "checks": {}, "judge": good},
        {"id": "b", "q": "Sual b?", "reply": "Cavab b.", "consulted": [], "checks": {}, "judge": {"error": "timeout"}},
        {"id": "c", "q": "Sual c?", "reply": "Cavab c.", "consulted": ["simurg"], "checks": {}, "judge": {"xarakter": 2}},
        {"id": "d", "q": "Sual d?", "error": "boom"},
        {"id": "a", "q": "Sual a?", "reply": "Cavab a.", "consulted": ["koroglu"], "checks": {}, "judge": good},
    ]}


def test_pack_is_blind_and_deduplicated(tmp_path):
    rows, key = cal.build_pack([_report()])
    assert [k["source_id"] for k in key] == ["a"]  # error / partial judge / failed rows / duplicate dropped
    assert all(row[d] == "" for row in rows for d in DIMS)
    cal.write_pack(rows, key, tmp_path)
    csv_text = (tmp_path / "labels.csv").read_text(encoding="utf-8-sig")
    assert "qusurlar" not in csv_text and "judge" not in csv_text.lower()
    assert json.loads((tmp_path / "key.json").read_text(encoding="utf-8"))[0]["judge"]["mentalitet"] == 5


def test_pack_order_is_seeded_and_ids_are_opaque():
    rep = {"results": [{"id": f"q{i}", "q": "?", "reply": f"r{i}", "consulted": [], "checks": {},
                        "judge": {d: 3 for d in DIMS}} for i in range(12)]}
    _, k1 = cal.build_pack([rep], seed=1)
    _, k2 = cal.build_pack([rep], seed=1)
    _, k3 = cal.build_pack([rep], seed=2)
    assert k1 == k2 and k1 != k3
    assert [k["item_id"] for k in k1] == [f"P{i:03d}" for i in range(1, 13)]


def test_end_to_end_cli_with_synthetic_labels(tmp_path, capsys):
    rep = {"results": [{"id": f"q{i}", "q": "?", "reply": f"r{i}", "consulted": [], "checks": {},
                        "judge": {d: 1 + i % 5 for d in DIMS}} for i in range(10)]}
    src = tmp_path / "rep.json"
    src.write_text(json.dumps(rep), encoding="utf-8")
    out = tmp_path / "pack"
    assert cal.main(["pack", "--reports", str(src), "--out", str(out)]) == 0
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((out / "labels.csv").open(encoding="utf-8-sig")))
    for row, k in zip(rows, key):  # synthetic rater: agrees with the judge
        for d in DIMS:
            row[d] = str(k["judge"][d])
    with (out / "filled.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cal.PACK_FIELDS)
        w.writeheader()
        w.writerows(rows)
    assert cal.main(["score", "--labels", str(out / "filled.csv"), "--key", str(out / "key.json"),
                     "--json", str(out / "res.json")]) == 0
    res = json.loads((out / "res.json").read_text(encoding="utf-8"))
    assert all(res[d]["exact"] == 1.0 for d in DIMS)
    assert "xarakter" in capsys.readouterr().out
