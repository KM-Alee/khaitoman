#!/usr/bin/env bash
# PreToolUse hook (Bash): enforce the PR workflow in docs/WORKFLOW.md.
# Blocks commits on main, pushes to main, and force-pushes. Exit 2 = blocked, reason on stderr.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
exec python3 - "$(cat)" <<'PY'
import json, re, shlex, subprocess, sys

cmd = json.loads(sys.argv[1] or "{}").get("tool_input", {}).get("command", "")
if "git" not in cmd:
    sys.exit(0)

def branch(cwd):
    r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True)
    return r.stdout.strip()

def block(msg):
    print(f"Blocked by git_guard (docs/WORKFLOW.md): {msg}", file=sys.stderr)
    sys.exit(2)

for seg in re.split(r"&&|\|\||[;|\n]", cmd):
    try:
        toks = shlex.split(seg)
    except ValueError:
        toks = seg.split()
    i = next((k for k, t in enumerate(toks) if t == "git" or t.endswith("/git")), None)
    if i is None:
        continue
    cwd, j = ".", i + 1
    while j < len(toks) and toks[j].startswith("-"):
        if toks[j] == "-C" and j + 1 < len(toks):
            cwd = toks[j + 1]
        j += 2 if toks[j] in ("-C", "-c") else 1
    if j >= len(toks):
        continue
    sub, args = toks[j], toks[j + 1 :]
    if sub == "commit" and branch(cwd) == "main":
        block("no commits on main; branch first (`git switch -c feat/<id>-<slug>`), then /ship.")
    if sub != "push":
        continue
    for a in args:
        if a in ("-f", "--force", "--mirror") or (a.startswith("--force") and not a.startswith(("--force-with-lease", "--force-if-includes"))):
            block(f"`{a}` is not allowed; merge instead of rewriting pushed history.")
    pos = [a for a in args if not a.startswith("-")]
    refs = pos[1:]
    for r in refs:
        if r.startswith("+"):
            block(f"force refspec `{r}` is not allowed.")
        dst = r.split(":")[-1].removeprefix("refs/heads/")
        if dst == "main" or (dst == "HEAD" and branch(cwd) == "main"):
            block("pushing to main is not allowed; open a PR (/ship).")
    if not refs and branch(cwd) == "main":
        block("pushing to main is not allowed; open a PR (/ship).")
sys.exit(0)
PY
