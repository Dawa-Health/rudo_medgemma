"""Supabase/PostgREST persistence layer. The HTTP session is replaced by a recording fake."""
from datetime import datetime, timezone

import pytest

import db
from conftest import FakeResponse

PHONE = "263770000001"


class FakeSession:
    def __init__(self):
        self.calls = []
        self.queue = []          # responses returned in order; default is 204 no content

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json,
                           "headers": headers, "timeout": timeout})
        if self.queue:
            r = self.queue.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return FakeResponse(204, content=b"")


@pytest.fixture
def sb(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(db, "_session", session)
    monkeypatch.setattr(db, "SUPABASE_URL", "https://sb.test")
    monkeypatch.setattr(db, "SUPABASE_KEY", "sb_secret_fake")
    return session


@pytest.fixture
def disabled(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(db, "_session", session)
    monkeypatch.setattr(db, "SUPABASE_URL", "")
    monkeypatch.setattr(db, "SUPABASE_KEY", "")
    return session


def ok(data):
    return FakeResponse(200, data)


# ─────────────── low level ───────────────

def test_enabled_flag(monkeypatch):
    monkeypatch.setattr(db, "SUPABASE_URL", "https://x")
    monkeypatch.setattr(db, "SUPABASE_KEY", "")
    assert not db.enabled()
    monkeypatch.setattr(db, "SUPABASE_KEY", "k")
    assert db.enabled()


def test_headers_secret_key_not_sent_as_bearer(monkeypatch):
    monkeypatch.setattr(db, "SUPABASE_KEY", "sb_secret_fake")
    h = db._headers()
    assert h == {"apikey": "sb_secret_fake", "Content-Type": "application/json"}


def test_headers_legacy_jwt_and_prefer(monkeypatch):
    monkeypatch.setattr(db, "SUPABASE_KEY", "eyJfake.jwt")
    h = db._headers("return=minimal")
    assert h["Authorization"] == "Bearer eyJfake.jwt"
    assert h["Prefer"] == "return=minimal"


def test_ts_format_is_postgrest_safe():
    dt = datetime(2026, 1, 2, 3, 4, 5, 999, tzinfo=timezone.utc)
    assert db._ts(dt) == "2026-01-02T03:04:05Z"
    assert "+" not in db._ts()
    assert db._now().tzinfo is not None


def test_call_builds_request_and_parses_json(sb):
    sb.queue.append(ok([{"a": 1}]))
    assert db._call("GET", "users", {"x": "1"}, prefer="count=exact") == [{"a": 1}]
    c = sb.calls[0]
    assert c["url"] == "https://sb.test/rest/v1/users"
    assert c["headers"]["Prefer"] == "count=exact"
    assert c["timeout"] == db.SUPABASE_TIMEOUT


def test_call_http_error_raises(sb):
    sb.queue.append(FakeResponse(409, text="conflict"))
    with pytest.raises(RuntimeError, match="409"):
        db._call("POST", "users")


def test_call_empty_and_non_json_body(sb):
    sb.queue.append(FakeResponse(204, content=b""))
    assert db._call("DELETE", "kv") is None
    sb.queue.append(FakeResponse(200, text="not-json"))
    assert db._call("GET", "kv") is None


# ─────────────── KV store ───────────────

def test_kv_ping(sb):
    assert db.kv.ping() is True
    assert sb.calls[0]["params"] == {"select": "key", "limit": "1"}


def test_kv_get_found_and_missing(sb):
    sb.queue += [ok([{"value": "v1"}]), ok([])]
    assert db.kv.get("k") == "v1"
    assert db.kv.get("missing") is None
    params = sb.calls[0]["params"]
    assert params["key"] == "eq.k"
    assert params["or"].startswith("(expires_at.is.null,expires_at.gt.")


def test_kv_set_plain_with_expiry_and_json_value(sb):
    assert db.kv.set("k", {"a": 1}, ex=60) is True
    c = sb.calls[0]
    assert c["method"] == "POST"
    assert c["json"]["value"] == '{"a": 1}'
    assert c["json"]["expires_at"].endswith("Z")
    assert "merge-duplicates" in c["headers"]["Prefer"]


def test_kv_set_without_expiry(sb):
    db.kv.set("k", "v")
    assert sb.calls[0]["json"] == {"key": "k", "value": "v", "expires_at": None}


def test_kv_set_nx_inserted_and_duplicate(sb):
    sb.queue += [FakeResponse(204, content=b""), ok([{"key": "k"}])]
    assert db.kv.set("k", "1", ex=10, nx=True) is True
    assert sb.calls[0]["method"] == "DELETE"            # expired row cleared first
    assert sb.calls[0]["params"]["expires_at"].startswith("lt.")
    assert "ignore-duplicates" in sb.calls[1]["headers"]["Prefer"]

    sb.queue += [FakeResponse(204, content=b""), ok([])]
    assert db.kv.set("k", "1", ex=10, nx=True) is None


def test_kv_delete(sb):
    assert db.kv.delete("k") == 1
    assert sb.calls[0]["params"] == {"key": "eq.k"}


# ─────────────── users ───────────────

def test_get_user_state(sb):
    sb.queue += [ok([{"state": {"step": "chat"}}]), ok([])]
    assert db.get_user_state(PHONE) == {"step": "chat"}
    assert db.get_user_state(PHONE) is None


def test_save_user_state_upserts(sb):
    state = {"user_id": "DH-0001-ABCD", "language": "shona", "step": "chat"}
    db.save_user_state(PHONE, state)
    body = sb.calls[0]["json"]
    assert body["phone"] == PHONE and body["language"] == "shona" and body["state"] == state
    assert sb.calls[0]["params"] == {"on_conflict": "phone"}


# ─────────────── messages ───────────────

def test_get_messages_reversed_and_shaped(sb):
    sb.queue.append(ok([
        {"id": 2, "role": "bot", "message": "b", "message_en": "b-en", "created_at": "t2"},
        {"id": 1, "role": "user", "message": "u", "created_at": "t1"},
    ]))
    out = db.get_messages(PHONE, limit=5)
    assert out == [
        {"role": "user", "message": "u", "message_en": None, "timestamp": "t1"},
        {"role": "bot", "message": "b", "message_en": "b-en", "timestamp": "t2"},
    ]
    assert sb.calls[0]["params"]["limit"] == "5"


def test_get_messages_none_body(sb):
    sb.queue.append(FakeResponse(204, content=b""))
    assert db.get_messages(PHONE) == []


def test_add_message(sb):
    db.add_message(PHONE, "user", "hello", "hello-en")
    assert sb.calls[0]["json"] == {"phone": PHONE, "role": "user", "message": "hello",
                                   "message_en": "hello-en"}


def test_set_last_message_en_patches_newest(sb):
    sb.queue.append(ok([{"id": 42}]))
    db.set_last_message_en(PHONE, "user", "english text")
    assert sb.calls[1]["method"] == "PATCH"
    assert sb.calls[1]["params"] == {"id": "eq.42"}
    assert sb.calls[1]["json"] == {"message_en": "english text"}


def test_set_last_message_en_no_rows_or_no_text(sb):
    sb.queue.append(ok([]))
    db.set_last_message_en(PHONE, "user", "x")
    assert len(sb.calls) == 1
    db.set_last_message_en(PHONE, "user", "")
    assert len(sb.calls) == 1


def test_delete_messages(sb):
    db.delete_messages(PHONE)
    assert sb.calls[0]["method"] == "DELETE"
    assert sb.calls[0]["params"] == {"phone": f"eq.{PHONE}"}


def test_delete_last_message_if_role(sb):
    sb.queue.append(ok([{"id": 7, "role": "user"}]))
    db.delete_last_message_if_role(PHONE, "user")
    assert sb.calls[1]["params"] == {"id": "eq.7"}

    sb.calls.clear()
    sb.queue.append(ok([{"id": 8, "role": "bot"}]))
    db.delete_last_message_if_role(PHONE, "user")
    assert len(sb.calls) == 1        # newest is a bot message: nothing deleted


# ─────────────── referrals and orders ───────────────

def test_add_referral(sb):
    db.add_referral(PHONE, "Clinic Poster 1", "DH-0001-ABCD")
    assert sb.calls[0]["url"].endswith("/referrals")
    assert sb.calls[0]["json"]["source"] == "Clinic Poster 1"


def test_add_order_normalises_types(sb):
    db.add_order(PHONE, "DH-0001-ABCD", "Birth kit", 200, "2", "Test Town")
    body = sb.calls[0]["json"]
    assert body["price"] == "200" and body["quantity"] == 2 and body["status"] == "pending"


# ─────────────── disabled and failure paths ───────────────

def test_everything_is_noop_when_disabled(disabled, caplog):
    assert db.get_user_state(PHONE) is None
    db.save_user_state(PHONE, {})
    assert db.get_messages(PHONE) == []
    db.add_message(PHONE, "user", "x")
    db.set_last_message_en(PHONE, "user", "x")
    db.delete_messages(PHONE)
    db.delete_last_message_if_role(PHONE, "user")
    db.add_referral(PHONE, "s", "u")
    db.add_order(PHONE, "u", "p", 1, 1, "a")
    assert disabled.calls == []
    assert "referral not saved" in caplog.text and "order not saved" in caplog.text


@pytest.mark.parametrize("fn, args", [
    (db.get_user_state, (PHONE,)),
    (db.save_user_state, (PHONE, {})),
    (db.get_messages, (PHONE,)),
    (db.add_message, (PHONE, "user", "x")),
    (db.set_last_message_en, (PHONE, "user", "x")),
    (db.delete_messages, (PHONE,)),
    (db.delete_last_message_if_role, (PHONE, "user")),
    (db.add_referral, (PHONE, "s", "u")),
    (db.add_order, (PHONE, "u", "p", 1, 1, "a")),
])
def test_supabase_errors_are_logged_not_raised(sb, caplog, fn, args):
    sb.queue.append(FakeResponse(500, text="boom"))
    result = fn(*args)
    assert result in (None, [])
    assert "[db]" in caplog.text
