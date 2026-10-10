#!/usr/bin/env bash
# Local worker runtime. No host project dependencies, secret reads or git mutations.
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "agent-runtime: $*" >&2; exit 1; }
runtime=.agent-work
verify_seed_image() {
  local image=$1 local_lock=$2 image_lock=$3 source_hash local_hash
  source_hash=$(docker run --rm --network none --entrypoint sha256sum "$image" "$image_lock") || fail "cannot verify seed image $image"
  local_hash=$(sha256sum "$local_lock")
  [[ "${source_hash%% *}" == "${local_hash%% *}" ]] || fail "seed image $image does not match this worktree's lockfile; rebuild it through the project workflow"
}
record_image() {
  local service=$1 suffix
  case "$service" in
    api) suffix=dev; sha256sum uv.lock > "$runtime/api.locks" ;;
    web) suffix=web; sha256sum web/package-lock.json > "$runtime/web.locks" ;;
    demo) suffix=demo; sha256sum uv.lock web/package-lock.json > "$runtime/demo.locks"; rm -f "$runtime/demo-needs-build" ;;
    e2e) suffix=e2e; sha256sum web/package-lock.json > "$runtime/e2e.locks" ;;
    vision) suffix=vision ;;
    *) fail "unknown service $service" ;;
  esac
  docker image inspect "$project-$suffix:local" --format '{{.Id}}' > "$runtime/$service.image"
}
check_image() {
  local service=$1 suffix actual
  case "$service" in api) suffix=dev ;; web) suffix=web ;; demo) suffix=demo ;; e2e) suffix=e2e ;; vision) suffix=vision ;; *) fail "unknown service $service" ;; esac
  [[ -f "$runtime/$service.image" ]] || fail "missing $service image record; build it explicitly"
  if [[ "$service" == demo && -e "$runtime/demo-needs-build" ]]; then
    fail 'build demo from this worktree before running its frozen code'
  fi
  actual=$(docker image inspect "$project-$suffix:local" --format '{{.Id}}')
  [[ "$actual" == "$(cat "$runtime/$service.image")" ]] || fail "$service image tag changed outside this worker"
  if [[ "$service" != vision ]]; then
    sha256sum --check --status "$runtime/$service.locks" || fail "$service lockfiles changed; lead must build that worker image before running"
  fi
}
case "${1:-help}" in
  init)
    name=${2:-}; slot=${3:-}
    [[ "$name" =~ ^[a-z][a-z0-9-]{0,35}$ ]] || fail 'name must be a short lowercase slug'
    [[ "$slot" =~ ^[1-3]$ ]] || fail 'slot must be 1, 2 or 3; lead allocates it globally'
    [[ -f .git ]] || fail 'init requires a dedicated linked Git worktree'
    branch=$(git branch --show-current) || fail 'cannot identify worker Git branch'
    [[ -n "$branch" && "$branch" != main ]] || fail 'init requires a worker branch, not main or detached HEAD'
    # Filename checks only: never open secret files. load_dotenv in the app also
    # searches ancestors, so the parent must choose a clean worktree location.
    probe=$(pwd -P)
    while :; do
      [[ ! -e "$probe/.env" ]] || fail 'worktree or ancestor has .env; choose a clean location'
      [[ "$probe" != / ]] || break
      probe=$(dirname "$probe")
    done
    shopt -s nullglob
    secret_names=(.env.*)
    for secret_name in "${secret_names[@]}"; do
      [[ "$secret_name" == .env.example ]] || fail 'worker must not have secret environment files'
    done
    [[ ! -e "$runtime" ]] || fail 'runtime already exists; inspect it rather than overwriting'
    # !override/!reset need a recent Compose. Docker validates the generated file below.
    declare -A seed_images
    for image in aabflow-dev:local aabflow-web-dev:local aabflow:local aabflow-e2e:local; do
      seed_images[$image]=$(docker image inspect "$image" --format '{{.Id}}') || fail "missing $image; use the existing project setup workflow"
    done
    verify_seed_image "${seed_images[aabflow-dev:local]}" uv.lock /app/uv.lock
    verify_seed_image "${seed_images[aabflow-dev:local]}" pyproject.toml /app/pyproject.toml
    verify_seed_image "${seed_images[aabflow-web-dev:local]}" web/package-lock.json /app/web/package-lock.json
    verify_seed_image "${seed_images[aabflow-web-dev:local]}" web/package.json /app/web/package.json
    verify_seed_image "${seed_images[aabflow-e2e:local]}" web/package-lock.json /app/web/package-lock.json
    verify_seed_image "${seed_images[aabflow-e2e:local]}" web/package.json /app/web/package.json
    mkdir "$runtime"
    project="aabflow-worker-$name"
    printf '%s\n' "$project" > "$runtime/project"
    cat > "$runtime/compose.yaml" <<EOF
services:
  api:
    image: $project-dev:local
    env_file: !reset []
    ports: !override ["127.0.0.1:$((18000 + slot)):8000"]
    environment:
      AABFLOW_DATA_DIR: /app/data
      AABFLOW_DB_PATH: /app/data/agent.sqlite
      AABFLOW_WORKERS: "1"
      AABFLOW_SOLVER_WORKERS: "2"
      AABFLOW_SCIENCE_WORKERS: "2"
      OMP_NUM_THREADS: "2"
      OPENBLAS_NUM_THREADS: "2"
      OPENAI_API_KEY: \${OPENAI_API_KEY:-}
      AABFLOW_OPENAI_MODEL: \${AABFLOW_OPENAI_MODEL:-gpt-6.1-sol}
  web:
    image: $project-web:local
    ports: !override ["127.0.0.1:$((15170 + slot)):5173"]
  demo:
    image: $project-demo:local
    env_file: !reset []
    ports: !override ["127.0.0.1:$((18000 + slot)):8000"]
    environment:
      AABFLOW_DATA_DIR: /app/data
      AABFLOW_DB_PATH: /app/data/agent.sqlite
      AABFLOW_WORKERS: "1"
      AABFLOW_SOLVER_WORKERS: "2"
      AABFLOW_SCIENCE_WORKERS: "2"
      OMP_NUM_THREADS: "2"
      OPENBLAS_NUM_THREADS: "2"
      OPENAI_API_KEY: \${OPENAI_API_KEY:-}
      AABFLOW_OPENAI_MODEL: \${AABFLOW_OPENAI_MODEL:-gpt-6.1-sol}
  e2e:
    image: $project-e2e:local
  vision:
    image: $project-vision:local
EOF
    docker compose --env-file /dev/null -p "$project" -f compose.yaml -f "$runtime/compose.yaml" config --quiet
    for pair in 'dev aabflow-dev:local' 'web aabflow-web-dev:local' 'demo aabflow:local' 'e2e aabflow-e2e:local'; do
      read -r suffix source <<< "$pair"
      image_id=${seed_images[$source]}
      docker image tag "$image_id" "$project-$suffix:local"
    done
    for service in api web demo e2e; do record_image "$service"; done
    # Frozen source/web bundle must be rebuilt from this worker, not merely retagged.
    touch "$runtime/demo-needs-build"
    if docker image inspect aabflow-vision:local --format '{{.Id}}' >/dev/null 2>&1; then
      image_id=$(docker image inspect aabflow-vision:local --format '{{.Id}}')
      docker image tag "$image_id" "$project-vision:local"
      record_image vision
    fi
    echo "Worker runtime prepared: $project, API/demo :$((18000 + slot)), web :$((15170 + slot))"
    ;;
  seed)
    [[ -f "$runtime/project" ]] || fail 'run init in this worker worktree first'
    seed=${2:-}; group=${3:-}
    [[ -d "$seed" ]] || fail 'seed must be an existing checkout'
    case "$group" in
      raw) path=data/raw ;;
      experiments) path=data/experiments ;;
      libraries) path=data/libraries ;;
      models) path=data/models ;;
      vision) path=vision/Delineate-Anything ;;
      *) fail 'choose one required asset group: raw, experiments, libraries, models, vision' ;;
    esac
    seed=$(cd "$seed" && pwd -P)
    git -C "$seed" rev-parse --show-toplevel >/dev/null || fail 'seed must be a Git checkout'
    [[ "$seed" != "$(pwd -P)" ]] || fail 'seed must be a different checkout'
    # Only ignored assets, never tracked metadata or runtime DB/runs/reports/secrets.
    # A reflink gives private copy-on-write storage; fallback is an ordinary private copy.
    listing=$(mktemp "$runtime/seed-list.XXXXXX")
    if ! git -C "$seed" ls-files --others --ignored --exclude-standard -z -- "$path" > "$listing"; then
      rm -f "$listing"
      fail 'asset listing failed; no seeding performed'
    fi
    count=0
    while IFS= read -r -d '' asset; do
      case "/$asset/" in */.env/*|*/.env.*/*) continue ;; esac
      case "${asset##*/}" in *.sqlite*|*.db|*.db-wal|*.db-shm|*.db-journal) continue ;; esac
      [[ -f "$seed/$asset" && ! -L "$seed/$asset" ]] || continue
      [[ ! -e "$asset" ]] || continue
      mkdir -p "$(dirname "$asset")"
      cp --reflink=auto --no-clobber -- "$seed/$asset" "$asset"
      count=$((count + 1))
    done < "$listing"
    rm -f "$listing"
    echo "Privately copied $count ignored $group assets; verify against this worktree's manifests before use"
    ;;
  compose)
    shift
    [[ -f "$runtime/project" ]] || fail 'run init in this worker worktree first'
    read -r project < "$runtime/project"
    [[ "$project" =~ ^aabflow-worker-[a-z][a-z0-9-]{0,35}$ ]] || fail 'invalid project record'
    files=(-f compose.yaml)
    if [[ "${1:-}" == --gpu ]]; then files+=(-f compose.gpu.yaml); shift; fi
    files+=(-f "$runtime/compose.yaml")
    # Only leading Compose options are parsed; a program argument named "build"
    # must never bless changed locks. Explicit service builds refresh only those images.
    args=("$@")
    index=0
    while [[ "${args[$index]:-}" == --profile ]]; do index=$((index + 2)); done
    command=${args[$index]:-}
    services=()
    if [[ "$command" == build ]]; then
      for arg in "${args[@]:$((index + 1))}"; do
        case "$arg" in api|web|demo|e2e|vision) services+=("$arg") ;; --no-cache|--pull) ;; *) fail 'build requires explicit service names (optional --no-cache/--pull)' ;; esac
      done
      [[ ${#services[@]} -gt 0 ]] || fail 'build requires explicit service names'
    elif [[ "$command" == run ]]; then
      start_dependencies=true
      index=$((index + 1))
      while [[ "${args[$index]:-}" == -* ]]; do
        case "${args[$index]}" in
          --no-deps) start_dependencies=false; index=$((index + 1)) ;;
          --rm|-T|-d|--detach|--interactive|-i) index=$((index + 1)) ;;
          *) fail 'unsupported run option; use documented Make commands' ;;
        esac
      done
      service=${args[$index]:-}
      check_image "$service"
      if "$start_dependencies"; then
        case "$service" in web) check_image api ;; e2e) check_image demo ;; esac
      fi
    elif [[ "$command" == up ]]; then
      start_dependencies=true
      for arg in "${args[@]:$((index + 1))}"; do
        [[ "$arg" != --no-deps ]] || start_dependencies=false
      done
      explicit_services=0
      for arg in "${args[@]:$((index + 1))}"; do
        case "$arg" in
          api|web|demo|e2e|vision)
            check_image "$arg"
            if "$start_dependencies"; then
              case "$arg" in web) check_image api ;; e2e) check_image demo ;; esac
            fi
            explicit_services=$((explicit_services + 1))
            ;;
          --build) fail 'build images explicitly before up' ;;
          -* ) ;;
          *) fail 'up requires explicit service names' ;;
        esac
      done
      [[ "$explicit_services" -gt 0 ]] || fail 'up requires explicit service names'
    fi
    HOST_UID=${HOST_UID:-$(id -u)} HOST_GID=${HOST_GID:-$(id -g)} \
      docker compose --env-file /dev/null -p "$project" "${files[@]}" "$@"
    if [[ "$command" == build ]]; then
      for service in "${services[@]}"; do record_image "$service"; done
    fi
    ;;
  *)
    cat <<'EOF'
scripts/agent_runtime.sh init <unique-slug> <slot 1..3>
scripts/agent_runtime.sh seed <source-checkout> <raw|experiments|libraries|models|vision>
scripts/agent_runtime.sh compose [--gpu] <docker compose arguments>
make test DC='./scripts/agent_runtime.sh compose'
make train-surrogate GPU=1 DC='./scripts/agent_runtime.sh compose --gpu'
Prepare only in a dedicated worker worktree. Lead owns slots/resources and shared files.
Compose does not load .env. Init requires a clean linked worktree and clean ancestors.
Provider credentials may be inherited from the host environment; do not display them.
EOF
    ;;
esac
