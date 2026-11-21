"""The staging smoke script must refuse to run without opt-in and report honestly.
Everything is faked here; this does NOT test live services."""
import importlib.util
import os
from types import SimpleNamespace

import pytest

from conftest import FakeKV, FakeResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("staging_smoke", os.path.join(ROOT, "scripts", "staging_smoke.py"))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_refuses_without_explicit_opt_in(capsys):
    assert smoke.run([], environ={}) == 2
    assert "Refusing" in capsys.readouterr().out


def test_unconfigured_services_are_skipped_not_passed(capsys, monkeypatch):
    monkeypatch.delenv("WA_TOKEN", raising=False)
    assert smoke.run([], environ={"RUDO_STAGING": "1"}) == 0
    out = capsys.readouterr().out
    assert "PASS" not in out and out.count("SKIP") == 6


def test_failures_are_reported_and_exit_nonzero(capsys, monkeypatch):
    monkeypatch.setattr(smoke, "check_medgemma", lambda: (_ for _ in ()).throw(RuntimeError("asleep")))
    assert smoke.run([], environ={"RUDO_STAGING": "1"}) == 1
    assert "FAIL  medgemma" in capsys.readouterr().out


def test_supabase_round_trip(monkeypatch):
    import db
    kv = FakeKV()
    monkeypatch.setattr(db, "enabled", lambda: True)
    monkeypatch.setattr(db, "kv", kv)
    assert "round trip" in smoke.check_supabase()
    assert kv.store == {}                                      # smoke row cleaned up
    kv.get = lambda key: None
    with pytest.raises(RuntimeError):
        smoke.check_supabase()


def test_model_checks(monkeypatch):
    import langid_client
    import medgemma_client
    import translategemma_client as tc
    monkeypatch.setattr(medgemma_client, "MEDGEMMA_URL", "https://m.test")
    monkeypatch.setattr(medgemma_client, "ask_medgemma", lambda q: "Eight contacts.")
    assert smoke.check_medgemma() == "15 chars"
    monkeypatch.setattr(medgemma_client, "ask_medgemma", lambda q: None)
    with pytest.raises(RuntimeError):
        smoke.check_medgemma()

    monkeypatch.setattr(tc, "TG_URL", "https://t.test")
    monkeypatch.setattr(tc, "_tg_translate", lambda t, s, d: "Shona text")
    assert smoke.check_translategemma() == "en->sn 10 chars"

    monkeypatch.setattr(langid_client, "LANGID_URL", "https://l.test")
    monkeypatch.setattr(langid_client, "detect_remote", lambda m: "shona")
    assert smoke.check_langid() == "detected shona"
    monkeypatch.setattr(langid_client, "detect_remote", lambda m: None)
    with pytest.raises(RuntimeError):
        smoke.check_langid()


def test_whatsapp_and_webhook_checks(monkeypatch):
    import requests
    calls = []
    monkeypatch.setenv("WA_TOKEN", "t")
    monkeypatch.setenv("PHONE_ID", "p")
    monkeypatch.setenv("VERIFY_TOKEN", "v")
    monkeypatch.setattr(requests, "get", lambda url, **kw: calls.append(("get", url)) or
                        FakeResponse(200, text=kw.get("params", {}).get("hub.challenge", "")))
    monkeypatch.setattr(requests, "post", lambda url, **kw: calls.append(("post", kw["json"]["to"])) or
                        FakeResponse(200, {}))
    assert smoke.check_whatsapp_token() == "phone number id readable"
    assert not any(c[0] == "post" for c in calls)              # no message without --send-to
    assert "accepted for 263770000009" in smoke.check_whatsapp_token("263770000009")
    assert smoke.check_webhook("https://bot.test/webhook") == "verification handshake ok"
    assert smoke.check_webhook(None) is None
    monkeypatch.setattr(requests, "get", lambda url, **kw: FakeResponse(403, text="Failed"))
    with pytest.raises(RuntimeError):
        smoke.check_webhook("https://bot.test/webhook")


def test_passing_check_is_reported_as_pass(capsys, monkeypatch):
    monkeypatch.delenv("WA_TOKEN", raising=False)
    monkeypatch.setattr(smoke, "check_langid", lambda: "detected shona")
    assert smoke.run([], environ={"RUDO_STAGING": "1"}) == 0
    assert "PASS  langid          detected shona" in capsys.readouterr().out
