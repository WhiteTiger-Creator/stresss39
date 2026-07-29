#!/usr/bin/env bash
set -uo pipefail

mkdir -p /logs/verifier

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    echo 0 > /logs/verifier/reward.txt
    exit 0
fi

CANDIDATE_USER="${CANDIDATE_USER:-tree-candidate}"

# --- Real OS-level isolation of the verifier tree from the candidate ---
# The candidate-controlled learner must run as an unprivileged user that CANNOT
# read /tests, so it cannot copy the reference fixtures (even via os.open/os.read)
# and hardcode the expected model/predictions. pytest itself stays root.
if [ "$(id -u)" = "0" ] && id "$CANDIDATE_USER" >/dev/null 2>&1; then
    chown -R root:root /tests 2>/dev/null || true
    chmod 700 /tests 2>/dev/null || true
    find /tests -mindepth 1 -exec chmod go-rwx {} + 2>/dev/null || true

    mkdir -p /app/output
    chmod 0777 /app/output 2>/dev/null || true
    chown -R "$CANDIDATE_USER":"$CANDIDATE_USER" /app/output 2>/dev/null || true

    # Establish the authoritative /app/output from an UNPRIVILEGED learner run.
    runuser -u "$CANDIDATE_USER" -- \
        python3 /app/fit_forest.py --data-dir /app/data --output-dir /app/output \
        >/logs/verifier/candidate_fit.log 2>&1 || true
fi

set +e

python3 -m pytest -o cache_dir=/tmp/pytest_cache \
  --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
RC=$?

if [ "$RC" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
