#!/usr/bin/env bash
# Stop hook: before Claude finishes, run the fast tests for whatever changed.
# Exit 2 makes Claude keep working on the failure. Skips when nothing relevant changed.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
input=$(cat)
active=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("stop_hook_active", False))' "$input" 2>/dev/null)
[[ "$active" == "True" ]] && exit 0
docker info >/dev/null 2>&1 || exit 0

changed=$(git status --porcelain -uall 2>/dev/null | awk '{print $NF}')
py=$(echo "$changed" | grep -E '^(api|tests|scripts)/.*\.py$|^pyproject\.toml$' || true)
web=$(echo "$changed" | grep -E '^web/' || true)
fail=0 log=""

if [[ -n "$py" ]]; then
  out=$(make -s test 2>&1) || { fail=1; log+=$'\n== make test failed ==\n'"$(echo "$out" | grep -v -E '^ ?Container ' | tail -n 40)"; }
fi
if [[ -n "$web" ]]; then
  out=$(docker compose run --rm --no-deps -T web sh -c "npm run -s typecheck && npm run -s test" 2>&1) \
    || { fail=1; log+=$'\n== web typecheck/vitest failed ==\n'"$(echo "$out" | grep -v -E '^ ?Container ' | tail -n 40)"; }
fi
if [[ $fail -ne 0 ]]; then
  echo "Checks failed on uncommitted changes. Fix them before finishing:$log" >&2
  exit 2
fi
exit 0
