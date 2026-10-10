# Resume the AabFlow DAG

Read AGENTS.md, CLAUDE.md and docs/AGENT_WORKFLOW.md. Recover the parent's private checkpoint; reconcile actual GitHub PR states/SHAs, each worktree status/HEAD, running containers/processes, leases, Cursor IDs, assets and executed evidence. Preserve unfinished changes. Inspect stale active work before reclaiming anything; resume its agent if possible, otherwise issue a complete fresh assignment to the named custom agent in its existing worktree.

Invalidate affected descendants atomically after upstream changes. Validate checkpoint and manifest in Docker and run plan --state. Check actual Grok 4.7/high/500k/Fast off, base ancestry, file ownership, worker slots and resources before each dispatch. Then follow /aabflow-build to completion, including all self-review fixes, real checks, PR shipping and independent reviewer gates. Do not recreate completed work or advance partial core/AT gates.
