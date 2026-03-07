# API Contract (GatewayChef)

## Response Shape
All API endpoints return a JSON object with this shape:

```json
{
  "ok": true,
  "data": { ... },
  "error": null
}
```

On error:

```json
{
  "ok": false,
  "data": { "missing": ["..."] },
  "error": {
    "message": "Human readable error",
    "code": "optional_code"
  }
}
```

**Common HTTP Status Codes:**
- `200`: Success
- `400`: Bad Request (Validation failed, missing data)
- `500`: Internal Server Error (Unhandled exception)
- `502`: Bad Gateway (Upstream service unreachable/error, e.g., Milesight API, Gateway Connection Refused)
- `504`: Gateway Timeout (Upstream service timed out)

Notes:
- `ok` reflects transport/validation success for the endpoint.
- `data` may be `null` on error, or include `missing` when configuration is incomplete.
- `error.message` is the primary string for UI logging.

## Endpoints

### Gateway
- `GET /api/gateway/device-info`
  - `data`: `{ status, mac, eui, vpn_ip, wifi_ssid, interfaces, cellular_online }`
  - **Errors:** Returns `504` on timeout, `502` on connection error.
- `GET /api/gateway/device-info-lora`
  - `data`: passthrough payload from Node-RED
  - **Errors:** Returns `504` on timeout, `502` on connection error.
- `GET /api/gateway/status-cellular`
  - `data`: passthrough payload from gateway
  - **Errors:** Returns `504` on timeout, `502` on connection error.

### Database
- `GET /api/db/fetch-ip`
  - `data`: `{ vpn_ip, private_key }`
- `POST /api/db/vpn-key`
  - body: `{ vpn_ip }`
  - `data`: `{ private_key, serial_number }`
- `POST /api/db/gateway`
  - body: `{ vpn_ip?, eui?, serial_number? }`
  - `data`: `{ vpn_ip, eui, wifi_ssid, serial_number, gateway_name, sim_iccid, sim_vendor_id, sim_vendor_name }`
- `POST /api/db/customer-update`
  - body: `{ vpn_ip, gateway_name?, serial_number?, sim_iccid?, sim_vendor_id?, sim_card_id? }`
  - `data`: `{ status: "success" }`
- `POST /api/provision`
  - body: full provisioning payload from UI
  - `data`: `{ status: "success", message }`
- `POST /api/confirm`
  - body: `{ vpn_ip }`
  - `data`: `{ status: "success", message }`

### SIM
- `GET /api/sim/vendors`
  - `data`: `{ vendors: [{ id, name, apn }] }`
- `POST /api/sim/next`
  - body: `{ vendor_id }`
  - `data`: `{ id, iccid, sim_id }`

### Network
- `POST /api/network/ping`
  - body: `{ host }`
  - `data`: `{ ok: boolean, output: string }`
- `POST /api/network/ping-service`
  - body: `{ host }`
  - optional header: `X-Ping-Service-Token`
  - `data`: `{ ok: boolean, output: string }`
- `POST /api/network/vpn-check`
  - body: `{ vpn_ip }` (or `{ host }`)
  - uses cloud proxy (`VPN_PING_PROVIDER_URL`) if configured, else local ping
  - `data`: `{ ok: boolean, output: string }`

### Webservice
- `POST /api/webservice/clientsearch`
  - body: `{ query, username, password }`
- `POST /api/webservice/gateways`
  - body: `{ clientId, username, password }`
- `POST /api/webservice/search-by-eui`
  - body: `{ eui, username, password }`
- `POST /api/webservice/create-gateway`
  - body: `{ clientId, lns, name, gatewayId, gatewayEui, simIccid, simId, manufacturer, type, serialNumber, username, password }`
  - forwards serial to webservice as `serialNumber` and compatibility aliases `serial` / `serial_number`

### ChirpStack
- `GET /api/chirpstack/config`
  - `data`: `{ ready: boolean, missing: [] }`
- `POST /api/chirpstack/check`
  - body: `{ eui }`
  - `data`: `{ status: "success", exists: boolean }`
- `POST /api/chirpstack/command`
  - body: `{ eui, serial_number, gateway_name }`
  - `data`: `{ status: "success", payload, url }`
- `POST /api/chirpstack/create`
  - body: `{ eui, serial_number, gateway_name }`
  - create payload sets `gateway.statsInterval` (default `30`, configurable via `CHIRPSTACK_STATS_INTERVAL_SECS`)
  - `data`: `{ status: "success", data }`

### Milesight
- `GET /api/milesight/config`
  - `data`: `{ ready: boolean, missing: [] }`
- `POST /api/milesight/check`
  - body: `{ eui }`
  - `data`: `{ status: "success", exists, serial_number, name, model, details }`
- `POST /api/milesight/command`
  - body: `{ eui, gateway_name }`
  - `data`: `{ status: "success", message }`
- `POST /api/milesight/dry-run`
  - body: `{ eui, gateway_name }`
  - `data`: `{ status: "success", exists, would_create, create_payload }`
- `POST /api/milesight/create`
  - body: `{ eui?, serial_number?, gateway_name }`
  - `data`: `{ status: "success", data, request_id }`
