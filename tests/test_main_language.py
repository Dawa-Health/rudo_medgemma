"""main.py language detection: Gemini classifier (mocked), keyword fallback, language switching."""
from types import SimpleNamespace

import pytest

import main
from conftest import USER


# ─────────────── Gemini classifier ───────────────

class FakeClassifier:
    def __init__(self, response=None, exc=None):
        self.response, self.exc = response, exc
        self.init_kwargs = None
        self.prompts = []

    def __call__(self, **kwargs):          # stands in for genai.GenerativeModel(...)
        self.init_kwargs = kwargs
        return self

    def generate_content(self, prompt):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return self.response


def resp(text, finish=1, candidates=True):
    cands = [SimpleNamespace(finish_reason=finish, safety_ratings=[])] if candidates else []
    return SimpleNamespace(candidates=cands, text=text)


@pytest.fixture
def classifier(monkeypatch):
    def install(**kw):
        fake = FakeClassifier(**kw)
        monkeypatch.setattr(main.genai, "GenerativeModel", fake)
        return fake
    return install


def test_llm_detect_valid_language(classifier):
    fake = classifier(response=resp(" Shona.\n"))
    assert main._llm_detect_language("Ndine pamuviri") == "shona"
    assert fake.init_kwargs["model_name"] == main.model_name
    assert fake.init_kwargs["generation_config"]["temperature"] == 0
    assert 'Message: "Ndine pamuviri"' in fake.prompts[0]


@pytest.mark.parametrize("response", [
    resp("klingon"),                 # unsupported label
    resp("shona", finish=3),         # blocked by safety
    resp("", candidates=False),      # nothing returned
])
def test_llm_detect_rejects_bad_output(classifier, response):
    classifier(response=response)
    assert main._llm_detect_language("text") is None


def test_llm_detect_api_error_returns_none(classifier):
    classifier(exc=RuntimeError("quota exceeded"))
    assert main._llm_detect_language("text") is None


# ─────────────── detect_language ───────────────

@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setattr(main, "_llm_detect_language", lambda m: None)
    monkeypatch.setattr(main, "user_states", {})


def test_digits_keep_current_language(no_llm):
    main.user_states[USER] = {"language": "bemba"}
    assert main.detect_language("12", USER) == "bemba"
    assert main.detect_language("12") == "english"


@pytest.mark.parametrize("word, lang", [
    ("mhoro", "shona"), ("sawubona", "ndebele"), ("mwaiseni", "bemba"),
    ("zikomo", "chinyanja"), ("mwabuka", "tonga"), ("ndalumba", "lozi"),
])
def test_exact_matches_skip_the_model(monkeypatch, word, lang):
    monkeypatch.setattr(main, "_llm_detect_language", lambda m: pytest.fail("LLM must not be called"))
    assert main.detect_language(word.upper()) == lang


def test_llm_result_is_used(monkeypatch):
    monkeypatch.setattr(main, "_llm_detect_language", lambda m: "tonga")
    monkeypatch.setattr(main, "user_states", {USER: {"language": "english"}})
    assert main.detect_language("Ndiyanda kuziba", USER) == "tonga"
    monkeypatch.setattr(main, "_llm_detect_language", lambda m: "english")
    assert main.detect_language("hello there friend", USER) == "english"


@pytest.mark.parametrize("text, lang", [
    ("How are you, I need help with pregnancy", "english"),
    ("ndinoda kuziva nezve nhumbu yangu", "shona"),
    ("ngifuna ukwazi ngesisu", "ndebele"),
    ("ndikufuna kudziwa za mimba", "chinyanja"),
])
def test_keyword_fallback_when_llm_unavailable(no_llm, text, lang):
    assert main.detect_language(text) == lang


def test_keyword_fallback_tie_prefers_current_language(no_llm):
    # "kuti" scores for both chinyanja and bemba.
    main.user_states[USER] = {"language": "bemba"}
    assert main.detect_language("kuti", USER) == "bemba"
    main.user_states[USER] = {"language": "english"}
    assert main.detect_language("kuti", USER) in ("chinyanja", "bemba")


def test_keyword_fallback_no_signal_keeps_current(no_llm):
    main.user_states[USER] = {"language": "lozi"}
    assert main.detect_language("xyzzy qwerty", USER) == "lozi"


# ─────────────── maybe_update_language ───────────────

def test_maybe_update_language(bot, monkeypatch):
    m = bot.main
    m.user_states[USER] = {"language": "shona", "step": "chat"}

    assert m.maybe_update_language(USER, "   ") == "shona"
    assert m.maybe_update_language(USER, "42") == "shona"

    bot.models.lang = "english"
    assert m.maybe_update_language(USER, "ok thanks") == "shona"   # too short to flip

    bot.models.lang = "ndebele"
    assert m.maybe_update_language(USER, "ngifuna ukwazi ngesisu sami") == "ndebele"
    assert bot.db.users[USER]["language"] == "ndebele"              # persisted

    bot.models.lang = "ndebele"
    assert m.maybe_update_language(USER, "ngiyabonga kakhulu wena") == "ndebele"
