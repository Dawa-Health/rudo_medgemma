#!/usr/bin/env python3
"""
Staging smoke checks for Rudo's live integrations. NOT part of the unit test suite.

Runs only when RUDO_STAGING=1 is set, against the services named in the usual environment
variables (see README "Configuration reference"). Uses synthetic text only, never reads or
writes patient data, and is read-only except for:
  * one Supabase kv row "smoke:<timestamp>" that is written, read back and deleted, and
  * one WhatsApp text, only when --send-to <test number> is given.

Usage:
  RUDO_STAGING=1 python scripts/staging_smoke.py [--send-to 2637XXXXXXXX] [--webhook-url URL]

Each check prints PASS / FAIL / SKIP (not configured). Exit code 1 if any check FAILs.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SYNTHETIC_TEXT = "How many antenatal visits should I have?"   # no personal data


def _check(name, fn):
    try:
        detail = fn()
    except Exception as e:                      # report, never raise
        return name, "FAIL", f"{type(e).__name__}: {e}"
    if detail is None:
        return name, "SKIP", "not configured"
    return name, "PASS", detail


def check_supabase():
    import db
    if not db.enabled():
        return None
    key = f"smoke:{int(time.time())}"
    db.kv.ping()
    db.kv.set(key, "ok", ex=60)
    got = db.kv.get(key)
    db.kv.delete(key)
    if got != "ok":
        raise RuntimeError(f"kv round trip returned {got!r}")
    return "kv ping + write/read/delete round trip"


def check_medgemma():
    import medgemma_client
    if not medgemma_client.medgemma_enabled():
        return None
    answer = medgemma_client.ask_medgemma(SYNTHETIC_TEXT)
    if not answer:
        raise RuntimeError("no answer (Space asleep, wrong URL or token?)")
    return f"{len(answer)} chars"


def check_translategemma():
    import translategemma_client as tc
    if not tc.translategemma_enabled():
        return None
    out = tc._tg_translate(SYNTHETIC_TEXT, "english", "shona")
    return f"en->sn {len(out)} chars"


def check_langid():
    import langid_client
    if not langid_client.LANGID_URL:
        return None
    lang = langid_client.detect_remote("Mhoroi, makadini?")
    if lang is None:
        raise RuntimeError("no language returned")
    return f"detected {lang}"


def check_whatsapp_token(send_to=None):
    import requests
    token, phone_id = os.environ.get("WA_TOKEN"), os.environ.get("PHONE_ID")
    if not token or not phone_id:
        return None
    r = requests.get(f"https://graph.facebook.com/v19.0/{phone_id}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    r.raise_for_status()
    detail = "phone number id readable"
    if send_to:
        r = requests.post(f"https://graph.facebook.com/v19.0/{phone_id}/messages",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"messaging_product": "whatsapp", "to": send_to, "type": "text",
                                "text": {"body": "Rudo staging smoke test (synthetic message)."}},
                          timeout=15)
        r.raise_for_status()
        detail += f"; test message accepted for {send_to}"
    return detail


def check_webhook(url=None):
    import requests
    token = os.environ.get("VERIFY_TOKEN")
    if not url or not token:
        return None
    r = requests.get(url, params={"hub.mode": "subscribe", "hub.verify_token": token,
                                  "hub.challenge": "smoke123"}, timeout=15)
    if r.status_code != 200 or r.text != "smoke123":
        raise RuntimeError(f"verification handshake returned {r.status_code} {r.text[:80]!r}")
    return "verification handshake ok"


def run(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--send-to", help="WhatsApp TEST number to receive one synthetic message")
    p.add_argument("--webhook-url", help="deployed https://.../webhook to check the handshake")
    args = p.parse_args(argv)
    if environ.get("RUDO_STAGING") != "1":
        print("Refusing to run: set RUDO_STAGING=1 to confirm these are staging credentials.")
        return 2
    results = [
        _check("supabase", check_supabase),
        _check("medgemma", check_medgemma),
        _check("translategemma", check_translategemma),
        _check("langid", check_langid),
        _check("whatsapp", lambda: check_whatsapp_token(args.send_to)),
        _check("webhook", lambda: check_webhook(args.webhook_url)),
    ]
    for name, status, detail in results:
        print(f"{status:4}  {name:15} {detail}")
    return 1 if any(s == "FAIL" for _, s, _ in results) else 0


if __name__ == "__main__":
    sys.exit(run())
