#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:5000}"
TEST_EMAIL="${TEST_EMAIL:-smoke.$(date +%s)@gatewaychef.local}"
TEST_PASSWORD="${TEST_PASSWORD:-SmokeTest1234!}"
TEST_FULL_NAME="${TEST_FULL_NAME:-Smoke Test User}"
RUN_WRITE_SMOKE="${RUN_WRITE_SMOKE:-false}"
TEST_VPN_IP="${TEST_VPN_IP:-}"
API_TOKEN="${API_TOKEN:-}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

print_step() {
  echo
  echo "==> $1"
}

fail() {
  echo "[FAIL] $1" >&2
  exit 1
}

json_get() {
  local file="$1"
  local expr="$2"
  python3 - "$file" "$expr" <<'PY'
import json
import sys

file_path = sys.argv[1]
expr = sys.argv[2]
parts = [p for p in expr.split('.') if p]

with open(file_path, 'r', encoding='utf-8') as f:
    try:
        data = json.load(f)
    except Exception:
        print("")
        sys.exit(0)

cur = data
for part in parts:
    if isinstance(cur, dict) and part in cur:
        cur = cur[part]
    else:
        print("")
        sys.exit(0)

if cur is None:
    print("")
elif isinstance(cur, (dict, list)):
    print(json.dumps(cur))
else:
    print(str(cur))
PY
}

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local token="${4:-}"
  local out_body="$5"

  local url="${BASE_URL}${path}"
  local auth_args=()
  local body_args=()
  local service_auth_args=()

  if [[ -n "$token" ]]; then
    auth_args=(-H "Authorization: Bearer ${token}")
  fi


  if [[ -n "$API_TOKEN" && "$path" == /api/* ]]; then
    service_auth_args=(-H "X-API-Token: ${API_TOKEN}")
  fi

  if [[ -n "$body" ]]; then
    body_args=(-H "Content-Type: application/json" --data "$body")
  fi

  local status
  status=$(curl -sS -o "$out_body" -w "%{http_code}" -X "$method" "$url" "${service_auth_args[@]}" "${auth_args[@]}" "${body_args[@]}")
  echo "$status"
}

print_step "GET /"
ROOT_BODY="$TMP_DIR/root.json"
ROOT_STATUS=$(request "GET" "/" "" "" "$ROOT_BODY")
if [[ "$ROOT_STATUS" != "200" ]]; then
  fail "GET / returned status $ROOT_STATUS"
fi
APP_MODE=$(json_get "$ROOT_BODY" "mode")
SKIP_AUTH="false"
if [[ "$APP_MODE" == "cloud_api" ]]; then
  SKIP_AUTH="true"
fi
echo "[OK] GET / -> 200"

TOKEN=""
if [[ "$SKIP_AUTH" == "false" ]]; then
  print_step "POST /api/auth/register"
  REGISTER_BODY="$TMP_DIR/register.json"
  REGISTER_PAYLOAD=$(cat <<JSON
{"email":"$TEST_EMAIL","password":"$TEST_PASSWORD","full_name":"$TEST_FULL_NAME"}
JSON
  )
  REGISTER_STATUS=$(request "POST" "/api/auth/register" "$REGISTER_PAYLOAD" "" "$REGISTER_BODY")

  if [[ "$REGISTER_STATUS" == "200" ]]; then
    TOKEN=$(json_get "$REGISTER_BODY" "data.token")
    [[ -n "$TOKEN" ]] || fail "Register succeeded but token missing"
    echo "[OK] register -> 200"
  elif [[ "$REGISTER_STATUS" == "409" ]]; then
    echo "[INFO] register -> 409 (already exists), trying login"
  else
    cat "$REGISTER_BODY" >&2 || true
    fail "register returned status $REGISTER_STATUS"
  fi

  print_step "POST /api/auth/login"
  LOGIN_BODY="$TMP_DIR/login.json"
  LOGIN_PAYLOAD=$(cat <<JSON
{"email":"$TEST_EMAIL","password":"$TEST_PASSWORD"}
JSON
  )
  LOGIN_STATUS=$(request "POST" "/api/auth/login" "$LOGIN_PAYLOAD" "" "$LOGIN_BODY")
  if [[ "$LOGIN_STATUS" != "200" ]]; then
    cat "$LOGIN_BODY" >&2 || true
    fail "login returned status $LOGIN_STATUS"
  fi
  LOGIN_TOKEN=$(json_get "$LOGIN_BODY" "data.token")
  [[ -n "$LOGIN_TOKEN" ]] || fail "login succeeded but token missing"
  TOKEN="$LOGIN_TOKEN"
  echo "[OK] login -> 200"

  print_step "GET /api/auth/me"
  ME_BODY="$TMP_DIR/me.json"
  ME_STATUS=$(request "GET" "/api/auth/me" "" "$TOKEN" "$ME_BODY")
  if [[ "$ME_STATUS" != "200" ]]; then
    cat "$ME_BODY" >&2 || true
    fail "me returned status $ME_STATUS"
  fi
  ME_EMAIL=$(json_get "$ME_BODY" "data.email")
  [[ "$ME_EMAIL" == "$TEST_EMAIL" ]] || fail "me email mismatch: got '$ME_EMAIL' expected '$TEST_EMAIL'"
  echo "[OK] me -> 200"
else
  echo "[INFO] cloud_api mode erkannt: auth smoke wird uebersprungen."
fi

print_step "GET /api/db/fetch-ip"
FETCH_IP_BODY="$TMP_DIR/fetch_ip.json"
FETCH_IP_STATUS=$(request "GET" "/api/db/fetch-ip" "" "" "$FETCH_IP_BODY")
if [[ "$FETCH_IP_STATUS" == "200" ]]; then
  VPN_IP=$(json_get "$FETCH_IP_BODY" "data.vpn_ip")
  [[ -n "$VPN_IP" ]] || fail "fetch-ip 200 but vpn_ip missing"
  echo "[OK] fetch-ip -> 200 (vpn_ip=$VPN_IP)"

  print_step "POST /api/db/vpn-key"
  VPN_KEY_BODY="$TMP_DIR/vpn_key.json"
  VPN_KEY_PAYLOAD=$(cat <<JSON
{"vpn_ip":"$VPN_IP"}
JSON
)
  VPN_KEY_STATUS=$(request "POST" "/api/db/vpn-key" "$VPN_KEY_PAYLOAD" "" "$VPN_KEY_BODY")
  if [[ "$VPN_KEY_STATUS" != "200" ]]; then
    cat "$VPN_KEY_BODY" >&2 || true
    fail "vpn-key returned status $VPN_KEY_STATUS"
  fi
  echo "[OK] vpn-key -> 200"
elif [[ "$FETCH_IP_STATUS" == "404" ]]; then
  echo "[WARN] fetch-ip -> 404 (keine FREE IP vorhanden)"
else
  cat "$FETCH_IP_BODY" >&2 || true
  fail "fetch-ip returned status $FETCH_IP_STATUS"
fi

if [[ "$RUN_WRITE_SMOKE" == "true" ]]; then
  print_step "WRITE smoke: POST /api/db/customer-update"
  [[ -n "$TEST_VPN_IP" ]] || fail "RUN_WRITE_SMOKE=true requires TEST_VPN_IP"
  WRITE_BODY="$TMP_DIR/write_update.json"
  WRITE_PAYLOAD=$(cat <<JSON
{"vpn_ip":"$TEST_VPN_IP","gateway_name":"SMOKE-TEST-GW"}
JSON
)
  WRITE_STATUS=$(request "POST" "/api/db/customer-update" "$WRITE_PAYLOAD" "" "$WRITE_BODY")
  if [[ "$WRITE_STATUS" != "200" ]]; then
    cat "$WRITE_BODY" >&2 || true
    fail "customer-update returned status $WRITE_STATUS"
  fi
  echo "[OK] customer-update -> 200"
fi

echo
if [[ "$RUN_WRITE_SMOKE" == "true" ]]; then
  echo "Smoke test passed (read + write checks)."
else
  echo "Smoke test passed (read-only checks)."
fi
