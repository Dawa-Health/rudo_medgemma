# Rudo MedGemma — Handoff

**State as of 2026-11-18.** Nothing merged or deployed.

## Where things are

| What | Location |
|---|---|
| Branch (pushed) | `samuels-changes` on fork https://github.com/Samuel04-png/rudo_medgemma/tree/samuels-changes |
| Pull request | https://github.com/Dawa-Health/rudo_medgemma/pull/1 → `Dawa-Health/rudo_medgemma:main` (open, ready for review, mergeable) |
| Base | upstream `main` @ `af2545c` |
| Git working copy | `~/Downloads/rudo_medgemma-review` (remotes: `origin` = Dawa-Health, `fork` = Samuel04-png) |
| Original download + local venvs | `~/Downloads/rudo_medgemma-main` (`.venv` 3.9, `.venv-py310`, `.venv-py312`; `~/rudo-venvs/py3.11`) |
| Pre-audit backup | `~/Downloads/rudo_medgemma-snapshot-20261118-095739/` |
| Verified grpcio wheels | `~/rudo-wheelhouse/` (SHA-256 checked against PyPI) |
| Full audit | `CLAUDE_INDEPENDENT_AUDIT.md` · also `GAP_REMEDIATION_REPORT.md`, `COVERAGE_REPORT.md` |

## Commits on `samuels-changes`

| SHA | Change |
|---|---|
| `3a44031` | Bemba cervical-cancer data: remove the overwritten duplicate assignment (loaded value unchanged, hash-checked) |
| `6ca790d` | Pin bot dependencies; split `requirements-server.txt` (numpy<2 for fasttext) + Linux lock; `.python-version` 3.12 |
| `34c1391` | Safety: screen urgent messages before routing; text normalisation; activate local self-harm phrases; narrow "end my"; no follow-up/product offer after the self-harm message |
| `b88262d` | 707 tests, coverage gate, CI workflow, `verify_local.sh`, `staging_smoke.py` |
| `ea4471b` | Audit, gap-remediation and coverage reports |
| (this file) | `HANDOFF.md` |

## Verified results

**Tests:** 707 collected, 707 passed, 0 failed, 0 skipped, 0 xfail.

**Coverage:**
- Lines: 1,641/1,645 = **99.76%**
- Branches: 545/550 = 99.09%
- Combined: 2,186/2,195 = 99.59%

| Python | Clean install | `pip check` | Startup | Suite |
|---|---|---|---|---|
| 3.12.14 (production; Vercel default) | pass | pass | pass | 707 passed |
| 3.11.16 | pass | pass | pass | 707 passed |
| 3.10.21 | pass | pass | pass | 707 passed |

- **Model server:** dependencies resolve for Linux x86_64 on Python 3.11 and 3.12 (`requirements-server.lock`). Not installed or run on a GPU.
- **Install failures:** every one seen during the audit was a network timeout (PyPI file host), never a package incompatibility.

## ⚠ Clinical review flag: Shona and Lozi self-harm phrases

All six languages' phrases are **active**, on the project team's confirmation of the existing wording. An earlier coding agent's **unverified** English glosses describe two of them as illness, not self-harm:

| Language | Phrase | Unverified agent gloss |
|---|---|---|
| Shona | `ndinovave kubuda` | "I keep vomiting" |
| Lozi | `ha ni zuba mbilien` | "I am very sick" |

If those glosses are correct, users writing these words get the self-harm support message **instead of a medical answer**, for example when asking about vomiting in pregnancy. The clinical reviewer and the language reviewer must confirm the meanings before merge. The glosses are kept in `LOCAL_SELF_HARM_REVIEW_NOTES` in `medgemma_guardrails.py`.

Also for the clinical reviewer: the narrowed "end my" pattern no longer treats "end my pain" as self-harm (deliberate, because of labour pain).

## Outstanding

1. **Hosted CI has not run.**
   - Fork runs were refused: "account is locked due to a billing issue". Fix in GitHub → Settings → Billing for `Samuel04-png`, then re-run.
   - No run has appeared on PR #1; a Dawa-Health maintainer probably needs to approve workflows from a first-time contributor.
2. **Approvals required by `CONTRIBUTING.md`:** one maintainer, one clinical reviewer, one language reviewer.
3. **Staging:** run `scripts/staging_smoke.py` with staging credentials, and do the README's test-number checks in each language. Not done; no credentials were available.
4. **GPU host:**
   - Install `requirements-server.lock` and load both models.
   - Confirm `nlp_endpoints.py`'s `torch_dtype=` works on transformers 5; change it to `dtype=` if not.
5. **Optional cleanup:**
   - The agent phone number is hard-coded in `main.py` (CONTRIBUTING asks for an env var).
   - `google-generativeai` is the legacy SDK.
   - CONTRIBUTING links `CODE_OF_CONDUCT.md`, but the file is named `CODE_OF-CONDUCT.md`.

## Next commands

```bash
# Re-run the hosted CI on the fork after fixing billing
gh run rerun --failed -R Samuel04-png/rudo_medgemma $(gh run list -R Samuel04-png/rudo_medgemma --branch samuels-changes --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch -R Samuel04-png/rudo_medgemma

# PR status / checks
gh pr view 1 -R Dawa-Health/rudo_medgemma
gh pr checks 1 -R Dawa-Health/rudo_medgemma

# Local verification (per Python version; venvs outside the repo; logs in verify-logs/)
cd ~/Downloads/rudo_medgemma-review
VERSIONS="3.12 3.11 3.10" bash scripts/verify_local.sh
MODEL_SERVER=1 VERSIONS="3.12" bash scripts/verify_local.sh

# Quick suite on one interpreter
PYTHON=~/Downloads/rudo_medgemma-main/.venv-py312/bin/python bash scripts/coverage.sh

# Staging (staging credentials only, exported in your shell)
RUDO_STAGING=1 python scripts/staging_smoke.py --webhook-url https://<staging-host>/webhook

# Further fixes: commit on the branch, then a normal push (never force)
git -C ~/Downloads/rudo_medgemma-review push fork samuels-changes
```
