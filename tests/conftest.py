"""
Shared fixtures for the Rudo test suite.

Safety rules enforced here:
* Every credential is a synthetic placeholder, set before any project module is imported.
* Supabase, MedGemma, TranslateGemma and language-ID URLs are removed from the environment,
  so modules import in their "not configured" state.
* A socket-level guard makes any real network connection (WhatsApp, Supabase, Gemini,
  Hugging Face) raise immediately, so a missing mock fails loudly instead of calling out.
* All phone numbers and messages are synthetic test data.
"""
import json
import os
import socket
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Synthetic configuration only: never real tokens.
_FAKE_ENV = {
    "WA_TOKEN": "test-wa-token",
    "PHONE_ID": "test-phone-id",
    "GEN_API": "test-gemini-key",
    "OWNER_PHONE": "+10000000000",
    "VERIFY_TOKEN": "test-verify-token",
}
_UNSET_ENV = [
    "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "MEDGEMMA_URL", "MEDGEMMA_TOKEN", "HF_TOKEN",
    "TRANSLATEGEMMA_URL", "TRANSLATEGEMMA_TOKEN", "LANGID_URL", "TG_IN_LANGS", "TG_OUT_LANGS",
    "TG_LANGS", "TRANSLATE_LANGS", "VERIFY_ALL", "VERIFY_OUT", "TRANSLATE_DEBUG", "MEDGEMMA_FOOTER",
]
os.environ.update(_FAKE_ENV)
for _k in _UNSET_ENV:
    os.environ.pop(_k, None)


class NetworkBlockedError(RuntimeError):
    pass


def _blocked(*_a, **_kw):
    raise NetworkBlockedError("Real network access is disabled in the test suite")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# ─────────────────────────────────────────────
#  Generic fakes
# ─────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", content=None, lines=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")
        if content is None:
            content = self.text.encode() if self.text else b""
        self.content = content
        self._lines = lines or []

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeKV:
    """In-memory stand-in for db.kv (get / set(ex, nx) / delete / ping)."""

    def __init__(self):
        self.store = {}
        self.expiry = {}
        self.fail = False

    def _check(self):
        if self.fail:
            raise RuntimeError("kv unavailable")

    def ping(self):
        self._check()
        return True

    def get(self, key):
        self._check()
        return self.store.get(key)

    def set(self, key, value, ex=None, nx=False):
        self._check()
        if nx and key in self.store:
            return None
        self.store[key] = value
        self.expiry[key] = ex
        return True

    def delete(self, key):
        self._check()
        self.store.pop(key, None)
        return 1


class FakeDB:
    """In-memory replacement for the Supabase-backed functions in db.py that main.py calls."""

    def __init__(self):
        self.users = {}
        self.messages = {}
        self.referrals = []
        self.orders = []

    def get_user_state(self, phone):
        state = self.users.get(phone)
        return json.loads(json.dumps(state)) if state is not None else None

    def save_user_state(self, phone, state):
        self.users[phone] = json.loads(json.dumps(state))

    def get_messages(self, phone, limit=30):
        return [dict(m) for m in self.messages.get(phone, [])][-limit:]

    def add_message(self, phone, role, message, message_en=None):
        self.messages.setdefault(phone, []).append(
            {"role": role, "message": message, "message_en": message_en, "timestamp": "t"})

    def set_last_message_en(self, phone, role, text_en):
        if not text_en:
            return
        for m in reversed(self.messages.get(phone, [])):
            if m["role"] == role:
                m["message_en"] = text_en
                return

    def delete_messages(self, phone):
        self.messages.pop(phone, None)

    def delete_last_message_if_role(self, phone, role):
        msgs = self.messages.get(phone, [])
        if msgs and msgs[-1]["role"] == role:
            msgs.pop()

    def add_referral(self, phone, source, user_id):
        self.referrals.append({"phone": phone, "source": source, "user_id": user_id})

    def add_order(self, phone, user_id, product, price, quantity, address):
        self.orders.append({"phone": phone, "user_id": user_id, "product": product,
                            "price": price, "quantity": quantity, "address": address})


class WhatsAppRecorder:
    """Captures every Graph API POST that main.py makes."""

    def __init__(self):
        self.calls = []
        self.status_code = 200

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.status_code, {"messages": [{"id": "wamid.test"}]})

    def texts_to(self, phone):
        return [c["json"]["text"]["body"] for c in self.calls
                if c["json"]["to"] == phone and c["json"]["type"] == "text"]

    def interactive_to(self, phone):
        return [c["json"] for c in self.calls
                if c["json"]["to"] == phone and c["json"]["type"] == "interactive"]

    def all_text(self, phone):
        return "\n".join(self.texts_to(phone))


# ─────────────────────────────────────────────
#  main.py harness
# ─────────────────────────────────────────────

USER = "263770000001"          # synthetic WhatsApp number
USER2 = "263770000002"
PHONE_ID = "test-phone-id"


@pytest.fixture
def bot(monkeypatch):
    """
    main.py with in-memory persistence, a recorded WhatsApp API, and every model call
    (Gemini language ID, TranslateGemma, MedGemma) replaced by a controllable stub.
    """
    import main

    fake_db = FakeDB()
    for name in ("get_user_state", "save_user_state", "get_messages", "add_message",
                 "set_last_message_en", "delete_messages", "delete_last_message_if_role",
                 "add_referral", "add_order"):
        monkeypatch.setattr(main.db, name, getattr(fake_db, name))

    kv = FakeKV()
    monkeypatch.setattr(main, "redis_client", kv)
    monkeypatch.setattr(main, "user_states", {})

    wa = WhatsAppRecorder()
    monkeypatch.setattr(main, "requests", SimpleNamespace(post=wa.post))

    models = SimpleNamespace(
        lang=None,                         # what the Gemini classifier returns
        medgemma=["Drink plenty of water and attend your antenatal visits regularly."],
        medgemma_questions=[],
        medgemma_histories=[],
        translations=[],
        translate_fn=None,
    )

    def fake_llm_detect(message):
        return models.lang

    def fake_ask_medgemma(question, history=None):
        models.medgemma_questions.append(question)
        models.medgemma_histories.append(history)
        if models.medgemma:
            return models.medgemma.pop(0) if len(models.medgemma) > 1 else models.medgemma[0]
        return None

    def fake_translate(text, src, tgt):
        models.translations.append((text, src, tgt))
        if models.translate_fn:
            return models.translate_fn(text, src, tgt)
        return f"[{tgt}] {text}"

    monkeypatch.setattr(main, "_llm_detect_language", fake_llm_detect)
    monkeypatch.setattr(main, "ask_medgemma", fake_ask_medgemma)
    monkeypatch.setattr(main, "medgemma_enabled", lambda: True)
    monkeypatch.setattr(main, "translate", fake_translate)
    monkeypatch.setattr(main, "translategemma_enabled", lambda: True)

    return SimpleNamespace(main=main, db=fake_db, kv=kv, wa=wa, models=models,
                           client=main.app.test_client())


def wa_text(sender, body, msg_id=None, phone_id=PHONE_ID):
    """Synthetic WhatsApp Cloud API webhook payload for one text message."""
    msg = {"from": sender, "type": "text", "text": {"body": body}}
    if msg_id:
        msg["id"] = msg_id
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone_id}, "messages": [msg]}}]}]}


def wa_button(sender, button_id, msg_id=None, phone_id=PHONE_ID):
    msg = {"from": sender, "type": "interactive",
           "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "x"}}}
    if msg_id:
        msg["id"] = msg_id
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone_id}, "messages": [msg]}}]}]}
