# Cutover Checkliste (Alt-DB -> Neue interne DB)

Stand: 2026-03-06

## Zielbild
- PostgreSQL laeuft privat im Coolify-Netz.
- Kein direkter Internetzugriff auf die DB.
- Zugriff nur ueber `gatewayChef` API.

## A) Vorbereitung
1. Neue Umgebung in Coolify erstellen (App + interne PostgreSQL).
2. Env setzen:
   - `DB_HOST` auf internen DB-Service
   - `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
   - `JWT_SECRET`
3. Sicherstellen, dass die App beim Start Migrationen ausfuehrt (`python scripts/migrate.py`).

## B) Datenuebernahme (Einmalig)
1. Quell-/Ziel-URLs bereitstellen:
   - `SOURCE_DATABASE_URL`
   - `TARGET_DATABASE_URL`
2. Import starten:
```bash
SOURCE_DATABASE_URL='postgresql://...' \
TARGET_DATABASE_URL='postgresql://...' \
IMPORT_MODE='schema-and-data' \
./scripts/import_legacy_dump.sh
```
3. Validieren:
   - Tabellen vorhanden: `gateway_inventory`, `sim_cards`, `sim_vendors`, `users`
   - Stichprobe auf Datensaetze (`SELECT count(*) ...`)

## C) Verifikation vor Umschalten
1. API Smoke Tests:
   - `POST /api/auth/register`
   - `POST /api/auth/login`
   - `GET /api/auth/me`
   - `GET /api/db/fetch-ip`
   - `POST /api/db/customer-update`
   - `POST /api/provision`
2. Paralleltest gegen Staging-UI mit Testdatensatz.
3. Schreibtest pruefen (Statuswechsel `FREE` -> `IN_PROGRESS` -> `DEPLOYED`).

## D) Umschalten
1. Schreibzugriffe im Altsystem kurz einfrieren.
2. Delta-Import aus Alt-DB (erneut Script laufen lassen).
3. App-Konfiguration final auf neue interne DB setzen.
4. Produktivverkehr auf neue API-Instanz umleiten.

## E) Nachkontrolle
1. Error-Logs 30-60 Minuten beobachten.
2. Random Stichproben auf 5-10 Provisionierungsfaelle.
3. Alte DB auf read-only oder nur internes Netz beschraenken.
4. Oeffentlichen DB-Zugriff schliessen.

## Rollback
1. Traffic zur alten API/DB zurueck.
2. Neue App pausieren.
3. Ursachenanalyse (Schema, Datenkonflikte, Env-Fehler).
4. Nach Fix neuen Cutover-Termin mit erneutem Delta-Import.
