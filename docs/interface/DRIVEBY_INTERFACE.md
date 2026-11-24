# Schnittstelle Gateway-Flow ↔ Drive-by-App (dbapp)

Verbindlicher Vertrag zwischen dem Node-RED-Flow auf den UG65-Gateways (`gateway_profiles/flows/<ver>.json`)
und allen Lesern (Drive-by-App, GatewayChef). Maschinenlesbar: [`driveby-health.schema.json`](driveby-health.schema.json).

## Regeln (gelten für jede neue Flow-Version)

1. **Nur hinzufügen.** Endpunkte, Felder, Typen und Bedeutungen bleiben. Ein Bruch wäre eine neue Major-Version (2.x) und wird hier vorher angekündigt.
2. **Leser ignorieren Unbekanntes** und behandeln fehlende neuere Felder als „ältere Version“, nicht als Fehler.
3. **Version erkennen** über `flow_version` (in `/driveby/health` und `/device-info`), nicht über das Vorhandensein von Feldern raten.
4. **HTTP-Status ≠ Ausfall der Schnittstelle:** `/driveby/health` und `/lora/health` liefern 503 mit vollständigem Body, wenn der Paket-Forwarder schweigt.

## Endpunkte (Port 1880, alle Versionen ab 1.1.0 identisch)

| Endpunkt | Inhalt |
|---|---|
| `GET /driveby/health` | Funk-/Forwarder-Zustand, siehe Schema |
| `GET /lora/health` | `status` ONLINE / LNS_DISCONNECTED / …, `lns_connected`, `seconds_since_ack`, `seconds_since_stat`, `last_seen` |
| `GET /lora/gaps`, `/lora/gaps/graph` | Ringpuffer der Verbindungslücken |
| `GET /status?since=<seq>&boot_id=<id>` | Statuslog inkrementell (max. 30 Einträge, `dropped` bei Lücke) |
| `GET /device-info` | MAC, SSID, Interfaces, VPN-IP, `flow_version` |
| `GET /device-info-lora` | LoRa-Konfiguration |

## Änderungen je Version

| Version | Änderung | Wirkung auf Leser |
|---|---|---|
| 1.1.0 | Basis | – |
| 1.2.0 | `/driveby/health`: neues Objekt `radio` (30-min-Fenster: rx, CRC %, tx, ACK %, RSSI/SNR) | additiv |
| 1.3.0 | `radio.sf`, `radio.tx_failed`; neue Liste `devices` (Sensoren je DevAddr/DevEUI) | additiv |
| 1.3.1 | `/device-info`: MAC kommt pro Anfrage richtig (vorher bei parallelen Anfragen manchmal `00:00:00:00:00:00`) | Fehlerbehebung, Format gleich |
| 1.4.0 | Gateway meldet sich zusätzlich selbst bei der GatewayChef-Cloud (jede Minute puffern, alle 10 min senden) | keine Änderung an den Endpunkten |

## Für Entwickler der Leser

- Testfälle: je eine Antwort aus 1.1.0, 1.2.0, 1.3.x, 1.4.0 parsen (fehlendes `radio`/`devices`, `null`-Werte, HTTP 503 mit Body).
- Echte Antworten: `curl http://<vpn-ip>:1880/driveby/health` (0.116 läuft mit 1.4.0).
