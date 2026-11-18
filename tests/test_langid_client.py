"""Remote language-ID client (HTTP mocked)."""
import pytest

import langid_client as lc
from conftest import FakeResponse


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(lc, "LANGID_URL", "https://langid.test/detect")
    monkeypatch.setattr(lc, "LANGID_TOKEN", "tok")


def test_disabled_or_empty_returns_none(monkeypatch):
    monkeypatch.setattr(lc, "LANGID_URL", "")
    assert lc.detect_remote("Mhoro") is None


@pytest.mark.parametrize("msg", ["", "   ", None])
def test_blank_message_returns_none(on, msg):
    assert lc.detect_remote(msg) is None


def test_supported_language_returned_with_auth(monkeypatch, on):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return FakeResponse(200, {"language": "shona", "confidence": 0.93})

    monkeypatch.setattr(lc.requests, "post", fake_post)
    assert lc.detect_remote("Mhoro, makadini") == "shona"
    assert seen["headers"] == {"Authorization": "Bearer tok"}
    assert seen["json"] == {"text": "Mhoro, makadini"}


def test_no_token_means_no_auth_header(monkeypatch, on):
    monkeypatch.setattr(lc, "LANGID_TOKEN", None)
    seen = {}
    monkeypatch.setattr(lc.requests, "post", lambda url, json=None, headers=None, timeout=None:
                        seen.update(h=headers) or FakeResponse(200, {"language": "english"}))
    assert lc.detect_remote("hello") == "english"
    assert seen["h"] == {}


@pytest.mark.parametrize("resp", [FakeResponse(200, {"language": "french"}),
                                  FakeResponse(200, {"language": None}),
                                  FakeResponse(500)])
def test_unsupported_or_failed_returns_none(monkeypatch, on, resp):
    monkeypatch.setattr(lc.requests, "post", lambda *a, **k: resp)
    assert lc.detect_remote("bonjour") is None
