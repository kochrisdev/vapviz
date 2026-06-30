#!/usr/bin/env bash
#
# Claude Code PreToolUse(Bash) hook. If the command being run is a `git commit`,
# run the fast gate and BLOCK the commit (exit 2) if it fails. Anything that
# isn't a real commit passes through instantly (exit 0).
#
# Wired in .claude/settings.json. Escape hatch: `git commit --no-verify`.
set -uo pipefail

payload="$(cat)"
cmd="$(printf '%s' "$payload" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' \
  2>/dev/null || true)"

# Only gate actual commits; let everything else (incl. --no-verify) pass.
case "$cmd" in
  *"git commit"*) printf '%s' "$cmd" | grep -q -- '--no-verify' && exit 0 ;;
  *) exit 0 ;;
esac

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
log="$(mktemp -t vapviz-commit-gate.XXXXXX)"
if ! ( cd "$root" && ./scripts/check.sh ) >"$log" 2>&1; then
  {
    echo "🚫 Commit blocked — the vapviz gate failed. Fix it, or override with: git commit --no-verify"
    echo "----- gate output (tail) -----"
    tail -25 "$log"
  } >&2
  rm -f "$log"
  exit 2
fi
rm -f "$log"
exit 0
