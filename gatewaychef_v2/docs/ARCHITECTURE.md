# GatewayChef v2 Architektur

## Zielbild

Die v2 behandelt drei reale Betriebsfaelle:

- `Neu`
  Gateway ist noch `bbdbmon_golden` oder technisch unvollstaendig.
- `Konfiguriert als Draft`
  Gateway ist technisch sauber, aber noch keinem Kunden zugeordnet oder noch nicht im Webservice angelegt.
- `Konfiguriert und freigegeben`
  Gateway ist technisch sauber, in den Cloud-Systemen angelegt und in der Cloud DB final bestaetigt.

Der interne Lauf bleibt zustandsbasiert:

`DRAFT -> PRECHECK_PASSED -> CONFIG_PENDING -> CONFIG_APPLIED -> CLOUD_SYNCED -> VERIFIED -> DONE`

Fehlschlaege landen in `FAILED`. Der Lauf darf erneut angestossen werden, ohne bestehende Cloud-Eintraege blind zu duplizieren.

## Kernbausteine

- `blueprint.py`
  Stellt die v2 UI und die API unter `/gatewaychef-v2/api/...` bereit.
- `services.py`
  Zentraler Orchestrator. Erzwingt Guardrails, Idempotenz, Draft-/Freigabe-Logik und Readiness-Gates.
- `repository.py`
  Persistiert Provisionierungslaufe und Audit-Events getrennt vom Alt-Pfad.
- `connectors.py`
  Kapselt Gateway-, Cloud-DB-, ChirpStack-, Milesight-, Webservice- und VPN-Health-Zugriffe.
- `static/app.js`
  Fuehrt Discovery, Zustandsableitung und operatorfuehrende UI-Logik zusammen.

## Discovery und Zustandsableitung

Beim Laden liest die v2 automatisch:

- Gateway Device-Info
- LoRa-Konfiguration
- LoRa-Health
- bestehenden Cloud-DB-Eintrag per VPN-IP oder EUI
- optional die Webservice-Zuordnung per EUI, sobald Login-Daten vorliegen

Aus diesen Daten wird der sichtbare Zustand abgeleitet:

- `Neu konfigurieren`
- `Technisch unvollstaendig`
- `Technisch ok, Draft`
- `Technisch ok, Webservice offen`
- `Technisch ok, Freigabe offen`
- `Technisch ok + freigegeben`

## Sicherheitsprinzipien

- Kein Klartext-Logging sensibler Werte
- Fail-fast bei fehlenden kritischen ENV-Werten fuer Inventar oder Cloud-Sync
- Korrelation pro Lauf ueber `run_id` bzw. Trace-ID
- `Neu konfigurieren` nur nach expliziter Bestaetigung
- Bereits freigegebene Gateways werden bei einem fehlgeschlagenen Verify nicht rueckgestuft

## Draft vs. Freigabe

Wenn keine `client_id` gesetzt ist:

- Cloud-DB-Snapshot darf als `IN_PROGRESS` gespeichert werden
- Webservice-Anlage wird bewusst ausgelassen
- Readiness bleibt `BLOCK`
- finale Freigabe ist nicht erlaubt

Wenn `client_id` gesetzt ist und der Webservice-Eintrag fehlt:

- v2 bietet gezielt die Anlage im Webservice an
- erst danach kann der Gateway verifiziert und freigegeben werden

## Readiness Report

Die Abschlusspruefung wertet pro Gateway aus:

- Gateway-Konfiguration stimmt mit den Zielwerten ueberein
- VPN ist ueber den Cloud-Health-Call erreichbar
- LoRa/LNS ist gesund
- ChirpStack-Eintrag existiert
- Milesight-Eintrag existiert
- Kunde ist zugeordnet
- Webservice-Eintrag existiert
- Datenbank-Snapshot passt zum finalen Sollzustand

Nur bei `release_gate=PASS` ist `DONE` erlaubt.
