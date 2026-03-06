# DB Hotspots (bereinigt)

Stand: 2026-03-06
Quelle: `/Users/jochen/bb/projects/milesight_lora_gw_config/provisioner`

## Kritische Dateien
- `routes/db.py`
- `db/sim.py`
- `db/connection.py`

## Kritische Endpunkte (in `routes/db.py`)
- `GET /api/db/fetch-ip`
- `POST /api/db/vpn-key`
- `POST /api/db/gateway`
- `POST /api/db/customer-update`
- `POST /api/provision`
- `GET /api/sim/vendors`
- `POST /api/sim/next`
- `POST /api/confirm`

## SQL/Transaktions-Hinweise
- Verwendet `FOR UPDATE SKIP LOCKED` (IP-Auswahl)
- Verwendet `FOR UPDATE` (Provisionierung/Statuswechsel)
- Enthält State-Transitionen (`FREE` -> `IN_PROGRESS` -> weitere Updates)

## Sofortige Refactor-Ziele
1. SQL aus `routes/db.py` in Repository-Klassen verschieben
2. Transaktionslogik in Services kapseln
3. Auth-/User-Layer vor schreibenden Endpunkten erzwingen
4. Lock-Semantik in Tests absichern
