#!/usr/bin/env bash
# Local multi-version verification for the Rudo bot (macOS / Linux).
#
#   bash scripts/verify_local.sh                 # checks 3.12 (production), 3.10, 3.11
#   VERSIONS="3.12" bash scripts/verify_local.sh # just one version
#   MODEL_SERVER=1 bash scripts/verify_local.sh  # also resolve GPU-server deps (metadata only)
#   FRESH=1 ...                                  # delete and recreate the venvs first
#
# Per version: find interpreter -> venv in $VENV_ROOT (outside the repo, so coverage never
# measures it) -> pip install -r requirements-dev.txt (pinned prod + pytest; no AI models)
# -> pip check -> startup check (no credentials, no network) -> full suite with coverage gate.
# It never installs Python itself, never downloads model weights, never uses real credentials.
# Everything is written to verify-logs/verify-<timestamp>.log (gitignored).
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
VERSIONS="${VERSIONS:-3.12 3.10 3.11}"
VENV_ROOT="${VENV_ROOT:-$HOME/rudo-venvs}"
mkdir -p verify-logs "$VENV_ROOT"
LOG="$REPO/verify-logs/verify-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

# No real credentials or service URLs, whatever the calling shell has exported.
unset SUPABASE_URL SUPABASE_SERVICE_KEY MEDGEMMA_URL MEDGEMMA_TOKEN HF_TOKEN TRANSLATEGEMMA_URL \
      TRANSLATEGEMMA_TOKEN LANGID_URL WA_TOKEN PHONE_ID GEN_API OWNER_PHONE VERIFY_TOKEN || true

classify() {   # $1 = log file -> prints the most likely failure category
  local f="$1"
  if grep -qE "ReadTimeoutError|Read timed out|ConnectTimeout|ConnectionError|Max retries exceeded|IncompleteRead|ProtocolError|Temporary failure in name resolution|nodename nor servname|SSLError" "$f"; then
    echo "NETWORK (transient: re-run; already-downloaded files are reused from the cache)"
  elif grep -qE "requires a different Python|Requires-Python|No matching distribution found|Could not find a version that satisfies|ResolutionImpossible|conflicting dependencies" "$f"; then
    echo "INCOMPATIBLE PACKAGE / PYTHON VERSION (real problem: report it)"
  elif grep -qE "CUDA|nvcc|libcuda|triton|xformers|bitsandbytes|Unsloth.*(only|support)|platform.*not supported" "$f"; then
    echo "UNSUPPORTED HARDWARE / PLATFORM (expected on a Mac for GPU packages)"
  elif grep -qE "Failed building wheel|subprocess-exited-with-error|error: command .* failed|xcrun: error" "$f"; then
    echo "BUILD FAILURE (missing compiler/headers or no wheel for this platform)"
  elif grep -qE "is not set|KeyError: '(WA_TOKEN|GEN_API|SUPABASE|MEDGEMMA)|Missing user_number" "$f"; then
    echo "MISSING CONFIGURATION"
  else
    echo "UNKNOWN (see log)"
  fi
}

find_python() {  # $1 = 3.12 etc.
  local v="$1" c
  for c in "$(command -v "python$v" 2>/dev/null)" "$HOME/.local/bin/python$v" \
           "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v" \
           "/Library/Frameworks/Python.framework/Versions/$v/bin/python$v"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  [ "$v" = "3.9" ] && [ -x /usr/bin/python3 ] && /usr/bin/python3 -c 'import sys; exit(sys.version_info[:2] != (3, 9))' && { echo /usr/bin/python3; return 0; }
  return 1
}

echo "=== Rudo local verification $(date) ==="
echo "repo: $REPO | macOS $(sw_vers -productVersion 2>/dev/null || uname -r) | $(uname -m)"
echo "production runtime (.python-version): $(cat .python-version 2>/dev/null || echo 'not set')"
echo "CI matrix: $(grep -E 'python-version: \[' .github/workflows/tests.yml | sed 's/^ *//')"
echo "pip cache: $(du -sh "$(python3 -m pip cache dir 2>/dev/null || echo ~/Library/Caches/pip)" 2>/dev/null | cut -f1)"
echo

declare -a SUMMARY
for v in $VERSIONS; do
  echo "──────── Python $v ────────"
  PY="$(find_python "$v")" || { echo "Python $v: NOT INSTALLED (see the install step in the instructions)"; SUMMARY+=("$v  NOT INSTALLED"); continue; }
  echo "interpreter: $PY ($("$PY" --version 2>&1))"
  VENV="$VENV_ROOT/py$v"
  [ "${FRESH:-0}" = 1 ] && rm -rf "$VENV"
  [ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV" || { SUMMARY+=("$v  VENV FAILED"); continue; }
  ILOG="$REPO/verify-logs/install-py$v.log"
  echo "installing requirements-dev.txt (log: $ILOG) ..."
  if ! "$VENV/bin/python" -m pip install --disable-pip-version-check --timeout 120 --retries 10 \
        -r requirements-dev.txt >"$ILOG" 2>&1; then
    cat_=$(classify "$ILOG"); echo "INSTALL FAILED: $cat_"; tail -5 "$ILOG"
    SUMMARY+=("$v  INSTALL FAILED - $cat_"); continue
  fi
  "$VENV/bin/python" -m pip list --disable-pip-version-check 2>/dev/null \
    | grep -iE "^(flask|werkzeug|google-generativeai|requests|pytest|pytest-cov) " | tr -s ' ' | paste -sd ';' -
  if ! "$VENV/bin/python" -m pip check --disable-pip-version-check; then
    SUMMARY+=("$v  PIP CHECK FAILED (dependency conflict)"); continue
  fi
  SLOG="$REPO/verify-logs/startup-py$v.log"
  if ! VERIFY_TOKEN=startup-check "$VENV/bin/python" -W ignore - >"$SLOG" 2>&1 <<'EOF'
from api.index import app
import db, medgemma_client, translategemma_client
rules = {r.rule for r in app.url_map.iter_rules()}
assert {"/", "/webhook", "/agent-timeout"} <= rules, rules
assert not db.enabled() and not medgemma_client.medgemma_enabled() and not translategemma_client.translategemma_enabled()
c = app.test_client()
assert c.get("/").status_code == 200
assert c.get("/webhook?hub.mode=subscribe&hub.verify_token=startup-check&hub.challenge=7").data == b"7"
assert c.get("/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=7").status_code == 403
assert c.post("/webhook", json={"entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}).status_code == 200
assert c.post("/agent-timeout", json={}).status_code == 400
print("startup OK:", sorted(r for r in rules if not r.startswith("/static")))
EOF
  then
    echo "STARTUP FAILED: $(classify "$SLOG")"; tail -8 "$SLOG"; SUMMARY+=("$v  STARTUP FAILED"); continue
  fi
  cat "$SLOG"
  TLOG="$REPO/verify-logs/tests-py$v.log"
  PYTHON="$VENV/bin/python" bash scripts/coverage.sh -q -p no:cacheprovider -rxs >"$TLOG" 2>&1
  rc=$?
  grep -E "^TOTAL|Required test coverage|passed|failed|error" "$TLOG" | tail -4
  "$VENV/bin/python" -m coverage report --format=total >/dev/null 2>&1 && \
  "$VENV/bin/python" - <<'EOF'
import json, subprocess, sys
t = json.loads(subprocess.run([sys.executable, "-m", "coverage", "json", "-o", "-", "-q"],
                              capture_output=True, text=True).stdout)["totals"]
print(f"lines {t['covered_lines']}/{t['num_statements']} = {100*t['covered_lines']/t['num_statements']:.2f}% | "
      f"branches {t['covered_branches']}/{t['num_branches']} = {100*t['covered_branches']/t['num_branches']:.2f}% | "
      f"combined {t['percent_covered']:.2f}%")
EOF
  if [ $rc = 0 ]; then SUMMARY+=("$v  PASS"); else SUMMARY+=("$v  TESTS/COVERAGE FAILED (exit $rc, see $TLOG)"); fi
done

if [ "${MODEL_SERVER:-0}" = 1 ]; then
  echo "──────── Model server (resolution for Linux x86_64 + CUDA; nothing installed) ────────"
  if command -v uv >/dev/null; then
    for v in 3.11 3.12; do
      MLOG="$REPO/verify-logs/model-server-py$v.log"
      if uv pip compile requirements-server.txt --python-platform x86_64-manylinux_2_28 \
           --python-version "$v" --no-header -q -o "$MLOG.txt" >"$MLOG" 2>&1; then
        echo "py$v: resolves. $(grep -ciE '^[a-z0-9_.-]+==' "$MLOG.txt") packages; key pins: $(grep -iE '^(torch|transformers|numpy|fasttext|unsloth)==' "$MLOG.txt" | paste -sd ' ' -)"
        [ "$v" = 3.12 ] && { diff <(grep -E '==' requirements-server.lock) <(grep -E '==' "$MLOG.txt") >/dev/null \
          && echo "py3.12: identical to requirements-server.lock" \
          || echo "py3.12: differs from requirements-server.lock (newer releases on PyPI; see $MLOG.txt)"; }
        SUMMARY+=("model-server py$v  RESOLVES (not installed: needs Linux + NVIDIA GPU)")
      else
        echo "py$v: $(classify "$MLOG")"; tail -6 "$MLOG"; SUMMARY+=("model-server py$v  FAILED - $(classify "$MLOG")")
      fi
    done
  else
    echo "uv not found: skipping (brew install uv)"; SUMMARY+=("model-server  SKIPPED (no uv)")
  fi
fi

rm -rf htmlcov coverage.xml .coverage
echo; echo "=== SUMMARY ==="; printf "%s\n" ${SUMMARY[@]+"${SUMMARY[@]}"}; echo "full log: $LOG"
