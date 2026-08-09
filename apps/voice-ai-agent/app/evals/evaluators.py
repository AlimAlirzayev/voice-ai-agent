"""Deterministic evaluators for the offline golden regression suite."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    category: str
    passed: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]


def evaluate_text(case: dict[str, Any], reply: str) -> EvaluationResult:
    expected = case["expected"]
    checks: list[str] = []
    failures: list[str] = []

    if reply.strip():
        checks.append("non_empty")
    else:
        failures.append("reply is empty")

    sentence_count = len([part for part in re.split(r"[.!?]+", reply) if part.strip()])
    if sentence_count <= expected.get("max_sentences", 3):
        checks.append("sentence_limit")
    else:
        failures.append(f"too many sentences: {sentence_count}")

    for forbidden in expected.get("must_not_contain", []):
        if forbidden not in reply:
            checks.append(f"absent:{forbidden}")
        else:
            failures.append(f"contains forbidden text: {forbidden}")

    if expected.get("language") == "az":
        az_markers = ("ə", "ı", "ö", "ü", "ş", "ç", "Salam", "mən", "sən")
        if any(marker.lower() in reply.lower() for marker in az_markers):
            checks.append("azerbaijani_marker")
        else:
            failures.append("no Azerbaijani language marker detected")

    for expected_text in expected.get("reply_contains", []):
        if expected_text.lower() in reply.lower():
            checks.append(f"contains:{expected_text}")
        else:
            failures.append(f"missing expected text: {expected_text}")

    history_length = case.get("fixture_history_length")
    minimum_history = expected.get("history_length_min")
    if minimum_history is not None:
        if history_length is not None and history_length >= minimum_history:
            checks.append("history_length")
        else:
            failures.append(f"history length below minimum: {minimum_history}")

    return EvaluationResult(
        case["id"],
        case["category"],
        not failures,
        tuple(checks),
        tuple(failures),
    )


def evaluate_voice(case: dict[str, Any], response: dict[str, Any]) -> EvaluationResult:
    expected = case["expected"]
    checks: list[str] = []
    failures: list[str] = []

    for field in expected["required_fields"]:
        if response.get(field) is not None:
            checks.append(f"field:{field}")
        else:
            failures.append(f"missing field: {field}")

    if response.get("audio_mime") in expected["audio_mime"]:
        checks.append("audio_mime")
    else:
        failures.append(f"unsupported audio mime: {response.get('audio_mime')}")

    try:
        decoded = base64.b64decode(response.get("audio_base64", ""), validate=True)
    except (binascii.Error, ValueError, TypeError):
        decoded = b""
    if decoded:
        checks.append("audio_base64")
    else:
        failures.append("audio_base64 is not valid non-empty base64")

    return EvaluationResult(
        case["id"],
        case["category"],
        not failures,
        tuple(checks),
        tuple(failures),
    )


def evaluate_case(case: dict[str, Any]) -> EvaluationResult:
    """Evaluate a recorded fixture without calling an external provider."""
    if "response" in case:
        return evaluate_voice(case, case["response"])
    fixture = case.get("fixture_response", "")
    if isinstance(fixture, dict):
        case = {
            **case,
            "fixture_history_length": fixture.get("history_length"),
        }
        fixture = fixture.get("reply", "")
    return evaluate_text(case, fixture)
