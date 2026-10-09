#!/usr/bin/env bash
# PostToolUse hook: lint/format edited Python with ruff inside the api image.
# Exit 2 sends remaining lint errors back to Claude to fix. Never blocks on infra problems.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)
[[ "$file" == *.py ]] || exit 0
rel=$(realpath --relative-to="$PWD" "$file" 2>/dev/null) || exit 0
[[ "$rel" == ../* || ! -f "$rel" ]] && exit 0
docker info >/dev/null 2>&1 || exit 0
out=$(docker compose run --rm --no-deps -T api sh -c "ruff format --quiet '$rel' && ruff check --fix --quiet '$rel'" 2>&1)
status=$?
out=$(echo "$out" | grep -v -E '^ ?Container ')
if [[ $status -ne 0 && -n "$out" ]]; then
  echo "ruff found problems in $rel (file was auto-formatted; fix the rest):" >&2
  echo "$out" | tail -n 40 >&2
  exit 2
fi
exit 0
