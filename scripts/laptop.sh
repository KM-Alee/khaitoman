#!/usr/bin/env bash
# Host orchestration only: project dependencies and backup code execute in Docker.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
state="$root/.laptop"
mkdir -p "$state"
if [[ ! -f "$state/settings" ]]; then
  umask 077
  cat > "$state/settings" <<EOF
HOST_UID=$(id -u)
HOST_GID=$(id -g)
AABFLOW_RUNTIME_ENV_FILE=${AABFLOW_RUNTIME_ENV_FILE:-$root/.env}
AABFLOW_LAPTOP_PORT=8010
AABFLOW_CORS_ORIGINS=http://127.0.0.1:5180,http://localhost:5180
AABFLOW_TUNNEL_TOKEN_FILE=$state/cloudflared-token
EOF
fi
dc() { docker compose --env-file "$state/settings" -f "$root/compose.laptop.yaml" "$@"; }
snapshot_data() {
  local source=$1 destination=$2
  [[ -d "$source" ]] || { echo "Data source does not exist: $source" >&2; exit 1; }
  docker run --rm --user "$(id -u):$(id -g)" --entrypoint python \
    -v "$root/scripts:/tools:ro" -v "$source:/app/data" -v "$state:/snapshots" \
    aabflow-dev:local /tools/laptop_snapshot.py --source /app/data --destination "/snapshots/$destination"
}
check_backend() {
  dc exec -T backend python -c 'import json,urllib.request; h=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/v2/health", timeout=10)); assert h["status"]=="ok" and h["dispatcher"]=="running"; print(json.dumps(h, indent=2))'
}
backup_store() {
  local name="backup-$(date -u +%Y%m%dT%H%M%SZ)"
  snapshot_data "$state/data" "$name" || return $?
  cp -a "$state/vision" "$state/$name.vision" || return $?
  dc images -q backend > "$state/$name.image" || return $?
  echo "Backup: $state/$name (plus .vision and .image)"
}
set_image_tag() {
  sed -i '/^AABFLOW_IMAGE_TAG=/d' "$state/settings"
  printf 'AABFLOW_IMAGE_TAG=%s\n' "$1" >> "$state/settings"
}
case "${1:-status}" in
  seed)
    [[ $# == 2 ]] || { echo "Usage: $0 seed /absolute/path/to/source/data (quiesce writers first)" >&2; exit 2; }
    snapshot_data "$(realpath "$2")" data
    source_root=$(dirname -- "$(realpath "$2")")
    mkdir -p "$state/vision"
    cp -a "$source_root/vision/runs" "$source_root/vision/batches" "$state/vision/"
    ;;
  build) dc --profile vision build backend vision ;;
  up) dc up -d --wait --wait-timeout 180 backend; check_backend ;;
  update)
    # Build before interrupting service; preserve a full backup before changing its image.
    previous=$(dc images -q backend)
    [[ -n "$previous" ]] || { echo "Start the backend before using update." >&2; exit 1; }
    docker image tag "$previous" aabflow-laptop-backend:previous
    current_tag=$(sed -n 's/^AABFLOW_IMAGE_TAG=//p' "$state/settings")
    current_tag=${AABFLOW_IMAGE_TAG:-${current_tag:-local}}
    previous_vision=$(docker image inspect "aabflow-laptop-vision:$current_tag" --format '{{.Id}}')
    docker image tag "$previous_vision" aabflow-laptop-vision:previous
    printf '%s\n' "$previous" > "$state/previous-image"
    set_image_tag local
    dc --profile vision build backend vision
    dc stop backend
    if ! backup_store; then
      dc start backend
      exit 1
    fi
    dc up -d --wait --wait-timeout 180 backend
    check_backend
    ;;
  rollback)
    [[ -f "$state/previous-image" ]] || { echo "No previous update image recorded." >&2; exit 1; }
    # Data migrations require restoring the matching backup as documented.
    set_image_tag previous
    dc up -d --wait --wait-timeout 180 backend
    check_backend
    ;;
  backup)
    dc stop backend
    if ! backup_store; then
      dc start backend
      exit 1
    fi
    dc up -d --wait --wait-timeout 180 backend
    ;;
  check) check_backend ;;
  vision)
    [[ $# == 2 && "$2" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Usage: $0 vision ONBOARDING_ID" >&2; exit 2; }
    dc --profile vision run --rm --no-deps -T vision python /app/vision/run_pending.py "/app/data/onboarding/$2"
    ;;
  status) dc ps; systemctl --user is-active aabflow-laptop-guard.service || true ;;
  logs) dc logs --tail 100 -f backend ;;
  stop) dc --profile tunnel stop tunnel backend; systemctl --user stop aabflow-laptop-guard.service || true ;;
  tunnel-up)
    [[ -f "$state/access-ready" ]] || { echo "Configure same-site Cloudflare Access and CORS first (docs/LAPTOP_DEPLOYMENT.md), then create .laptop/access-ready." >&2; exit 1; }
    dc --profile tunnel up -d --wait --wait-timeout 180 backend tunnel
    dc exec -T backend python -c '
import time, urllib.request
for attempt in range(30):
    try:
        with urllib.request.urlopen("http://tunnel:2000/ready", timeout=2) as response:
            assert response.status == 200
        print("Named tunnel has a live Cloudflare connection")
        break
    except (OSError, AssertionError):
        if attempt == 29:
            raise
        time.sleep(2)
'
    ;;
  tunnel-stop) dc --profile tunnel stop tunnel ;;
  awake)
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/aabflow-laptop-guard.service" <<EOF
[Unit]
Description=AabFlow laptop sleep inhibitor and backend health recovery

[Service]
ExecStart=/usr/bin/systemd-inhibit --what=sleep:idle:handle-lid-switch --mode=block --who=AabFlow --why=Serving-laptop-backend "$root/scripts/laptop.sh" watch
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable aabflow-laptop-guard.service
    systemctl --user restart aabflow-laptop-guard.service
    systemctl --user --no-pager status aabflow-laptop-guard.service
    ;;
  watch)
    while true; do
      container=$(dc ps -q backend)
      if [[ -n "$container" ]]; then
        health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")
        if [[ "$health" == unhealthy ]]; then
          echo "Backend unhealthy after consecutive checks; restarting its container."
          dc restart --timeout 10 backend
        fi
      fi
      sleep 30
    done
    ;;
  *) echo "Usage: $0 {seed SOURCE_DATA|build|up|update|rollback|backup|check|vision ONBOARDING_ID|status|logs|stop|tunnel-up|tunnel-stop|awake}" >&2; exit 2 ;;
esac
