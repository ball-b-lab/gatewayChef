# Refactor Plan

Stand: 2026-04-15

## Ziel

Dieser Plan zerlegt die naechsten Architektur- und Stabilitaetsarbeiten in kleine, umsetzbare Phasen.
Reihenfolge ist bewusst so gewaehlt, dass zuerst Betriebsrisiken sinken und erst danach groessere UI-Umbauten folgen.

## Leitlinien

- Kein Parallel-Stack neben der aktuellen App einziehen.
- `main` bleibt Release-Baseline.
- Jede Phase soll separat testbar und rueckrollbar bleiben.
- Schreibende DB-Flows erst nach Service-Extraktion aendern.
- UI-Umbauten erst starten, wenn Backend-Fehlerbilder klarer und stabiler sind.

## Phase 0: Baseline und Guardrails

### Ziel

Aktuelle Risiken sichtbar machen und das Refactoring gegen unbeabsichtigte Regressionen absichern.

### Arbeitspakete

- Inventar der kritischen Flows dokumentieren:
  - Gateway lesen
  - VPN-IP reservieren
  - Kundendaten speichern
  - Provisioning speichern
  - Gateway als `DEPLOYED` markieren
  - Cloud Table laden
- Fuer diese Flows bestehende Tests den jeweiligen Dateien und Endpunkten zuordnen.
- Fehlende Smoke-/Unit-Test-Luecken als Checkliste erfassen.
- Logging-Regeln definieren:
  - Keine Klartext-Secrets in Logs
  - Keine unredigierten Fremd-Responses in Standard-Logs
  - Debug-Logs nur bei explizitem Debug-Betrieb
- Sichere Runtime-Defaults definieren:
  - `FLASK_DEBUG=false` als sicherer Default
  - Browser-Auto-Open nur lokal
  - keine rohen Exception-Texte an Operatoren

### Ziel-Dateien

- [app.py](/Users/jochen/bb/projects/gatewayChef/app.py)
- [config.py](/Users/jochen/bb/projects/gatewayChef/config.py)
- [docs/ARCHITECTURE.md](/Users/jochen/bb/projects/gatewayChef/docs/ARCHITECTURE.md)
- [docs/DB_HOTSPOTS.md](/Users/jochen/bb/projects/gatewayChef/docs/DB_HOTSPOTS.md)
- [scripts/smoke_test.sh](/Users/jochen/bb/projects/gatewayChef/scripts/smoke_test.sh)

### Akzeptanzkriterien

- Kritische Operator-Flows sind benannt und referenzierbar.
- Es gibt eine klare Liste, welche Flows heute durch Tests abgesichert sind und welche nicht.
- Default-Verhalten fuer Produktion ist defensiv statt debug-lastig.

## Phase 1: DB- und Provisioning-Refactor

### Ziel

`routes/db.py` auf eine duenne HTTP-Schicht reduzieren und Transaktionslogik in Services kapseln.

### Arbeitspakete

- Neue Service-/Repository-Zustaendigkeiten schneiden:
  - Inventory Read Service
  - Inventory Write/Provisioning Service
  - SIM Assignment Service
  - Cloud Table Query Service
- SQL aus den Route-Handlern extrahieren:
  - `/api/db/gateway`
  - `/api/db/table-view`
  - `/api/sim/next`
  - `/api/provision`
  - `/api/confirm`
  - `/api/db/mark-deployed`
- Einheitliche Fehlerobjekte fuer DB- und Businessfehler verwenden.
- State-Transitionen zentral definieren:
  - `FREE -> IN_PROGRESS`
  - `IN_PROGRESS -> DEPLOYED`
  - Wiederholte Aufrufe sollen deterministisch sein
- Locking-Semantik sichtbar machen und mit Tests absichern.
- Repositories so schneiden, dass Query-Absichten pro Methode klar sind.

### Ziel-Dateien

- [routes/db.py](/Users/jochen/bb/projects/gatewayChef/routes/db.py)
- [services/provisioning_service.py](/Users/jochen/bb/projects/gatewayChef/services/provisioning_service.py)
- [repositories/gateway_inventory_repository.py](/Users/jochen/bb/projects/gatewayChef/repositories/gateway_inventory_repository.py)
- [db/sim.py](/Users/jochen/bb/projects/gatewayChef/db/sim.py)
- `services/*` und `repositories/*` fuer neue Extraktionen

### Tests

- [tests/test_provisioning_service.py](/Users/jochen/bb/projects/gatewayChef/tests/test_provisioning_service.py)
- [tests/test_gateway_inventory_import_route.py](/Users/jochen/bb/projects/gatewayChef/tests/test_gateway_inventory_import_route.py)
- neue Tests fuer:
  - idempotentes Provisioning
  - doppelte Confirm-Aufrufe
  - Konflikte bei SIM-Zuordnung
  - gueltige State-Transitionen

### Akzeptanzkriterien

- `routes/db.py` enthaelt keine komplexe Transaktionslogik mehr.
- Schreibende Flows laufen ueber Services mit klaren Fehler- und Commit-Grenzen.
- Kritische Provisioning-Flows sind durch gezielte Tests abgesichert.

## Phase 2: Integrations- und Netzwerk-Hardening

### Ziel

Alle externen Abhaengigkeiten ueber saubere Client-Grenzen und einheitliches Fehlverhalten absichern.

### Arbeitspakete

- API-Clients einfuehren fuer:
  - Gateway
  - ChirpStack
  - Milesight
  - Webservice
  - Cloud DB/VPN Proxy
- Timeout-, Retry- und JSON-Parsing-Regeln vereinheitlichen.
- Fehlerklassifikation vereinheitlichen:
  - Connect/Timeout
  - Auth/Unauthorized
  - Not Found
  - Upstream invalid response
  - Retryable vs non-retryable
- Logging zentralisieren und Secrets redigieren.
- Fallbacks bewusst entscheiden:
  - `curl`-Fallback am Gateway entweder sauber kapseln oder entfernen
  - Proxy-Fallbacks nur dort, wo sie betrieblich gewollt sind
- DB-Verbindungsaufbau haerten:
  - `connect_timeout`
  - sinnvolle Keepalive-Optionen
  - optional Connection Pooling fuer Cloud-Betrieb

### Ziel-Dateien

- [routes/gateway.py](/Users/jochen/bb/projects/gatewayChef/routes/gateway.py)
- [routes/network.py](/Users/jochen/bb/projects/gatewayChef/routes/network.py)
- [routes/chirpstack.py](/Users/jochen/bb/projects/gatewayChef/routes/chirpstack.py)
- [routes/milesight.py](/Users/jochen/bb/projects/gatewayChef/routes/milesight.py)
- [routes/webservice.py](/Users/jochen/bb/projects/gatewayChef/routes/webservice.py)
- [db/connection.py](/Users/jochen/bb/projects/gatewayChef/db/connection.py)
- `services/*client*.py` oder `integrations/*`

### Tests

- Route-Tests pro Integration mit Mocking von Upstream-Fehlern
- Timeouts, 401/403, 404, invalid JSON, leerer Response-Body
- gezielte Tests fuer VPN-Proxy- und Gateway-Health-Logik

### Akzeptanzkriterien

- Route-Dateien enthalten keine duplizierte `requests`-Fehlerbehandlung mehr.
- Alle externen Integrationen melden Fehler konsistent und operator-tauglich.
- Secrets und sensitive Payloads erscheinen nicht mehr in Standard-Logs.

## Phase 3: UI-Workflow zerlegen und absichern

### Ziel

Die operatorische Hauptstrecke vereinfachen und den Browser-Status robuster machen.

### Arbeitspakete

- [static/js/workflow.js](/Users/jochen/bb/projects/gatewayChef/static/js/workflow.js) nach Domainen aufteilen:
  - gateway-read
  - inventory/db
  - external-services
  - final-check
  - cloud-table
- Inline-Handler aus [templates/index.html](/Users/jochen/bb/projects/gatewayChef/templates/index.html) entfernen und Events in JS registrieren.
- Explizites Workflow-Modell einfuehren:
  - aktueller Schritt
  - blocker
  - warning
  - actionable next step
- Arbeitsstand lokal persistieren:
  - Kunde
  - Gateway-Name
  - VPN-IP
  - SIM-Auswahl
  - letzte gelesenen Gateway-Daten
- Statusanzeige vereinfachen:
  - Connectivity
  - Missing Input
  - Mismatch
  - External API Failure
- Cloud Table operativer machen:
  - Statusfilter
  - Stale-Sync-Hinweis
  - kompaktere Row-Aktionen
- Einen klaren "Naechste Aktion"-Block im Workflow einfuehren.

### Ziel-Dateien

- [templates/index.html](/Users/jochen/bb/projects/gatewayChef/templates/index.html)
- [static/js/main.js](/Users/jochen/bb/projects/gatewayChef/static/js/main.js)
- [static/js/workflow.js](/Users/jochen/bb/projects/gatewayChef/static/js/workflow.js)
- [static/js/ui.js](/Users/jochen/bb/projects/gatewayChef/static/js/ui.js)
- [static/js/state.js](/Users/jochen/bb/projects/gatewayChef/static/js/state.js)
- [static/js/api.js](/Users/jochen/bb/projects/gatewayChef/static/js/api.js)
- [static/css/app.css](/Users/jochen/bb/projects/gatewayChef/static/css/app.css)

### Manuelle Verifikation

- Cloud Table Tab oeffnen und laden
- Haupt-Workflow einmal komplett durchlaufen
- Refresh waehrend des Workflows
- Teilweise ausgefuellte Formulare wiederherstellen
- Fehlerfall pro externer Integration im UI pruefen

### Akzeptanzkriterien

- `workflow.js` ist nicht mehr die zentrale Sammeldatei fuer fast alles.
- Formzustand geht bei Refresh nicht mehr verloren.
- Operator sieht jederzeit klar, was blockiert und was als naechstes zu tun ist.

## Phase 4: Security- und Ops-Hardening

### Ziel

Betriebssicherheit, Deployment-Klarheit und sensible Daten besser absichern.

### Arbeitspakete

- Hart kodierte Zugangsdaten aus der UI entfernen.
- Debug-/Diagnoseinformationen von User-Fehlern trennen.
- Auth- und Service-Token-Grenzen pruefen:
  - lokale User-Auth
  - Cloud Service Token
  - VPN Ping Token
- Build-/Release-Doku auf den tatsaechlichen Stand ziehen.
- Optional:
  - Health endpoints fuer App-internen Zustand
  - strukturierte Logs
  - Request IDs / Correlation IDs

### Ziel-Dateien

- [templates/index.html](/Users/jochen/bb/projects/gatewayChef/templates/index.html)
- [app.py](/Users/jochen/bb/projects/gatewayChef/app.py)
- [routes/auth.py](/Users/jochen/bb/projects/gatewayChef/routes/auth.py)
- [utils/api_token.py](/Users/jochen/bb/projects/gatewayChef/utils/api_token.py)
- [docs/DEPLOYMENT.md](/Users/jochen/bb/projects/gatewayChef/docs/DEPLOYMENT.md)
- [docs/RELEASE_BASELINE.md](/Users/jochen/bb/projects/gatewayChef/docs/RELEASE_BASELINE.md)

### Akzeptanzkriterien

- Keine offensichtlichen Secrets mehr im Frontend.
- Fehlerausgaben sind fuer Operatoren nuetzlich, ohne interne Details preiszugeben.
- Betriebsdoku passt zu den tatsaechlichen Start- und Deploy-Pfaden.

## Empfohlene Reihenfolge fuer die Umsetzung

1. Phase 0 fertigziehen und Testluecken sichtbar machen.
2. Phase 1 fuer DB/Provisioning durchziehen, bevor weitere Features kommen.
3. Phase 2 direkt danach, damit Integrationsfehler konsistent werden.
4. Phase 3 erst starten, wenn Backend-Fehlerbilder stabil sind.
5. Phase 4 parallel zu spaeteren Cleanups oder kurz vor einem groesseren Release.

## Definition of Done pro Phase

- Code ist auf einer kurzen Branch umgesetzt.
- Betroffene Unit-Tests laufen gruen.
- Bearbeitete Python-Entrypoints kompilieren mit `python3 -m py_compile`.
- Bei UI-Aenderungen sind Cloud Table und Haupt-Workflow manuell geprueft.
- Betroffene Doku ist aktualisiert.

## Nicht-Ziele in diesem Plan

- Kein Rewrite auf anderes Framework.
- Keine zweite UI oder zweite API-Struktur.
- Keine umfangreiche Produktneugestaltung vor der Stabilisierung der Operator-Flows.
