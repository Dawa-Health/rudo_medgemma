"""
End-to-end safety routing: an urgent message (self-harm wording or a maternal danger sign) must
reach the guardrail response whatever conversation step the user is in, through the real webhook,
router and compose_reply. All messages are synthetic; WhatsApp, Supabase and models are faked.

The "test-only phrase" used to exercise local-language activation is a synthetic token, not a
translation: no unapproved wording is ever used as if it were approved.
"""
import json

import pytest

import main
import medgemma_guardrails as g
from conftest import PHONE_ID, USER, wa_text

AGENT = main.AGENTS["Agent 1"]
ANSWER = "Drink plenty of water and attend your antenatal visits regularly."
SUPPORT = f"💛 {g.SELF_HARM_DEFAULT}"
REFERRAL = f"⚠️ {g.SEE_DOCTOR_DEFAULT}"
SELF_HARM_MSGS = ["I want to kill myself", "I don’t want to live anymore",
                  "i want to KILL MYSELF", "I want to end\nmy life"]
DANGER_MSGS = ["I am bleeding a lot", "I can’t breathe", "the baby stopped  moving"]
SYNTHETIC_PHRASE = "zzqx test phrase"


@pytest.fixture(autouse=True)
def footer_on(monkeypatch):
    monkeypatch.setattr(g, "FOOTER_ON", True)


def registered(bot, lang="english", step="chat", **extra):
    bot.db.users[USER] = {"step": step, "language": lang, "registered": True,
                          "user_id": "DH-0001-TEST", "first_message": False, **extra}


def post(bot, text, msg_id=None):
    r = bot.client.post("/webhook", json=wa_text(USER, text, msg_id=msg_id))
    assert r.status_code == 200


def texts(bot):
    return bot.wa.texts_to(USER)


@pytest.fixture
def approve_synthetic(monkeypatch):
    """Activate one synthetic phrase for 'bemba' to test the activation path."""
    fixtures = dict(g.MULTILINGUAL_SELF_HARM_FIXTURES)
    fixtures["bemba"] = ([SYNTHETIC_PHRASE], "test-only", g.APPROVED)
    monkeypatch.setattr(g, "MULTILINGUAL_SELF_HARM_FIXTURES", fixtures)


# ─────────────── shop steps must not swallow urgent messages ───────────────

SHOP_CASES = [
    ("shop_quantity", {"shop_selected_product": "Birth kit", "shop_selected_price": "K200"}),
    ("shop_address", {"cart": [{"product": "Birth kit", "price": "K200", "quantity": 1}]}),
    ("shop_browse", {}),
    ("shop_product_name", {}),
    ("shop_order_decision", {}),
    ("shop_add_more", {"cart": [{"product": "Birth kit", "price": "K200", "quantity": 1}]}),
    ("shop_interest", {}),
    ("shop_more_categories", {}),
]


@pytest.mark.parametrize("step, extra", SHOP_CASES)
def test_self_harm_during_shop_gets_support_not_shop_reply(bot, step, extra):
    registered(bot, step=step, **extra)
    bot.models.lang = "english"
    post(bot, "kill myself")                       # short: not caught by the "new question" escape
    assert SUPPORT in texts(bot)
    assert bot.db.orders == []                     # never saved as a delivery address
    st = bot.db.users[USER]
    assert "cart" not in st and st["step"] == "chat"
    # stored so later MedGemma context is coherent (shop replies are otherwise not stored)
    assert bot.db.messages[USER][0]["message"] == "kill myself"


@pytest.mark.parametrize("step, extra", SHOP_CASES)
def test_danger_sign_during_shop_gets_referral(bot, step, extra):
    registered(bot, step=step, **extra)
    bot.models.lang = "english"
    post(bot, "bleeding heavily")
    assert any(t.startswith(REFERRAL) for t in texts(bot))
    assert bot.db.orders == []


def test_ordinary_shop_reply_still_works(bot):
    registered(bot, step="shop_quantity", shop_selected_product="Birth kit", shop_selected_price="K200")
    post(bot, "2")
    assert bot.db.users[USER]["cart"][0]["quantity"] == 2
    assert bot.models.medgemma_questions == []


def test_address_with_no_urgent_wording_is_still_saved(bot):
    registered(bot, step="shop_address", cart=[{"product": "Birth kit", "price": "K200", "quantity": 1}])
    post(bot, "Plot 7, Test Road, agent street, restart estate")     # keyword-looking but not urgent
    assert bot.db.orders[0]["address"] == "Plot 7, Test Road, agent street, restart estate"


# ─────────────── follow-up yes/no must not swallow urgent messages ───────────────

@pytest.mark.parametrize("text", ["yes kill myself", "no I'm bleeding", "no, want to die"])
def test_urgent_short_follow_up_reply_is_answered(bot, text):
    registered(bot, step="follow_up")
    bot.models.lang = "english"
    post(bot, text)
    out = texts(bot)
    assert any(t.startswith("💛") or t.startswith("⚠️") for t in out)
    assert not any("purchase" in t for t in out)
    assert main.ASK_QUESTION_MAP.get("english", "Please ask your question.") not in out


def test_plain_follow_up_no_still_offers_products(bot):
    registered(bot, step="follow_up")
    bot.models.lang = "english"
    post(bot, "no")
    assert bot.db.users[USER]["step"] == "shop_interest"


# ─────────────── self-harm must not be followed by "anything else?" / product offers ───────────────

def test_no_follow_up_or_product_offer_after_self_harm_support(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, "I want to kill myself")
    out = texts(bot)
    assert out[-1] == SUPPORT
    assert "Is there anything else I can help you with?" not in out
    assert bot.db.users[USER]["step"] == "chat"
    post(bot, "no")                                         # a following "no" is not a shop opt-in
    assert bot.db.users[USER]["step"] != "shop_interest"


def test_danger_sign_answer_keeps_follow_up(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, "I have heavy bleeding, what should I do?")
    out = texts(bot)
    assert any(t.startswith(REFERRAL) and ANSWER in t for t in out)
    assert out[-1] == "Is there anything else I can help you with?"


# ─────────────── reset / agent request combined with urgent wording ───────────────

def test_reset_word_with_self_harm_is_not_treated_as_reset(bot):
    bot.db.add_message(USER, "user", "earlier")
    registered(bot)
    bot.models.lang = "english"
    post(bot, "restart, I want to die")
    assert SUPPORT in texts(bot)
    assert "Hello! How can I help you today?" not in texts(bot)


def test_agent_request_with_self_harm_sends_support_and_escalates(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, "I want to kill myself, let me talk to someone")
    out = texts(bot)
    assert out[0] == SUPPORT
    assert "Looking for a human agent" in out[1]
    assert bot.db.users[USER]["step"] == "waiting_for_agent"
    assert bot.wa.interactive_to(AGENT)                       # escalation preserved


def test_plain_agent_request_unchanged(bot):
    registered(bot)
    post(bot, "talk to someone")
    assert "Looking for a human agent" in texts(bot)[0]
    assert len(texts(bot)) == 1


# ─────────────── waiting for an agent ───────────────

@pytest.mark.parametrize("text, expected", [("I want to kill myself", SUPPORT),
                                            ("I am bleeding a lot", REFERRAL)])
def test_urgent_message_while_waiting_for_agent_gets_response(bot, text, expected):
    registered(bot, step="waiting_for_agent")
    bot.kv.store[main._agent_request_key(USER)] = json.dumps({"status": "pending"})
    post(bot, text)
    assert texts(bot) == [expected]
    assert bot.db.users[USER]["step"] == "waiting_for_agent"          # still queued for a human
    assert bot.models.medgemma_questions == []


def test_ordinary_message_while_waiting_is_still_silent(bot):
    registered(bot, step="waiting_for_agent")
    bot.kv.store[main._agent_request_key(USER)] = json.dumps({"status": "pending"})
    post(bot, "hello?")
    assert texts(bot) == []


# ─────────────── human-agent session: urgent text still goes to the human ───────────────

def test_urgent_message_in_agent_session_is_relayed_to_agent(bot):
    registered(bot, step="human_agent_chat", agent_phone=AGENT)
    bot.kv.store[main._agent_session_key(USER)] = json.dumps({"agent_phone": AGENT})
    post(bot, "I want to kill myself")
    assert "I want to kill myself" in bot.wa.all_text(AGENT)
    assert bot.models.medgemma_questions == []


# ─────────────── normalisation through the full pipeline ───────────────

@pytest.mark.parametrize("text", SELF_HARM_MSGS)
def test_self_harm_variants_end_to_end(bot, text):
    registered(bot)
    bot.models.lang = "english"
    post(bot, text)
    assert SUPPORT in texts(bot)
    assert not any(ANSWER in t for t in texts(bot))


@pytest.mark.parametrize("text", DANGER_MSGS)
def test_danger_variants_end_to_end(bot, text):
    registered(bot)
    bot.models.lang = "english"
    post(bot, text)
    assert any(t.startswith(REFERRAL) for t in texts(bot))


# ─────────────── service failures ───────────────

def test_self_harm_with_translation_down_and_lang_id_failing(bot):
    registered(bot, lang="shona")
    bot.models.lang = None                                  # Gemini classifier unavailable

    def down(*a):
        raise RuntimeError("TranslateGemma down")
    bot.models.translate_fn = down
    post(bot, "Ndine shungu, I want to die")                # mixed-language message
    assert SUPPORT in texts(bot)


def test_self_harm_with_medgemma_down(bot, monkeypatch):
    registered(bot)
    bot.models.lang = "english"
    monkeypatch.setattr(main, "medgemma_enabled", lambda: False)
    post(bot, "I want to end my life")
    assert texts(bot)[-1] == SUPPORT


@pytest.mark.parametrize("model_output", [None, "", "<eos>", "ok.", "Rest. Rest. Rest. Rest."])
def test_danger_sign_with_missing_or_malformed_model_output(bot, model_output):
    registered(bot)
    bot.models.lang = "english"
    bot.models.medgemma = [model_output]
    post(bot, "my waters broke")
    assert texts(bot)[-1] == REFERRAL or texts(bot)[-2] == REFERRAL


def test_duplicate_urgent_delivery_answered_once(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, "I want to kill myself", msg_id="wamid.urgent")
    post(bot, "I want to kill myself", msg_id="wamid.urgent")
    assert texts(bot).count(SUPPORT) == 1


# ─────────────── local-language activation path (synthetic phrase) ───────────────

LANG_PHRASES = [(lang, p) for lang, (ps, _d, _s) in g.MULTILINGUAL_SELF_HARM_FIXTURES.items() for p in ps]


def test_all_local_languages_active_in_production():
    assert {lang for lang, _ in LANG_PHRASES} == {"shona", "ndebele", "chinyanja", "bemba", "tonga", "lozi"}
    assert all(g.multilingual_self_harm_fixture_status(l) == g.APPROVED for l, _ in LANG_PHRASES)


@pytest.mark.parametrize("lang, phrase", LANG_PHRASES)
def test_local_phrase_end_to_end_with_translation_and_langid_down(bot, lang, phrase):
    """Real webhook -> router -> answer pipeline. TranslateGemma raises, the Gemini language
    classifier returns nothing, MedGemma must not be consulted, and the user gets the support
    message and no follow-up/product prompt."""
    registered(bot, lang=lang)
    bot.models.lang = None

    def down(*a):
        raise RuntimeError("translator down")
    bot.models.translate_fn = down
    post(bot, phrase)
    assert texts(bot)[-1] == SUPPORT
    assert bot.models.medgemma_questions == []
    assert bot.models.translations == []                 # never waited on translation
    assert bot.db.users[USER]["step"] == "chat"


@pytest.mark.parametrize("lang, phrase", LANG_PHRASES)
def test_local_phrase_detected_when_language_misclassified_as_english(bot, lang, phrase):
    registered(bot, lang="english")
    bot.models.lang = "english"
    post(bot, f"Hi, I have a question about my clinic visit. {phrase}")
    assert SUPPORT in texts(bot)
    assert not any(ANSWER in t for t in texts(bot))


@pytest.mark.parametrize("step, extra", [
    ("shop_quantity", {"shop_selected_product": "Birth kit", "shop_selected_price": "K200"}),
    ("shop_address", {"cart": [{"product": "Birth kit", "price": "K200", "quantity": 1}]}),
    ("follow_up", {}),
])
@pytest.mark.parametrize("lang, phrase", LANG_PHRASES)
def test_local_phrase_not_swallowed_by_shop_or_follow_up(bot, step, extra, lang, phrase):
    registered(bot, lang=lang, step=step, **extra)
    bot.models.lang = lang
    post(bot, phrase)
    assert SUPPORT in texts(bot)
    assert bot.db.orders == []
    assert bot.db.users[USER]["step"] == "chat"


@pytest.mark.parametrize("lang, phrase", LANG_PHRASES)
def test_local_phrase_while_waiting_for_agent(bot, lang, phrase):
    registered(bot, lang=lang, step="waiting_for_agent")
    bot.kv.store[main._agent_request_key(USER)] = json.dumps({"status": "pending"})
    post(bot, phrase)
    assert texts(bot) == [SUPPORT]
    assert bot.db.users[USER]["step"] == "waiting_for_agent"     # still queued for a human


def test_local_phrase_with_agent_request_escalates(bot):
    registered(bot, lang="ndebele")
    bot.models.lang = "ndebele"
    post(bot, "angifuni ukupila, ngifuna ukukhuluma lomuntu, talk to someone")
    out = texts(bot)
    assert out[0] == SUPPORT and out[1] == main.CONNECTING_MAP["ndebele"]
    assert bot.db.users[USER]["step"] == "waiting_for_agent"
    assert bot.wa.interactive_to(AGENT)


def test_local_phrase_in_agent_session_goes_to_human(bot):
    registered(bot, lang="bemba", step="human_agent_chat", agent_phone=AGENT)
    bot.kv.store[main._agent_session_key(USER)] = json.dumps({"agent_phone": AGENT})
    post(bot, "nshakusanga ubulwele")
    assert "nshakusanga ubulwele" in bot.wa.all_text(AGENT)
    assert texts(bot) == []


def test_duplicate_local_phrase_delivery_answered_once(bot):
    registered(bot, lang="tonga")
    post(bot, "ndiilonda kapati", msg_id="wamid.tonga")
    post(bot, "ndiilonda kapati", msg_id="wamid.tonga")
    assert texts(bot).count(SUPPORT) == 1


@pytest.mark.parametrize("lang, text", [
    ("bemba", "Ndi ne fumo, ubulwele bwa mutwe"),      # contains "ubulwele" only
    ("tonga", "Ndiyanda kuziba kapati"),               # contains "kapati" only
    ("shona", "Ndiri kubuda ropa"),                   # danger sign, not self-harm
    ("ndebele", "Ngifuna ukwazi ngempilo"),
])
def test_ordinary_local_messages_still_reach_medgemma_or_referral(bot, lang, text):
    registered(bot, lang=lang)
    bot.models.lang = lang
    bot.models.translate_fn = lambda t, s, d: "question in English" if d == "english" else \
        "Enda kukiriniki uye inwa mvura yakawanda mazuva ose."
    post(bot, text)
    assert SUPPORT not in texts(bot)
    assert bot.models.medgemma_questions == ["question in English"]


def test_approved_phrase_routes_to_support_without_translation(bot, approve_synthetic):
    registered(bot, lang="bemba")
    bot.models.lang = None

    def down(*a):
        raise RuntimeError("translator down")
    bot.models.translate_fn = down
    post(bot, "ZZQX   Test Phrase.")
    assert texts(bot)[-1] == SUPPORT
    assert bot.models.medgemma_questions == []


def test_approved_phrase_detected_when_language_misclassified(bot, approve_synthetic):
    registered(bot, lang="english")
    bot.models.lang = "english"                            # classifier wrongly says English
    post(bot, "Hello. zzqx test phrase")
    assert SUPPORT in texts(bot)


def test_approved_phrase_during_shop_step(bot, approve_synthetic):
    registered(bot, lang="bemba", step="shop_quantity")
    post(bot, "zzqx test phrase")
    assert SUPPORT in texts(bot)
    assert bot.db.users[USER]["step"] == "chat"


def test_approved_phrase_is_whole_word_only(approve_synthetic):
    assert g.is_self_harm("zzqx test phrase")
    assert not g.is_self_harm("zzqxx test phrases")
    assert not g.is_self_harm("azzqx test phrase")
    assert g.assess_safety("zzqx test phrase").matches == (("self_harm", "bemba", SYNTHETIC_PHRASE),)
