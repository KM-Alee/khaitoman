# AabFlow command interface (T13.4). Targets not built yet fail loudly; none fake success.
.PHONY: setup doctor provider-check test science-smoke contracts web-build web-test ui-checks dev-api dev-web demo \
        water-tests pilot-a pilot-b candidates train-surrogate domain-tests core-acceptance copilot-evals release-check

UV := uv run

setup:            ## install everything (uv + npm + vision env + weights)
	./scripts/setup.sh

doctor:           ## versions, assets, GPU, network, provider key status
	$(UV) python scripts/doctor.py

provider-check:   ## doctor plus a real OpenAI model-availability call
	$(UV) python scripts/doctor.py --provider-smoke

test:             ## fast Python unit tests
	$(UV) pytest -q -m "not scientific"

science-smoke:    ## T5.4 crop engine gates
	$(UV) pytest -q -m scientific

contracts:        ## export OpenAPI and regenerate TypeScript types
	$(UV) python -c "import json; from aabflow.main import app; open('contracts/openapi.json','w').write(json.dumps(app.openapi(), indent=2, sort_keys=True))"
	cd web && npm run gen:api

web-build:
	cd web && npm ci && npm run build

web-test:
	cd web && npm run test

ui-checks:
	cd web && npm run e2e

dev-api:          ## FastAPI with reload on :8000
	$(UV) uvicorn aabflow.main:app --app-dir api --reload --host 127.0.0.1 --port 8000

dev-web:          ## Vite on :5173 proxying /api/v2 to :8000
	cd web && npm run dev

demo:             ## serve the frozen build on one local origin; no installs or downloads
	@test -f web/dist/index.html || (echo "web/dist missing: run make web-build first" && exit 1)
	$(UV) uvicorn aabflow.main:app --app-dir api --host 127.0.0.1 --port 8000

water-tests pilot-a pilot-b candidates train-surrogate domain-tests core-acceptance copilot-evals release-check:
	@echo "make $@: not implemented yet" >&2; exit 1
