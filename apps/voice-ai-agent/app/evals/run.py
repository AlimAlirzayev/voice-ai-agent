"""Run the offline golden evaluation suite.

This suite validates response contracts and recorded regression fixtures without
spending provider credits. Live model quality is evaluated separately in
LangSmith using the same case IDs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.evals.evaluators import evaluate_case


def main() -> int:
    dataset = json.loads((Path(__file__).with_name("golden.json")).read_text(encoding="utf-8"))
    results = [evaluate_case(case) for case in dataset]
    for result in results:
        state = "PASS" if result.passed else "FAIL"
        print(f"{state} {result.case_id} [{result.category}]")
        for failure in result.failures:
            print(f"  - {failure}")
    passed = sum(result.passed for result in results)
    print(f"\n{passed}/{len(results)} golden cases passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
