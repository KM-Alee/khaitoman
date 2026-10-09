# AabFlow

Irrigation and canal water-allocation planner (AICON hackathon build).

- Product spec: [prd-flow-v2.md](prd-flow-v2.md)
- Implementation contract: [aab-flow-tech-doc-v2.md](aab-flow-tech-doc-v2.md)
- Doc change log: [review/CHANGES.md](review/CHANGES.md)

## Getting started

You only need Docker (Engine + Compose v2) and make.

```bash
./scripts/setup.sh    # builds every image, downloads model weights, runs checks
make up               # API http://127.0.0.1:8000  UI http://127.0.0.1:5173
```

Put `OPENAI_API_KEY` in `.env` for the copilot. `make help` lists every command.

## Day to day

| Task | Command |
|---|---|
| Start / stop the dev stack | `make up` / `make down` |
| Python unit tests | `make test` |
| Crop engine smoke test | `make science-smoke` |
| Web tests / production build | `make web-test` / `make web-build` |
| Shell in the API container | `make shell` |
| Added a dependency | edit `pyproject.toml` or `web/package.json`, then `make deps` and commit both lockfiles |
| Pulled someone else's dependency change | `make build` |
| Frozen demo / browser checks | `make demo` / `make ui-checks` |

Containers run as your user (`HOST_UID`/`HOST_GID` in `.env`), so generated files stay yours. `data/` is mounted from the repo, and large data is git-ignored.

## Building with Claude Code

The repo ships a shared Claude Code setup in `.claude/`, so both contributors get the same workflow. Open Claude Code in this folder.

| Command | What it does |
|---|---|
| `/status` | Where the build stands and the next step |
| `/milestone M1` | Builds a whole milestone from the specs, with tests, status update and a local commit |
| `/feature F05` | Same for one feature |
| `/acceptance` | Runs every check and refreshes AT01–AT18 in `docs/STATUS.md` |
| `/fix <error>` | Reproduces a failure and fixes the root cause |
| `/spec <question>` | Answers from the PRD and tech doc with section references |

Edits are auto-accepted and routine `make`, `docker compose` and `git` commands run without prompts; pushes, hard resets and reading `.env` are blocked. Python edits are auto-linted, and tests run before Claude finishes a task. Splitting work: one person per milestone stream (data, science, optimizer/API, UI), each committing on their own branch.
