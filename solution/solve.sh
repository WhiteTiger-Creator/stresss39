#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Inspect before changing anything (read-only) ---
# Read the deployment state the runbook requires.
cat /app/docs/deployment_runbook.md || true

# Read the output contract: schemas, key sets, identifier payloads, checksum encodings.
python3 -c "import json;print(json.dumps(json.load(open('/app/docs/rebuild_contract.json')),indent=2))"

# Locate the governing CAB entries. The log is long and mostly routine, so index the
# ticketed decisions first, then read the ones that govern each stage.
grep -n "IDX-" /app/rebuild/index_review_log.md | head -60 || true
python3 -c "import json;print(json.dumps(json.load(open('/app/docs/rebuild_contract.json'))['governing_entry_index'],indent=2))"

# Confirm which entries are superseded rather than governing.
grep -n "Superseded\|Revised" /app/rebuild/index_review_log.md | head -20 || true

# Inspect the current host state and the broken compiler before touching either.
ls -la /usr/local/bin/index-rebuild /var/lock /app/output 2>&1 || true
getent passwd svc-indexer || echo "svc-indexer not provisioned"
ls -la /etc/cron.d/ 2>&1 || true
sed -n '1,60p' /app/workflow/index_rebuild.py || true

# Read the operational inputs the compile reconciles.
ls -la /app/data || true
python3 -c "import json;d=json.load(open('/app/data/segments.json'));print(len(d),'segment rows')"

# --- Restore the deployment state defined in /app/docs/deployment_runbook.md ---

# Dedicated system account with no interactive shell.
if ! getent passwd svc-indexer >/dev/null; then
  useradd --system --shell /usr/sbin/nologin svc-indexer
fi

# Operator wrapper: executable, targets the live compiler, honors the lock.
cat > /usr/local/bin/index-rebuild <<'EOF'
#!/bin/sh
LOCK=/var/lock/index-rebuild.lock
if [ -e "$LOCK" ]; then
  exit 75
fi
exec python3 /app/workflow/index_rebuild.py "$@"
EOF
chmod 0755 /usr/local/bin/index-rebuild

# Clear the stale lock left by the crashed rollout.
rm -f /var/lock/index-rebuild.lock

# Reinstate the schedule.
printf '*/5 * * * * svc-indexer /usr/local/bin/index-rebuild --input /app/data/segments.json --output-dir /app/output\n' \
  > /etc/cron.d/index-rebuild
chmod 0644 /etc/cron.d/index-rebuild

# Output directory ownership and mode per runbook.
mkdir -p /app/output
chown svc-indexer:svc-indexer /app/output
chmod 0750 /app/output

# Log directory per runbook: prune the rollout leftover, then hand the directory to
# the system account and drop the world-writable mode.
mkdir -p /var/log/index-rebuild
rm -f /var/log/index-rebuild/compile.log.0
chown -R svc-indexer:svc-indexer /var/log/index-rebuild
chmod 0750 /var/log/index-rebuild

# Rotation drop-in. The su/create lines keep rotated files owned by svc-indexer.
cat > /etc/logrotate.d/index-rebuild <<'ROTEOF'
/var/log/index-rebuild/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    su svc-indexer svc-indexer
    create 0640 svc-indexer svc-indexer
}
ROTEOF
chmod 0644 /etc/logrotate.d/index-rebuild

# --- Restore the compiler itself and produce the rebuild outputs ---

cp "${SCRIPT_DIR}/index_rebuild_fixed.py" /app/workflow/index_rebuild.py
chmod +x /app/workflow/index_rebuild.py

/usr/local/bin/index-rebuild --input /app/data/segments.json --output-dir /app/output
