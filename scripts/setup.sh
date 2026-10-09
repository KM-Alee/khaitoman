#!/usr/bin/env bash
# AabFlow: one command to get a contributor from clone to a working Docker stack.
#
#   ./scripts/setup.sh                 # everything (dev images, vision image + weights, demo/test images, checks)
#   ./scripts/setup.sh --skip-vision   # skip the Delineate Anything image and weights
#   ./scripts/setup.sh --gpu           # CUDA torch in the vision image (needs nvidia-container-toolkit)
#   ./scripts/setup.sh --skip-checks   # don't run doctor/tests at the end
#
# Only Docker is installed on the host. Python (uv), Node and all libraries live
# in images. Safe to re-run. The log is saved under evidence/environment/ (M0 evidence).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_VISION=0 SKIP_CHECKS=0 GPU=0
for arg in "$@"; do
  case "$arg" in
    --skip-vision) SKIP_VISION=1 ;;
    --skip-checks) SKIP_CHECKS=1 ;;
    --gpu) GPU=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$ROOT/evidence/environment/setup-$STAMP.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m    ok:\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m    warning:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m    error:\033[0m %s\n' "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Network on the build machine can be flaky; retry image builds a few times.
retry() {
  local n=1 max=3
  until "$@"; do
    [[ $n -ge $max ]] && return 1
    warn "attempt $n failed; retrying in $((n * 10))s"
    sleep $((n * 10)); n=$((n + 1))
  done
}

COMPOSE=(docker compose)
[[ $GPU -eq 1 ]] && COMPOSE+=(-f compose.yaml -f compose.gpu.yaml)

echo "AabFlow setup $STAMP on $(uname -srm)"

# ---------------------------------------------------------------------------
step "1/6 Docker engine, Compose v2, Buildx"
if ! have docker || ! docker compose version >/dev/null 2>&1 || ! docker buildx version >/dev/null 2>&1; then
  echo "    installing Docker (needs sudo)"
  if have pacman; then sudo pacman -S --needed --noconfirm docker docker-compose docker-buildx
  elif have apt-get; then curl -fsSL https://get.docker.com | sudo sh
  elif have dnf; then sudo dnf install -y docker-ce docker-ce-cli docker-compose-plugin docker-buildx-plugin
  else die "install Docker Engine with the compose and buildx plugins, then re-run"
  fi
fi
if ! docker info >/dev/null 2>&1; then
  if have systemctl; then sudo systemctl enable --now docker; fi
  docker info >/dev/null 2>&1 || {
    if ! id -nG | grep -qw docker; then
      sudo usermod -aG docker "$USER"
      die "added $USER to the docker group: log out and back in (or run 'newgrp docker'), then re-run"
    fi
    die "Docker daemon is not reachable"
  }
fi
ok "$(docker --version)"
ok "$(docker compose version)"

# ---------------------------------------------------------------------------
step "2/6 Local config (.env)"
[[ -f .env ]] || { cp .env.example .env; ok "created .env from .env.example"; }
grep -q '^HOST_UID=' .env || echo "HOST_UID=$(id -u)" >> .env
grep -q '^HOST_GID=' .env || echo "HOST_GID=$(id -g)" >> .env
ok "containers run as $(id -u):$(id -g) so files they write stay yours"
grep -q '^OPENAI_API_KEY=.\+' .env && ok "OPENAI_API_KEY set" || warn "OPENAI_API_KEY empty in .env (needed for the copilot, M7)"

# ---------------------------------------------------------------------------
step "3/6 Dev images: api (Python 3.11 + uv.lock) and web (Node 24 + package-lock)"
export DOCKER_BUILDKIT=1
retry "${COMPOSE[@]}" build api web
ok "aabflow-dev:local and aabflow-web-dev:local built"

# ---------------------------------------------------------------------------
step "4/6 Demo and browser-test images"
retry "${COMPOSE[@]}" --profile test build demo e2e
ok "aabflow:local (frozen demo) and aabflow-e2e:local (Playwright) built"

# ---------------------------------------------------------------------------
if [[ $SKIP_VISION -eq 0 ]]; then
  step "5/6 Vision image (Delineate Anything, torch, GDAL) and model weights"
  retry "${COMPOSE[@]}" --profile vision build vision
  mkdir -p data/models/delineate-anything
  retry "${COMPOSE[@]}" --profile vision run --rm --no-deps vision python /app/scripts/fetch_weights.py
  ok "weights in data/models/delineate-anything (hashes in SHA256SUMS)"
else
  step "5/6 Vision image skipped (--skip-vision)"
fi

# ---------------------------------------------------------------------------
step "6/6 Checks"
if [[ $SKIP_CHECKS -eq 0 ]]; then
  make doctor || warn "doctor reported missing items (see above)"
  make test || die "unit tests failed"
  make science-smoke || die "AquaCrop smoke test failed"
  make web-test || die "web tests failed"
  make web-build || die "web build failed"
  ok "unit tests, crop smoke, vitest and production web build passed"
else
  echo "    skipped (--skip-checks)"
fi

printf '\n\033[1;32mSetup finished.\033[0m Log: %s\n' "${LOG#"$ROOT"/}"
echo "Start developing with 'make up' (API http://127.0.0.1:8000, UI http://127.0.0.1:5173)."
