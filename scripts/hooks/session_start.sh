#!/usr/bin/env bash
# SessionStart hook: give Claude the current build state as context.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
echo "## AabFlow session context"
echo "Branch: $(git branch --show-current 2>/dev/null)"
echo "Recent commits:"; git log --oneline -5 2>/dev/null | sed 's/^/  /'
changes=$(git status --porcelain 2>/dev/null | wc -l)
echo "Uncommitted files: $changes"
echo
echo "Milestones (docs/STATUS.md):"
grep -E '^\| M[0-9] ' docs/STATUS.md 2>/dev/null | awk -F'|' '{gsub(/^ +| +$/,"",$2); gsub(/^ +| +$/,"",$4); print "  " $2 ": " $4}'
if command -v gh >/dev/null 2>&1; then
  prs=$(timeout 6 gh pr list --json number,title,author,reviewDecision,isDraft \
    --jq '.[] | "  #\(.number) \(.title) [\(.author.login); \(if .isDraft then "draft" else (.reviewDecision // "awaiting review") end)]"' 2>/dev/null)
  gaps=$(timeout 6 gh issue list --label gap --json number,title --jq '.[] | "  #\(.number) \(.title)"' 2>/dev/null)
  echo "Open PRs (docs/WORKFLOW.md):"; echo "${prs:-  none}"
  echo "Open gap issues:"; echo "${gaps:-  none}"
fi
if docker info >/dev/null 2>&1; then
  running=$(docker compose ps --services --status running 2>/dev/null | paste -sd' ' -)
  echo "Docker: up; running services: ${running:-none}"
else
  echo "Docker: daemon not reachable; make targets will fail until it is running"
fi
exit 0
