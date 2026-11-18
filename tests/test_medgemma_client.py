"""MedGemma Gradio client: history shaping, SSE parsing and failure handling (HTTP is mocked)."""
import json

import pytest

import medgemma_client as mc
from conftest import FakeResponse


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(mc, "MEDGEMMA_URL", "https://medgemma.test")
    monkeypatch.setattr(mc, "MEDGEMMA_TOKEN", "space-token")
    monkeypatch.setattr(mc, "HF_TOKEN", None)


# ─────────────── pairs_from_history ───────────────

def test_pairs_empty_inputs():
    assert mc.pairs_from_history(None) == []
    assert mc.pairs_from_history([]) == []
    assert mc.pairs_from_history([{"role": "user", "message": "current"}]) == []


def test_pairs_builds_user_model_pairs_and_drops_current_question():
    long_reply = "Attend at least eight antenatal contacts during pregnancy."
    entries = [
        {"role": "user", "message": "How many visits?"},
        {"role": "bot", "message": long_reply},
        {"role": "user", "message": "current question"},
    ]
    assert mc.pairs_from_history(entries) == [{"user": "How many visits?", "model": long_reply}]


def test_pairs_skips_short_acks_blank_and_orphans():
    reply = "This is a long enough model answer for history."
    entries = [
        {"role": "bot", "message": "Orphan bot message with no question first."},
        {"role": "user", "message": "   "},
        {"role": "user", "message": "q1"},
        {"role": "bot", "message": "ok thanks"},          # < 20 chars: skipped, q1 stays pending
        {"role": "user", "message": "q2"},
        {"role": "bot", "message": reply},
        {"role": "user", "message": None},
        {"role": "user", "message": "current"},
    ]
    assert mc.pairs_from_history(entries) == [{"user": "q2", "model": reply}]


def test_pairs_keeps_only_last_max_turns():
    entries = []
    for i in range(5):
        entries += [{"role": "user", "message": f"q{i}"},
                    {"role": "bot", "message": f"answer number {i} long enough here"}]
    entries.append({"role": "user", "message": "now"})
    out = mc.pairs_from_history(entries, max_turns=2)
    assert [p["user"] for p in out] == ["q3", "q4"]


# ─────────────── headers / SSE ───────────────

def test_headers_with_and_without_hf_token(monkeypatch):
    monkeypatch.setattr(mc, "HF_TOKEN", None)
    assert mc._headers() == {"Content-Type": "application/json"}
    monkeypatch.setattr(mc, "HF_TOKEN", "hf_fake")
    assert mc._headers()["Authorization"] == "Bearer hf_fake"


def test_read_sse_complete():
    resp = FakeResponse(lines=["", "event: generating", "data: [\"partial\"]",
                               "event: complete", 'data: ["Final answer."]'])
    assert mc._read_sse_result(resp) == "Final answer."


def test_read_sse_ignores_comment_and_id_lines():
    resp = FakeResponse(lines=[": keep-alive", "id: 7", "event: complete", 'data: ["ok answer"]'])
    assert mc._read_sse_result(resp) == "ok answer"


def test_read_sse_complete_with_empty_payload():
    resp = FakeResponse(lines=["event: complete", "data: []"])
    assert mc._read_sse_result(resp) == ""


def test_read_sse_error_event_raises():
    resp = FakeResponse(lines=["event: error", "data: null"])
    with pytest.raises(RuntimeError, match="error"):
        mc._read_sse_result(resp)


def test_read_sse_stream_without_result_raises():
    with pytest.raises(RuntimeError, match="ended"):
        mc._read_sse_result(FakeResponse(lines=["event: heartbeat", "data: null"]))


# ─────────────── ask_medgemma ───────────────

def test_ask_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(mc, "MEDGEMMA_URL", "")
    assert mc.medgemma_enabled() is False
    assert mc.ask_medgemma("question") is None


def _install(monkeypatch, post_responses, stream_response, record):
    def fake_post(url, headers=None, json=None, timeout=None):
        record.append(("post", url, json))
        return post_responses.pop(0)

    def fake_get(url, headers=None, stream=False, timeout=None):
        record.append(("get", url, None))
        return stream_response

    monkeypatch.setattr(mc.requests, "post", fake_post)
    monkeypatch.setattr(mc.requests, "get", fake_get)


def test_ask_gradio5_route_success(monkeypatch, enabled):
    record = []
    _install(monkeypatch,
             [FakeResponse(200, {"event_id": "evt1"})],
             FakeResponse(200, lines=["event: complete", 'data: ["  Rest and hydrate.  "]']),
             record)
    history = [{"user": "q", "model": "a"}]
    assert mc.ask_medgemma("Is it safe?", history=history) == "Rest and hydrate."
    kind, url, body = record[0]
    assert url == "https://medgemma.test/gradio_api/call/answer"
    assert body["data"] == ["Is it safe?", json.dumps(history), mc.MAX_NEW_TOKENS, "space-token"]
    assert record[1][1] == "https://medgemma.test/gradio_api/call/answer/evt1"


def test_ask_falls_back_to_gradio4_route(monkeypatch, enabled):
    record = []
    _install(monkeypatch,
             [FakeResponse(404), FakeResponse(200, {"event_id": "e2"})],
             FakeResponse(200, lines=["event: complete", 'data: ["Answer."]']),
             record)
    assert mc.ask_medgemma("q") == "Answer."
    assert record[1][1] == "https://medgemma.test/call/answer"


def test_ask_no_route_found(monkeypatch, enabled):
    _install(monkeypatch, [FakeResponse(404), FakeResponse(404)], None, [])
    assert mc.ask_medgemma("q") is None


def test_ask_empty_model_text_returns_none(monkeypatch, enabled):
    _install(monkeypatch, [FakeResponse(200, {"event_id": "e"})],
             FakeResponse(200, lines=["event: complete", 'data: ["   "]']), [])
    assert mc.ask_medgemma("q") is None


@pytest.mark.parametrize("post, stream", [
    (FakeResponse(500), None),                                            # HTTP error
    (FakeResponse(200, {"no_event": 1}), None),                           # malformed JSON
    (FakeResponse(200, {"event_id": "e"}), FakeResponse(503)),            # stream fails
    (FakeResponse(200, {"event_id": "e"}),
     FakeResponse(200, lines=["event: error", "data: \"GPU OOM\""])),     # model error
])
def test_ask_service_failures_return_none(monkeypatch, enabled, post, stream):
    _install(monkeypatch, [post], stream, [])
    assert mc.ask_medgemma("q") is None


def test_ask_timeout_returns_none(monkeypatch, enabled):
    def boom(*a, **k):
        raise mc.requests.Timeout("slow")
    monkeypatch.setattr(mc.requests, "post", boom)
    assert mc.ask_medgemma("q") is None
