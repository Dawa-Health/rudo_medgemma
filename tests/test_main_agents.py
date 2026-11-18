"""Human-agent escalation: request broadcast, accept/reject, relays, END CHAT, timeouts."""
import json

import pytest

import main
from conftest import PHONE_ID, USER

AGENT = main.AGENTS["Agent 1"]
AGENT_NORM = main.normalize_phone(AGENT)
SECOND_AGENT = "+260000000002"


@pytest.fixture
def two_agents(monkeypatch):
    monkeypatch.setattr(main, "AGENTS", {"Agent 1": AGENT, "Agent 2": SECOND_AGENT})


def pending_request(bot, status="pending"):
    bot.kv.store[main._agent_request_key(USER)] = json.dumps({"status": status, "user_number": USER})


# ─────────────── notify ───────────────

def test_notify_agents_stores_request_and_sends_buttons(bot):
    bot.main.user_states[USER] = {"user_id": "DH-0001-TEST", "language": "shona"}
    bot.main.notify_agents_of_request(USER, PHONE_ID)

    req = json.loads(bot.kv.store[main._agent_request_key(USER)])
    assert req["status"] == "pending" and req["user_id"] == "DH-0001-TEST" and req["language"] == "shona"
    assert bot.kv.expiry[main._agent_request_key(USER)] == main.AGENT_TIMEOUT_SECONDS + 10
    assert json.loads(bot.kv.store[main._agent_rejections_key(USER)]) == []

    msg = bot.wa.interactive_to(AGENT)[0]
    ids = [b["reply"]["id"] for b in msg["interactive"]["action"]["buttons"]]
    assert ids == [f"agent_accept:{USER}", f"agent_reject:{USER}"]
    assert "DH-0001-TEST" in msg["interactive"]["body"]["text"]


def test_notify_agents_survives_kv_failure_and_unknown_user(bot):
    bot.kv.fail = True
    bot.main.notify_agents_of_request(USER, PHONE_ID)
    assert bot.wa.interactive_to(AGENT)          # agents are still notified


def test_notify_agents_without_kv(bot, monkeypatch):
    monkeypatch.setattr(main, "redis_client", None)
    bot.main.notify_agents_of_request(USER, PHONE_ID)
    assert bot.wa.interactive_to(AGENT)


# ─────────────── accept ───────────────

def test_accept_connects_user_and_agent(bot, two_agents):
    bot.main.user_states[USER] = {"step": "waiting_for_agent", "language": "english"}
    pending_request(bot)
    bot.main.handle_agent_accept(AGENT, USER, PHONE_ID)

    req = json.loads(bot.kv.store[main._agent_request_key(USER)])
    assert req["status"] == "accepted" and req["accepted_by"] == AGENT
    session = json.loads(bot.kv.store[main._agent_session_key(USER)])
    assert session["agent_phone"] == AGENT
    assert f"agent_user_session:{AGENT_NORM}" in bot.kv.store

    assert bot.main.user_states[USER]["step"] == "human_agent_chat"
    assert bot.db.users[USER]["agent_phone"] == AGENT
    assert "connected to the user" in bot.wa.all_text(AGENT)
    assert "Agent 1 has accepted" in bot.wa.all_text(USER)
    assert "accepted by Agent 1" in bot.wa.all_text(SECOND_AGENT)


def test_accept_without_kv(bot, monkeypatch):
    monkeypatch.setattr(main, "redis_client", None)
    bot.main.handle_agent_accept(AGENT, USER, PHONE_ID)
    assert "unavailable" in bot.wa.all_text(USER)


def test_accept_expired_request(bot):
    bot.main.handle_agent_accept(AGENT, USER, PHONE_ID)
    assert "expired" in bot.wa.all_text(AGENT)


def test_accept_already_accepted(bot):
    pending_request(bot, status="accepted")
    bot.main.handle_agent_accept(AGENT, USER, PHONE_ID)
    assert "already been accepted" in bot.wa.all_text(AGENT)


def test_accept_handles_dict_payload_and_errors(bot, caplog):
    bot.kv.store[main._agent_request_key(USER)] = {"status": "pending"}     # non-string value
    bot.main.handle_agent_accept(AGENT, USER, PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "human_agent_chat"

    bot.kv.fail = True
    bot.main.handle_agent_accept(AGENT, USER, PHONE_ID)
    assert "Error in handle_agent_accept" in caplog.text


# ─────────────── reject ───────────────

def test_reject_by_last_agent_returns_user_to_bot(bot):
    bot.main.user_states[USER] = {"step": "waiting_for_agent", "language": "shona"}
    bot.db.users[USER] = dict(bot.main.user_states[USER])
    pending_request(bot)
    bot.kv.store[main._agent_rejections_key(USER)] = json.dumps([])

    bot.main.handle_agent_reject(AGENT, USER, PHONE_ID)

    assert "rejected this chat" in bot.wa.all_text(AGENT)
    assert bot.main.user_states[USER]["step"] == "chat"
    assert main._agent_request_key(USER) not in bot.kv.store
    assert "Ndine urombo" in bot.wa.all_text(USER)     # Shona "no agent available"


def test_reject_with_other_agents_remaining(bot, two_agents):
    pending_request(bot)
    bot.kv.store[main._agent_rejections_key(USER)] = [AGENT]       # non-string list, duplicate agent
    bot.main.handle_agent_reject(AGENT, USER, PHONE_ID)
    assert json.loads(bot.kv.store[main._agent_rejections_key(USER)]) == [AGENT]
    assert bot.wa.texts_to(USER) == []                               # still waiting for Agent 2


def test_reject_missing_rejection_list(bot, two_agents):
    pending_request(bot)
    bot.main.handle_agent_reject(SECOND_AGENT, USER, PHONE_ID)
    assert json.loads(bot.kv.store[main._agent_rejections_key(USER)]) == [SECOND_AGENT]


def test_reject_edge_cases(bot, monkeypatch, caplog):
    bot.main.handle_agent_reject(AGENT, USER, PHONE_ID)
    assert "already expired" in bot.wa.all_text(AGENT)

    bot.kv.store[main._agent_request_key(USER)] = {"status": "accepted"}
    bot.main.handle_agent_reject(AGENT, USER, PHONE_ID)
    assert "already handled" in bot.wa.all_text(AGENT)

    bot.kv.fail = True
    bot.main.handle_agent_reject(AGENT, USER, PHONE_ID)
    assert "Error in handle_agent_reject" in caplog.text

    monkeypatch.setattr(main, "redis_client", None)
    n = len(bot.wa.calls)
    bot.main.handle_agent_reject(AGENT, USER, PHONE_ID)
    assert len(bot.wa.calls) == n


# ─────────────── no agents ───────────────

@pytest.mark.parametrize("lang, needle", [
    ("english", "no agents are available"), ("ndebele", "Uxolo"), ("chinyanja", "Pepani"),
    ("bemba", "Njelelako"), ("lozi", "Ni maswabi"), ("tonga", "Ndatola"),
])
def test_no_agents_message_in_user_language(bot, lang, needle):
    bot.db.users[USER] = {"step": "waiting_for_agent", "language": lang, "agent_phone": AGENT}
    bot.main._handle_no_agents_available(USER, PHONE_ID)
    assert needle in bot.wa.all_text(USER)
    assert "agent_phone" not in bot.main.user_states[USER]


def test_no_agents_kv_cleanup_failure_is_ignored(bot):
    bot.kv.fail = True
    bot.main._handle_no_agents_available(USER, PHONE_ID)
    assert bot.main.user_states[USER]["step"] == "chat"


# ─────────────── relays ───────────────

def test_relay_user_message_to_agent(bot):
    assert bot.main.relay_user_message_to_agent(USER, "hi", PHONE_ID) is False      # no session
    bot.kv.store[main._agent_session_key(USER)] = json.dumps({"agent_phone": None})
    assert bot.main.relay_user_message_to_agent(USER, "hi", PHONE_ID) is False      # broken session
    bot.kv.store[main._agent_session_key(USER)] = json.dumps({"agent_phone": AGENT})
    assert bot.main.relay_user_message_to_agent(USER, "I have pain", PHONE_ID) is True
    assert f"*User ({USER}):* I have pain" in bot.wa.all_text(AGENT)


def test_relay_user_message_failures(bot, monkeypatch):
    bot.kv.fail = True
    assert bot.main.relay_user_message_to_agent(USER, "x", PHONE_ID) is False
    monkeypatch.setattr(main, "redis_client", None)
    assert bot.main.relay_user_message_to_agent(USER, "x", PHONE_ID) is False


def start_session(bot):
    bot.kv.store[f"agent_user_session:{AGENT_NORM}"] = json.dumps({"user_number": USER})
    bot.kv.store[main._agent_session_key(USER)] = json.dumps({"agent_phone": AGENT})
    pending_request(bot, status="accepted")


def test_relay_agent_message_to_user(bot):
    assert bot.main.relay_agent_message_to_user(AGENT, "hello", PHONE_ID) is False   # no session
    bot.kv.store[f"agent_user_session:{AGENT_NORM}"] = {"user_number": None}
    assert bot.main.relay_agent_message_to_user(AGENT, "hello", PHONE_ID) is False
    start_session(bot)
    assert bot.main.relay_agent_message_to_user(AGENT, "  Please rest.  ", PHONE_ID) is True
    assert "*Agent:* Please rest." in bot.wa.all_text(USER)


@pytest.mark.parametrize("lang, needle", [
    ("english", "Your agent has ended"), ("shona", "Mubatsiri"), ("ndebele", "Umhloli"),
    ("chinyanja", "Wothandiza"), ("bemba", "Umwafwilishi"), ("lozi", "Mubasi"), ("tonga", "Wakugwasya"),
])
def test_agent_end_chat_returns_user_to_bot(bot, lang, needle):
    bot.db.users[USER] = {"step": "human_agent_chat", "language": lang, "agent_phone": AGENT}
    start_session(bot)
    assert bot.main.relay_agent_message_to_user(AGENT, "end chat", PHONE_ID) is True
    assert bot.kv.store == {}
    assert bot.main.user_states[USER]["step"] == "chat"
    assert "ended the chat session" in bot.wa.all_text(AGENT)
    assert needle in bot.wa.all_text(USER)


def test_relay_agent_failures(bot, monkeypatch):
    bot.kv.fail = True
    assert bot.main.relay_agent_message_to_user(AGENT, "x", PHONE_ID) is False
    monkeypatch.setattr(main, "redis_client", None)
    assert bot.main.relay_agent_message_to_user(AGENT, "x", PHONE_ID) is False


# ─────────────── timeout check ───────────────

def test_check_timeout_pending_does_nothing(bot):
    pending_request(bot)
    bot.main.check_agent_request_timeout(USER, PHONE_ID)
    assert bot.wa.calls == []


def test_check_timeout_expired_kv_error_and_no_kv(bot, monkeypatch):
    bot.main.check_agent_request_timeout(USER, PHONE_ID)
    assert "no agents" in bot.wa.all_text(USER)

    bot.wa.calls.clear()
    bot.kv.fail = True
    bot.main.check_agent_request_timeout(USER, PHONE_ID)
    assert "no agents" in bot.wa.all_text(USER)

    bot.wa.calls.clear()
    monkeypatch.setattr(main, "redis_client", None)
    bot.main.check_agent_request_timeout(USER, PHONE_ID)
    assert "no agents" in bot.wa.all_text(USER)


# ─────────────── /agent-timeout endpoint ───────────────

def test_agent_timeout_endpoint_validation(bot):
    r = bot.client.post("/agent-timeout", json={"user_number": USER})
    assert r.status_code == 400


def test_agent_timeout_endpoint_pending_hands_back(bot):
    pending_request(bot)
    r = bot.client.post("/agent-timeout", json={"user_number": USER, "phone_id": PHONE_ID})
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}
    assert "no agents" in bot.wa.all_text(USER)


def test_agent_timeout_endpoint_accepted_or_missing_is_noop(bot):
    bot.kv.store[main._agent_request_key(USER)] = {"status": "accepted"}
    assert bot.client.post("/agent-timeout", json={"user_number": USER, "phone_id": PHONE_ID}).status_code == 200
    del bot.kv.store[main._agent_request_key(USER)]
    assert bot.client.post("/agent-timeout", json={"user_number": USER, "phone_id": PHONE_ID}).status_code == 200
    assert bot.wa.calls == []


def test_agent_timeout_endpoint_without_kv_and_error(bot, monkeypatch):
    bot.kv.fail = True
    r = bot.client.post("/agent-timeout", json={"user_number": USER, "phone_id": PHONE_ID})
    assert r.status_code == 500 and r.get_json()["status"] == "error"
    monkeypatch.setattr(main, "redis_client", None)
    assert bot.client.post("/agent-timeout", json={"user_number": USER, "phone_id": PHONE_ID}).status_code == 200
