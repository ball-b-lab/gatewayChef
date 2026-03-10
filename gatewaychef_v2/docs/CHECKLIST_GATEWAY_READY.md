# Checkliste: Gateway wirklich fertig?

- Gateway meldet die erwartete EUI.
- Gateway meldet die reservierte VPN-IP.
- Gateway meldet die erwartete WiFi-SSID.
- VPN-Health-Check auf die reservierte IP ist erfolgreich.
- ChirpStack enthaelt das Gateway.
- Milesight enthaelt das Gateway.
- Kunde ist zugeordnet.
- Webservice enthaelt den Gateway-Eintrag.
- `gateway_inventory` enthaelt den finalen Snapshot mit `VERIFIED` oder `DEPLOYED`.
- Readiness Report zeigt `PASS`.
- Laufstatus ist `DONE`.

## Nicht fertig, aber bewusst als Draft erlaubt

Diese Punkte sind fuer einen Draft zulaessig:

- keine `Kunden-ID`
- kein Webservice-Eintrag
- Cloud DB Status `IN_PROGRESS`

Ein Draft ist nicht freigegeben und darf nicht als fertig markiert werden.
