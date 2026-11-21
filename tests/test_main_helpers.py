"""main.py: WhatsApp sending, text classifiers, referral parsing, onboarding helpers."""
from types import SimpleNamespace

import pytest

import main
from conftest import PHONE_ID, USER


# ─────────────── signal matching ───────────────

def test_contains_signal_word_boundaries_and_phrases():
    assert main._contains_signal("i need an agent now", ["agent"])
    assert not main._contains_signal("reagents in the lab", ["agent"])
    assert main._contains_signal("please talk to a person", ["talk to a person"])
    assert not main._contains_signal("anything", [])


def test_normalize_phone():
    assert main.normalize_phone("+260978760105") == "260978760105"
    assert main.normalize_phone("263770000001") == "263770000001"


# ─────────────── WhatsApp sending ───────────────

def test_split_for_whatsapp():
    assert main._split_for_whatsapp("short") == ["short"]
    text = "a" * 6 + "\n" + "b" * 6 + "\n" + "c" * 3
    assert main._split_for_whatsapp(text, limit=10) == ["a" * 6, "b" * 6 + "\n" + "c" * 3]
    assert main._split_for_whatsapp("x" * 15 + "\nyy", limit=10) == ["x" * 15, "yy"]


def test_send_posts_to_graph_api_and_saves_history(bot):
    resp = bot.main.send("Hello there", USER, PHONE_ID, message_en="Hello there (en)")
    call = bot.wa.calls[0]
    assert call["url"] == f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    assert call["headers"]["Authorization"] == "Bearer test-wa-token"
    assert call["json"] == {"messaging_product": "whatsapp", "to": USER, "type": "text",
                            "text": {"body": "Hello there"}}
    assert resp.status_code == 200
    assert bot.db.messages[USER] == [{"role": "bot", "message": "Hello there",
                                      "message_en": "Hello there (en)", "timestamp": "t"}]


def test_send_long_message_is_split_but_stored_once(bot):
    long = ("line " * 500 + "\n") * 3
    bot.main.send(long, USER, PHONE_ID)
    assert len(bot.wa.calls) > 1
    assert all(len(c["json"]["text"]["body"]) <= main.WHATSAPP_MAX_CHARS for c in bot.wa.calls)
    assert len(bot.db.messages[USER]) == 1


def test_send_error_status_is_logged(bot, caplog):
    bot.wa.status_code = 400
    bot.main.send("x", USER, PHONE_ID)
    assert "Send failed" in caplog.text


def test_say_and_agent_messages_never_enter_history(bot):
    bot.main.say("Fixed UI text", USER, PHONE_ID)
    agent = next(iter(main.AGENTS.values()))
    bot.main.send("to agent", agent, PHONE_ID)
    assert bot.db.messages == {}


def test_send_interactive_buttons(bot):
    buttons = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
    bot.main.send_interactive_buttons("+260000000000", "Body", buttons, PHONE_ID)
    payload = bot.wa.calls[0]["json"]
    assert payload["type"] == "interactive"
    assert payload["interactive"]["body"]["text"] == "Body"
    assert [b["reply"]["id"] for b in payload["interactive"]["action"]["buttons"]] == ["a", "b"]


# ─────────────── human-agent intent ───────────────

@pytest.mark.parametrize("text, expected", [
    ("I want to speak to a person", True),
    ("Can I talk to someone please", True),
    ("customer service", True),
    ("agent", True),
    ("human please", True),
    ("Support", True),
    ("Does the support belt help with back pain during pregnancy?", False),
    ("Is a human papilloma virus test painful for me?", False),
    ("What is folic acid?", False),
])
def test_is_human_agent_request(text, expected):
    assert main.is_human_agent_request(text) is expected


def test_agent_key_helpers():
    assert main._agent_request_key("1") == "agent_request:1"
    assert main._agent_session_key("1") == "agent_session:1"
    assert main._agent_rejections_key("1") == "agent_rejections:1"


# ─────────────── referrals ───────────────

@pytest.mark.parametrize("text, source", [
    ("Hi DawaMom, I got connected from Test Pharmacy Poster 1.", "Test Pharmacy Poster 1"),
    ("I saw your poster at the clinic", "at the clinic"),   # trigger fallback, no "from"
    ("came from the flyer", "the flyer"),                   # "from " is tried before "from the "
    ("hey dawamom", None),
    ("I'm from Harare!", "Harare"),
    ("What is HPV?", None),
])
def test_extract_referral_source(text, source):
    assert main.extract_referral_source(text) == source


def test_extract_referral_trigger_without_place_is_ignored():
    # "from " is present but only punctuation follows: no empty referral must be recorded.
    assert main.extract_referral_source("I got connected from ?") is None


def test_extract_referral_trigger_fallback():
    # No "from " anywhere: the text after the longest trigger is used.
    assert main.extract_referral_source("saw the poster at Test Clinic") == "at Test Clinic"


def test_is_referral_greeting():
    assert main.is_referral_greeting("Hi DawaMom, I got connected from Test Clinic")
    assert not main.is_referral_greeting("I got connected from Test Clinic")
    assert not main.is_referral_greeting("Hi DawaMom")


def test_save_referral_source(bot):
    bot.main.user_states[USER] = {"user_id": "DH-0001-TEST"}
    bot.main.save_referral_source(USER, "Poster 9")
    bot.main.save_referral_source("263770009999", "Poster 10")
    assert bot.db.referrals == [
        {"phone": USER, "source": "Poster 9", "user_id": "DH-0001-TEST"},
        {"phone": "263770009999", "source": "Poster 10", "user_id": "unregistered"},
    ]


# ─────────────── English checks ───────────────

def test_looks_like_english_leak():
    english = "You should see the doctor when the pain is bad and you bleed"
    assert main.looks_like_english_leak(english, "shona")
    assert not main.looks_like_english_leak(english, "english")
    assert not main.looks_like_english_leak("", "shona")
    assert not main.looks_like_english_leak("Enda kuchiremba", "shona")
    assert not main.looks_like_english_leak(
        "Enda kuchiremba kana uine kurwadziwa kwakanyanya kubuda ropa", "shona")


def test_looks_english():
    assert main.looks_english("short text")
    assert main.looks_english(None)
    assert main.looks_english("- Missed period, nausea, tiredness, breast tenderness of pregnancy")
    assert not main.looks_english("Ndine pamuviri uye ndinonzwa kurwadziwa zvikuru nhasi chaizvo")


# ─────────────── onboarding / classifiers ───────────────

def test_auto_register_builds_id_from_phone(bot, monkeypatch):
    bot.main.user_states[USER] = {"step": "language_detection"}
    monkeypatch.setattr(main.random, "choices", lambda pop, k: list("ABCD"))
    uid = bot.main.auto_register(USER)
    assert uid == "DH-0001-ABCD"
    assert bot.main.user_states[USER] == {"step": "chat", "phone_digits": "0001",
                                          "user_id": "DH-0001-ABCD", "registered": True,
                                          "first_message": False}


@pytest.mark.parametrize("text, expected", [
    ("hi", True), ("Good morning Rudo", True), ("muli shani", True), ("Mhoroi!", True),
    ("", False), ("hi I am bleeding", False), ("hi hi hi hi hi hi", False),
])
def test_is_greeting_only(text, expected):
    assert main.is_greeting_only(text) is expected


@pytest.mark.parametrize("text, expected", [("restart", True), ("Can we start over", True),
                                            ("reset", True), ("restarted my pills", False)])
def test_is_reset_request(text, expected):
    assert main.is_reset_request(text) is expected


@pytest.mark.parametrize("text, yes, no", [
    ("yes", True, False), ("Yes please", True, False), ("hongu", True, False),
    ("no", False, True), ("no thank you", False, True), ("kwete", False, True),
    ("yes but I have a question about my baby", False, False),
    ("maybe", False, False),
])
def test_is_yes_is_no(text, yes, no):
    assert main.is_yes(text) is yes
    assert main.is_no(text) is no


def test_looks_like_new_question_and_skip_language_update():
    assert main.looks_like_new_question("why?")
    assert main.looks_like_new_question("one two three four five")
    assert not main.looks_like_new_question("yes please")
    assert main.skip_language_update("shop_quantity", "2")
    assert main.skip_language_update("follow_up", "yes please")
    assert not main.skip_language_update("follow_up", "what about iron tablets")
    assert not main.skip_language_update("chat", "hi")


def test_failure_message_has_agent_hint():
    assert main.failure_message("shona") == main.FALLBACK_MAP["shona"] + main.AGENT_HINT
    assert main.failure_message("english").startswith("Sorry, there was a problem")


def test_retry_returns_first_success_and_raises_last():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("first")
        return "ok"

    assert main._retry(flaky) == "ok"

    def always():
        raise KeyError("nope")

    with pytest.raises(KeyError):
        main._retry(always, attempts=3)


# ─────────────── state / history plumbing ───────────────

def test_ensure_user_state_new_cached_saved_and_refresh(bot):
    assert bot.main.ensure_user_state(USER) is True
    assert bot.main.user_states[USER]["step"] == "language_detection"
    assert bot.main.ensure_user_state(USER) is False          # cached

    bot.db.users[USER] = {"step": "chat", "language": "shona"}
    assert bot.main.ensure_user_state(USER, refresh=True) is False
    assert bot.main.user_states[USER]["language"] == "shona"  # DB wins over stale cache


def test_save_single_user_state_only_known_users(bot):
    bot.main.save_single_user_state("unknown")
    assert bot.db.users == {}
    bot.main.user_states[USER] = {"step": "chat"}
    bot.main.save_single_user_state(USER)
    assert bot.db.users[USER] == {"step": "chat"}


def test_conversation_wrappers(bot):
    m = bot.main
    m.save_user_conversation(USER, "user", 123)
    m.set_last_message_en(USER, "user", "one two three")
    assert m.get_user_conversation(USER)[0]["message"] == "123"
    assert m.get_user_conversation(USER)[0]["message_en"] == "one two three"
    m.drop_last_user_message(USER)
    assert m.get_user_conversation(USER) == []
    m.save_user_conversation(USER, "user", "x")
    m.clear_conversation(USER)
    assert m.get_user_conversation(USER) == []


def test_history_for_model_english_uses_plain_text(bot):
    for role, msg in [("user", "q1"), ("bot", "a1"), ("user", "   "), ("user", "current")]:
        bot.db.add_message(USER, role, msg)
    out = bot.main._history_for_model(USER, "english")
    assert [e["message"] for e in out] == ["q1", "a1", ""]
    assert out[-1] == {"role": "user", "message": ""}


def test_history_for_model_pivot_keeps_only_english_versions(bot):
    bot.db.add_message(USER, "user", "Ndine pamuviri", "I am pregnant")
    bot.db.add_message(USER, "bot", "Mhoroi! (fixed UI text)")           # no English: dropped
    bot.db.add_message(USER, "bot", "Local reply", "English reply")
    bot.db.add_message(USER, "user", "current")
    out = bot.main._history_for_model(USER, "shona")
    assert [e["message"] for e in out] == ["I am pregnant", "English reply", ""]


def test_home_page_renders(bot):
    r = bot.client.get("/")
    assert r.status_code == 200


def test_api_index_exposes_flask_app():
    from api import index
    assert index.app is main.app
    assert index.__all__ == ["app"]


def test_products_catalogue_shape():
    from products_data import products_by_category
    assert products_by_category
    for items in products_by_category.values():
        for p in items:
            assert set(p) >= {"name", "price", "availability", "description"}


def test_whatsapp_recorder_sanity(bot):
    # The recorder must be what main.py uses: no real HTTP client is reachable.
    assert isinstance(bot.main.requests, SimpleNamespace)
