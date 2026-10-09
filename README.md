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
