# Gateway Auto-Config (Prototyp)

Ziel: Ein UG65 wird direkt über seine interne Web-API konfiguriert, statt Werte per Copy & Paste
ins Web-UI zu übertragen oder ein Golden Backup einzuspielen.

## Bausteine

- `services/gateway_config.py`: API-Client (`UG65Client`), Profil-Rendering, Abgleich (`plan`), Schreiben (`execute`)
- `gateway_profiles/ug65-<firmware>.json`: Soll-Konfiguration je freigegebener Firmware
- `scripts/gateway_autoconfig.py`: Kommandozeile, Standard ist **Dry-Run**

## Protokoll (UG65, FW 60.0.0.49)

`POST http://<gateway>/cgi` mit `{"id", "execute": 1, "core", "function", "values"}`.

| Zweck | Aufruf |
|---|---|
| Login | `core=user`, `function=login`, `values=[{username, password, base: "web_login"}]`, Passwort AES-128-CBC mit dem festen Key/IV aus `login.js` |
| Lesen | `function=get`, `values=[{base}]` |
| Schreiben | `function=set`, `values=[{base, index, value: {nur geänderte Felder}}]` |
| WireGuard-Peers | `value.peers=[{..., action}]`, 1 = anlegen, 2 = ändern, 3 = löschen |
| Übernehmen | `core=yruo_apply`, `function=apply` |
| Neustart | `core=yruo_upgrade`, `function=reboot` |

`status=-2` heißt: nicht eingeloggt oder Sitzung abgelaufen.

## Ablauf

1. Firmware aus der Antwort (`rtver`) prüfen. Weicht sie vom Profil ab, wird nicht geschrieben (Override: `--force-firmware`).
2. Pro Profil-Abschnitt lesen, Felder vergleichen, nur Abweichungen schreiben.
3. `apply`, danach erneut lesen und vergleichen (Verifikation).
4. Optional Neustart.

## Gerätewerte

| Platzhalter | Quelle |
|---|---|
| `gateway_id` | EUI aus `/node-red/device-info` (oder `--eui`) |
| `vpn_address` | `--vpn-ip` + `/32` |
| `vpn_private_key` | `--from-db` (gateway_inventory) oder `GATEWAY_VPN_PRIVATE_KEY` |
| `wifi_ssid` | `bbdbmon_<x>.<y>` aus der VPN-IP |
| `wifi_key` | `GATEWAY_WIFI_KEY` |
| `vpn_server_public_key` | `VPN_SERVER_PUBLIC_KEY` |

Geheimwerte nur über Umgebung/`.env`, nie als Argument. In der Ausgabe werden sie maskiert.
Fehlt ein Wert, wird das Feld im Dry-Run als „nicht geprüft“ gelistet. Mit `--apply` bricht das Tool dann ab.

## Nutzung

```bash
python scripts/gateway_autoconfig.py --vpn-ip 172.30.0.116             # Dry-Run
python scripts/gateway_autoconfig.py --vpn-ip 172.30.0.116 --from-db --apply --reboot
```

Exit-Codes: 0 = OK/keine Abweichung, 1 = Dry-Run mit Abweichungen, 2 = Fehler, 3 = Verifikation fehlgeschlagen.

## Neue Firmware freigeben

1. Ein korrekt eingerichtetes Gateway mit der neuen Firmware auslesen.
2. `gateway_profiles/ug65-<neu>.json` aus dem alten Profil kopieren, Felder abgleichen.
3. Dry-Run gegen dieses Gateway muss „keine Abweichung“ melden.

## Offen

- Node-RED-Flows einspielen (Admin-API `/node-red/flows`, eigener Login)
- Firmware-Upgrade automatisieren
- Einbindung in die UI („Gateway konfigurieren“-Button) und in den Provisioning-Ablauf
- WLAN-Ländercode: Profil setzt `DE` (Referenzgerät stand auf `CN`)
