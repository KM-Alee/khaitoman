#!/usr/bin/env bash
# AabFlow: install everything the build needs, using uv for all Python.
#
#   ./scripts/setup.sh                 # everything
#   ./scripts/setup.sh --skip-vision   # skip Delineate Anything env + weights
#   ./scripts/setup.sh --cpu           # force CPU torch even if a GPU answers
#   ./scripts/setup.sh --skip-checks   # don't run doctor/tests at the end
#
# Safe to re-run: every step is idempotent. A full log is saved under
# evidence/environment/ as M0 evidence (T1.3, T12.5).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_VISION=0 SKIP_CHECKS=0 FORCE_CPU=0
for arg in "$@"; do
  case "$arg" in
    --skip-vision) SKIP_VISION=1 ;;
    --skip-checks) SKIP_CHECKS=1 ;;
    --cpu) FORCE_CPU=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

PYTHON_VERSION=3.11
NODE_MAJOR=24
# Delineate Anything pinned to the commit checked on 2026-10-10 (T2.4: confirm against the pinned commit).
DELINEATE_REPO=https://github.com/Lavreniuk/Delineate-Anything.git
DELINEATE_COMMIT=4cfab87ecccbe8d1bda4167676f623e3728570d9
DELINEATE_WEIGHTS=(DelineateAnything.pt DelineateAnythingv2.pt DelineateAnything-S.pt)

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$ROOT/evidence/environment/setup-$STAMP.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m    ok:\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m    warning:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m    error:\033[0m %s\n' "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

pkg_install() {
  # Installs system packages with whatever manager this machine has.
  if have pacman; then sudo pacman -S --needed --noconfirm "$@"
  elif have apt-get; then sudo apt-get update -qq && sudo apt-get install -y "$@"
  elif have dnf; then sudo dnf install -y "$@"
  elif have brew; then brew install "$@"
  else die "no supported package manager found; install manually: $*"
  fi
}

echo "AabFlow setup $STAMP on $(uname -srm)"

# ---------------------------------------------------------------------------
step "1/8 System packages (git, make, curl, GDAL for the vision env)"
NEED=()
have git  || NEED+=(git)
have make || NEED+=(make)
have curl || NEED+=(curl)
if [[ $SKIP_VISION -eq 0 ]] && ! have gdal-config; then
  if have pacman || have brew; then NEED+=(gdal)
  elif have apt-get; then NEED+=(gdal-bin libgdal-dev)
  elif have dnf; then NEED+=(gdal gdal-devel)
  fi
fi
if [[ ${#NEED[@]} -gt 0 ]]; then
  echo "    installing: ${NEED[*]} (needs sudo)"
  pkg_install "${NEED[@]}"
fi
ok "git $(git --version | awk '{print $3}'), make, curl present"
[[ $SKIP_VISION -eq 0 ]] && ok "GDAL $(gdal-config --version)"

# ---------------------------------------------------------------------------
step "2/8 uv and Python $PYTHON_VERSION"
if ! have uv; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "$(uv --version)"
uv python install "$PYTHON_VERSION"
ok "Python $PYTHON_VERSION managed by uv"

# ---------------------------------------------------------------------------
step "3/8 Main Python env (.venv): science, GIS, optimizer, API, surrogate, copilot"
uv lock
uv sync --python "$PYTHON_VERSION"
uv run python - <<'PY'
import aquacrop, ortools, pandas, numpy, geopandas, rasterio, pystac_client, lightgbm, sklearn, fastapi, pydantic, openai
from importlib.metadata import version as v
for d in ["aquacrop","ortools","numpy","pandas","geopandas","shapely","pyproj","pyarrow","rasterio",
          "pystac-client","lightgbm","scikit-learn","fastapi","pydantic","uvicorn","openai","pytest","hypothesis"]:
    print(f"    {d:15s} {v(d)}")
PY
ok "main env imports passed; uv.lock written"

# ---------------------------------------------------------------------------
step "4/8 Node $NODE_MAJOR"
node_major() { node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/'; }
if [[ "$(node_major)" != "$NODE_MAJOR" ]]; then
  if have fnm; then
    fnm install "$NODE_MAJOR" && eval "$(fnm env)" && fnm use "$NODE_MAJOR"
  elif [[ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]]; then
    # shellcheck disable=SC1091
    . "${NVM_DIR:-$HOME/.nvm}/nvm.sh" && nvm install "$NODE_MAJOR" && nvm use "$NODE_MAJOR"
  else
    curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
    export PATH="$HOME/.local/share/fnm:$PATH"
    eval "$(fnm env)" && fnm install "$NODE_MAJOR" && fnm use "$NODE_MAJOR"
  fi
fi
[[ "$(node_major)" == "$NODE_MAJOR" ]] || die "Node $NODE_MAJOR not active (found $(node -v 2>/dev/null || echo none))"
ok "node $(node -v), npm $(npm -v)"

# ---------------------------------------------------------------------------
step "5/8 Web dependencies (React, Vite, MapLibre, ECharts, Tailwind, tests)"
( cd web && if [[ -f package-lock.json ]]; then npm ci; else npm install; fi )
ok "web/node_modules installed; package-lock.json pinned"

# ---------------------------------------------------------------------------
step "6/8 Playwright Chromium (UI checks, offline test)"
( cd web && npx playwright install chromium ) || warn "Playwright browser install failed; UI checks will not run until fixed"

# ---------------------------------------------------------------------------
if [[ $SKIP_VISION -eq 0 ]]; then
  step "7/8 Vision env (.venv-vision): Delineate Anything + torch + GDAL bindings + weights"
  VDIR="$ROOT/vision/Delineate-Anything"
  if [[ ! -d "$VDIR/.git" ]]; then git clone "$DELINEATE_REPO" "$VDIR"; fi
  git -C "$VDIR" fetch --quiet origin
  git -C "$VDIR" checkout --quiet "$DELINEATE_COMMIT"
  ok "Delineate Anything at $(git -C "$VDIR" rev-parse --short HEAD)"

  [[ -x .venv-vision/bin/python ]] || uv venv --python "$PYTHON_VERSION" .venv-vision
  VPY="$ROOT/.venv-vision/bin/python"

  GPU=0
  if [[ $FORCE_CPU -eq 0 ]] && have nvidia-smi && nvidia-smi >/dev/null 2>&1; then GPU=1; fi
  if [[ $GPU -eq 1 ]]; then
    echo "    nvidia-smi answered: installing CUDA torch"
    uv pip install --python "$VPY" torch torchvision --index-url https://download.pytorch.org/whl/cu128
  else
    echo "    no working GPU driver (or --cpu): installing CPU torch"
    uv pip install --python "$VPY" torch torchvision --index-url https://download.pytorch.org/whl/cpu
  fi
  uv pip install --python "$VPY" -r "$VDIR/requirements.txt"
  # GDAL Python bindings must match the system libgdal exactly.
  uv pip install --python "$VPY" setuptools wheel numpy
  uv pip install --python "$VPY" --no-build-isolation "gdal[numpy]==$(gdal-config --version)"

  WEIGHTS_DIR="$ROOT/data/models/delineate-anything"
  mkdir -p "$WEIGHTS_DIR"
  for w in "${DELINEATE_WEIGHTS[@]}"; do
    "$VPY" -c "from huggingface_hub import hf_hub_download as d; print('    ' + d('MykolaL/DelineateAnything', '$w', local_dir='$WEIGHTS_DIR'))"
  done
  ( cd "$WEIGHTS_DIR" && sha256sum ./*.pt > SHA256SUMS ) && ok "weights hashed in data/models/delineate-anything/SHA256SUMS"

  "$VPY" - <<'PY'
import torch, ultralytics
from osgeo import gdal
print(f"    torch {torch.__version__} cuda_available={torch.cuda.is_available()}")
print(f"    ultralytics {ultralytics.__version__}, gdal {gdal.__version__}")
PY
  ok "vision env imports passed"
else
  step "7/8 Vision env skipped (--skip-vision)"
fi

# ---------------------------------------------------------------------------
step "8/8 Local config and checks"
if [[ ! -f .env ]]; then cp .env.example .env; ok "created .env from .env.example (add OPENAI_API_KEY there)"; fi

if [[ $SKIP_CHECKS -eq 0 ]]; then
  uv run python scripts/doctor.py || warn "doctor reported missing items (see above)"
  uv run pytest -q || die "pytest failed"
  ( cd web && npm run test && npm run build ) || die "web tests/build failed"
  ok "pytest, vitest and production web build passed"
fi

printf '\n\033[1;32mSetup finished.\033[0m Log: %s\n' "${LOG#"$ROOT"/}"
echo "Next: tell Claude it's done. Dev servers: 'make dev-api' and 'make dev-web'."
