# Node-RED-Flow-Bundles

Eine Datei je Version: `<version>.json` (z. B. `1.0.0.json`). Inhalt ist der normale Flow-Export aus Node-RED
(Menü → Export → alle Flows, JSON).

- In jedem Bundle steht ein Kommentar-Node mit dem Namen `gatewaychef-flow <version>`. Daran wird auch ein
  später auf dem Gerät veränderter Stand noch erkannt.
- Node-IDs bleiben zwischen Versionen gleich. Node-RED behält dann die gespeicherten Zugangsdaten
  (z. B. MQTT-Passwörter) der Nodes. Zugangsdaten gehören nie in den Export.
- Die höchste Version gilt als Soll-Stand für das Update aus der Ferne.
- Geheimwerte stehen nur als Platzhalter `{{name}}` im Bundle. GatewayChef setzt sie beim Deploy ein,
  heute nur `gateway_login_password_enc` aus `GATEWAY_PASSWORD`.
- `1.1.0` braucht das 3. Packet-Forwarder-Ziel (Patch `driveby-udp-forward`). Erst den Patch einspielen,
  dann den Flow. Details: `docs/NODERED_DRIVEBY_REVIEW.md`.
- `1.1.1` (22.11.2026): ACK an den Packet Forwarder geht von Port 1702 (vorher Zufallsport, der Forwarder
  verwarf die ACKs, `connected 0`, `ackr 0`). Danach Patch `lns-nodered-first`: Node-RED ist 1. Ziel,
  Cortex 2., der interne LNS ist aus.

Erzeugen vom Referenzgerät: `python scripts/fleet.py nodered-export --host <ip> --version 1.0.0`
- `1.2.0` (23.11.2026): `/node-red/driveby/health` liefert zusätzlich `radio` (letzte 30 min aus den
  Packet-Forwarder-Statistiken): `crc_error_pct`, `rx_total`/`rx_ok`, `ack_pct`, `rssi_avg`/`snr_avg`/`rssi_min`
  der empfangenen Pakete. Sonst unverändert zu 1.1.1.
- `1.3.0` (23.11.2026): `devices` = gehörte Sensoren der letzten 24 h (DevAddr bzw. DevEUI bei Join, max. 500)
  mit `count`, `seconds_since`, `rssi`, `snr`, `sf`, `freq`, `fcnt`; `radio.sf` (SF-Verteilung 30 min) und
  `radio.tx_failed` (Downlinks, die der Forwarder nicht senden konnte = dwnb − txnb; den Grund sieht nur der LNS).
