#!/usr/bin/env bash
# Reproducible coverage run: terminal report, HTML report (htmlcov/), XML (coverage.xml),
# and a hard failure if total coverage drops below the fail_under value in .coveragerc (80%).
#
# Usage:
#   source <venv>/bin/activate && bash scripts/coverage.sh   # uses the ACTIVE virtualenv
#   PYTHON=/path/to/python bash scripts/coverage.sh           # or an explicit interpreter
# Interpreter choice: $PYTHON, else $VIRTUAL_ENV/bin/python. There is deliberately no silent
# fallback to .venv or the system python3: running the suite on the wrong version is how a
# "3.12" check previously ran on 3.9.6.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"; SOURCE="PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PY="$VIRTUAL_ENV/bin/python"; SOURCE="active virtualenv $VIRTUAL_ENV"
else
  echo "coverage.sh: no interpreter selected. Activate a virtualenv or set PYTHON=/path/to/python." >&2
  exit 2
fi
if ! command -v "$PY" >/dev/null 2>&1 && [[ ! -x "$PY" ]]; then
  echo "coverage.sh: interpreter not found: $PY" >&2
  exit 2
fi
echo "coverage.sh: using $("$PY" -c 'import sys; print(sys.executable, "-", sys.version.split()[0])') (from $SOURCE)"

# Never let a developer's real credentials leak into a test run.
unset SUPABASE_URL SUPABASE_SERVICE_KEY MEDGEMMA_URL MEDGEMMA_TOKEN HF_TOKEN \
      TRANSLATEGEMMA_URL TRANSLATEGEMMA_TOKEN LANGID_URL WA_TOKEN GEN_API || true

"$PY" -m pytest \
  --cov --cov-config=.coveragerc \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=xml \
  "$@"
