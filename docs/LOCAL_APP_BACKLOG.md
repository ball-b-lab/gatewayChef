# Local App Backlog

Stand: 2026-03-07

## Phase 1 (Stabilisierung)
- [x] GW Status Zeilenfarben und OK/NO Icons gegen reale Gateway-Antworten verifizieren.
- [x] Sicherstellen, dass Target `Gateway ID` immer konsistent zur abgeleiteten/gelesenen EUI ist.
- [x] Webservice-Flow mit echten Kundendaten-End-to-End pruefen (Suche, Auswahl, Anlage).
- [x] Optional: Auth-Pfade fuer reinen Local+Cloud-DB-Proxy Betrieb entkoppeln (wenn lokal kein Auth benoetigt).

## Phase 2 (Bedienbarkeit)
- [x] Sichtbarer Hinweis in UI, wenn `SKIP_AUTH`-Testmodus aktiv genutzt wird (nur Doku/Operator-Hinweis).
- [x] Klare Bedienhinweise fuer Fehlerfaelle `VPN check proxy`, `DB proxy`, `Gateway offline`.

## Phase 3 (Inhalt)
- [x] Platzhalter-Hilfebilder in `static/help/images/` ersetzen.

## Umsetzung (Dateien)
- Status/EUI/Webservice-Robustheit: `static/js/workflow.js`, `routes/webservice.py`
- Runtime-Hinweise/Badges: `templates/index.html`, `static/js/main.js`, `static/js/ui.js`
- Local-vs-Cloud Auth-Trennung: `config.py`, `app.py`
- Help-Inhalte: `static/help/README.md`, `static/help/login.md`, `static/help/login.json`
