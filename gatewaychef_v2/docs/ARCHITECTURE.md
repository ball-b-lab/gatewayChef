# GatewayChef v2 Architektur

## Zielbild

Die v2 trennt den Provisionierungsprozess in klar definierte, persistierte Zustandsuebergaenge:

`DRAFT -> PRECHECK_PASSED -> CONFIG_PENDING -> CONFIG_APPLIED -> CLOUD_SYNCED -> VERIFIED -> DONE`

Fehlschlaege landen in `FAILED`, koennen aber nach Korrektur erneut angestossen werden.

## Kernbausteine

- `blueprint.py`
  Stellt die v2 UI und die API unter `/gatewaychef-v2/api/...` bereit.
- `services.py`
  Zentraler Orchestrator. Erzwingt Guardrails, Idempotenz und Readiness-Gates.
- `repository.py`
  Persistiert Provisionierungslaufe und Audit-Events in separaten v2 Tabellen.
- `connectors.py`
  Kapselt Gateway-, DB-, ChirpStack-, Milesight-, Webservice- und Network-Zugriffe.

## Sicherheitsprinzipien

- Kein Klartext-Logging sensibler Werte
- Fail-fast bei fehlenden kritischen ENV-Werten fuer Inventar oder Cloud-Sync
- Korrelation pro Lauf ueber `run_id` bzw. Trace-ID
- Abschluss nur nach erfolgreicher Verifikation

## Readiness Report

Die Abschlusspruefung wertet pro Gateway aus:

- Gateway-Konfiguration stimmt mit reservierten Zielwerten ueberein
- VPN ist erreichbar
- ChirpStack-Eintrag existiert
- Milesight-Eintrag existiert
- Webservice-Eintrag existiert, falls `client_id` gesetzt ist
- Datenbank-Snapshot passt zum beobachteten Zielzustand

Nur bei `release_gate=PASS` ist `DONE` erlaubt.
