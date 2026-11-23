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
  - `data`: `{ status, mac, eui, vpn_ip, wifi_ssid, interfaces, cellular_online, firmware_version, hardware_version }`
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
  - nur Vorschau, **reserviert nicht**. Zum Vergeben `reserve-ip` nutzen.
- `POST /api/db/reserve-ip`
  - body: `{ eui }`
  - bindet atomar den nächsten `FREE`-Eintrag an die EUI (Status `IN_PROGRESS`, `FOR UPDATE SKIP LOCKED`).
    Ist die EUI schon gebunden, kommt derselbe Eintrag zurück (`reused: true`). Zwei gleichzeitige
    Aufrufe bekommen nie dieselbe IP.
  - `data`: `{ vpn_ip, private_key, reused, server_public_key }`
  - `404`, wenn der Pool leer ist
- `GET /api/db/gateways`
  - alle Einträge außer `FREE`: `[{ vpn_ip, eui, gateway_name, serial_number, status_overall, last_sync }]`, ohne Keys
- `GET /api/db/pool-status`
  - `data`: `{ free, total, vpn_ips }` (für `scripts/pool_refill.py`)
- `POST /api/db/vpn-key`
  - body: `{ vpn_ip }`
  - `data`: `{ private_key, serial_number, server_public_key }`
  - `server_public_key` kommt aus `VPN_SERVER_PUBLIC_KEY` der Cloud-Instanz (leer, wenn nicht gesetzt)
- `POST /api/db/import-gateway-inventory`
  - multipart/form-data mit Feld `file` = generierte `peer_inventory.csv`
  - importiert nur `gateway`-Profile nach `gateway_inventory`
  - `data`: `{ inserted, skipped_existing, ignored_non_gateway, processed_gateway_rows }`
- `POST /api/db/gateway`
  - body: `{ vpn_ip?, eui?, serial_number? }`
  - `data`: `{ vpn_ip, eui, wifi_ssid, serial_number, gateway_name, sim_iccid, sim_vendor_id, sim_vendor_name }`
- `POST /api/db/customer-update`
  - body: `{ vpn_ip, gateway_name?, serial_number?, eui?, wifi_ssid?, sim_iccid?, sim_vendor_id?, sim_card_id? }`
  - `data`: `{ status: "success" }`
- `POST /api/db/manual-gateway`
  - body: `{ vpn_ip, private_key, wifi_ssid? }`
  - creates a manual `gateway_inventory` seed row with `status_overall='FREE'`
  - `data`: `{ status: "success", id, vpn_ip, wifi_ssid, status_overall }`
- `POST /api/db/mark-deployed`
  - body: `{ vpn_ip }`
  - marks an existing `gateway_inventory` row as `DEPLOYED`
  - `data`: `{ status: "success", message }`
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
  - body: `{ eui?, serial_number? }`
  - checks first by `eui`; if needed falls back to `serial_number` for legacy/serial-based Milesight entries
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

### Flotte (nur Station/lokal, nicht im `cloud_api`-Modus)
Ohne `apply: true` wird immer nur geprüft.
- `GET /station`: Einrichtungsstation mit mehreren Ports und Vorgangsliste
- `GET /api/station/overview`: `{ports: [{port, iface, vlan, gateway: {host, eui}, job}], jobs: [...]}`
- `POST /api/station/run` `{ port, mode: dry|apply|check, options: {new, client_id, client_name, iccid, sim_vendor_id, serial, name, vpn_ip} }`
- `GET /api/station/job/<id>`: Stand, Ergebnis und Protokoll eines Vorgangs (Einrichtung oder Flotten-Update mit `apply`)
- `GET /fleet`: Weboberfläche
- `GET /api/fleet/status?deep=1&ip=a,b`: Erreichbarkeit über VPN und EUI-Abgleich; `deep` liest zusätzlich
  Firmware, WLAN-Region und Flow-Version
  Jede Zeile eines erreichbaren Gateways enthält `driveby` (aus `/node-red/driveby/health`, ab Flow 1.1.0, sonst `null`):
  `flow_version`, `receiving` (stat < 65 s), `seconds_since_stat`, `seconds_since_rxpk`, `rxpk`,
  `app_seconds_since_poll`, `app_last_poll`, `app_client`, `app_polls` (wann die dbmonitor-App zuletzt `/status` abgeholt hat).
  Ab Flow 1.2.0 zusätzlich `driveby.radio` (letzte 30 min): `crc_error_pct`, `rx_total`, `rx_ok`, `ack_pct`, `rssi_avg`, `snr_avg`, `rssi_min`.
  Ab Flow 1.3.0 zusätzlich `driveby.radio.sf` (`{"SF7": n, …}`), `driveby.radio.tx_failed` und `driveby.devices`
  (gehörte Sensoren 24 h: `id`, `kind` devaddr|join, `count`, `seconds_since`, `rssi`, `snr`, `sf`, `freq`, `fcnt`).
  `deep` liefert außerdem `health` über die Gateway-API (ohne IMSI/ICCID/IMEI/Zell-ID):
  `health.cellular` (`status`, `connected_for`, `provider`, `net_type`, `band`, `register`, `signal_dbm`, `rsrp_dbm`,
  `rsrq_db`, `sinr_db`, `data_usage` = Modemzähler) und `health.system` (`uptime_s`, `cpu_load`, `memory_avail_percent`,
  `storage_avail_percent`, `lns` = aktive Forwarder-Ziele mit `connected`). Ältere Firmware liefert nicht alle Felder.
  Ohne exaktes Profil enthält die Zeile `profile` (genutztes neuestes Profil) und `firmware_compat`.
- `GET /api/fleet/catalog`: Patches, Flow-Bundles, freigegebene Firmwares
- `POST /api/fleet/patch` `{ vpn_ip, name, apply, allow_risky }`
  - `data.result`: `ok | would_change | changed | skipped | offline | failed`
- `POST /api/fleet/nodered` `{ vpn_ip, version, apply }`
  - `data.result`: `ok | would_change | updated | unchanged | failed | offline`; bei `failed` zusätzlich
    `rolled_back` und `rollback_ok`
- `POST /api/fleet/firmware` `{ vpn_ip, version, apply, force }`
  - Vor dem Upload Stabilitaetspruefung wie bei `align` (4x erreichbar, Latenz < 3 s, Cloud-LNS laut Forwarder verbunden);
    sonst `skipped` ohne Upload. `force: true` ueberspringt die Pruefung.
  - `data.result`: `ok | would_change | updated | skipped | failed | offline`, dazu `checks: [{label, ok, info}]`
    (Upload, Neustart, Firmware, upgrade_error, Schnittstelle, Node-RED-Flows erhalten)
- `GET /api/fleet/compare?ip=a,b` Soll-Ist gegen den Standard (Profil der Firmware ohne VPN/Mobilfunk/Netz,
  neuester Flow). Je Gateway `result: ok | would_change | blocked | offline | error`, `changes: [{label, lns, fields}]`,
  `flow: {current, target, ok}`, `firmware_ok`, `firmware_newest`. Schreibt nichts.
- `POST /api/fleet/align` `{ vpn_ip, apply, force }` gleicht ein Gateway an den Standard an.
  - Ohne `apply` nur Vergleich. Mit `apply` zuerst Stabilitätsprüfung (`STABLE_SAMPLES`=4 Antworten im
    Abstand `STABLE_INTERVAL`=5 s, Latenz < `STABLE_MAX_MS`=3000, Cloud-LNS laut Packet Forwarder `servs[].connected` verbunden; `/lora/health` zaehlt nicht, die Anzeige ist auf aelteren Flows unzuverlaessig). Nicht stabil →
    `result: skipped`, nichts geschrieben. `force` überspringt die Prüfung (nur vor Ort).
  - Reihenfolge: Flow → Parameter → LNS-Ziele zuletzt und allein. Nach den LNS-Zielen muss das Gateway
    antworten, der Forwarder den Cloud-LNS als verbunden melden (`LNS_VERIFY_WAIT`=90 s) und der Datenweg frische Pakete liefern,
    sonst werden die alten Ziele zurückgeschrieben (`rolled_back`, `rollback_ok`), `result: failed`.
  - `result: changed | skipped | failed | ok | would_change`, dazu `checks`.
- `GET /api/fleet/catalog` enthält zusätzlich `firmware_images` und `firmware_upload_configured`

## VPN-Peers (`/vpn`, `GET /api/vpn/peers`)

Seite `/vpn` listet alle Peers des Gateway-VPN mit Name, letztem Handshake, Traffic und — wo
vorhanden — Gateway-Name/Seriennr./Status aus der DB. Filter: online (< 3 min), heute, inaktiv
(> 1 Tag), nie verbunden; Bereich (Infrastruktur/Gateways/Stationen); freie Pool-Plätze ausblenden.

Quelle: Der VPN-Server schreibt minütlich `wgpeer json` (ohne Schlüssel) nach
`/var/lib/wgpeer/www/peers.json` und stellt es per `wgpeer-http.service` nur auf
`172.30.0.1:8787` bereit (nur durch den Tunnel erreichbar). Die App liest es über
`VPN_PEERS_URL` (Default `http://172.30.0.1:8787/peers.json`). In `APP_MODE=cloud` nur mit
Authentik-Login.

## Fernwartung in der Cloud (`APP_MODE=cloud`)

In der Cloud gibt es nur Fernwartung: `/` leitet auf `/fleet`, die Einrichtung vor Ort
(`/api/gateway/*`, Milesight, ChirpStack-Anlage, Webservice, `/station`) ist nicht registriert.

- `/fleet`: Funktionsblöcke Prüfen · Standard & Einstellungen · Drive-by-Schnittstelle (WLAN) ·
  Firmware; Filter (online/offline, Firmware, Schnittstelle, Funkempfang, DB-Status), Suche über
  alle Felder, Sortierung per Spaltenkopf. Firmware/WLAN-Region/Schnittstelle werden beim Öffnen
  einmal per „Tief prüfen“ gelesen und für schnelle Prüfungen gemerkt (`deep_age`).
- `/fleet/gw/<ip>`: Einzelsicht mit ChirpStack-Paketen (24 h stündlich / 7 Tage täglich),
  VPN-Handshake und Traffic, Soll-Ist, letzte Vorgänge, Aktionen für dieses Gateway.
- `GET /api/fleet/gateway/<ip>/stats?days=1|7` → `{gateway, chirpstack{last_seen, rx, tx, rx_per_freq}, vpn}`
- `GET /api/fleet/jobs?ip=` → letzte Vorgänge (nur seit Start des Prozesses)
