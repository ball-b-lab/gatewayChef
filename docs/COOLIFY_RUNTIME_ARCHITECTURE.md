# Coolify Runtime Architecture (GatewayChef)

Stand: 2026-03-06

## 1) Zielbild in einem Satz
- Die App ist oeffentlich ueber HTTPS erreichbar.
- Die neue PostgreSQL-DB laeuft intern im Coolify-Netz (nicht oeffentlich).
- Clients greifen nur auf die API zu, nicht direkt auf die DB.

## 2) Was laeuft wo?

### Lokal (dein Rechner)
- Optional fuer Entwicklung:
  - `python app.py` (lokale App)
  - optional lokales Postgres via `docker compose` (nur dev)
- Optional fuer Migration-Tools:
  - `scripts/import_legacy_dump.sh` (liest alte DB, schreibt neue DB)

### Cloud (Coolify)
- App-Container: `gatewayChef` (Dockerfile)
- DB-Container: PostgreSQL-Resource in Coolify (separat anzulegen)
- Reverse Proxy (Coolify intern): TLS + Routing von Domain auf App-Port

## 3) Container und Ports

### App-Container
- In Dockerfile: `EXPOSE 5000`
- App-Prozess: `python app.py`
- Muss mit `HOST=0.0.0.0` und `PORT=5000` laufen.

### DB-Container (Coolify PostgreSQL Resource)
- Postgres hoert intern auf `5432`.
- In Produktion: keinen oeffentlichen Port publishen.
- Zugriff nur intern vom App-Container ueber Coolify-Netz.

### Reverse Proxy
- Extern: `https://<deine-domain>`
- Internes Ziel: App-Container Port `5000`
- Wenn App nicht startet oder auf falschem Port hoert, gibt es `503`.

## 4) Wichtige Env-Variablen (Betrieb)

Diese Variablen gehoeren in die Coolify-App (laufender Betrieb):

- `DB_HOST=<interner db-service-name>`
- `DB_PORT=5432`
- `DB_NAME=<neue-db-name>`
- `DB_USER=<neuer-db-user>`
- `DB_PASSWORD=<neues-db-passwort>`
- `HOST=0.0.0.0`
- `PORT=5000`
- `OPEN_BROWSER=false`
- `FLASK_DEBUG=false`
- `JWT_SECRET=<starker-secret-wert>`
- `JWT_ALGORITHM=HS256`
- `JWT_EXPIRES_HOURS=24`
- `CHIRPSTACK_URL=...`
- `CHIRPSTACK_API_TOKEN=...`
- `CHIRPSTACK_TENANT_ID=...`
- `CHIRPSTACK_STATS_INTERVAL_SECS=30`
- `MILESIGHT_URL=...`
- `MILESIGHT_CLIENT_ID=...`
- `MILESIGHT_CLIENT_SECRET=...`
- `MILESIGHT_TOKEN_URL=`
- `GATEWAY_USER=...`
- `GATEWAY_PASSWORD=...`
- `VPN_PING_SERVICE_TOKEN=<shared-token>`

Wichtig:
- `DB_*` in der App zeigen nach Cutover immer auf die neue DB.
- Nie auf die alte DB zeigen lassen, wenn du schon umgestellt hast.

## 5) Env-Variablen fuer Migration (einmalig)

Nur fuer den Import-Lauf (`scripts/import_legacy_dump.sh`):

- `SOURCE_DATABASE_URL=postgresql://<alt-user>:<alt-pass>@<alt-host>:5432/<alt-db>`
- `TARGET_DATABASE_URL=postgresql://<neu-user>:<neu-pass>@<neu-host>:5432/<neu-db>`

Optional:
- `IMPORT_MODE=schema-and-data` oder `data-only`
- `TABLES="gateway_inventory sim_cards sim_vendors"`

Wichtig:
- `SOURCE_DATABASE_URL`/`TARGET_DATABASE_URL` sind nicht die normalen Laufzeit-`DB_*` der App.
- Sie werden nur waehrend des Import-Skripts genutzt.

## 6) Datenmigration: alt -> neu (Ablauf)

1. Neue Postgres-DB in Coolify anlegen.
2. App in Coolify auf neue DB-`DB_*` konfigurieren.
3. Einmaligen Import aus alter DB in neue DB fahren (`import_legacy_dump.sh`).
4. Smoke-Test gegen neue API.
5. Alte DB-Zugriffspfade abschalten (kein Direktzugriff mehr fuer Clients).

## 7) Warum 503 passiert (und wie erkennen)

Typische Ursachen:
- App-Prozess startet nicht (Crash beim Start).
- App hoert auf anderem Port als Reverse Proxy erwartet.
- Startup-Kommando blockiert/failt (z. B. Migration mit fehlenden DB-Rechten).

Checkliste:
- Runtime Logs in Coolify pruefen.
- `PORT=5000`, `HOST=0.0.0.0` verifizieren.
- DB-Verbindung und Rechte pruefen.

## 8) VPN-Ping-Architektur

Problem:
- Lokaler Rechner ist nicht im VPN und kann `172.30.x.x` nicht pingen.

Loesung:
- Lokale App ruft `/api/network/vpn-check` auf.
- Wenn `VPN_PING_PROVIDER_URL` gesetzt ist, forwarded die lokale App an Cloud `/api/network/ping-service`.
- Cloud-App fuehrt den Ping aus (im Cloud-Netz) und liefert Status zurueck.

Dazu setzen:
- Cloud-App: `VPN_PING_SERVICE_TOKEN=<secret>`
- Lokale App: 
  - `VPN_PING_PROVIDER_URL=https://<cloud-app-url>`
  - `VPN_PING_SERVICE_TOKEN=<same-secret>`

## 9) Minimaler Mental-Model Summary

- Betrieb: App -> neue interne DB
- Migration: alte DB -> neue DB (einmalig)
- Proxy: Internet -> Coolify Proxy -> App:5000
- DB bleibt intern, API ist die einzige Boundary
