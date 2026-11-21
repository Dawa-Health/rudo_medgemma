# Test Coverage Report — Rudo MedGemma

> **Current status (2026-11-18, release round).** The sections below describe the
> original 2026-11-17 suite and are kept for history; use these figures instead:
>
> | Metric | Current |
> |---|---|
> | Tests | 707 collected · 707 passed · 0 failed · 0 skipped · 0 xfail |
> | Line coverage | 1,641 / 1,645 statements = **99.76%** |
> | Branch coverage | 545 / 550 = 99.09% |
> | Combined | 2,186 / 2,195 = 99.59% |
> | CI | Python 3.10 + 3.12 (`ubuntu-latest` = Ubuntu 26.04; setup-python builds exist for both), pinned production deps, `pip check`, startup check, 80% gate. Hosted run: not yet executed (see audit, GitHub) |
> | Interpreter | `scripts/coverage.sh` uses `$PYTHON` or the active virtualenv and prints it; it no longer falls back to `.venv` silently |
>
> Since the original report, production code has changed: safety routing, text normalisation,
> activated local-language self-harm phrases and a narrower "end my" pattern in `main.py` and
> `medgemma_guardrails.py`. See `CLAUDE_INDEPENDENT_AUDIT.md`.

---

**Date:** 2026-11-17 · **Python:** 3.9.6 · **pytest** 8.4.2 · **coverage.py** 7.10.7

## Result

| Metric | Before | After |
|---|---|---|
| Tests | 0 (no test suite existed) | **524 passed, 0 failed, 0 skipped** |
| Line coverage | 0.00% (0 / 1,474 statements measured) | **99.80% (1,499 / 1,502 statements)** |
| Branch coverage | — | 99.20% (494 / 498 branches) |
| Combined line + branch (the `coverage` "TOTAL") | 0.00% | **99.65%** |
| CI gate | none | fails below **80%** |

The baseline denominator was 1,474 statements and the final one is 1,502. `training/` and `api/` have no `__init__.py`, so coverage only counts their files once something imports them. With no tests, none of those 28 statements were visible at baseline (26 in `training/`, 2 in `api/`). See *Measurement integrity*.

## How to reproduce

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
scripts/coverage.sh            # terminal report + htmlcov/index.html + coverage.xml, fails < 80%
```

* `scripts/coverage.sh` unsets real credential variables (Supabase, WhatsApp, Gemini, MedGemma, TranslateGemma, HF) before running.
* The HTML report is written to `htmlcov/index.html`.
* CI: `.github/workflows/tests.yml` runs the same script on Python 3.9 and 3.11 for every push and pull request. It passes no secrets, enforces `--cov-fail-under=80`, and uploads `htmlcov/` as a build artifact.
* The gate was checked in both directions: with the threshold set to 99.9% the script exits 1, and at 80% it exits 0.

## Per-module coverage

| Module | Stmts | Missed | Branches | Partial | Cover |
|---|---|---|---|---|---|
| `main.py` (bot, router, webhook, agents, shop) | 872 | 1 | 310 | 2 | 99.75% |
| `translategemma_client.py` | 188 | 0 | 66 | 1 | 99.61% |
| `db.py` (Supabase/PostgREST) | 125 | 0 | 32 | 0 | 100% |
| `nlp_endpoints.py` (NLLB / GlotLID server) | 101 | 0 | 36 | 0 | 100% |
| `medgemma_client.py` | 66 | 0 | 28 | 0 | 100% |
| `medgemma_guardrails.py` | 49 | 0 | 14 | 0 | 100% |
| `medgemma_server.py` (GPU server) | 49 | 2 | 10 | 1 | 94.92% |
| `langid_client.py` | 22 | 0 | 2 | 0 | 100% |
| `api/index.py`, `products_data.py`, `training/*` (15 files) | 30 | 0 | 0 | 0 | 100% |

## What the tests cover

| Test file | Tests | Focus |
|---|---|---|
| `test_guardrails.py` | 76 | Danger-sign patterns (English and local bleeding words), self-harm detection and its priority over all model output, referral line when the model fails, footer toggle, output cleaning (control tokens, repetition loops, truncation) |
| `test_main_pipeline.py` | 18 | Full multilingual pipeline: local → English → MedGemma → guardrails → local. Covers danger signs found only in the English translation, model outages, non-English model output (retried, then discarded), English leaking into the translation, translation retries, and failure messages kept out of history |
| `test_main_webhook.py` | 40 | End-to-end Flask webhook: verification handshake, onboarding in all 7 languages, referrals, reset, language switching, a complete shop order, a complete human-agent session, non-text messages, duplicate-delivery de-duplication, user isolation, start-up with Supabase configured |
| `test_main_agents.py` | 36 | Escalation: broadcast, accept/reject, all agents rejecting, relays in both directions, END CHAT in every language, timeouts, the `/agent-timeout` endpoint, and key-value store outages |
| `test_main_shop.py` | 110 | Follow-up yes/no, every shop step in every language, cart and orders, the order address skipping keyword routing |
| `test_main_helpers.py` | 62 | WhatsApp sending (splitting at 3,800 chars, error status, what gets stored in history), intent classifiers, referral parsing, user state and history shaping for MedGemma |
| `test_main_language.py` | 20 | Gemini classifier (mocked: valid, blocked, unknown, API error), exact-match fast path, keyword fallback, tie-breaking, protection against a short reply flipping the language |
| `test_translategemma_client.py` | 55 | Masking protected terms, chunking, TranslateGemma HTTP, Gemini fallback and review, English-leak retry, routing per direction, heuristics that trigger review |
| `test_medgemma_client.py` | 20 | History pairing, Gradio SSE parsing, Gradio 5 → 4 route fallback, every service failure returning `None` |
| `test_db.py` | 34 | PostgREST requests, key-value expiry and `nx`, JWT vs `sb_secret_` headers, disabled mode, errors logged and never raised |
| `test_model_servers.py` | 28 | MedGemma server prompt format, auth, token caps; NLLB translate/detect endpoints, all with fake torch/unsloth/transformers/fasttext |
| `test_langid_client.py`, `test_training_data.py`, `test_network_guard.py` | 25 | Remote language ID, knowledge-base integrity, proof that real HTTP is blocked |

## Safety constraints, and how they are enforced

* **No real network calls.** `tests/conftest.py` patches `socket.connect`, `getaddrinfo` and `create_connection` for every test, so any un-mocked WhatsApp, Supabase, Gemini or Hugging Face call fails immediately. `test_network_guard.py` checks this.
* **No real credentials or patient data.** The environment holds only `test-…` placeholders, and Supabase/MedGemma/TranslateGemma URLs are removed before import. Phone numbers (`26377000000x`) and messages are synthetic.
* **No production code changed.** No clinical logic was edited. File timestamps confirm the only changes outside `tests/` are the new `pytest.ini`, `.coveragerc`, `requirements-dev.txt`, `scripts/coverage.sh`, `.github/workflows/tests.yml`, this report, and 5 appended `.gitignore` lines for coverage artefacts. `LICENSE.txt`, `vercel.json` and `requirements.txt` are unchanged.
* **Real guardrails in pipeline tests.** The integration tests stub only the external services (translation, MedGemma, Gemini, WhatsApp, Supabase). `compose_reply`, `clean_model_output` and `pairs_from_history` run unmodified.

## Measurement integrity

* `.coveragerc` measures every `.py` file in the repo except `tests/` and `.venv/`. There are **no `# pragma: no cover` exclusions**.
* A filesystem comparison found one production file coverage could not see: `training/` has no `__init__.py`, so `training/cervical_cancer_data_bemba.py` was left out. `test_training_data.py` now imports it, and every production `.py` file is in the report.
* **Mutation check.** Ten deliberate bugs were injected into a scratch copy of the code; the suite failed on every one:

| Mutation | Failing tests |
|---|---|
| Self-harm check no longer takes priority | 3 |
| Bleeding pattern removed from danger signs | 4 |
| Danger referral only fires when the model answered | 2 |
| Guardrails ignore the English translation | 1 |
| Duplicate webhook deliveries not ignored | 1 |
| Failure message stored in MedGemma history | 1 |
| Local-language text leaks into MedGemma history | 1 |
| Agent END CHAT broken | 8 |
| Supabase history returned newest-first | 1 |
| No Gemini fallback when TranslateGemma fails | 1 |

* The suite runs in about 1–4 seconds and gave the same result on repeated runs.

## Remaining gaps

| Location | Why it is not covered |
|---|---|
| `main.py:2156`, `medgemma_server.py:71-72` | `if __name__ == "__main__":` blocks that start a real server (and load GPU weights). These are entry points, not logic. |
| `main.py` 195→197, `translategemma_client.py` 156→158 | The "`current` is empty after the loop" branch in the two message splitters. In practice it is unreachable: the loop always leaves a value in `current`, and empty input returns earlier. |

**Not covered by this suite (by design):**

* Real model quality: MedGemma answers, translation accuracy, Gemini language ID.
* Real WhatsApp/Supabase contract behaviour.
* Load and concurrency.

These need staging tests with test credentials, not unit tests.

## Observations for the team (no code changed)

1. `training/cervical_cancer_data_bemba.py` is never imported by `main.py` (only Chinyanja and Lozi cervical-cancer data are). It also assigns `cervical_cancer_data_bemba` twice, so the first block (lines 1–154) is overwritten. Worth checking whether this is intended.
2. The cervical-cancer data modules are **tuples** of strings, while the pregnancy modules are single strings. This probably comes from trailing commas.
3. `SELF_HARM_SUPPORT` has no local-language translations yet, so every user gets the English support message. This is the clinically reviewed default, and the tests lock it in.
4. `requirements.txt` is unpinned, and on Python 3.9 pip's resolver backtracked for more than 10 minutes without finishing. The test environment installs only the 3 packages production code actually imports (`requirements-dev.txt`). Pinning versions would make deployments reproducible too.
5. `main.py` sets `genai.configure(...)` and `logging.basicConfig(force=True)` at import time. Tests work around this, but moving these into an app factory would make the module easier to reuse.

## Files added

```
tests/            conftest.py + 14 test modules (524 tests)
pytest.ini        test discovery and warning filters
.coveragerc       measure everything except tests/.venv; fail_under = 80; HTML → htmlcov/
requirements-dev.txt
scripts/coverage.sh
.github/workflows/tests.yml
COVERAGE_REPORT.md
htmlcov/ , coverage.xml   generated reports (gitignored)
```

Nothing has been committed or pushed. The directory is not a git repository.
