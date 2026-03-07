# Coolify Runtime Architecture (GatewayChef)

Stand: 2026-03-07

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
- App laeuft mit `APP_MODE=cloud_api` und exponiert nur:
  - DB API (`/api/db/*`, `/api/sim/*`, `/api/provision`, `/api/confirm`)
  - VPN Ping Service (`/api/network/ping-service`, `/api/network/vpn-check`)

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

- `APP_MODE=cloud_api`
- `DB_HOST=<interner db-service-name>`
- `DB_PORT=5432`
- `DB_NAME=<neue-db-name>`
- `DB_USER=<neuer-db-user>`
- `DB_PASSWORD=<neues-db-passwort>`
- `HOST=0.0.0.0`
- `PORT=5000`
- `OPEN_BROWSER=false`
- `FLASK_DEBUG=false`
- `API_SERVICE_TOKEN=<shared-token-local-cloud>`
- `VPN_PING_SERVICE_TOKEN=<shared-token>`
- `APP_BUILD_SHA=<git-sha>`
- `APP_BUILD_TAG=<release-tag>`
- `APP_BUILD_TIME=<utc-timestamp>`

Wichtig:
- `DB_*` in der App zeigen nach Cutover immer auf die neue DB.
- Nie auf die alte DB zeigen lassen, wenn du schon umgestellt hast.
- Cloud braucht im Zielbild keine Gateway-/ChirpStack-/Milesight-/Webservice-Credentials.

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

## 9) DB API Proxy aus lokaler App

Lokaler Runner kann DB-Aufrufe an die Cloud API weiterreichen:

- Lokal setzen:
  - `DB_API_PROVIDER_URL=https://<cloud-app-url>`
  - `API_SERVICE_TOKEN=<same-token-as-cloud>`
- Ergebnis:
  - lokale Endpunkte `/api/db*`, `/api/sim*`, `/api/provision`, `/api/confirm`
    werden serverseitig an Cloud weitergeleitet.
  - Frontend bleibt unveraendert auf relativen `/api/...`-Pfaden.

## 10) Minimaler Mental-Model Summary

- Betrieb: App -> neue interne DB
- Migration: alte DB -> neue DB (einmalig)
- Proxy: Internet -> Coolify Proxy -> App:5000
- DB bleibt intern, API ist die einzige Boundary

## 11) Versionsnachweis (Cloud)

Die Cloud API liefert `GET /api/version` mit Build-Metadaten.

Beispiel:
```bash
curl -sS 'https://<deine-domain>/api/version'
```

Erwartung:
- `data.app_mode=cloud_api`
- `data.build_sha` entspricht deployed Commit

Hinweis zu Build-Metadaten:
- Du kannst `APP_BUILD_SHA/APP_BUILD_TAG/APP_BUILD_TIME` in Coolify setzen.
- Wenn sie leer bleiben, ist das ok:
  - `build_sha` faellt auf Git SHA zurueck
  - `build_tag` und `build_time` bleiben `unknown`
- Vorteil mit gesetzten Werten: besserer Deploy-Nachweis.
- Nachteil: zusaetzlicher Pflegeaufwand pro Deploy.
