from app.graph.guardrails import is_self_harm_risk


def test_detects_self_harm_language_across_languages():
    assert is_self_harm_risk("Artıq yaşamaq istəmirəm, intihar etmək istəyirəm.")
    assert is_self_harm_risk("I just want to kill myself.")
    assert is_self_harm_risk("не хочу жить, хочу покончить с собой")


def test_does_not_flag_ordinary_questions():
    assert not is_self_harm_risk("Kredit götürüb biznes açmalıyammı?")
    assert not is_self_harm_risk("Sevdiyim insanla aramı düzəltmək istəyirəm.")
    assert not is_self_harm_risk("")
    assert not is_self_harm_risk(None)
