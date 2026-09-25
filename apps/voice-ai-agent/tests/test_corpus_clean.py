"""The corpus stays free of print apparatus, and the cleaner never eats words."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("clean_corpus", ROOT / "scripts" / "clean_corpus.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def test_corpus_is_already_clean():
    cc.VOCAB.update(cc._vocab())
    for path in sorted(cc.CORPUS.rglob("*.txt")):
        raw, new = cc.clean_file(path)
        assert raw == new, f"{path.name} still carries apparatus: run scripts/clean_corpus.py"


def test_no_digits_left_in_any_body():
    for path in sorted(cc.CORPUS.rglob("*.txt")):
        body = "".join(l for l in path.read_text(encoding="utf-8").splitlines(True) if not l.startswith("#"))
        assert not re.search(r"\d", body), path.name


def test_known_debris_is_removed_and_words_survive():
    cc.VOCAB.clear()
    cc.VOCAB.update({"yerin", "ölməgə", "yitməgə"})
    dirty = ("Qara ye- D67 rin üstinə. Bay4börə bəg 13 durdı. Ölməgə-yitməgə getməmişdim. "
             "deyərlərEnsiklopediyada “derlər” gedib. - Red., bir ər. üryan göründü*.")
    clean = cc.clean_body(dirty)
    assert clean == ("Qara yerin üstinə. Baybörə bəg durdı. Ölməgə-yitməgə getməmişdim. "
                     "deyərlər, bir ər. üryan göründü.")
    assert cc.clean_body("* * *") == "* * *"
