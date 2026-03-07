# Migration zu User-Layer (gatewayChef)

Stand: 2026-03-06
Quelle: `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner`
Ziel: `/Users/jochen/bb/projects/gatewayChef`

## 1) Ist-Zustand (bereinigt)
- Framework: Flask (Python)
- Direkter DB-Zugriff: `psycopg2`
- Haupt-Hotspots mit SQL:
  - `routes/db.py`
  - `db/sim.py`
  - `db/connection.py`
- Kritischer Bereich: mehrere `FOR UPDATE` / `FOR UPDATE SKIP LOCKED` Flows (Reservierung/Provisionierung)

## 2) Zielarchitektur
- API Layer (Flask routes): nur HTTP, Auth, Validation, Response-Mapping
- Service Layer: Geschaeftslogik + Transaktionsgrenzen
- Repository Layer: einziger Ort mit SQL
- AuthN/AuthZ: Benutzer + Rollen (`user`, `admin`) + JWT/Sessions
- Migrations: versionierte DDL/DML in `migrations/`

## 3) Empfohlene Reihenfolge
1. Characterization-Tests fuer bestehende kritische Flows (`fetch-ip`, `customer-update`, `provision`)
2. User-Model + Login/Register + `me` Endpoint einfuehren
3. `routes/db.py` in Service + Repository schneiden
4. `db/sim.py` in `sim_repository` migrieren
5. Route fuer Route auf den Service-Layer umstellen
6. RBAC auf schreibende/administrative Endpunkte aktivieren

## 4) Erster Implementierungsschnitt (Sprint 1)
- Neues Paketgeruest:
  - `auth/` (jwt utils, password hashing)
  - `repositories/` (gateway_repository.py, sim_repository.py)
  - `services/` (provisioning_service.py)
- Endpunkte:
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `GET /api/auth/me`
- Bestehende Endpunkte bleiben funktionsgleich, aber intern ueber `services/provisioning_service.py` aufrufbar (zunaechst nur fuer `fetch-ip` + `vpn-key`).

## 5) SQL-Migration Prioritaet
- P1: `fetch-ip` (lock semantics sicherstellen)
- P1: `customer-update` (sim assignment + state transition)
- P1: `provision` (komplette Schreib-Transaktion)
- P2: read-only lookup Endpunkte (`gateway`, `sim-vendors`, `sim-cards`)

## 6) Risiken
- Lock-Verhalten darf nicht regressieren (`FOR UPDATE [SKIP LOCKED]`)
- Zwischenstand ohne Auth darf nicht produktiv exponiert werden
- Gemischte Logik in Route und SQL erhoeht Fehlerwahrscheinlichkeit bis zur vollstaendigen Entkopplung

## 7) Konkrete naechste Commands
```bash
cd /Users/jochen/bb/projects/gatewayChef
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Danach:
```bash
# Branch fuer Migration
cd /Users/jochen/bb/projects/gatewayChef
git checkout -b codex/user-layer-foundation
```

## 8) Definition of Done fuer neue User-Layer Basis
- Login/Register/me lauffaehig
- Mindestens 2 bestehende DB-Endpunkte nutzen Service+Repository statt Direkt-SQL in Route
- Automatisierte Tests fuer Lock-/Provisionierungsfluss vorhanden
- Keine SQL-Statements mehr in den migrierten Route-Dateien
