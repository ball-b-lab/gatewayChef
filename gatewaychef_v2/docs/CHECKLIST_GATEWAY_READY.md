# Checkliste: Gateway wirklich fertig?

- Gateway meldet die erwartete EUI.
- Gateway meldet die reservierte VPN-IP.
- Gateway meldet die erwartete WiFi-SSID.
- VPN-Ping auf die reservierte IP ist erfolgreich.
- ChirpStack enthaelt das Gateway.
- Milesight enthaelt das Gateway.
- Webservice enthaelt den Gateway-Eintrag, wenn `client_id` gesetzt ist.
- `gateway_inventory` enthaelt den finalen Snapshot.
- Readiness Report zeigt `PASS`.
- Laufstatus ist `DONE`.
