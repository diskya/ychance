#!/usr/bin/env bash
# codex-worker <prompt-file>: runs codex exec under `ychance-worker` profile.
# stdout: codex last message, "---", git status --short, "---", git diff --stat.
set -euo pipefail
prompt_file="${1:?usage: codex-worker.sh <prompt-file>}"
out_file="$(mktemp /tmp/codex-out.XXXXXX)"
err_file="$(mktemp /tmp/codex-err.XXXXXX)"
trap 'rm -f "$out_file" "$err_file"' EXIT
cd /home/ubuntu/ychance
if ! codex exec -p ychance-worker \
    -c 'sandbox_workspace_write.network_access=true' \
    -C /home/ubuntu/ychance \
    -o "$out_file" "$(cat "$prompt_file")" </dev/null >/dev/null 2>"$err_file"; then
  echo "CODEX FAILED. stderr:" >&2; cat "$err_file" >&2; exit 1
fi
cat "$out_file"
printf '\n---\n'; git status --short
printf '\n---\n'; git diff --stat
