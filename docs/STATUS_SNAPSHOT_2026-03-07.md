# STATUS SNAPSHOT (Ist-Stand) - 2026-03-07

Projektpfad: `/Users/jochen/bb/projects/gatewayChef`

Hinweis: Dieses Dokument beschreibt nur den Ist-Stand vom 2026-03-07 und nimmt **keine** Veraenderungen vor.

## 1) Architektur-Istzustand (lokale App vs cloud_api vs DB)

### Lokale App (aktiver Modus in diesem Workspace)
- Aktueller Modus ist `APP_MODE=local` (aus `config.py` Default und aktueller `.env` ohne gesetztes `APP_MODE`).
- In `local` werden alle Blueprints geladen, inkl. Gateway/ChirpStack/Milesight/Webservice.
- Root `/` liefert die UI (`templates/index.html`).

Belege:
- `/Users/jochen/bb/projects/gatewayChef/app.py` (Blueprint-Registrierung, Mode-Switch)
- `/Users/jochen/bb/projects/gatewayChef/config.py` (`APP_MODE` Default `local`)
- `/Users/jochen/bb/projects/gatewayChef/.env` (kein `APP_MODE` gesetzt)

### Cloud API Modus (implementiert, aber hier nicht als aktiver Runtime-Modus konfiguriert)
- `APP_MODE=cloud_api` ist vorgesehen.
- In `cloud_api` sind nur DB/Auth/Network-Blueprints aktiv; Gateway-/ChirpStack-/Milesight-/Webservice-Routen werden nicht registriert.
- Root `/` liefert dann JSON Service-Status statt UI.

Belege:
- `/Users/jochen/bb/projects/gatewayChef/app.py:42`
- `/Users/jochen/bb/projects/gatewayChef/app.py:50`
- `/Users/jochen/bb/projects/gatewayChef/docs/TARGET_ARCHITECTURE_LOCAL_CLOUD.md:129`

### DB-Anbindung
- DB-Zugriff erfolgt ueber `DATABASE_URL` **oder** `DB_*` (`db/connection.py`).
- Aktuell aus `.env`: `DB_HOST=localhost`, `DB_PORT=5432`, `DB_NAME=gatewaychef`.
- DB-nahe API-Endpunkte liegen unter `routes/db.py` (`/api/db/*`, `/api/sim/*`, `/api/provision`, `/api/confirm`).

Belege:
- `/Users/jochen/bb/projects/gatewayChef/db/connection.py`
- `/Users/jochen/bb/projects/gatewayChef/.env:6`
- `/Users/jochen/bb/projects/gatewayChef/.env:18`
- `/Users/jochen/bb/projects/gatewayChef/routes/db.py:20`

## 2) Welche Container laufen in Coolify, welche Ports sind offen/geschlossen

### Dokumentierter Coolify-Iststand (aus Projektdoku)
- App-Container (`gatewayChef`) mit internem App-Port `5000`.
- PostgreSQL als eigene Coolify-DB-Resource mit internem Port `5432`.
- Reverse Proxy exponiert HTTPS (Domain) nach App:5000.
- DB soll in Produktion **nicht oeffentlich** exponiert sein.

Belege:
- `/Users/jochen/bb/projects/gatewayChef/docs/COOLIFY_RUNTIME_ARCHITECTURE.md:20`
- `/Users/jochen/bb/projects/gatewayChef/docs/COOLIFY_RUNTIME_ARCHITECTURE.md:27`
- `/Users/jochen/bb/projects/gatewayChef/docs/COOLIFY_RUNTIME_ARCHITECTURE.md:32`
- `/Users/jochen/bb/projects/gatewayChef/docs/COOLIFY_RUNTIME_ARCHITECTURE.md:37`

### Direkt verifizierbarer Laufstatus in diesem Workspace (lokal, nicht Coolify)
Aktuell laufende lokale Container (docker host):
- `gatewaychef_db` -> `0.0.0.0:5432->5432/tcp`
- `redis` -> `6379/tcp` (nur intern sichtbar, kein Host-Mapping)
- `gis_app-flask-1` -> `0.0.0.0:5002->5000/tcp`

Hinweis:
- Ein direkter API-/UI-Zugriff auf den Coolify-Host ist in diesem Workspace nicht hinterlegt; daher wurde fuer Coolify-Status auf die projektdokumentierte Soll-/Ist-Beschreibung referenziert.

## 3) Welche ENV-Variablen aktuell relevant sind (gruppiert: local app, cloud api, db)

Hinweis: Sensible Werte sind als `SET`/`LEER` markiert, nicht im Klartext ausgeschrieben.

### A) Local App (aktueller Laufkontext)
Aus `/Users/jochen/bb/projects/gatewayChef/.env` und `/Users/jochen/bb/projects/gatewayChef/config.py`:
- `PORT=5011`
- `HOST=0.0.0.0`
- `FLASK_DEBUG=true`
- `OPEN_BROWSER=true`
- `APP_MODE` nicht gesetzt in `.env` -> effektiv `local` via `config.py`
- `VPN_PING_PROVIDER_URL` = LEER
- `VPN_PING_SERVICE_TOKEN` = SET
- `API_SERVICE_TOKEN` = LEER (in `.env` nicht gesetzt, in `config.py` vorhanden)

Belege:
- `/Users/jochen/bb/projects/gatewayChef/.env:30`
- `/Users/jochen/bb/projects/gatewayChef/.env:31`
- `/Users/jochen/bb/projects/gatewayChef/.env:96`
- `/Users/jochen/bb/projects/gatewayChef/.env:99`
- `/Users/jochen/bb/projects/gatewayChef/config.py:41`
- `/Users/jochen/bb/projects/gatewayChef/config.py:72`

### B) Cloud API (fuer produktiven cloud_api-Betrieb relevant)
- `APP_MODE=cloud_api`
- `HOST=0.0.0.0`
- `PORT=5000`
- `OPEN_BROWSER=false`
- `FLASK_DEBUG=false`
- `API_SERVICE_TOKEN` (empfohlen fuer `/api/db*`, `/api/sim*`, `/api/provision`, `/api/confirm`)
- `VPN_PING_SERVICE_TOKEN`
- `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRES_HOURS`

Belege:
- `/Users/jochen/bb/projects/gatewayChef/docs/DEPLOYMENT.md:86`
- `/Users/jochen/bb/projects/gatewayChef/docs/DEPLOYMENT.md:87`
- `/Users/jochen/bb/projects/gatewayChef/docs/DEPLOYMENT.md:89`
- `/Users/jochen/bb/projects/gatewayChef/docs/TARGET_ARCHITECTURE_LOCAL_CLOUD.md:131`
- `/Users/jochen/bb/projects/gatewayChef/utils/api_token.py`

### C) DB
- Primar fuer Runtime: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` oder alternativ `DATABASE_URL`
- Fuer einmaligen Import: `SOURCE_DATABASE_URL`, `TARGET_DATABASE_URL`, optional `IMPORT_MODE`, `TABLES`

Belege:
- `/Users/jochen/bb/projects/gatewayChef/db/connection.py`
- `/Users/jochen/bb/projects/gatewayChef/scripts/import_legacy_dump.sh:12`
- `/Users/jochen/bb/projects/gatewayChef/scripts/import_legacy_dump.sh:15`

## 4) DB-Status nach Import (Tabellen, Counts, zentrale Felder)

Datenbasis: laufende lokale DB `gatewaychef_db` (`gatewaychef`, Stand 2026-03-07, direkte SQL-Abfrage via `psql`).

### Tabellen vorhanden (public)
- `gateway_inventory`
- `sim_cards`
- `sim_vendors`
- `users`
- `schema_migrations`

### Row Counts
- `gateway_inventory`: 1
- `sim_cards`: 1
- `sim_vendors`: 1
- `users`: 0
- `schema_migrations`: 2

### Migrationsstand
- `001_create_users.sql`
- `002_legacy_core_tables.sql`

Belege:
- `/Users/jochen/bb/projects/gatewayChef/migrations/001_create_users.sql`
- `/Users/jochen/bb/projects/gatewayChef/migrations/002_legacy_core_tables.sql`
- `/Users/jochen/bb/projects/gatewayChef/scripts/migrate.py`

### Zentrale Feldbeobachtungen (`gateway_inventory`)
- `status_overall`: `FREE=1` (kein `IN_PROGRESS`/`DEPLOYED` Datensatz)
- Vollstaendigkeit (1 Datensatz):
  - `serial_number` vorhanden: 1
  - `private_key` vorhanden: 1
  - `sim_card_id` vorhanden: 1
  - `eui` vorhanden: 0

Schema-Referenz:
- `/Users/jochen/bb/projects/gatewayChef/migrations/002_legacy_core_tables.sql:24`
- `/Users/jochen/bb/projects/gatewayChef/migrations/002_legacy_core_tables.sql:32`
- `/Users/jochen/bb/projects/gatewayChef/migrations/002_legacy_core_tables.sql:47`

## 5) Bekannte Risiken/Abweichungen zur Original-App (`/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner`)

### A) Laufmodus/Blueprint-Scope erweitert
- Neu: `APP_MODE` schaltet zwischen lokaler Voll-App und `cloud_api` Surface.
- Original hatte keinen Mode-Switch und immer volle Route-Registrierung.
- Risiko: Fehlkonfiguration von `APP_MODE` kann unbeabsichtigt Routen aus-/einschalten.

Vergleich:
- Neu: `/Users/jochen/bb/projects/gatewayChef/app.py:42`
- Alt: `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/app.py:44`

### B) Auth-Layer hinzugekommen (users + JWT)
- Neu: `routes/auth.py`, `auth/jwt_auth.py`, `users`-Tabelle/Migration.
- Alt: kein `/api/auth/*`-Stack.
- Risiko: zusaetzliche Betriebsabhaengigkeit auf `JWT_SECRET` und User-Datenpflege.

Vergleich:
- Neu: `/Users/jochen/bb/projects/gatewayChef/routes/auth.py`
- Alt Config ohne Auth-Block: `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/config.py`

### C) Service-Token-Schutz fuer DB-Endpunkte neu
- Neu: `routes/db.py` erzwingt optional `X-API-Token` via `utils/api_token.py`.
- Alt: kein solcher Guard.
- Risiko: Wenn Cloud `API_SERVICE_TOKEN` gesetzt ist, lokale Aufrufer ohne Header brechen mit `401`.

Vergleich:
- Neu: `/Users/jochen/bb/projects/gatewayChef/routes/db.py:14`
- Neu: `/Users/jochen/bb/projects/gatewayChef/utils/api_token.py`
- Alt: `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/routes/db.py` (ohne `before_request` Token-Guard)

### D) VPN-Ping Proxy-Pattern neu
- Neu: `/api/network/vpn-check` kann an Cloud `/api/network/ping-service` forwarden (`VPN_PING_PROVIDER_URL`).
- Alt: nur lokaler `/api/network/ping`.
- Risiko: Token-/URL-Mismatch fuehrt zu 401/502 bei VPN-Checks.

Vergleich:
- Neu: `/Users/jochen/bb/projects/gatewayChef/routes/network.py:69`
- Neu: `/Users/jochen/bb/projects/gatewayChef/routes/network.py:91`
- Alt: `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/routes/network.py:10`

### E) Datenlage nach Import derzeit minimal
- Nur je 1 Datensatz in Kern-Tabellen (`gateway_inventory`, `sim_cards`, `sim_vendors`), `users=0`.
- Risiko: Smoke-Tests mit realistischen Last-/Kantenfaellen sind auf dieser Datenbasis nur eingeschraenkt aussagekraeftig.

## 6) Konkrete naechste 5 Schritte zur Stabilisierung (ohne Implementierung in diesem Dokument)

1. **Coolify Runtime verifizieren (Live):**
   App-Container-Health, DB-Resource-Reachability, Proxy-Route (`https -> app:5000`) gegen reale Coolify-Instanz pruefen und protokollieren.

2. **Token-Matrix verbindlich festziehen:**
   `API_SERVICE_TOKEN` und `VPN_PING_SERVICE_TOKEN` fuer Lokal+Cloud konsistent setzen und in einem Betriebsblatt festhalten (inkl. Header-Namen und betroffene Endpunkte).

3. **DB-Import-Validierung erweitern:**
   Fuer `gateway_inventory`, `sim_cards`, `sim_vendors` feste Post-Import SQL-Pruefungen dokumentieren (Counts, Statusverteilung, Null-Checks fuer Schluesselfelder, FK-Konsistenz).

4. **Cloud-Mode Smoke-Test standardisieren:**
   `scripts/smoke_test.sh` mit `BASE_URL` (Cloud) und optional `API_TOKEN` als Pflicht-Gate vor Produktivnutzung etablieren.

5. **Cutover-Rest-Risiken schliessen:**
   Explizit nachweisen, dass keine Direktzugriffe mehr auf alte/public DB stattfinden (nur API-Pfad), inkl. Netzwerk-/Firewall-Check und Betriebsfreigabe.

---

## Quellen (Datei-/Pfadreferenzen)
- `/Users/jochen/bb/projects/gatewayChef/app.py`
- `/Users/jochen/bb/projects/gatewayChef/config.py`
- `/Users/jochen/bb/projects/gatewayChef/.env`
- `/Users/jochen/bb/projects/gatewayChef/docker-compose.yml`
- `/Users/jochen/bb/projects/gatewayChef/routes/db.py`
- `/Users/jochen/bb/projects/gatewayChef/routes/network.py`
- `/Users/jochen/bb/projects/gatewayChef/utils/api_token.py`
- `/Users/jochen/bb/projects/gatewayChef/db/connection.py`
- `/Users/jochen/bb/projects/gatewayChef/scripts/import_legacy_dump.sh`
- `/Users/jochen/bb/projects/gatewayChef/scripts/migrate.py`
- `/Users/jochen/bb/projects/gatewayChef/migrations/001_create_users.sql`
- `/Users/jochen/bb/projects/gatewayChef/migrations/002_legacy_core_tables.sql`
- `/Users/jochen/bb/projects/gatewayChef/docs/COOLIFY_RUNTIME_ARCHITECTURE.md`
- `/Users/jochen/bb/projects/gatewayChef/docs/TARGET_ARCHITECTURE_LOCAL_CLOUD.md`
- `/Users/jochen/bb/projects/gatewayChef/docs/DEPLOYMENT.md`
- `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/app.py`
- `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/config.py`
- `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/routes/network.py`
- `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner/routes/db.py`
