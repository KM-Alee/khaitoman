# AabFlow command interface (T13.4). Everything runs in Docker; only Docker is needed on the host.
# Targets not built yet fail loudly; none fake success.
.NOTPARALLEL:
.PHONY: help setup build deps up down logs shell lock doctor provider-check test lint science-smoke \
        contracts web-test web-build ui-checks demo vision-weights vision-shell \
        water-tests pilot-a pilot-b candidates train-surrogate library-adequacy domain-tests core-acceptance copilot-evals release-check

DC   := docker compose
ifeq ($(GPU),1)
DC   := docker compose -f compose.yaml -f compose.gpu.yaml
endif
API  := $(DC) run --rm --no-deps api
WEB  := $(DC) run --rm --no-deps web
VIS  := $(DC) --profile vision run --rm --no-deps vision

help:             ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 18

setup:            ## first-time install: Docker check, all images, weights, checks
	./scripts/setup.sh

build:            ## rebuild dev images after dependency changes
	$(DC) build api web

deps: lock build  ## re-lock, rebuild, and refresh the web node_modules volume
	$(DC) up -d --renew-anon-volumes web

up:               ## API on :8000 (reload) + Vite UI on :5173
	$(DC) up -d api web
	@echo "API http://127.0.0.1:8000/api/v2/health   UI http://127.0.0.1:5173"

down:
	$(DC) --profile vision --profile demo --profile test down

logs:
	$(DC) logs -f api web

shell:            ## bash in the API container
	$(API) bash

lock:             ## regenerate uv.lock and web/package-lock.json after editing dependencies
	$(API) uv lock
	$(WEB) npm install --package-lock-only --ignore-scripts

doctor:           ## versions, assets, network, provider key status (all containers)
	$(API) python scripts/doctor.py
	$(WEB) sh -c 'echo "node $$(node -v), npm $$(npm -v)"; test -d node_modules/vite && echo "web deps: ok"'
	-$(VIS) python -c "import torch, ultralytics; from osgeo import gdal; print('vision: torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'ultralytics', ultralytics.__version__, 'gdal', gdal.__version__)"

provider-check:   ## doctor plus a real OpenAI model-availability call
	$(API) python scripts/doctor.py --provider-smoke

test:             ## fast Python unit tests
	$(API) pytest -q --ignore=tests/scientific

lint:             ## ruff check + format check (hooks auto-fix edited files)
	$(API) sh -c "ruff check api tests scripts && ruff format --check api tests scripts"

science-smoke:    ## T5.4 crop engine gates (real AquaCrop)
	$(API) pytest -q tests/scientific

contracts:        ## export OpenAPI and regenerate TypeScript types
	$(API) python -c "import json; from aabflow.main import app; open('contracts/openapi.json','w').write(json.dumps(app.openapi(), indent=2, sort_keys=True))"
	$(WEB) npm run gen:api

web-test:
	$(WEB) npm run test

web-build:
	$(WEB) npm run build

ui-checks:        ## Playwright + axe against the frozen demo image
	$(DC) --profile test build demo e2e
	$(DC) --profile test run --rm e2e
	$(DC) --profile test stop demo

demo:             ## frozen build on :8000; no installs or downloads at start
	$(DC) stop api
	$(DC) --profile demo up -d demo
	@echo "Demo http://127.0.0.1:8000"

vision-weights:   ## download Delineate Anything weights + SHA256SUMS
	$(VIS) python /app/scripts/fetch_weights.py

vision-shell:
	$(VIS) bash

water-tests:      ## chronology, network, roster, pond, pump invariants (unit + property)
	$(API) pytest -q tests/unit/test_water_*.py tests/property

pilot-a pilot-b:  ## onboarding pipeline -> reviewed, validated, published pilot package (exit 3: run printed vision command, rerun)
	$(API) python scripts/publish_pilot.py --pilot $@ --version reviewed-v1

candidates:       ## exact experiments + candidate libraries, e.g. make candidates PILOT=pilot-a
	$(API) python scripts/science_build_libraries.py $(or $(PILOT),pilot-a)

train-surrogate:  ## fixed-split surrogate training, evaluation artifacts and gate
	$(API) python scripts/science_train_surrogate.py

library-adequacy: ## denser exact libraries and objective/investment stability on both pilots/crops
	$(API) python scripts/science_library_adequacy.py

domain-tests:     ## AT02–AT04 crop/ledger gates, water properties, both pilots' published libraries (run candidates first)
	$(API) pytest -v tests/scientific/test_crop_gates.py tests/scientific/test_published_libraries.py tests/scientific/test_library_adequacy.py tests/unit/test_candidate_publication.py tests/unit/test_candidate_density.py tests/unit/test_water_*.py tests/property

core-acceptance: ## v1: run each existing AT test once; fail on failures; list AT ids with no test. Not G-CORE.
	$(API) python scripts/core_acceptance.py

copilot-evals release-check:
	@echo "make $@: not implemented yet" >&2; exit 1
