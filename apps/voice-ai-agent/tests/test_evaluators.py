import base64

from app.evals.evaluators import evaluate_text, evaluate_voice


def test_text_evaluator_catches_language_and_format_regressions():
    case = {
        "id": "text",
        "category": "language",
        "expected": {
            "language": "az",
            "max_sentences": 3,
            "must_not_contain": ["```"],
        },
    }

    result = evaluate_text(case, "Salam! Bu qısa cavabdır.")
    assert result.passed

    failed = evaluate_text(case, "Hello.\n```code```.\nThis is too long. More text.")
    assert not failed.passed
    assert "contains forbidden text: ```" in failed.failures
    assert any(failure.startswith("too many sentences") for failure in failed.failures)


def test_voice_evaluator_validates_audio_contract():
    case = {
        "id": "voice",
        "category": "voice",
        "expected": {
            "audio_mime": ["audio/ogg"],
            "required_fields": ["transcript", "reply", "audio_base64", "audio_mime"],
        },
    }
    response = {
        "transcript": "Salam",
        "reply": "Salam!",
        "audio_base64": base64.b64encode(b"ogg").decode(),
        "audio_mime": "audio/ogg",
    }
    assert evaluate_voice(case, response).passed

    response["audio_base64"] = "not-base64"
    assert not evaluate_voice(case, response).passed
