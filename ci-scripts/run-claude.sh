#!/bin/bash
# Wrapper script for running Claude in CI.
# When run as root, re-execs itself as the claude-ci user.
set -euo pipefail

# Re-exec as claude-ci when running as root
if [ "$(id -u)" -eq 0 ]; then
  exec runuser -u claude-ci -- bash "$0" "$@"
fi

export PATH="$HOME/.local/bin:$PATH"

echo "--- Preflight checks ---"
fail=0
for var in JIRA_USER GCP_PROJECT_ID GCP_SERVICE_ACCOUNT_KEY; do
  if [ -z "$(eval echo \$$var)" ]; then
    echo "ERROR: $var is not set"
    fail=1
  else
    echo "OK: $var is set"
  fi
done
[ "$fail" -eq 1 ] && exit 1

claude --version

# Clone project repo if specified (skills are defined in the repo itself)
workdir="."
if [ -n "${CLAUDE_REPO:-}" ]; then
  branch_args=()
  if [ -n "${CLAUDE_REPO_BRANCH:-}" ]; then
    branch_args=(--branch "$CLAUDE_REPO_BRANCH")
  fi
  workdir="/tmp/claude-workdir"
  if [ -d "$workdir" ]; then
    echo "--- Reusing existing workdir: $workdir ---"
  else
    echo "--- Cloning project repo: $CLAUDE_REPO ${CLAUDE_REPO_BRANCH:+(branch: $CLAUDE_REPO_BRANCH)} ---"
    git clone --depth 1 "${branch_args[@]}" "$CLAUDE_REPO" "$workdir"
  fi
  echo "--- Skill repo commit: $(git -C "$workdir" log --oneline -1) ---"
fi

# Fetch any plugins
plugin_args=()
plugin_base="/tmp/claude-plugins"
for url in ${CLAUDE_PLUGINS:-}; do
  # Derive directory name from repo URL (e.g. https://github.com/user/repo -> repo)
  name=$(basename "$url" .git)
  dir="$plugin_base/$name"
  if [ -d "$dir" ]; then
    echo "--- Reusing existing plugin: $name ---"
  else
    echo "--- Fetching plugin: $name ---"
    git clone --depth 1 "$url" "$dir"
  fi
  plugin_args+=(--plugin-dir "$dir")
done

ci_scripts="$(cd "$(dirname "$0")" && pwd)"
cd "$workdir"

# Install Python dependencies if requirements.txt exists
if [ -f requirements.txt ]; then
  echo "--- Installing Python dependencies ---"
  pip3 install -r requirements.txt --index-url "${PIP_INDEX_URL:-https://pypi.org/simple/}"
fi

# Start OTEL collector to capture token/cost metrics
export OTEL_LOG_FILE="/tmp/claude-otel.jsonl"
rm -f "$OTEL_LOG_FILE"
python3 "$ci_scripts/otel-collector.py" &
otel_pid=$!
echo "--- OTEL collector started (pid $otel_pid) ---"

# Configure Claude to export OTEL data to our local collector
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/json
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_METRIC_EXPORT_INTERVAL=10000

set +e
claude_fifo="/tmp/claude-stream.fifo"
rm -f "$claude_fifo"
mkfifo "$claude_fifo"

claude -p "${1:?Usage: $0 <prompt>}" \
  --model "${CLAUDE_MODEL:-claude-opus-4-6}" \
  "${plugin_args[@]}" \
  --dangerously-skip-permissions \
  --output-format stream-json \
  --include-partial-messages \
  --verbose 2>/tmp/claude-stderr.log > "$claude_fifo" &
claude_pid=$!

python3 -u "$ci_scripts/stream-claude.py" --claude-pid "$claude_pid" < "$claude_fifo"
stream_rc=$?

# stream-claude.py exits when the FIFO closes (Claude exited naturally)
# or with exit code 42 (FULL RUN COMPLETE — it killed Claude intentionally).
# Safety net: kill Claude if still running (e.g., stream-claude.py crashed).
if kill -0 "$claude_pid" 2>/dev/null; then
  echo "--- Claude still running after stream exit, killing (pid=$claude_pid) ---"
  kill "$claude_pid" 2>/dev/null
fi
wait "$claude_pid" 2>/dev/null
rc=$?

# SIGTERM (rc=143) or SIGPIPE (rc=141): only treat as success when
# stream-claude.py signaled FULL RUN COMPLETE (exit code 42).
if [ "$rc" -eq 143 ] || [ "$rc" -eq 141 ]; then
  if [ "$stream_rc" -eq 42 ]; then
    echo "--- FULL RUN COMPLETE: Claude terminated as expected ---"
    rc=0
  else
    echo "WARNING: Claude killed unexpectedly (rc=$rc, stream_rc=$stream_rc)"
  fi
elif [ "$rc" -ne 0 ]; then
  echo "WARNING: Claude exited with rc=$rc"
fi

rm -f "$claude_fifo"

# Wait for Claude's final OTEL flush (CLAUDE_CODE_OTEL_FLUSH_TIMEOUT_MS, default 5s)
sleep 7

# Stop OTEL collector and print summary
kill $otel_pid 2>/dev/null
wait $otel_pid 2>/dev/null

echo "--- Claude exit code: $rc ---"
echo "--- stderr log ---"
cat /tmp/claude-stderr.log >&2

echo ""
echo "--- OTEL Token/Cost Summary ---"
python3 "$ci_scripts/otel-summary.py" "$OTEL_LOG_FILE"

# Copy artifacts into CI project directory for GitLab artifact upload
if [ -n "${CI_PROJECT_DIR:-}" ]; then
  cp -f /tmp/claude-otel.jsonl "$CI_PROJECT_DIR/claude-otel.jsonl" 2>/dev/null || true
  cp -f /tmp/claude-stderr.log "$CI_PROJECT_DIR/claude-stderr.log" 2>/dev/null || true
fi

exit $rc
