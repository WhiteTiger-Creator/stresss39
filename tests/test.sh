#!/usr/bin/env bash
set -uo pipefail

EXPECTED_TESTS=52
mkdir -p /logs/verifier
# Default to no reward; only an exact, clean pass overwrites this.
echo 0 > /logs/verifier/reward.txt

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 0
fi

TEST_DIR="${TEST_DIR:-/tests}"

set +e
# Run pytest from a clean temp cwd in isolated / safe-path mode with a verifier-owned config cut,
# so a module planted in the agent-writable /app (a `pytest.py`, a `pytest/` package, a stray
# `conftest.py`, or any verifier-helper name) cannot shadow pytest, the stdlib or the test helpers,
# and no stray PYTHONPATH or cwd entry is honoured during grading:
#   * cd into a fresh empty temp dir  -> /app is never the cwd, so cwd-on-sys.path shadows nothing;
#   * unset PYTHONPATH + `-I` (isolated) + PYTHONSAFEPATH=1 -> env vars and the unsafe cwd/script
#     path are not prepended to sys.path, so imports resolve only from the protected stdlib/site;
#   * absolute interpreter /usr/local/bin/python3 -> not resolved through an agent-shadowable $PATH;
#   * --confcutdir + --import-mode=importlib -> pytest will not walk up into /app for conftest and
#     does not insert collected rootdirs onto sys.path.
RUNDIR="$(mktemp -d)"
cd "$RUNDIR"
unset PYTHONPATH
PYTHONSAFEPATH=1 /usr/local/bin/python3 -I -B -m pytest \
  --confcutdir="${TEST_DIR}" \
  --import-mode=importlib \
  -p no:cacheprovider \
  -o cache_dir=/tmp/pytest_cache \
  --ctrf /logs/verifier/ctrf.json \
  "${TEST_DIR}/test_outputs.py" -rA
RC=$?

# Gate on the EXACT expected passing count from the CTRF report, not just pytest's exit code, so a
# shadow framework that exits 0 without collecting the real suite still scores reward 0.
PASS_OK=$(/usr/local/bin/python3 -I -B -c "
import json
try:
    s=json.load(open('/logs/verifier/ctrf.json'))['results']['summary']
    ok = s.get('passed')==$EXPECTED_TESTS and s.get('failed',1)==0 and s.get('tests')==$EXPECTED_TESTS
    print('1' if ok else '0')
except Exception:
    print('0')
" 2>/dev/null)

# Collapse "pytest exited 0" AND "exact expected pass count" into one status.
[ "$RC" -eq 0 ] && [ "$PASS_OK" = "1" ]
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
