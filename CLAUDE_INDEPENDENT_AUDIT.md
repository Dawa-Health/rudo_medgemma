# Independent Audit — Rudo MedGemma

**Date:** 2026-11-18 · **Scope:** the work Cline reported (dependencies, Bemba data, multilingual self-harm fixtures, tests, coverage, CI, `GAP_REMEDIATION_REPORT.md`), plus safety routing, dependency verification, and GitHub/CI readiness.
**Reference baseline:** upstream `github.com/Dawa-Health/rudo_medgemma` `main` @ `3260259` ("Add files via upload"), cloned and diffed file by file.
**Backup:** a full copy of the pre-audit working tree is at `~/Downloads/rudo_medgemma-snapshot-20261118-095739/`.

## Release round — current status (supersedes earlier statements below where they differ)

| Item | Status | Evidence |
|---|---|---|
| Local-language self-harm phrases | **ACTIVE** in all six languages (8 phrases, text unchanged). Activated on the project team's written confirmation that the existing contents were clinically and linguistically verified. No reviewer names or dates were invented. | `MULTILINGUAL_SELF_HARM_FIXTURES` statuses = `APPROVED`; 8 per-phrase webhook tests with translation and language ID down; mutation "one language left PENDING" → 9 failures |
| "end my" false positive (H3) | **FIXED.** `\bend (?:my\|it all\|my life)\b` → `\bend (?:it all\|my (?:own )?(?:life\|suffering\|existence))\b`. The old `my` alternative also made `my life` unreachable. | Both former XFAIL cases now pass as normal tests; restoring the old strict-xfail marker gives XPASS(strict) → fail; 7 positive + 5 negative regression tests |
| Coverage script interpreter (new, M4) | **FIXED.** `coverage.sh` preferred `.venv/bin/python` over the active venv, so a "3.12" run used 3.9.6. It now uses `$PYTHON`, else the active `$VIRTUAL_ENV`, else exits 2, and prints the interpreter. `.coveragerc` now also omits `.venv*/`, `venv/`, `verify-logs/`. | Test log line `coverage.sh: using …3.12.14 (from PYTHON)` and `platform darwin, python 3.12.14-final-0`; denominator unchanged at 1,645 with venvs inside the repo |
| Tests | **707 collected, 707 passed, 0 failed, 0 skipped, 0 xfail** | Python 3.12.14 and 3.9.6 |
| Coverage | Lines **1,641/1,645 = 99.76%** · branches **545/550 = 99.09%** · combined **2,186/2,195 = 99.59%** | coverage.py JSON totals |
| Python 3.12 (production) | **PASS**: clean install, `pip check`, startup, suite | `verify-logs/verify-20261118-115009.log` |
| Python 3.10 / 3.11 | **PASS** on both: install, `pip check`, startup, 707 passed | `verify-logs/verify-20261118-121135.log`, `…-121307.log` |
| Model server | Resolves for Linux x86_64 on 3.11 and 3.12 (`requirements-server.lock`). **Not installed or run on a GPU.** | `uv pip compile --python-platform x86_64-manylinux_2_28` |
| Upstream | `main` moved `3260259` → `af2545c` (adds `CHARTER.md`, `CONTRIBUTING.md`, `CODE_OF-CONDUCT.md`; no overlap). Branch built on `af2545c`. | `git log 3260259..origin/main` |
| Push | **Refused by GitHub (403)**: `Samuel04-png` has `push: false` on `Dawa-Health/rudo_medgemma`. See *GitHub* below. | `git push` output |

**Residual clinical risk to monitor after release.** The earlier agent's unverified glosses described two of the now-active phrases as illness rather than self-harm: Shona `ndinovave kubuda` ("I keep vomiting") and Lozi `ha ni zuba mbilien` ("I am very sick"). The team's confirmation overrides those glosses. If the glosses were in fact right, users writing those exact words would get the self-harm support message instead of a medical answer. Review the logs for these two phrases in staging.

**Merge approvals required (CONTRIBUTING.md / CHARTER.md).** One maintainer; one clinical reviewer (guardrails and self-harm patterns); one language reviewer (local-language phrases).

## Summary for decision-makers (first audit pass)

1. **Ready for staging verification. Not ready for production** until the three items under *Pending external approval* are decided.
2. **The local-language self-harm phrases were NOT activated.** The team reported them as clinically and linguistically verified, but the file's own annotations contradict that: the Shona phrase is glossed *"I keep vomiting"* and the Lozi phrase *"I am very sick"*. A self-harm match replaces the medical answer with the crisis message, so activating them would hide answers to one of the most common pregnancy complaints. The production detector, routing and tests are built and in place. Activating a language is a one-word change (`"PENDING"` → `"APPROVED"`) once the exact phrase list is confirmed.
3. **Five safety defects in the original app were found and fixed.** They predate Cline. The most serious:
   - A message like "I want to die" sent while the user was in the shop flow was **saved as a delivery address and confirmed as an order**.
   - iPhone apostrophes made **"I don’t want to live"** and **"I can’t breathe"** go undetected.
4. **Cline's Bemba data fix and package removals are correct.** Cline's model-server requirements, CI matrix and several tests were not, and have been corrected.

## Findings and fixes

Severity: Critical = clinical safety / privacy / serious data integrity; High = production failure or important broken behaviour; Medium = reliability or significant test weakness; Low = documentation.

| # | Sev. | Origin | Finding | Status |
|---|---|---|---|---|
| C1 | Critical | Original app | Guardrails ran only in the final "answer" step, so earlier routing steps could swallow urgent messages. **Shop steps:** "I'm bleeding" got *"Please enter a number"*; in the address step, self-harm text was stored as the delivery address and an order confirmation was sent. **Follow-up:** "yes kill myself" was read as "yes"; "no I'm bleeding" was read as "no" and led to a product offer. **Reset:** "restart, I want to die" cleared the chat and replied *"Hello!"*. **Waiting for an agent:** urgent messages got no reply at all. | **Fixed**: `handle_message` screens every message first; the waiting step replies with the guardrail text. Confirmed by 27 tests that failed before the fix. |
| C2 | Critical | Original app | No text normalisation. iOS "smart punctuation" (`’`), double spaces, line breaks and non-breaking spaces defeated both self-harm and danger-sign patterns. Cline's two "Unicode normalization" tests contained `pass` and checked only plain ASCII. | **Fixed**: `normalize_for_safety()` (NFKC, apostrophe folding, whitespace collapse, casefold). The patterns themselves are unchanged. |
| C3 | Critical | Fixture content | The "approved" local phrases don't match their own glosses (vomiting, very sick, a Chinyanja phrase apparently ending in *"dance"*). All were still marked "requires verification" by Cline. | First pass: not activated, and the discrepancy reported. **Release round: the project team confirmed the existing contents; all six languages ACTIVE.** Glosses kept in `LOCAL_SELF_HARM_REVIEW_NOTES` as audit history. |
| H1 | High | Original app | After the self-harm support message, the bot asked *"Is there anything else I can help you with?"*; replying "no" opened the product offer (ultrasound, birth kits). | **Fixed**: no follow-up question after the support message. Danger-sign answers keep their follow-up. |
| H2 | High | Cline | `requirements-server.txt`: fasttext 0.9.3 calls `np.array(probs, copy=False)` in `predict()` (`FastText.py` line 239), which raises on NumPy 2. `/detect` would crash on a fresh install. `transformers` was also listed twice. | **Fixed** (`numpy<2`, exact fasttext pin). Verified from the package source; a GPU install was not run. |
| H3 | High | Original pattern | Self-harm false positive: `\bend (?:my\|it all\|my life)\b` matches any "end my", so *"How can I end my nausea?"* gets the crisis message and no answer. | **Fixed in the release round** (pattern narrowed; strict-xfail replaced by passing positive and negative tests). Possible false negative: "end my pain" is no longer self-harm. That is deliberate (labour pain); the clinical reviewer should confirm. |
| M4 | Medium | Coverage tooling | `coverage.sh` silently used `.venv/bin/python` (3.9.6) even with a 3.12 venv active; venvs named `.venv-*` were not excluded from measurement. | **Fixed** (release round). |
| M1 | Medium | Cline | Weak tests: two contained `pass`; one asserted that a misspelt word (`"antennatal"`) was absent, which is always true; one only checked `isinstance(str)`. They could not fail. | **Replaced** with behaviour tests (see Testing). |
| M2 | Medium | CI | The matrix ran 3.9 (README: "Python 3.10 or newer"; Vercel runs 3.12) and installed **unpinned** packages, so CI never tested the deployed versions. | **Fixed**: 3.10 + 3.12, installs `requirements.txt` pins, `pip check`, startup check, `fail-fast: false`, timeout, 14-day artifact retention. |
| M3 | Medium | Cline report | Mis-stated figures. The "9 + 7" test split was really 12 + 4. "1,504 / 1,507 combined" is the **line** ratio. It claimed "CI locally validated" (3.11 was never run) and "all 14 acceptance criteria met". | **Corrected** in `GAP_REMEDIATION_REPORT.md`. |
| L1 | Low | Cline | `requirements.txt` header said "Python 3.9 – 3.11"; README says 3.10+. | Documented; header comment left for the team. |
| — | OK | Cline | Bemba duplicate assignment removed. | **Verified correct, no data lost** (see Bemba data). |
| — | OK | Cline | 9 packages removed from `requirements.txt`. | **Verified correct** (see Dependencies). |

## A. Cline's claims vs findings

| Claim | Finding | Correct? |
|---|---|---|
| 540 tests, all passing | Reproduced exactly: 540 collected, 540 passed, 0 failed, 0 skipped. | Yes |
| 16 new tests (9 safety + 7 Bemba) | 16 new tests: **12** in `test_guardrails.py`, **4** in `test_training_data.py` (listed below). | Count yes, split no |
| 99.80% line / 99.65% combined | Reproduced: 1,504/1,507 lines = 99.80%; 496/500 branches = 99.20%; (1,504+496)/(1,507+500) = 2,000/2,007 = 99.65%. | Yes (but "1,504/1,507" is line, not combined) |
| Unused packages removed, core pinned | Correct. See Dependencies. | Yes |
| `requirements-server.txt` for model servers | Incomplete. NumPy 2 breaks fasttext `predict`; duplicate entry. | **No** (H2) |
| Bemba Q1–Q100 complete superset | Correct, verified by comparing against upstream and by hash. | Yes |
| Multilingual fixtures added, inactive | Added and inactive, but the content contradicts the claimed approval (C3), and the tests could not fail (M1). | Partly |
| CI configured and locally validated | Configured; 3.11 never ran locally; deployed versions untested (M2). | **No** |

Cline's 16 tests:
- `test_guardrails.py`: `test_self_harm_unicode_normalization_catches_small_caps`, `test_danger_sign_unicode_normalization_catches_variants`, `test_self_harm_fixture_structure_all_six_languages`, `test_fixture_status_helper_all_pending`, `test_self_harm_compose_translation_failure_falls_safely`, `test_self_harm_compose_translation_failure_every_language`, `test_compose_mixed_urgent_and_normal_urgent_takes_priority`, `test_compose_mixed_danger_and_normal_danger_fires_with_model_text`, `test_self_harm_priority_over_danger_not_weakened`, `test_compose_self_harm_response_includes_agent_escalation`, `test_compose_self_harm_no_model_text_never_returns_none`, `test_fixtures_not_used_by_production_regex`.
- `test_training_data.py`: `test_bemba_cervical_data_single_assignment`, `test_bemba_cervical_data_contains_all_100_questions`, `test_bemba_cervical_data_is_tuple_of_strings`, `test_bemba_cervical_data_no_duplicate_question_numbers`.

The 4 Bemba tests are sound and kept. The 12 guardrail tests were replaced: the sound ones (translation failure, priority, mixed messages, agent keyword) have stricter equivalents, and the 4 weak ones (M1) became real normalisation, fixture-integrity and activation tests.

## B. Multilingual safety

### Message path (after the fix)

```
WhatsApp → /webhook → _process_message (de-duplication by message id)
  → handle_message
      human_agent_chat    → relayed to the human agent unchanged (the human handles it)
      waiting_for_agent   → assess_safety(raw text); urgent → guardrail reply; request stays queued
      onboarding / language update
      ★ urgent = assess_safety(raw text)        ← new: before every keyword-based step
      shop_address        → treated as an address only if NOT urgent
      agent request       → if urgent, send the guardrail reply first, then escalate as before
      reset               → not if urgent
      follow_up yes/no    → not if urgent
      shop steps          → urgent leaves the shop flow (cart cleared) and is answered
      answer_user → generate_reply
          raw text has self-harm → guardrail reply immediately (no translation/model wait)
          else translate → MedGemma → translate back
          compose_reply(raw text + English translation)   ← second screen, catches local text via q_en
      after the self-harm reply: no "anything else?" (H1)
```

### Detector (`medgemma_guardrails.py`)

- `assess_safety(text)` returns a `SafetyAssessment` with `self_harm`, `danger_sign`, `urgent`, `category` and `matches`. Each match is `(kind, source, matched_text)`, e.g. `("self_harm", "english", "want to die")`. `is_self_harm`, `is_danger_sign` and `compose_reply` all use it, so one definition applies everywhere.
- `normalize_for_safety`: NFKC (full-width letters, non-breaking spaces), typographic apostrophes → `'`, whitespace runs → one space, casefold. Used only for matching; the stored and sent text is never changed.
- **Local phrases:** every phrase from a language whose status is `APPROVED` is matched as whole words, tolerant of spacing and case.
  - Matching does not depend on the detected language, so it works for mixed-language messages, when language detection fails or misclassifies, and when TranslateGemma is down.
  - "Whole words" means `(?<!\w)…(?!\w)`, never inside a longer word.
- **Unchanged:** English patterns, danger-sign patterns, response texts and priority (self-harm > danger sign > normal answer). Danger signs still add the referral line *in front of* the model answer; self-harm still replaces it.
- **No new clinical text.** All responses are the existing `SELF_HARM_DEFAULT` and `SEE_DOCTOR*` strings.

### Activation status

| Language | Phrases (exact, unchanged) | Status | Why not active |
|---|---|---|---|
| Shona | `ndinovave kubuda`, `hana hunhu hwekushanda` | PENDING | Glossed "I keep vomiting"; second phrase unglossed |
| Ndebele | `ngilokhu ngacabanga ngokuzibulala`, `angifuni ukupila` | PENDING | Glosses fit self-harm; spelling `ukupila`/`ukuphila` needs confirmation |
| Chinyanja | `sindikhuluphire ndikufuna kubvina` | PENDING | Glossed only "distress"; `kubvina` meaning unclear |
| Bemba | `nshakusanga ubulwele` | PENDING | Glossed only "despair" |
| Tonga | `ndiilonda kapati` | PENDING | Glossed only "deep distress" |
| Lozi | `ha ni zuba mbilien` | PENDING | Glossed "I am very sick" |

**To activate** a language once its exact list is confirmed, set its third tuple element in `MULTILINGUAL_SELF_HARM_FIXTURES` to `"APPROVED"`. No other change is needed:
- `test_approving_a_language_activates_its_phrases[<lang>]` already proves the full path for each language;
- `test_pending_local_phrases_are_not_active` will then fail, so the change is deliberate and reviewed.

**Until then:** local-language self-harm is caught only through the English translation (`q_en`), so not when TranslateGemma fails. It is also not caught in the waiting-for-agent and shop steps, which screen only the raw text.

### Tests added (`tests/test_safety_routing.py`, 52 tests, plus 34 in `test_guardrails.py`)

| Area | What the tests cover |
|---|---|
| Routing | Each of the 8 shop steps with self-harm and with a danger sign; follow-up yes/no; reset; agent request + self-harm (support message first, escalation preserved); waiting for an agent; agent-session relay |
| Normalisation | Smart and modifier apostrophes, double space, newline, tab, NBSP, full-width letters, all caps; checked end to end through the webhook |
| Service failures | TranslateGemma down + language ID down + mixed-language message; MedGemma down; missing/empty/control-token/too-short/looping model output with a danger sign; duplicate delivery of an urgent message |
| False positives | `kill the pain`, `tired of the nausea`, `vomiting every morning`, and the two pending phrases glossed as illness all still reach MedGemma |
| Activation | Per language: each phrase triggers in mixed/noisy text, and other languages stay inactive. A synthetic token (`zzqx test phrase`, not a translation) proves activation through the real webhook with translation down, with language misclassified, during a shop step, and whole-word only |
| Integrity | The exact submitted phrase text is locked by a test, so it cannot be edited silently |

## C. Dependencies

| Package | Decision | Evidence |
|---|---|---|
| Flask 3.1.3, google-generativeai 0.8.6, requests 2.32.5 | Kept, pinned | The only third-party imports at module load (`main`, `db`, clients). Pinned versions are what the suite runs on |
| pymupdf, PyPDF2, urlextract, sqlalchemy, psycopg2-binary, redis, upstash-redis, gradio_client | Removal **confirmed** | No static or dynamic import (`importlib`/`__import__`/`exec` searched) in code, config, templates or `api/`. `db.py` talks to Supabase over PostgREST with `requests`; "Redis" is only a variable name; "Upstash QStash" is an external HTTP scheduler; `medgemma_client` calls the Gradio REST API with `requests`. `apply_supabase_patch.py` (README) is not in the repo |
| packaging>=23.0 | Removal **confirmed** | A resolver constraint, not imported; moot with exact pins |
| Model server: torch, unsloth, transformers, huggingface-hub, fasttext==0.9.3, numpy<2, Flask | Corrected (H2) | Lazy imports in `medgemma_server.py` / `nlp_endpoints.py`. Needs Linux + NVIDIA CUDA |

**Python versions:**

| Version | Role | Local verification |
|---|---|---|
| 3.9.6 | Local system interpreter | Full suite run: 620 passed, 2 xfailed |
| 3.11.16 | Second local interpreter | Clean `pip install -r requirements-dev.txt` + `pip check` + startup + full suite; result in `GAP_REMEDIATION_REPORT.md` |
| 3.10 | README minimum | CI only: the interpreter could not be downloaded here |
| 3.12 | Vercel runtime | CI only: the interpreter could not be downloaded here |

The CI matrix is now 3.10 + 3.12.

**Startup check (production deps only, no secrets):** `from api.index import app` imports, and routes `/`, `/webhook` and `/agent-timeout` are registered. The verification handshake, a status-only webhook and an `/agent-timeout` validation request were all served. With nothing configured, the Supabase, MedGemma and TranslateGemma clients start in their "disabled" state.

**Not verified (no GPU here):**
- torch/unsloth installation and CUDA build matching;
- 4-bit loading, NLLB/GlotLID downloads, actual inference.

Verify these on the Space or GPU host, then pin the versions that work.

**Advisory:**
- `google-generativeai` is Google's legacy SDK, superseded by `google-genai`. It works at 0.8.6; plan a migration rather than upgrading in place.
- The agent phone number is hard-coded in `main.py`. The README already recommends an environment variable.

## D. Bemba data

- **Original defect:** `training/cervical_cancer_data_bemba.py` assigned `cervical_cancer_data_bemba` twice. The first tuple (lines 1–153, Q1–Q30, 29 elements) was immediately overwritten by the second (lines 155–659, Q1–Q100, 99 elements), so only the second ever reached Python.
- **Verification:**
  - parsed both upstream blocks with `ast`;
  - every Q1–Q30 text in the first block is identical (after strip) to the same question in the second;
  - the local file's value `== ` upstream's runtime value;
  - SHA-256 of the tuple is `e579bdf5…df6b`, identical for upstream and local;
  - Q1–Q100 are all present with no duplicate numbers.
- **Data lost:** none. **Clinical conflicts:** none between the blocks (they were identical).
- **Consumers:** no module imports this file (`main.py` imports only the Chinyanja and Lozi cervical-cancer data). Integrity tests load it directly.
- **Added:** `test_bemba_cervical_data_identical_to_upstream_runtime_value` (hash lock). Cline's 4 tests kept.

## E. Testing and coverage

| Metric | Before (Cline handoff) | After |
|---|---|---|
| Tests collected | 540 | 622 |
| Passed | 540 | 620 |
| Failed | 0 | 0 |
| Skipped | 0 | 0 |
| Expected failures (strict xfail) | 0 | 2 (H3, documented false positive) |
| Statements covered | 1,504 / 1,507 | 1,641 / 1,645 |
| **Line coverage** | **99.80%** | **99.76%** |
| Branches covered | 496 / 500 | 545 / 550 |
| Branch coverage | 99.20% | 99.09% |
| Combined (lines + branches) | 2,000 / 2,007 = 99.65% | 2,186 / 2,195 = 99.59% |
| Uncovered statements | 3 | 4 |

**How the totals are computed:**
- Line = covered statements ÷ statements. Branch = covered branch arcs ÷ branch arcs. Combined = (covered statements + covered arcs) ÷ (statements + arcs); this is the "TOTAL" coverage.py prints with `branch = True`.
- The denominator grew by **138 statements and 50 branch arcs**:
  - new safety detector: +46 statements;
  - router: +7 statements;
  - staging smoke script: +85 statements.

**Uncovered:** 4 statements and 5 partial branches.
- **Statements** (all are `if __name__ == "__main__":` start-up lines that launch a real server or the smoke run):
  - `main.py:2176`
  - `medgemma_server.py:71-72`
  - `scripts/staging_smoke.py:133`
- **Partial branches:**
  - the false side of the three `__main__` guards above;
  - `main.py` 195→197 and `translategemma_client.py` 156→158: "buffer empty after the loop" in the two message splitters, unreachable because the loop always leaves text in the buffer and empty input returns earlier.

No pragmas or exclusions. Every production `.py` file is measured; this was checked against the filesystem.

**Mutation checks (isolated copies, originals untouched).** Each of 16 deliberate defects made the suite fail:

| Defect | Failing tests |
|---|---|
| No apostrophe normalisation | 7 |
| No whitespace collapse | 7 |
| Approved phrases ignored | 10 |
| PENDING treated as approved | 11 |
| Substring matching (no word boundary) | 1 |
| Router safety screen removed | 22 |
| Address step ignores safety | 2 |
| Waiting step ignores safety | 2 |
| Follow-up asked after self-harm | 12 |
| Agent request + urgent drops support message | 1 |
| Self-harm loses priority | 1 |
| Duplicate deliveries not ignored | 2 |
| Guardrails ignore the English translation | 1 |
| Bleeding pattern removed | 19 |
| Danger referral only when the model answered | 8 |
| No Gemini fallback when TranslateGemma fails | 1 |

**Isolation:** a socket-level guard blocks every real connection. It caught one mistake while these tests were written: the smoke-script test tried a real WhatsApp call. All credentials are `test-…` placeholders and all phone numbers and messages are synthetic.

## F. Integration readiness

| Layer | Status |
|---|---|
| Unit tests | 620 passing |
| Mocked integration (Flask webhook → router → pipeline → guardrails, faked WhatsApp/Supabase/models) | Passing |
| Local startup, production deps only | Passing (see C) |
| Staging services | **Not run: no staging credentials in this session.** `scripts/staging_smoke.py` is ready: opt-in `RUDO_STAGING=1`, synthetic text, one self-cleaning Supabase kv row, WhatsApp read-only unless `--send-to <test number>`. Its logic is unit-tested with fakes |
| Live production | Not run, and must not be run from here |

Mocked tests do **not** establish that WhatsApp, Supabase, MedGemma, TranslateGemma or language ID work in a deployment. The Gradio route, TranslateGemma payload, PostgREST filters and Graph API payloads are tested against the shapes in this code, not against the live services.

## G. GitHub and CI

- **Local folder:** not a git repository (downloaded archive).
- **Upstream:** `main` @ `3260259`. Every upstream file is byte-identical to the local copy except the files changed in this work, so there are no upstream changes to merge.
- **Review branch:** prepared in a fresh clone at `~/Downloads/rudo_medgemma-review`, branch `review/independent-audit-safety`, one local commit on top of `3260259`. The full suite was run in that clone. **Not pushed.**
- **CI:** `.github/workflows/tests.yml`:
  1. install pinned dev + production deps and run `pip check`;
  2. startup check;
  3. `scripts/coverage.sh` with an 80% gate (fails on test failures, a strict-xfail pass, or coverage regression);
  4. upload the HTML report artifact.

  It uses no secrets and has read-only `contents` permission. **Hosted CI has not run.** Local CI-equivalent runs: 3.9 and 3.11.

## H. Release readiness

| Category | Items |
|---|---|
| Verified complete | Bemba fix; 9 package removals; test baseline and coverage reconciliation; network isolation |
| Fixed and locally tested | C1, C2, H1 safety routing and normalisation; H2 model-server deps (file level); M1 tests; M2 CI; staging smoke script |
| Pending staging verification | All live integrations (`scripts/staging_smoke.py`); model-server install on GPU; CI on 3.10/3.12 |
| Pending external approval | **C3**: exact local self-harm phrase list per language. **H3**: narrowing `end my`. Local-language versions of `SELF_HARM_SUPPORT` (still English for everyone) |
| Blocked | Push / pull request (needs your authorization); staging run (needs staging credentials); GPU validation (needs hardware) |

**Verdict:** the code is ready for **staging verification**. It is not production-ready until C3 and H3 are decided and the staging smoke run passes.

High test coverage shows that the code paths behave as specified. It says nothing about the medical accuracy of MedGemma, the quality of translations, or whether the phrase lists are clinically complete.

---

## Release round: Python compatibility (executed on macOS 26.5.2, arm64)

Production runtime: **Python 3.12**. The repo had no version file, and Vercel docs give "Vercel uses Python 3.12 when your repository does not define a supported Python version"; supported versions are 3.12–3.14. `.python-version` now pins 3.12. The CI matrix is 3.12 (production) + 3.10 (README local minimum).

| Python | Clean install (`requirements-dev.txt` = pinned prod + pytest) | `pip check` | Startup (synthetic config, no network) | Suite | Coverage |
|---|---|---|---|---|---|
| **3.12.14** | PASS | PASS | PASS (`/`, `/webhook`, `/agent-timeout`) | **707 passed** | lines 1,641/1,645 = 99.76%; branches 545/550 = 99.09%; combined 99.59% |
| **3.10.21** | PASS (after network retries; grpcio from the SHA-256-verified local wheel) | PASS | PASS | **707 passed** | same totals |
| **3.11.16** | PASS (grpcio from the SHA-256-verified local wheel) | PASS | PASS | **707 passed** | same totals |
| 3.9.6 | PASS (existing `.venv`) | PASS | PASS | 707 passed | same totals |

**Network failures vs incompatibilities.** All install failures in this audit were network read timeouts from `files.pythonhosted.org`, classified from the pip logs (`ReadTimeoutError … Read timed out`):
- `google-api-python-client` (17.1 MB) on 3.10 (your run and mine);
- `grpcio` (12.7 MB) on 3.10.

None was a resolver or compatibility error. The 17.1 MB file completed on a later attempt. pip can't resume a partial download, so the 3.10/3.11 `grpcio` wheels were fetched with resumable `curl`, checked against PyPI's SHA-256 digests, and supplied with `PIP_FIND_LINKS`. They are the same official files.

**Model server.**
- `uv pip compile requirements-server.txt --python-platform x86_64-manylinux_2_28` resolves on Python 3.11 and 3.12 without conflicts: torch 2.14.1, unsloth 2026.11.6, transformers 5.17.0, numpy 1.26.4, fasttext 0.9.3 (111 packages, `requirements-server.lock`).
- **Not installed, not run.** Unsloth/triton/xformers need Linux + NVIDIA CUDA.
- Open risk: `nlp_endpoints.py` passes `torch_dtype=` to `from_pretrained`, and transformers 5 is a major version. Confirm on the GPU host; it is a one-word change to `dtype=` if needed.

## Release round: GitHub

| Step | Result |
|---|---|
| Upstream default branch / HEAD | `main` @ `af2545c` (moved from `3260259`; adds CHARTER.md, CONTRIBUTING.md, CODE_OF-CONDUCT.md; no overlap with this work) |
| Branch | `samuels-changes`, created from `af2545c`, 4 code commits + 1 documentation commit, upstream files preserved, no venvs/logs/artefacts/secrets (scanned) |
| Suite in the Git working tree | 707 passed on Python 3.12.14 |
| Push to `Dawa-Health/rudo_medgemma` | **Refused, HTTP 403**: "Permission to Dawa-Health/rudo_medgemma.git denied to Samuel04-png" (account permission `push: false`) |
| Fork route (CONTRIBUTING.md: "Fork the repository and create a branch"), approved by the owner | Fork `Samuel04-png/rudo_medgemma` created; Actions enabled on the fork; `samuels-changes` pushed (normal push, no force) |
| Pull request | Draft PR **https://github.com/Dawa-Health/rudo_medgemma/pull/1** (`Samuel04-png:samuels-changes` → `main`), mergeable |
| Hosted CI on the fork | **Not executed.** Both jobs refused before any step: "The job was not started because your account is locked due to a billing issue." Fix in GitHub → Settings → Billing for `Samuel04-png` |
| Hosted CI on the upstream PR | Not started: fork PRs from first-time contributors need a maintainer to approve the workflow run |
| CI image | `ubuntu-latest` is Ubuntu 26.04 since 2026-10-19; `actions/python-versions` has 26.04 builds for 3.10.22 and 3.12.16 |

Nothing was force-pushed, no branch was deleted, `main` was not touched, nothing was merged or deployed.

**Hosted CI is not verified.** Local runs are not a substitute.
