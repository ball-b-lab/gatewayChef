# GatewayChef v2

Parallele, gehaertete Alternative zum bestehenden GatewayChef-Flow. Die v2 fuehrt Mitarbeiter durch einen expliziten Provisionierungsprozess mit Audit-Events, Readiness Report und Freigabe-Gate.

## Inhalte

- `templates/`, `static/`: Gefuehrte v2-Oberflaeche unter `/gatewaychef-v2/`
- `blueprint.py`: v2 API und UI Blueprint
- `services.py`: Workflow-Orchestrierung mit Guardrails
- `repository.py`: Persistenz fuer Provisionierungslaufe und Audit-Events
- `migrations/`: v2 Tabellen fuer Audit und Run-Zustaende
- `tests/`: Unit-, API- und Smoke-Tests fuer die v2
- `docs/`: Betriebs- und Architekturunterlagen

## Start

1. Bestehende App wie gewohnt starten.
2. Optional v2 Migrationen ausfuehren:
   `python gatewaychef_v2/scripts/migrate_v2.py`
3. v2 UI aufrufen:
   `http://localhost:5000/gatewaychef-v2/`

Weitere Hinweise stehen in den Dokumenten unter `gatewaychef_v2/docs/`.
