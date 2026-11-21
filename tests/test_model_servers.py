"""
GPU-side services (medgemma_server.py, nlp_endpoints.py) tested without a GPU.
torch / unsloth / transformers / fasttext / huggingface_hub are replaced by small fakes in
sys.modules, so no model weights are downloaded and no inference runs.
"""
import contextlib
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest
from flask import Flask


# ─────────────── fake ML stack ───────────────

class FakeTensor:
    def __init__(self, data):
        self.data = list(data)
        self.shape = (1, len(self.data))

    def __getitem__(self, item):
        return self.data[item]


class FakeBatch(dict):
    def to(self, device):
        assert device == "cuda"
        return self


def make_torch():
    torch = ModuleType("torch")
    torch.no_grad = contextlib.nullcontext
    torch.float16 = "float16"
    return torch


@pytest.fixture
def fake_torch(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", make_torch())


# ═════════════ medgemma_server ═════════════

import medgemma_server as ms  # noqa: E402


class FakeGemmaTokenizer:
    def __call__(self, text=None, return_tensors=None):
        self.prompt = text
        return FakeBatch(input_ids=FakeTensor([1, 2, 3]))

    def decode(self, ids, skip_special_tokens=True):
        return "  Generated answer.  " if list(ids) == [9, 9] else "?"


class FakeGemmaModel:
    def generate(self, **kw):
        self.kw = kw
        return [kw["input_ids"].data + [9, 9]]


@pytest.fixture
def server(monkeypatch, fake_torch):
    tok, model = FakeGemmaTokenizer(), FakeGemmaModel()
    monkeypatch.setattr(ms, "_state", {"model": model, "tokenizer": tok})
    monkeypatch.setattr(ms, "API_TOKEN", "srv-token")
    return SimpleNamespace(client=ms.app.test_client(), tok=tok, model=model)


AUTH = {"Authorization": "Bearer srv-token"}


def test_build_prompt_single_turn_includes_system():
    p = ms.build_prompt("Is ginger safe?")
    assert p == f"<start_of_turn>user\n{ms.SYSTEM}\n\nIs ginger safe?<end_of_turn>\n<start_of_turn>model\n"


def test_build_prompt_with_history_truncates_and_folds_system():
    hist = [{"user": f"u{i}", "model": f"m{i}"} for i in range(4)]
    p = ms.build_prompt("now?", hist)
    assert "u0" not in p and "u1" not in p                    # only the last 2 turns
    assert p.startswith(f"<start_of_turn>user\n{ms.SYSTEM}\n\nu2")
    assert p.count(ms.SYSTEM) == 1
    assert p.endswith("<start_of_turn>user\nnow?<end_of_turn>\n<start_of_turn>model\n")


def test_health(server):
    r = server.client.get("/health")
    assert r.get_json() == {"status": "ok", "adapter": ms.ADAPTER}


def test_answer_requires_token(server):
    assert server.client.post("/answer", json={"question": "q"}).status_code == 401
    assert server.client.post("/answer", json={"question": "q"},
                              headers={"Authorization": "Bearer wrong"}).status_code == 401


@pytest.mark.parametrize("body", [{}, {"question": "   "}, None])
def test_answer_requires_question(server, body):
    r = server.client.post("/answer", json=body, headers=AUTH)
    assert r.status_code == 400


def test_answer_generates_and_caps_tokens(server):
    r = server.client.post("/answer", headers=AUTH, json={
        "question": "x" * 2000, "max_new_tokens": 9999,
        "history": [{"user": "q", "model": "a"}]})
    assert r.status_code == 200
    assert r.get_json() == {"answer": "Generated answer."}
    assert server.model.kw["max_new_tokens"] == 400
    assert server.model.kw["do_sample"] is False
    assert ("x" * 1500) in server.tok.prompt and ("x" * 1501) not in server.tok.prompt


def test_answer_open_when_no_token_configured(server, monkeypatch):
    monkeypatch.setattr(ms, "API_TOKEN", None)
    r = server.client.post("/answer", json={"question": "hi there"})
    assert r.status_code == 200
    assert server.model.kw["max_new_tokens"] == 300


def test_get_model_loads_once(monkeypatch):
    loaded = []

    class FastModel:
        @staticmethod
        def from_pretrained(model_name, max_seq_length, load_in_4bit):
            loaded.append(model_name)
            return "M", "T"

        @staticmethod
        def for_inference(model):
            loaded.append(("inference", model))

    unsloth = ModuleType("unsloth")
    unsloth.FastModel = FastModel
    monkeypatch.setitem(sys.modules, "unsloth", unsloth)
    monkeypatch.setattr(ms, "_state", {})
    assert ms.get_model() == ("M", "T")
    assert ms.get_model() == ("M", "T")
    assert loaded == [ms.ADAPTER, ("inference", "M")]


# ═════════════ nlp_endpoints ═════════════

import nlp_endpoints as ne  # noqa: E402


class FakeNLLBTokenizer:
    def __init__(self):
        self.src_lang = None
        self.batches = []

    def convert_tokens_to_ids(self, code):
        return f"id:{code}"

    def __call__(self, sents, **kw):
        self.batches.append((self.src_lang, list(sents)))
        return FakeBatch(input_ids=list(sents))

    def batch_decode(self, gen, skip_special_tokens=True):
        return [f"T({s})" for s in gen]


class FakeNLLBModel:
    def __init__(self):
        self.calls = []

    def generate(self, **kw):
        self.calls.append(kw)
        return kw["input_ids"]


class FakeGlot:
    def __init__(self, labels, probs):
        self.result = (labels, probs)

    def predict(self, text, k=1):
        return self.result


@pytest.fixture
def nlp(monkeypatch, fake_torch):
    monkeypatch.setattr(ne, "API_TOKEN", "nlp-token")
    tok, model = FakeNLLBTokenizer(), FakeNLLBModel()
    state = {"nllb": (tok, model)}
    monkeypatch.setattr(ne, "_state", state)
    app = Flask("nlp-test")
    ne.register(app)
    return SimpleNamespace(client=app.test_client(), tok=tok, model=model, state=state)


NLP_AUTH = {"Authorization": "Bearer nlp-token"}


def test_register_refuses_without_token(monkeypatch):
    monkeypatch.setattr(ne, "API_TOKEN", None)
    with pytest.raises(RuntimeError, match="MEDGEMMA_TOKEN"):
        ne.register(Flask("x"))


def test_register_accepts_shared_gpu_lock(monkeypatch):
    monkeypatch.setattr(ne, "API_TOKEN", "t")
    ne.register(Flask("y"), gpu_lock=threading.Lock())


def test_latin_ok():
    assert ne._latin_ok("123 !!")
    assert ne._latin_ok("Mhoro, makadini? Ñoña")
    assert not ne._latin_ok("Привет мир")


@pytest.mark.parametrize("route", ["/translate", "/detect"])
def test_endpoints_require_auth(nlp, route):
    assert nlp.client.post(route, json={"text": "x"}).status_code == 401
    assert nlp.client.post(route, json={"text": "x"},
                           headers={"Authorization": "Bearer nope"}).status_code == 401


@pytest.mark.parametrize("body, code", [
    ({"text": ""}, 400),
    ({"text": "x" * (ne.MAX_CHARS + 1), "source_lang_code": "sn", "target_lang_code": "en"}, 413),
    ({"text": "hi", "source_lang_code": "fr", "target_lang_code": "en"}, 422),
    ({"text": "hi", "source_lang_code": "sn", "target_lang_code": "loz"}, 422),
])
def test_translate_validation(nlp, body, code):
    assert nlp.client.post("/translate", json=body, headers=NLP_AUTH).status_code == code


def test_translate_same_language_passthrough(nlp):
    r = nlp.client.post("/translate", headers=NLP_AUTH,
                        json={"text": "Mhoro", "source_lang_code": "sn", "target_lang_code": "sn"})
    assert r.get_json() == {"translation": "Mhoro", "engine": "none", "approximate": False}


def test_translate_splits_lines_and_sentences(nlp):
    text = "One. Two!\n\nThree?"
    r = nlp.client.post("/translate", headers=NLP_AUTH,
                        json={"text": text, "source_lang_code": "sn", "target_lang_code": "en"})
    data = r.get_json()
    assert r.status_code == 200
    assert data == {"translation": "T(One.) T(Two!)\n\nT(Three?)", "engine": "nllb-200",
                    "approximate": False}
    assert nlp.tok.batches[0] == ("sna_Latn", ["One.", "Two!"])
    assert nlp.model.calls[0]["forced_bos_token_id"] == "id:eng_Latn"


def test_translate_batches_of_eight_and_ndebele_approximate(nlp):
    text = " ".join(f"S{i}." for i in range(10))
    r = nlp.client.post("/translate", headers=NLP_AUTH,
                        json={"text": text, "source_lang_code": "en", "target_lang_code": "nd"})
    assert r.get_json()["approximate"] is True
    assert [len(b[1]) for b in nlp.tok.batches] == [8, 2]


def test_translate_rejects_wrong_script(nlp, monkeypatch):
    monkeypatch.setattr(ne, "_translate", lambda *a: "Привет")
    r = nlp.client.post("/translate", headers=NLP_AUTH,
                        json={"text": "hi", "source_lang_code": "en", "target_lang_code": "sn"})
    assert r.status_code == 422


def test_detect_empty_text(nlp):
    r = nlp.client.post("/detect", headers=NLP_AUTH, json={"text": "   "})
    assert r.get_json() == {"language": None, "confidence": 0.0, "scores": {}}


def test_detect_folds_labels_and_thresholds(nlp):
    nlp.state["glot"] = FakeGlot(
        ["__label__zul_Latn", "__label__nde_Latn", "__label__eng_Latn", "__label__fra_Latn"],
        [0.3, 0.3, 0.2, 0.2])
    r = nlp.client.post("/detect", headers=NLP_AUTH, json={"text": "Sawubona  unjani"})
    data = r.get_json()
    assert data["language"] == "ndebele"
    assert data["confidence"] == 0.6
    assert data["scores"] == {"ndebele": 0.6, "english": 0.2}


def test_detect_low_confidence_returns_none(nlp):
    nlp.state["glot"] = FakeGlot(["__label__sna_Latn", "__label__eng_Latn"], [0.3, 0.25])
    data = nlp.client.post("/detect", headers=NLP_AUTH, json={"text": "ok"}).get_json()
    assert data["language"] is None and data["confidence"] == 0.3


def test_detect_no_supported_labels(nlp):
    nlp.state["glot"] = FakeGlot(["__label__fra_Latn"], [0.99])
    data = nlp.client.post("/detect", headers=NLP_AUTH, json={"text": "bonjour"}).get_json()
    assert data == {"language": None, "confidence": 0.0, "scores": {}}


def test_model_loaders_cache(monkeypatch, fake_torch):
    monkeypatch.setattr(ne, "_state", {})
    events = []

    class _Loaded:
        def to(self, dev):
            events.append(("to", dev))
            return self

        def eval(self):
            events.append("eval")
            return self

    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = SimpleNamespace(
        from_pretrained=lambda mid: events.append(("tok", mid)) or "TOK")
    transformers.AutoModelForSeq2SeqLM = SimpleNamespace(
        from_pretrained=lambda mid, torch_dtype=None: events.append(("model", mid, torch_dtype)) or _Loaded())
    fasttext = ModuleType("fasttext")
    fasttext.load_model = lambda path: events.append(("ft", path)) or "GLOT"
    hub = ModuleType("huggingface_hub")
    hub.hf_hub_download = lambda repo, fname, token=None: events.append(("hub", repo, fname)) or "/fake/model.bin"
    for name, mod in (("transformers", transformers), ("fasttext", fasttext), ("huggingface_hub", hub)):
        monkeypatch.setitem(sys.modules, name, mod)

    tok, model = ne._get_nllb()
    assert tok == "TOK" and isinstance(model, _Loaded)
    ne._get_nllb()
    assert ne._get_glot() == "GLOT"
    ne._get_glot()
    assert events == [("tok", ne.NLLB_ID), ("model", ne.NLLB_ID, "float16"), ("to", "cuda"), "eval",
                      ("hub", "cis-lmu/glotlid", "model.bin"), ("ft", "/fake/model.bin")]
