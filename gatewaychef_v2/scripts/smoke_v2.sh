#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:5000}"

run_id="$(
  curl -sS -X POST "${BASE_URL}/gatewaychef-v2/api/runs" \
    -H 'Content-Type: application/json' \
    -d '{
      "operator_name":"Smoke Test",
      "gateway_name":"smoke-gw-01",
      "serial_number":"SER-SMOKE-01",
      "sim_vendor_id":"1",
      "sim_iccid":"8949000000000000001",
      "client_id":"1",
      "webservice_username":"demo",
      "webservice_password":"demo"
    }' | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["run_id"])'
)"

for step in precheck reserve; do
  curl -sS -X POST "${BASE_URL}/gatewaychef-v2/api/runs/${run_id}/${step}" -H 'Content-Type: application/json' -d '{}' >/dev/null
done

curl -sS -X POST "${BASE_URL}/gatewaychef-v2/api/runs/${run_id}/confirm-config" \
  -H 'Content-Type: application/json' \
  -d '{"confirm_apply":true,"note":"smoke"}' >/dev/null

for step in cloud-sync verify finalize; do
  curl -sS -X POST "${BASE_URL}/gatewaychef-v2/api/runs/${run_id}/${step}" \
    -H 'Content-Type: application/json' \
    -d '{"webservice_username":"demo","webservice_password":"demo"}' >/dev/null
done

curl -sS "${BASE_URL}/gatewaychef-v2/api/runs/${run_id}/report"
