#!/usr/bin/env bash
# Start wrapper for the station (systemd ExecStart). Updates the code to
# $GATEWAYCHEF_REF (main or a tag), then runs the web UI or a CLI command.
#   gatewaychef-run.sh                 web UI (Einrichtung + /fleet)
#   gatewaychef-run.sh setup ...       scripts/gateway_setup.py
#   gatewaychef-run.sh fleet ...       scripts/fleet.py
#   gatewaychef-run.sh pool ...        scripts/pool_refill.py
set -euo pipefail
APP_DIR="${GATEWAYCHEF_HOME:-/opt/gatewaychef}/app"
REF="${GATEWAYCHEF_REF:-main}"
export GATEWAYCHEF_ENV_FILE="${GATEWAYCHEF_ENV_FILE:-/etc/gatewaychef/env}"
export OPEN_BROWSER=false FLASK_DEBUG=false
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

if [[ "${GATEWAYCHEF_OFFLINE:-0}" != "1" ]]; then
  if git -C "$APP_DIR" fetch --quiet --tags origin; then
    if git -C "$APP_DIR" rev-parse --verify --quiet "refs/tags/$REF" >/dev/null; then target="$REF"; else target="origin/$REF"; fi
    git -C "$APP_DIR" reset --quiet --hard "$target"
  else
    echo "Update nicht moeglich (offline?), starte vorhandenen Stand." >&2
  fi
fi
echo "== GatewayChef $(git -C "$APP_DIR" describe --tags --always) =="
cd "$APP_DIR"
run() { exec uv run --quiet --python 3.12 --no-project --with-requirements requirements.txt python "$@"; }
case "${1:-ui}" in
  ui) run app.py ;;
  setup) shift; run scripts/gateway_setup.py "$@" ;;
  fleet) shift; run scripts/fleet.py "$@" ;;
  pool) shift; run scripts/pool_refill.py "$@" ;;
  *) echo "unbekannt: $1 (ui|setup|fleet|pool)" >&2; exit 2 ;;
esac
