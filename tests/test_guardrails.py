"""Clinical guardrails: danger-sign referral, self-harm handling and model-output cleaning."""
import pytest

import medgemma_guardrails as g


# ─────────────── danger signs ───────────────

@pytest.mark.parametrize("text", [
    "I am bleeding a lot",
    "heavy bleeding since morning",
    "There was blood loss after delivery",
    "I think I had a miscarriage",
    "she had convulsions last night",
    "having a seizure",
    "she has fits",
    "I fainted at the market",
    "she is unconscious",
    "I passed out",
    "severe headache and swelling",
    "severe abdominal pain",
    "I have blurred vision",
    "blurry vision today",
    "my swollen face worries me",
    "baby is not moving",
    "the baby stopped moving",
    "no fetal movement since yesterday",
    "my waters broke",
    "water has broke",
    "leaking fluid from below",
    "very high fever",
    "I can't breathe properly",
    "difficulty breathing",
    "labour pains started",
    "labor pain every 5 minutes",
    "haemorrhage after birth",
    "hemorrhaging",
    "passing blood",
    "heavy period for weeks",
    # local-language bleeding words
    "kubuda ropa kwakawanda",
    "kutuluka magazi",
    "ukuphuma kwegazi igazi",
    "kuswa bulowa",
    "kuelwa mali a mangi",
])
def test_danger_signs_detected(text):
    assert g.is_danger_sign(text)


@pytest.mark.parametrize("text", [
    "", None, "How many antenatal visits should I have?",
    "What foods are good during pregnancy?",
    "Is folic acid safe?",
    "bloodline",            # word boundary: not "blood loss"
])
def test_non_danger_text_not_flagged(text):
    assert not g.is_danger_sign(text)


# ─────────────── self-harm ───────────────

@pytest.mark.parametrize("text", [
    "I feel suicidal", "I want to kill myself", "I want to end my life",
    "I wanted to die", "I don't want to live anymore", "dont want to be alive",
    "I keep hurting myself", "thinking of harming myself", "self-harm", "self harm",
    "I will take my own life", "I am better off dead", "end it all",
])
def test_self_harm_detected(text):
    assert g.is_self_harm(text)


@pytest.mark.parametrize("text", ["", None, "I am tired of the nausea", "kill the pain please"])
def test_self_harm_not_flagged(text):
    assert not g.is_self_harm(text)


def test_see_doctor_line_localised_and_default():
    assert g.see_doctor_line("shona") == g.SEE_DOCTOR["shona"]
    for lang in ("ndebele", "chinyanja", "lozi", "tonga", "bemba"):
        assert g.see_doctor_line(lang) == g.SEE_DOCTOR[lang]
    assert g.see_doctor_line("english") == g.SEE_DOCTOR_DEFAULT
    assert g.see_doctor_line("unknown") == g.SEE_DOCTOR_DEFAULT


def test_self_harm_message_falls_back_to_english_default():
    # No local translations exist yet, so every language gets the reviewed English text.
    for lang in ("english", "shona", "bemba"):
        assert g.self_harm_message(lang) == g.SELF_HARM_DEFAULT
    assert "agent" in g.SELF_HARM_DEFAULT


# ─────────────── compose_reply ───────────────

def test_compose_self_harm_overrides_model_answer():
    out = g.compose_reply("I want to kill myself", "english", "Some model advice.")
    assert out == f"💛 {g.SELF_HARM_DEFAULT}"
    assert "Some model advice" not in out


def test_compose_self_harm_takes_priority_over_danger_sign():
    out = g.compose_reply("I am bleeding and want to die", "english", "advice")
    assert out.startswith("💛")


def test_compose_danger_sign_prefixes_referral_with_model_text():
    out = g.compose_reply("heavy bleeding", "shona", "Model answer in Shona.")
    assert out == f"⚠️ {g.SEE_DOCTOR['shona']}\n\nModel answer in Shona."


def test_compose_danger_sign_fires_even_without_model_text():
    # The referral must still reach the user if the model or translation failed.
    out = g.compose_reply("baby is not moving", "english", None)
    assert out == f"⚠️ {g.SEE_DOCTOR_DEFAULT}"


def test_compose_no_text_no_danger_returns_none():
    assert g.compose_reply("what should I eat?", "english", None) is None
    assert g.compose_reply("what should I eat?", "english", "") is None


def test_compose_normal_answer_gets_footer(monkeypatch):
    monkeypatch.setattr(g, "FOOTER_ON", True)
    out = g.compose_reply("what should I eat?", "bemba", "Eat vegetables.")
    assert out == f"Eat vegetables.\n\n{g.SEE_DOCTOR['bemba']}"


def test_compose_footer_can_be_disabled(monkeypatch):
    monkeypatch.setattr(g, "FOOTER_ON", False)
    assert g.compose_reply("what should I eat?", "english", "Eat vegetables.") == "Eat vegetables."


# ─────────────── clean_model_output ───────────────

def test_clean_none_and_empty():
    assert g.clean_model_output(None) is None
    assert g.clean_model_output("") is None


def test_clean_strips_control_tokens_and_internal_tags():
    raw = "<start_of_turn>model\nAttend antenatal care product_image regularly.<end_of_turn><eos><unused12>"
    out = g.clean_model_output(raw)
    assert out == "Attend antenatal care  regularly."


def test_clean_strips_leading_model_label():
    assert g.clean_model_output("model\nRest and drink water.") == "Rest and drink water."


def test_clean_removes_agent_and_unsolved_markers():
    out = g.clean_model_output("agent_request Please visit the clinic soon.unable_to_solve_query")
    assert out == "Please visit the clinic soon."


def test_clean_rejects_too_short():
    assert g.clean_model_output("Ok.") is None
    assert g.clean_model_output("<eos>  hi <eos>") is None


def test_clean_rejects_repetition_loop():
    looped = "Drink water. Drink water. Drink water. Rest well."
    assert g.clean_model_output(looped) is None


def test_clean_trims_truncated_sentence():
    text = "Eat iron-rich foods every day. Take folic acid as prescribed. Visit the cli"
    assert g.clean_model_output(text) == "Eat iron-rich foods every day. Take folic acid as prescribed."


def test_clean_keeps_truncated_text_when_cut_would_lose_too_much():
    text = "Hi. Eat iron rich foods such as beans and green leafy vegetables daily and"
    assert g.clean_model_output(text) == text


def test_clean_keeps_complete_answer():
    text = "Eat iron-rich foods (beans, greens)"
    # ends with ')' which counts as a complete ending
    assert g.clean_model_output(text) == text



# ─────────────── multilingual safety and normalisation ───────────────
# Replaces earlier placeholder tests that contained `pass`, asserted a misspelt word
# ("antennatal") and only checked isinstance(). Each test below fails if the behaviour breaks.

LOCAL_LANGS = ("shona", "ndebele", "chinyanja", "bemba", "tonga", "lozi")


@pytest.mark.parametrize("text", [
    "I don\u2019t want to live anymore",      # iOS smart apostrophe
    "I don\u02bct want to live",              # modifier-letter apostrophe
    "I want to kill  myself",                 # double space
    "I want to kill\nmyself",                 # line break
    "I want to kill\u00a0myself",             # non-breaking space
    "I want to \uff4b\uff49\uff4c\uff4c myself",    # full-width letters (NFKC)
    "I WANT TO END MY LIFE",
])
def test_self_harm_normalisation_variants(text):
    assert g.is_self_harm(text)


@pytest.mark.parametrize("text", ["I can\u2019t breathe", "heavy\u00a0bleeding", "BABY  IS NOT\tMOVING",
                                  "my waters\nbroke"])
def test_danger_sign_normalisation_variants(text):
    assert g.is_danger_sign(text)


def test_normalize_for_safety():
    assert g.normalize_for_safety(None) == ""
    assert g.normalize_for_safety("  A\u2019B \n\t C\u00a0D ") == "a'b c d"
    assert g.normalize_for_safety(123) == "123"


@pytest.mark.parametrize("text", [
    "I am tired of the nausea", "kill the pain please", "the dead baby clothes from my sister were washed",
    "I keep vomiting every morning",
    # partial approved phrases and their common component words must not trigger
    "ndinovave", "kubuda ropa", "ubulwele", "kapati", "ndiilonda", "ha ni zuba", "angifuni",
    "ukupila", "ndikufuna kudziwa", "hana", "mbilien zuba",
])
def test_false_positive_regressions(text):
    assert not g.is_self_harm(text)


# Formerly strict-xfail: the old pattern r"\bend (?:my|it all|my life)\b" matched any "end my".
@pytest.mark.parametrize("text", [
    "How can I end my nausea?", "how do I end my maternity leave early",
    "When will my morning sickness end? I want to end my vomiting",
    "how do i end my breastfeeding sessions", "I need to end my contract at work",
])
def test_end_my_ordinary_questions_are_not_self_harm(text):
    assert not g.is_self_harm(text)
    assert g.compose_reply(text, "english", "Model answer.").startswith("Model answer.")


@pytest.mark.parametrize("text", [
    "I want to end my life", "I am going to end my own life", "I just want to end it all",
    "I want to end my suffering", "I want to end my existence", "END MY LIFE",
    "I want to end\u00a0my  life",
])
def test_end_my_genuine_expressions_still_detected(text):
    assert g.is_self_harm(text)
    assert g.compose_reply(text, "english", "Model answer.") == f"💛 {g.SELF_HARM_DEFAULT}"


def test_assess_safety_structured_outcome():
    a = g.assess_safety("I am bleeding and I want to die")
    assert a.self_harm and a.danger_sign and a.urgent
    assert a.category == "self_harm"                      # self-harm outranks danger sign
    assert ("self_harm", "english", "want to die") in a.matches
    assert ("danger_sign", "pattern", "bleeding") in a.matches

    d = g.assess_safety("heavy bleeding")
    assert d.category == "danger_sign" and not d.self_harm

    n = g.assess_safety("What foods help with nausea?")
    assert n == g.SafetyAssessment(False, False) and n.category is None and not n.urgent
    assert g.assess_safety("") == g.SafetyAssessment(False, False)
    assert g.assess_safety(None).matches == ()


def test_fixture_structure_and_pending_status():
    assert set(g.MULTILINGUAL_SELF_HARM_FIXTURES) == set(LOCAL_LANGS)
    for lang in LOCAL_LANGS:
        phrases, description, status = g.MULTILINGUAL_SELF_HARM_FIXTURES[lang]
        assert phrases and all(isinstance(p, str) and p.strip() for p in phrases)
        assert description
        assert g.multilingual_self_harm_fixture_status(lang) == status
        assert lang in g.LOCAL_SELF_HARM_REVIEW_NOTES
    assert g.multilingual_self_harm_fixture_status("english") == "NOT_INCLUDED"


def test_submitted_phrase_text_is_unchanged():
    """The phrase wording must not be silently edited: these are the exact submitted strings."""
    assert {lang: entry[0] for lang, entry in g.MULTILINGUAL_SELF_HARM_FIXTURES.items()} == {
        "shona": ["ndinovave kubuda", "hana hunhu hwekushanda"],
        "ndebele": ["ngilokhu ngacabanga ngokuzibulala", "angifuni ukupila"],
        "chinyanja": ["sindikhuluphire ndikufuna kubvina"],
        "bemba": ["nshakusanga ubulwele"],
        "tonga": ["ndiilonda kapati"],
        "lozi": ["ha ni zuba mbilien"],
    }


APPROVED_PHRASES = [(lang, p) for lang in LOCAL_LANGS for p in g.MULTILINGUAL_SELF_HARM_FIXTURES[lang][0]]


def test_all_six_languages_are_active():
    for lang in LOCAL_LANGS:
        assert g.multilingual_self_harm_fixture_status(lang) == g.APPROVED
    assert sorted(g.approved_local_self_harm_phrases()) == sorted(APPROVED_PHRASES)
    assert len(APPROVED_PHRASES) == 8


@pytest.mark.parametrize("lang, phrase", APPROVED_PHRASES)
def test_each_approved_phrase_triggers_self_harm_reply(lang, phrase):
    """Exact phrase, shouted, extra spacing, inside a mixed English message: always detected,
    attributed to the right language, and the model answer is suppressed."""
    variants = [phrase, phrase.upper(), "  ".join(phrase.split()),
                f"Hello Rudo, quick question about my clinic visit. {phrase.capitalize()}."]
    for text in variants:
        a = g.assess_safety(text)
        assert a.self_harm and a.category == "self_harm", text
        assert ("self_harm", lang, phrase) in a.matches
        assert g.compose_reply(text, lang, "Model text.") == f"💛 {g.SELF_HARM_DEFAULT}"
        assert g.compose_reply(text, "english", None) == f"💛 {g.SELF_HARM_DEFAULT}"


@pytest.mark.parametrize("lang, phrase", APPROVED_PHRASES)
def test_approved_phrase_is_whole_word_only(lang, phrase):
    first, *rest = phrase.split()
    assert not g.is_self_harm("x" + phrase)                     # glued to a preceding word
    assert not g.is_self_harm(phrase + "x")                     # glued to a following word
    if rest:
        assert not g.is_self_harm(first)                        # first word alone


def test_status_gate_still_controls_activation(monkeypatch):
    """Setting a language back to PENDING switches its phrases off again (only that language)."""
    fixtures = dict(g.MULTILINGUAL_SELF_HARM_FIXTURES)
    phrases, desc, _ = fixtures["tonga"]
    fixtures["tonga"] = (phrases, desc, "PENDING")
    monkeypatch.setattr(g, "MULTILINGUAL_SELF_HARM_FIXTURES", fixtures)
    assert not g.is_self_harm("ndiilonda kapati")
    assert g.is_self_harm("angifuni ukupila")


def test_danger_sign_and_local_self_harm_together_self_harm_wins():
    out = g.compose_reply("ndiri kubuda ropa, angifuni ukupila", "shona", "Model text.")
    assert out == f"💛 {g.SELF_HARM_DEFAULT}"


def test_self_harm_fires_without_model_text_in_every_language():
    for lang in LOCAL_LANGS + ("english",):
        assert g.compose_reply("I want to kill myself", lang, None) == f"💛 {g.SELF_HARM_DEFAULT}"


def test_mixed_question_and_self_harm_suppresses_model_answer():
    out = g.compose_reply("What are antenatal visits? I don\u2019t want to live anymore", "english",
                          "You should attend at least 8 antenatal visits.")
    assert out == f"💛 {g.SELF_HARM_DEFAULT}"
    assert "8 antenatal visits" not in out


def test_mixed_question_and_danger_sign_keeps_model_answer():
    out = g.compose_reply("What should I eat? I am bleeding heavily.", "english", "Eat iron-rich foods.")
    assert out == f"⚠️ {g.SEE_DOCTOR_DEFAULT}\n\nEat iron-rich foods."


def test_self_harm_response_offers_human_agent():
    assert "*agent*" in g.compose_reply("I want to kill myself", "shona", None)
