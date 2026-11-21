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

Erzeugen vom Referenzgerät: `python scripts/fleet.py nodered-export --host <ip> --version 1.0.0`
