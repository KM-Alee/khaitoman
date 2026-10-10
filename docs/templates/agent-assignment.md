# Worker assignment (fill every field before dispatch)

- Node / parent PNN / builder identity:
- Cursor agent name and ID:
- Required and observed model: Grok 4.7 / high / 500k / Fast off
- Absolute worktree path / branch / exact base SHA:
- PR base ref and prerequisite commit ancestry checks:
- Input pilot/version/library/model hashes and private seed source:
- Exact writable files and excluded shared files:
- Resource leases / host-global worker slot / ports / Compose wrapper:
- Spec sections read and complete numbered requirements, including rejections:
- Existing code and contracts to extend; assumptions where specs are silent:
- Ordered implementation tasks with finite exit criteria:
- Every requirement's planned regression/integration/browser check:
- Commands (Docker/Make DC wrapper), log destinations and actual runtime data:
- Handoff destination: `<worktree>/.agent-work/handoffs/<node>.json`

Read AGENTS.md, CLAUDE.md, docs/AGENT_WORKFLOW.md and `brief <node>` before editing. Work only in this checkout and assignment. Request shared-file changes through the parent. Do not spawn agents, commit/push/merge/stash, change specs, read secrets, invent evidence or defer fixable findings. Return every requirement mapped to executed tests/artifacts and actual failures; the parent owns integration and PR shipping.
