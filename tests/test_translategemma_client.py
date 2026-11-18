"""TranslateGemma + Gemini translation pipeline. All HTTP and Gemini calls are mocked."""
import json
from types import SimpleNamespace

import pytest

import translategemma_client as tc
from conftest import FakeResponse


def gem_response(text, finish=1, candidates=True):
    cands = [SimpleNamespace(finish_reason=finish)] if candidates else []
    return SimpleNamespace(candidates=cands, text=text)


class FakeGemini:
    """Returns queued responses (or raises queued exceptions) and records prompts."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, prompt, generation_config=None):
        self.calls.append({"prompt": prompt, "cfg": generation_config})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def gem(monkeypatch):
    def install(*responses):
        fake = FakeGemini(*responses)
        monkeypatch.setattr(tc, "_gem_model", fake)
        return fake
    return install


@pytest.fixture
def tg_on(monkeypatch):
    monkeypatch.setattr(tc, "TG_URL", "https://tg.test/translate")
    monkeypatch.setattr(tc, "TG_TOKEN", "tg-token")
    monkeypatch.setattr(tc, "TG_IN_LANGS", {"shona", "chinyanja", "ndebele"})
    monkeypatch.setattr(tc, "TG_OUT_LANGS", set())
    monkeypatch.setattr(tc, "VERIFY_ALL", False)
    monkeypatch.setattr(tc, "VERIFY_OUT", True)


# ─────────────── configuration helpers ───────────────

def test_lang_set_parsing():
    assert tc._lang_set(" Shona, ,NDEBELE ,") == {"shona", "ndebele"}
    assert tc._lang_set("") == set()


def test_defaults_route_local_languages_through_pivot():
    for lang in ("shona", "ndebele", "chinyanja", "bemba", "tonga", "lozi"):
        assert tc.needs_translation(lang)
    assert not tc.needs_translation("english")


def test_translategemma_enabled(monkeypatch):
    monkeypatch.setattr(tc, "TG_URL", None)
    assert tc.translategemma_enabled() is False
    monkeypatch.setattr(tc, "TG_URL", "https://x")
    assert tc.translategemma_enabled() is True


def test_gem_requires_key(monkeypatch):
    monkeypatch.setattr(tc, "_gem_model", None)
    monkeypatch.delenv("GEN_API", raising=False)
    with pytest.raises(RuntimeError, match="GEN_API"):
        tc._gem()


def test_gem_lazily_builds_model_once(monkeypatch):
    built = []
    monkeypatch.setattr(tc, "_gem_model", None)
    monkeypatch.setenv("GEN_API", "fake")
    monkeypatch.delenv("GEN_MODEL", raising=False)
    monkeypatch.setattr(tc.genai, "configure", lambda api_key: built.append(("cfg", api_key)))
    monkeypatch.setattr(tc.genai, "GenerativeModel",
                        lambda name, safety_settings=None: built.append(("model", name)) or "MODEL")
    assert tc._gem() == "MODEL"
    assert tc._gem() == "MODEL"
    assert built == [("cfg", "fake"), ("model", "gemini-2.5-flash")]


# ─────────────── masking / chunking ───────────────

def test_mask_and_unmask_protected_terms():
    text = "Get an HPV test and an Ultrasound at Dawa Health; cervical cancer screening."
    masked, mapping = tc._mask(text)
    assert "HPV" not in masked and "cervical cancer" not in masked.lower()
    assert all(tok in masked for tok in mapping)
    restored = tc._unmask(masked, mapping)
    # canonical casing is restored
    assert "ultrasound" in restored and "HPV" in restored and "Dawa Health" in restored


def test_mask_no_terms():
    assert tc._mask("nothing here") == ("nothing here", {})


def test_chunks_short_and_long():
    assert tc._chunks("abc", 10) == ["abc"]
    text = "line one\nline two\nline three"
    assert tc._chunks(text, 18) == ["line one\nline two", "line three"]
    # a single line longer than the limit is kept whole
    assert tc._chunks("x" * 30 + "\nshort", 10) == ["x" * 30, "short"]
    assert tc._chunks("\n" + "y" * 12, 10) == ["y" * 12]


# ─────────────── TranslateGemma HTTP ───────────────

def test_translate_chunk_sends_auth_and_codes(monkeypatch, tg_on):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return FakeResponse(200, {"translation": "  Hello  "})

    monkeypatch.setattr(tc.requests, "post", fake_post)
    assert tc._translate_chunk("Mhoro", "sn", "en") == "Hello"
    assert seen["json"] == {"text": "Mhoro", "source_lang_code": "sn", "target_lang_code": "en"}
    assert seen["headers"]["Authorization"] == "Bearer tg-token"


def test_translate_chunk_without_token(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "TG_TOKEN", "")
    seen = {}
    monkeypatch.setattr(tc.requests, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        seen.update(h=headers) or FakeResponse(200, {"translation": "ok"}))
    tc._translate_chunk("x", "sn", "en")
    assert "Authorization" not in seen["h"]


@pytest.mark.parametrize("resp", [FakeResponse(200, {"translation": "   "}), FakeResponse(200, {})])
def test_translate_chunk_empty_raises(monkeypatch, tg_on, resp):
    monkeypatch.setattr(tc.requests, "post", lambda *a, **k: resp)
    with pytest.raises(ValueError):
        tc._translate_chunk("x", "sn", "en")


def test_translate_chunk_http_error(monkeypatch, tg_on):
    monkeypatch.setattr(tc.requests, "post", lambda *a, **k: FakeResponse(502))
    with pytest.raises(RuntimeError):
        tc._translate_chunk("x", "sn", "en")


def test_tg_translate_masks_chunks_and_unmasks(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "TG_MAX_CHARS", 12)
    sent = []

    def fake_chunk(text, src, tgt):
        sent.append((text, src, tgt))
        return text.upper()

    monkeypatch.setattr(tc, "_translate_chunk", fake_chunk)
    out = tc._tg_translate("hpv kit\n\nbuy now", "shona", "english")
    assert all(s[1:] == ("sn", "en") for s in sent)
    assert "HPV" in out
    assert not any("hpv" in s[0].lower() for s in sent)   # protected term never sent


def test_tg_translate_keeps_blank_chunks(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "TG_MAX_CHARS", 3)
    monkeypatch.setattr(tc, "_chunks", lambda text, limit: ["abc", "   "])
    monkeypatch.setattr(tc, "_translate_chunk", lambda t, s, d: "X")
    assert tc._tg_translate("whatever", "shona", "english") == "X\n"


# ─────────────── Gemini helpers ───────────────

def test_finished_ok_variants():
    assert tc._finished_ok(gem_response("x")) is True
    assert tc._finished_ok(gem_response("x", finish=SimpleNamespace(value=1))) is True
    assert tc._finished_ok(gem_response("x", finish=2)) is False
    assert tc._finished_ok(gem_response("x", candidates=False)) is False


def test_english_leak_detection():
    assert tc._english_leak_ratio("too short") == 0.0
    english = "You should go to the doctor when the pain is bad"
    assert tc._english_leak_ratio(english) > tc._LEAK_THRESHOLD
    assert tc._looks_like_english_leak(english, "shona")
    assert not tc._looks_like_english_leak(english, "english")
    assert not tc._looks_like_english_leak("", "shona")
    assert not tc._looks_like_english_leak("Enda kuchiremba kana uine kurwadziwa kwakanyanya zvikuru", "shona")


def test_gemini_generate_success_and_temperature(gem):
    fake = gem(gem_response("  Mhoro  "))
    assert tc._gemini_generate("p", temperature=0.7) == "Mhoro"
    assert fake.calls[0]["cfg"]["temperature"] == 0.7
    assert fake.calls[0]["cfg"]["max_output_tokens"] == 4096


@pytest.mark.parametrize("resp", [gem_response("x", finish=2), gem_response("   "), gem_response(None)])
def test_gemini_generate_rejects_truncated_or_empty(gem, resp):
    gem(resp)
    with pytest.raises(ValueError):
        tc._gemini_generate("p", 0.3)


def test_gemini_translate_to_english_prompt(gem):
    fake = gem(gem_response("I have pain in XQ5Z results."))
    out = tc._gemini_translate("Ndine marwadzo HPV", "shona", "english")
    assert out == "I have pain in HPV results."
    prompt = fake.calls[0]["prompt"]
    assert prompt.startswith("Respond in English only.")
    assert "from Shona into clear" in prompt
    assert "HPV" not in prompt.split("Message:")[1]


def test_gemini_translate_uses_language_enforcement(gem):
    fake = gem(gem_response("Enda kuchiremba nekukurumidza."))
    tc._gemini_translate("Go to the clinic quickly.", "english", "shona")
    assert fake.calls[0]["prompt"].startswith(tc.LANG_ENFORCE["shona"])


def test_gemini_translate_enforce_fallback_for_language_without_line(gem, monkeypatch):
    monkeypatch.setitem(tc.GEM_NAMES, "testlang", "Testlang")
    fake = gem(gem_response("ok translated text."))
    tc._gemini_translate("hello", "english", "testlang")
    assert fake.calls[0]["prompt"].startswith("Respond in Testlang only.")


LEAKY = "You should go to the clinic when the baby is not moving and the pain is bad"
LESS_LEAKY = "Enda kukiriniki kana mwana asiri kufamba uye the marwadzo akawanda"
CLEAN = "Enda kukiriniki kana mwana asiri kufamba uye marwadzo akawanda zvikuru"


def test_gemini_translate_retries_on_english_leak_and_keeps_better(gem):
    fake = gem(gem_response(LEAKY), gem_response(CLEAN))
    assert tc._gemini_translate("src", "english", "shona") == CLEAN
    assert fake.calls[1]["prompt"].startswith("CRITICAL")
    assert fake.calls[1]["cfg"]["temperature"] == tc.GEM_RETRY_TEMP


def test_gemini_translate_keeps_first_when_retry_not_better(gem):
    gem(gem_response(LEAKY), gem_response(LEAKY))
    assert tc._gemini_translate("src", "english", "shona") == LEAKY


def test_gemini_translate_keeps_first_when_retry_fails(gem):
    gem(gem_response(LEAKY), gem_response("x", finish=3))
    assert tc._gemini_translate("src", "english", "shona") == LEAKY


def test_gemini_translate_raises_when_first_attempt_fails(gem):
    gem(RuntimeError("quota"))
    with pytest.raises(RuntimeError):
        tc._gemini_translate("src", "english", "shona")


# ─────────────── Gemini review ───────────────

def test_review_ok(gem):
    fake = gem(gem_response(json.dumps({"ok": True, "translation": ""})))
    assert tc._gemini_review("src", "shona", "cand", "english") == (True, "")
    assert fake.calls[0]["cfg"]["response_mime_type"] == "application/json"


def test_review_correction(gem):
    gem(gem_response(json.dumps({"ok": False, "translation": "  fixed  "})))
    assert tc._gemini_review("src", "english", "cand", "shona") == (False, "fixed")


def test_review_null_translation(gem):
    gem(gem_response(json.dumps({"ok": False, "translation": None})))
    assert tc._gemini_review("s", "english", "c", "shona") == (False, "")


@pytest.mark.parametrize("resp", [gem_response("{}", finish=2), gem_response("not json"),
                                  RuntimeError("down")])
def test_review_failure_keeps_candidate(gem, resp):
    gem(resp)
    assert tc._gemini_review("s", "english", "c", "shona") == (True, "")


# ─────────────── heuristics / debug ───────────────

@pytest.mark.parametrize("src, out, unsure", [
    ("hello there", "", True),
    ("hello there", "   ", True),
    ("this sentence is longer than twenty", "this sentence is longer than twenty", True),
    ("a reasonably long source sentence", "short", True),
    ("hi", "a translation that is very much longer than three times", True),
    ("take 2 tablets", "tora mapiritsi 3", True),
    ("take 2 tablets daily", "tora mapiritsi 2 zuva", False),
    ("short", "short", False),
])
def test_looks_unsure(src, out, unsure):
    assert tc._looks_unsure(src, out) is unsure


def test_dbg_logs_only_when_enabled(monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr(tc, "TRANSLATE_DEBUG", False)
    tc._dbg("e", "a", "b", "in", "out")
    assert "translate-debug" not in caplog.text
    monkeypatch.setattr(tc, "TRANSLATE_DEBUG", True)
    tc._dbg("e", "a", "b", "in", "out")
    assert "translate-debug" in caplog.text


# ─────────────── translate() routing ───────────────

@pytest.mark.parametrize("text, src, tgt", [("", "shona", "english"), ("   ", "shona", "english"),
                                            ("same", "shona", "shona")])
def test_translate_noop(text, src, tgt):
    assert tc.translate(text, src, tgt) == text


def test_translate_inbound_uses_translategemma(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "_tg_translate", lambda t, s, d: "I am pregnant")
    monkeypatch.setattr(tc, "_gemini_review", lambda *a: pytest.fail("no review expected"))
    assert tc.translate("Ndine pamuviri", "shona", "english") == "I am pregnant"


def test_translate_without_tg_url_uses_gemini(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "TG_URL", None)
    monkeypatch.setattr(tc, "_gemini_translate", lambda t, s, d: "via gemini")
    assert tc.translate("Ndine pamuviri", "shona", "english") == "via gemini"


def test_translate_outbound_defaults_to_gemini(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "_tg_translate", lambda *a: pytest.fail("TG must not be used outbound"))
    monkeypatch.setattr(tc, "_gemini_translate", lambda t, s, d: "Enda kukiriniki")
    assert tc.translate("Go to the clinic", "english", "shona") == "Enda kukiriniki"


def test_translate_language_not_in_tg_list_uses_gemini(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "_gemini_translate", lambda t, s, d: "bemba->en")
    assert tc.translate("Muli shani", "bemba", "english") == "bemba->en"


def test_translate_tg_failure_falls_back_to_gemini(monkeypatch, tg_on):
    def boom(*a):
        raise RuntimeError("TG down")
    monkeypatch.setattr(tc, "_tg_translate", boom)
    monkeypatch.setattr(tc, "_gemini_translate", lambda t, s, d: "fallback")
    assert tc.translate("Ndine pamuviri", "shona", "english") == "fallback"


def test_translate_outbound_tg_is_reviewed_and_overridden(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "TG_OUT_LANGS", {"shona"})
    monkeypatch.setattr(tc, "_tg_translate", lambda *a: "bad translation")
    monkeypatch.setattr(tc, "_gemini_review", lambda *a: (False, "corrected"))
    assert tc.translate("Go to the clinic now", "english", "shona") == "corrected"


def test_translate_review_ok_keeps_tg_output(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "VERIFY_ALL", True)
    monkeypatch.setattr(tc, "_tg_translate", lambda *a: "I am pregnant")
    monkeypatch.setattr(tc, "_gemini_review", lambda *a: (True, ""))
    assert tc.translate("Ndine pamuviri", "shona", "english") == "I am pregnant"


def test_translate_review_rejects_without_fix_keeps_tg(monkeypatch, tg_on):
    monkeypatch.setattr(tc, "_tg_translate", lambda *a: "")           # unsure -> reviewed
    monkeypatch.setattr(tc, "_gemini_review", lambda *a: (False, ""))
    assert tc.translate("Ndine pamuviri", "shona", "english") == ""


def test_translate_unsure_numbers_trigger_review(monkeypatch, tg_on):
    calls = []
    monkeypatch.setattr(tc, "_tg_translate", lambda *a: "I am 5 months pregnant now")
    monkeypatch.setattr(tc, "_gemini_review",
                        lambda *a: calls.append(a) or (False, "I am 7 months pregnant now"))
    assert tc.translate("Ndine mwedzi 7 ndine pamuviri", "shona", "english") == "I am 7 months pregnant now"
    assert calls
