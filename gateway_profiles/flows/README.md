# Node-RED-Flow-Bundles

Eine Datei je Version: `<version>.json` (z. B. `1.0.0.json`). Inhalt ist der normale Flow-Export aus Node-RED
(Menü → Export → alle Flows, JSON).

- In jedem Bundle steht ein Kommentar-Node mit dem Namen `gatewaychef-flow <version>`. Daran wird auch ein
  später auf dem Gerät veränderter Stand noch erkannt.
- Node-IDs bleiben zwischen Versionen gleich. Node-RED behält dann die gespeicherten Zugangsdaten
  (z. B. MQTT-Passwörter) der Nodes. Zugangsdaten gehören nie in den Export.
- Die höchste Version gilt als Soll-Stand für das Update aus der Ferne.

Erzeugen vom Referenzgerät: `python scripts/fleet.py nodered-export --host <ip> --version 1.0.0`
