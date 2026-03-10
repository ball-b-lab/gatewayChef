# Migration und Rollback

## Migration

- Root-Schema unveraendert lassen
- zusaetzlich `gatewaychef_v2/scripts/migrate_v2.py` ausfuehren
- danach ist die v2 unter `/gatewaychef-v2/` verfuegbar

## Rollback

- v2 UI nicht mehr verwenden
- Blueprint-Registrierung entfernen oder Deployment ohne v2 ausrollen
- v2 Tabellen koennen separat entfernt werden:
  - `provisioning_v2_events`
  - `provisioning_v2_runs`
  - `schema_migrations_v2`

Bestehende Tabellen und der Alt-Workflow bleiben davon unberuehrt.
