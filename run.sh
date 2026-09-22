#!/usr/bin/env bash
# Only process setup lives here. The workflow lives in SKILL.md.
set -euo pipefail
umask 077
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MODE=${1:-preview}
case "$MODE" in preview|personal|group) ;; *) echo 'Usage: run.sh [preview|personal|group]' >&2; exit 2 ;; esac
[[ $# -le 1 ]] || { echo 'Unexpected arguments' >&2; exit 2; }
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
: "${HOME:?Set HOME to the production account home directory}"
for tool in codex bwrap flock timeout jq node gws-as; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
mkdir -p "$ROOT/state" "$ROOT/runs"
exec 9>"$ROOT/state/run.lock"
flock -n 9 || { echo 'Another Future Appetite run holds the lock' >&2; exit 1; }
if [[ "$MODE" == group && ! -f "$ROOT/state/group-enabled" ]]; then
  echo 'Group delivery is disabled pending Jay’s approval of the personal edition' >&2
  exit 1
fi
# Trusted private shell configuration, never model-generated input.
set -a
source "$ROOT/.env"
set +a
: "${OPENAI_API_KEY:?Missing OPENAI_API_KEY}"
: "${GOOGLE_USERNAME:?Missing GOOGLE_USERNAME}"
: "${PERSONAL_RECIPIENT:?Missing PERSONAL_RECIPIENT}"
if [[ "$MODE" == group ]]; then : "${RECIPIENT_EMAILS:?Missing RECIPIENT_EMAILS}"; fi
export BRIEFING_ROOT="$ROOT" BRIEFING_MODE="$MODE"
export RUN_DIR="$ROOT/runs/$(TZ=America/New_York date +%Y%m%d-%H%M%S)-$MODE-$$"
mkdir -p "$RUN_DIR"
if [[ "$MODE" == group ]]; then
  ATTEMPT="$ROOT/state/group-$(TZ=America/New_York date +%F).attempt"
  (set -o noclobber; printf '%s\n' "$RUN_DIR" > "$ATTEMPT") || {
    echo 'Group delivery already attempted today; investigate before retrying' >&2; exit 1;
  }
fi
export CODEX_HOME="$RUN_DIR/codex-home"
mkdir -p "$CODEX_HOME"
jq -n --arg mode "$MODE" --arg at "$(date -Iseconds)" --arg commit "$(git -C "$ROOT" rev-parse HEAD)" \
  '{mode:$mode,started_at:$at,commit:$commit,status:"running"}' > "$RUN_DIR/launch.json"
printf '%s\n' "$RUN_DIR"
set +e
CODEX_API_KEY="$OPENAI_API_KEY" timeout --signal=TERM --kill-after=30s 2400 \
  codex exec --ignore-user-config --skip-git-repo-check --ephemeral \
  --model gpt-6-astra --sandbox workspace-write \
  --add-dir "$ROOT/state" --add-dir "$HOME/.config/gws/profiles/$GOOGLE_USERNAME" \
  -C "$RUN_DIR" -c 'approval_policy="never"' -c 'model_reasoning_effort="high"' \
  -c 'sandbox_workspace_write.network_access=true' -c 'web_search="live"' \
  -c 'shell_environment_policy.inherit="all"' -c 'shell_environment_policy.ignore_default_excludes=true' \
  --enable skip_host_skill_discovery --disable apps --disable plugins --disable hooks \
  --disable memories --disable multi_agent --json --output-last-message "$RUN_DIR/result.md" \
  "Read $ROOT/skills/future-appetite/SKILL.md and execute it completely in $MODE mode. This is the authorized Future Appetite newsletter job. Use the environment for paths and credentials; never print secrets. Save this run's artifacts in $RUN_DIR. The launcher already holds the run lock. Do not change the skill, launcher, credentials, recipient configuration, or schedule. Finish by recording status.json as described in the skill." \
  > "$RUN_DIR/events.jsonl" 2> "$RUN_DIR/stderr.log"
RESULT=$?
set -e
jq --arg at "$(date -Iseconds)" --argjson code "$RESULT" \
  '. + {finished_at:$at,exit_code:$code,status:"exited"}' "$RUN_DIR/launch.json" > "$RUN_DIR/launch.tmp"
mv "$RUN_DIR/launch.tmp" "$RUN_DIR/launch.json"
[[ $RESULT -eq 0 ]] || { echo "Codex failed ($RESULT); inspect $RUN_DIR" >&2; exit "$RESULT"; }
if [[ "$MODE" == preview ]]; then
  jq -e '.status == "preview_ready" and .mode == "preview"' "$RUN_DIR/status.json" >/dev/null
else
  jq -e --arg mode "$MODE" '.status == "sent" and .mode == $mode and (.gmail_message_id | type == "string" and length > 0)' \
    "$RUN_DIR/status.json" >/dev/null
fi
echo "Completed $MODE run: $RUN_DIR"
