"""
End-to-end webhook tests: synthetic WhatsApp Cloud API payloads go through the Flask app,
the router and the reply pipeline. WhatsApp, Supabase and all models are faked.
"""
import importlib.util
import json
import os

import pytest

import main
import medgemma_guardrails as g
from conftest import PHONE_ID, USER, USER2, FakeKV, wa_button, wa_text

AGENT = main.AGENTS["Agent 1"]
ANSWER = "Drink plenty of water and attend your antenatal visits regularly."


@pytest.fixture(autouse=True)
def footer_on(monkeypatch):
    monkeypatch.setattr(g, "FOOTER_ON", True)


def post(bot, payload):
    r = bot.client.post("/webhook", json=payload)
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}
    return r


def registered(bot, phone=USER, lang="english", step="chat", **extra):
    bot.db.users[phone] = {"step": step, "language": lang, "registered": True,
                           "user_id": "DH-0001-TEST", "first_message": False, **extra}


# ─────────────── verification handshake ───────────────

def test_webhook_verification_success(bot):
    r = bot.client.get("/webhook?hub.mode=subscribe&hub.verify_token=test-verify-token&hub.challenge=abc123")
    assert r.status_code == 200 and r.data == b"abc123"


@pytest.mark.parametrize("qs", ["hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=x",
                                "hub.mode=unsubscribe&hub.verify_token=test-verify-token"])
def test_webhook_verification_failure(bot, qs):
    assert bot.client.get(f"/webhook?{qs}").status_code == 403


# ─────────────── non-message events ───────────────

def test_status_and_unknown_events_ignored(bot):
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}},
                                      {"value": {"something": 1}}]}]}
    post(bot, payload)
    post(bot, {})
    assert bot.client.post("/webhook", data="not json", content_type="text/plain").status_code == 200
    assert bot.wa.calls == []


def test_processing_error_still_returns_200(bot, caplog):
    bad = {"entry": [{"changes": [{"value": {"metadata": {}, "messages": [{"from": USER}]}}]}]}
    post(bot, bad)
    assert "Error processing message" in caplog.text


# ─────────────── onboarding ───────────────

def test_first_greeting_registers_and_welcomes(bot):
    bot.models.lang = "english"
    post(bot, wa_text(USER, "Hi", msg_id="m1"))
    st = bot.db.users[USER]
    assert st["registered"] and st["step"] == "chat" and st["user_id"].startswith("DH-0001-")
    texts = bot.wa.texts_to(USER)
    assert len(texts) == 1 and st["user_id"] in texts[0]
    assert bot.models.medgemma_questions == []       # greeting only: no model call


@pytest.mark.parametrize("lang, word", [("shona", "mhoro"), ("ndebele", "sawubona"),
                                        ("bemba", "mwaiseni"), ("chinyanja", "moni"),
                                        ("tonga", "mwabuka"), ("lozi", "ndalumba")])
def test_first_message_welcome_in_detected_language(bot, lang, word):
    post(bot, wa_text(USER, word))
    assert bot.db.users[USER]["language"] == lang
    assert bot.db.users[USER]["user_id"] in bot.wa.texts_to(USER)[0]


def test_first_message_with_question_is_answered(bot):
    bot.models.lang = "english"
    post(bot, wa_text(USER, "How many antenatal visits do I need?"))
    texts = bot.wa.texts_to(USER)
    assert "Your ID is" in texts[0]
    assert any(ANSWER in t for t in texts)
    assert texts[-1] == "Is there anything else I can help you with?"


def test_referral_greeting_is_saved_and_not_answered(bot):
    bot.models.lang = "english"
    post(bot, wa_text(USER, "Hi DawaMom, I got connected from Test Clinic Poster 3"))
    assert bot.db.referrals[0]["source"] == "Test Clinic Poster 3"
    assert bot.models.medgemma_questions == []


# ─────────────── normal chat ───────────────

def test_registered_user_question_answered_and_stored(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, wa_text(USER, "What foods help with nausea?"))
    roles = [m["role"] for m in bot.db.messages[USER]]
    assert roles == ["user", "bot"]
    assert bot.db.users[USER]["step"] == "follow_up"


def test_greeting_from_registered_user_resets_flow(bot):
    registered(bot, lang="shona", step="shop_browse", cart=[{"product": "x"}])
    post(bot, wa_text(USER, "mhoro"))
    assert bot.wa.texts_to(USER) == [main.GREET_MAP["shona"]]
    assert bot.db.users[USER]["step"] == "chat" and "cart" not in bot.db.users[USER]


def test_reset_request_clears_history(bot):
    registered(bot)
    bot.db.add_message(USER, "user", "old question")
    bot.models.lang = "english"
    post(bot, wa_text(USER, "restart"))
    assert USER not in bot.db.messages
    assert bot.wa.texts_to(USER) == ["Hello! How can I help you today?"]


def test_danger_sign_message_end_to_end(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, wa_text(USER, "I am bleeding heavily and feel faint"))
    reply = [t for t in bot.wa.texts_to(USER) if t.startswith("⚠️")]
    assert reply and reply[0].startswith(f"⚠️ {g.SEE_DOCTOR_DEFAULT}")


def test_model_outage_sends_failure_with_agent_hint(bot, monkeypatch):
    registered(bot)
    bot.models.lang = "english"
    monkeypatch.setattr(main, "medgemma_enabled", lambda: False)
    post(bot, wa_text(USER, "What foods help with nausea?"))
    assert bot.wa.texts_to(USER)[-1] == main.failure_message("english")
    assert "*agent*" in bot.wa.texts_to(USER)[-1]


def test_shona_user_full_pivot(bot):
    registered(bot, lang="shona")
    bot.models.lang = "shona"
    bot.models.translate_fn = lambda t, s, d: "What should I eat while pregnant?" if d == "english" \
        else "Idya miriwo uye inwa mvura yakawanda zuva rega rega."
    post(bot, wa_text(USER, "Ndodya chii ndine pamuviri?"))
    texts = bot.wa.texts_to(USER)
    assert texts[0] == main.THINKING_MAP["shona"]
    assert texts[1].startswith("Idya miriwo") and g.SEE_DOCTOR["shona"] in texts[1]
    assert texts[2] == main.FOLLOWUP_MAP["shona"]
    stored = bot.db.messages[USER]
    assert stored[0]["message_en"] == "What should I eat while pregnant?"
    assert stored[1]["message_en"] == ANSWER


def test_language_switch_mid_conversation(bot):
    registered(bot, lang="english")
    bot.models.lang = "ndebele"
    bot.models.translate_fn = lambda t, s, d: "question" if d == "english" else \
        "Dla imifino njalo unathe amanzi amanengi nsuku zonke."
    post(bot, wa_text(USER, "Ngifuna ukwazi ngokudla kwesisu"))
    assert bot.db.users[USER]["language"] == "ndebele"
    assert bot.wa.texts_to(USER)[0] == main.THINKING_MAP["ndebele"]


# ─────────────── follow-up + shop through the router ───────────────

def test_follow_up_no_then_shop_order_end_to_end(bot):
    registered(bot, step="follow_up")
    bot.models.lang = "english"
    post(bot, wa_text(USER, "no"))
    assert bot.db.users[USER]["step"] == "shop_interest"
    post(bot, wa_text(USER, "yes"))
    assert bot.db.users[USER]["step"] == "shop_browse"
    post(bot, wa_text(USER, "1"))
    assert bot.db.users[USER]["step"] == "shop_order_decision"
    post(bot, wa_text(USER, "Ultrasound"))
    assert bot.db.users[USER]["step"] == "shop_quantity"
    post(bot, wa_text(USER, "2"))
    post(bot, wa_text(USER, "no"))
    assert bot.db.users[USER]["step"] == "shop_address"
    post(bot, wa_text(USER, "Plot 1, Test Road, agent street"))    # address bypasses keyword checks
    assert bot.db.orders[0]["product"] == "Ultrasound" and bot.db.orders[0]["quantity"] == 2
    assert bot.db.users[USER]["step"] == "chat"
    # shop answers never enter the MedGemma history
    assert all(m["message"] not in ("2", "1", "Ultrasound") for m in bot.db.messages.get(USER, []))


def test_follow_up_new_question_is_answered(bot):
    registered(bot, step="follow_up")
    bot.models.lang = "english"
    post(bot, wa_text(USER, "And what about iron tablets?"))
    assert bot.models.medgemma_questions == ["And what about iron tablets?"]


def test_question_during_shop_escapes_flow(bot):
    registered(bot, step="shop_interest")
    bot.models.lang = "english"
    post(bot, wa_text(USER, "Is it normal to feel dizzy in the morning?"))
    assert bot.models.medgemma_questions == ["Is it normal to feel dizzy in the morning?"]
    assert bot.db.messages[USER][0] == {"role": "user", "message": "Is it normal to feel dizzy in the morning?",
                                        "message_en": None, "timestamp": "t"}


# ─────────────── human agent through the router ───────────────

def test_human_agent_full_session(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, wa_text(USER, "speak to a person"))
    assert bot.db.users[USER]["step"] == "waiting_for_agent"
    assert "Looking for a human agent" in bot.wa.texts_to(USER)[0]
    assert bot.wa.interactive_to(AGENT)

    post(bot, wa_button(AGENT, f"agent_accept:{USER}"))
    assert bot.db.users[USER]["step"] == "human_agent_chat"

    post(bot, wa_text(USER, "I have a question about bleeding"))
    assert "I have a question about bleeding" in bot.wa.all_text(AGENT)
    assert bot.models.medgemma_questions == []        # agent session bypasses the bot

    post(bot, wa_text(AGENT, "Please come to the clinic today"))
    assert "*Agent:* Please come to the clinic today" in bot.wa.all_text(USER)

    post(bot, wa_text(AGENT, "END CHAT"))
    assert bot.db.users[USER]["step"] == "chat"


def test_agent_reject_button(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, wa_text(USER, "agent"))
    post(bot, wa_button(AGENT, f"agent_reject:{USER}"))
    assert bot.db.users[USER]["step"] == "chat"
    assert "no agents" in bot.wa.all_text(USER)


def test_unknown_button_and_non_button_interactive(bot):
    post(bot, wa_button(AGENT, "something_else"))
    msg = {"from": USER, "type": "interactive", "interactive": {"type": "list_reply"}}
    post(bot, {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": PHONE_ID},
                                                 "messages": [msg]}}]}]})
    assert bot.wa.calls == []


def test_waiting_user_cancel(bot):
    registered(bot, lang="tonga", step="waiting_for_agent")
    bot.kv.store[main._agent_request_key(USER)] = json.dumps({"status": "pending"})
    post(bot, wa_text(USER, "cancel"))
    assert bot.db.users[USER]["step"] == "chat"
    assert bot.wa.texts_to(USER) == [main.CANCEL_MAP["tonga"]]
    assert main._agent_request_key(USER) not in bot.kv.store


def test_waiting_user_cancel_kv_failure_and_no_kv(bot, monkeypatch):
    registered(bot, step="waiting_for_agent")
    main.user_states[USER] = dict(bot.db.users[USER])
    bot.kv.fail = True
    main.handle_message(USER, "CANCEL", PHONE_ID)
    assert main.user_states[USER]["step"] == "chat"

    main.user_states[USER]["step"] = "waiting_for_agent"
    monkeypatch.setattr(main, "redis_client", None)
    main.handle_message(USER, "CANCEL", PHONE_ID)
    assert main.user_states[USER]["step"] == "chat"


def test_waiting_user_other_message_checks_timeout(bot):
    registered(bot, step="waiting_for_agent")
    bot.kv.store[main._agent_request_key(USER)] = json.dumps({"status": "pending"})
    post(bot, wa_text(USER, "hello?"))
    assert bot.db.users[USER]["step"] == "waiting_for_agent"     # still pending, nothing sent
    del bot.kv.store[main._agent_request_key(USER)]
    post(bot, wa_text(USER, "anyone?"))
    assert bot.db.users[USER]["step"] == "chat"


def test_human_agent_chat_with_lost_session_returns_to_bot(bot):
    registered(bot, lang="bemba", step="human_agent_chat", agent_phone=AGENT)
    post(bot, wa_text(USER, "muli shani"))
    assert bot.db.users[USER]["step"] == "chat"
    assert bot.wa.texts_to(USER) == [main.BACK_MAP["bemba"]]


def test_agent_without_session_is_treated_as_user(bot):
    bot.models.lang = "english"
    post(bot, wa_text(AGENT, "hi"))
    assert AGENT in bot.db.users                 # onboarded like any other number


# ─────────────── non-text / duplicates ───────────────

@pytest.mark.parametrize("lang", ["english", "shona", "lozi"])
def test_non_text_message(bot, lang):
    registered(bot, lang=lang)
    msg = {"from": USER, "type": "image", "image": {"id": "img1"}}
    post(bot, {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": PHONE_ID},
                                                 "messages": [msg]}}]}]})
    expected = main.NON_TEXT_MAP.get(lang, "Sorry, I can only process text messages. Please send a text message.")
    assert bot.wa.texts_to(USER) == [expected]


def test_duplicate_delivery_ignored(bot):
    registered(bot)
    bot.models.lang = "english"
    post(bot, wa_text(USER, "What foods help with nausea?", msg_id="wamid.1"))
    n = len(bot.wa.calls)
    post(bot, wa_text(USER, "What foods help with nausea?", msg_id="wamid.1"))
    assert len(bot.wa.calls) == n
    assert len(bot.models.medgemma_questions) == 1


def test_already_processed_edge_cases(bot, monkeypatch):
    assert main._already_processed(None) is False
    bot.kv.fail = True
    assert main._already_processed("x") is False
    monkeypatch.setattr(main, "redis_client", None)
    assert main._already_processed("x") is False


def test_two_users_are_isolated(bot):
    registered(bot, USER, lang="shona")
    registered(bot, USER2, lang="english")
    bot.models.lang = "english"
    post(bot, wa_text(USER2, "What foods help with nausea?"))
    assert USER not in bot.db.messages
    assert bot.db.users[USER]["language"] == "shona"


# ─────────────── module start-up with Supabase configured ───────────────

def _load_main_copy(monkeypatch, ping_ok):
    """Import a fresh copy of main.py with Supabase 'configured' to exercise start-up checks."""
    import logging

    import db
    kv = FakeKV()
    kv.fail = not ping_ok
    # main.py calls basicConfig(force=True), which would detach pytest's capture handler.
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: None)
    monkeypatch.setattr(db, "enabled", lambda: True)
    monkeypatch.setattr(db, "kv", kv)
    path = os.path.join(os.path.dirname(main.__file__), "main.py")
    spec = importlib.util.spec_from_file_location("main_startup_copy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, kv


def test_startup_with_supabase(monkeypatch, caplog):
    caplog.set_level("INFO")
    mod, kv = _load_main_copy(monkeypatch, ping_ok=True)
    assert mod.redis_client is kv
    assert "Successfully connected to Supabase" in caplog.text


def test_startup_supabase_ping_failure_is_logged(monkeypatch, caplog):
    mod, kv = _load_main_copy(monkeypatch, ping_ok=False)
    assert mod.redis_client is kv
    assert "Supabase connection check failed" in caplog.text
