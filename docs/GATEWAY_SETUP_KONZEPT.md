# Gateway Setup: Konzept und Umsetzung

Stand: 2026-11-18 · Branch `feat/gateway-auto-config`

## Ziel

Ein UG65 liegt am Arbeitsplatz. Ein Befehl richtet es komplett ein: DB-Eintrag, Gateway-Konfiguration,
VPN, Milesight-Plattform, Webservice. Jeder Schritt wird geprüft. Ohne Golden Backup und ohne Copy & Paste.

```
gatewaychef.cmd setup                         # prüfen (Dry-Run), nichts wird geschrieben
gatewaychef.cmd setup --apply --client-id 10999 --iccid 8949... --sim-vendor-id 2
gatewaychef.cmd setup --check                 # nur Prüfungen, z. B. vor dem Versand
```

(Unter macOS/Linux: `python scripts/gateway_setup.py ...`)

## Architektur

```
scripts/gateway_setup.py            CLI
services/setup/pipeline.py          Ablauf + Prüfungen je Schritt (kennt nur Interfaces)
services/setup/checks.py            Lesende Prüfungen: LAN, WireGuard, Mobilfunk, LNS, VPN Ende-zu-Ende
services/setup/factory.py           EINZIGE Stelle, die entscheidet, welche Implementierung läuft (.env)
services/setup/adapters/base.py     Interfaces: Inventory, Registry
services/setup/adapters/inventory.py    DbInventory (PostgreSQL) | ApiInventory (Cloud-gatewayChef)
services/setup/adapters/webservice.py   Ws1Webservice (heute) | Ws2Webservice (neue adminapi)
services/setup/adapters/platforms.py    MilesightPlatform | ChirpStackLns
services/gateway_config.py          Gateway-API (/cgi) + Profil-Abgleich
gateway_profiles/ug65-<fw>.json     Soll-Konfiguration je freigegebener Firmware
```

**Austauschbarkeit:** Die Pipeline ruft nur `find()`/`create()` (Registries) bzw. `get()`/`save()`/
`mark_deployed()` (Inventar). Für den Wechsel auf WS2 genügt `WEBSERVICE_BACKEND=ws2` plus Keys. Ein
weiteres System (z. B. ERPNext) ist eine neue `Registry`-Klasse und eine Zeile in `factory.py`.

| Variable | Werte | Standard |
|---|---|---|
| `INVENTORY_BACKEND` | `api`, `db` | `api`, wenn `DB_API_PROVIDER_URL` gesetzt und kein `DB_HOST` |
| `WEBSERVICE_BACKEND` | `ws1`, `ws2`, `off` | `ws1` |
| `MILESIGHT_ENABLED` | `true`/`false` | `true` |
| `CHIRPSTACK_ENABLED` | `true`/`false` | `false` |
| `GATEWAY_PROFILE` | Profilname | `ug65-60.0.0.49` |

## Schritte und Prüfungen

| # | Schritt | Prüft | Schreibt (nur mit `--apply`) |
|---|---|---|---|
| 1 | Vorprüfung | Inventar erreichbar · Gateway per LAN erreichbar · Login · **Firmware freigegeben** · welche Dienste konfiguriert sind | – |
| 2 | Identität | EUI gültig (keine Platzhalter-EUI) · VPN-IP aus DB per EUI, Argument oder Pool (`--new`) · **EUI nicht bei anderer VPN-IP** · **VPN-IP nicht von anderem Gerät belegt** · WireGuard-Key in DB · Seriennummer (Argument → DB → Milesight) · ICCID · Name | – |
| 3 | Datenbank | Abweichung DB ↔ Soll (EUI, SN, Name, SSID, SIM) | `gateway_inventory`, Status `IN_PROGRESS` |
| 4 | Gateway-Konfiguration | Ist ↔ Profil, Feld für Feld | nur Abweichungen, `apply`, **zurücklesen** |
| 5 | Netz & VPN | `wg0` aktiv mit der richtigen IP · Mobilfunk mit IP · Packet Forwarder verbunden mit LNS · Node-RED-LoRa-Health · **VPN Ende-zu-Ende** | – |
| 6 | Register | je System: vorhanden? Pflichtfelder da? | anlegen, dann **erneut suchen** (Bestätigung) |
| 7 | Abschluss | alle Schritte grün? | Status `DEPLOYED` |

Status je Schritt: `OK` · `NEU` (geschrieben) · `DIFF` (würde schreiben) · `WARN` · `--` (übersprungen) · `FEHL`.
`DEPLOYED` wird nur gesetzt, wenn kein Schritt `FEHL`, `DIFF` oder `--` meldet. Exit-Code 0 = alles ok,
1 = Dry-Run mit Änderungen, 2 = Fehler.

**Idempotent:** Ein zweiter Lauf auf einem fertigen Gateway ändert nichts und meldet überall `OK`.
Läuft ein Schritt nicht durch, setzt der nächste Lauf dort fort. Das ist in den Tests abgesichert.

### VPN-Test

Drei Stufen, damit ein Fehler eindeutig zuzuordnen ist:

1. **Am Gateway:** `wg0` ist aktiv und hat genau die VPN-IP aus der DB (`/node-red/device-info`).
2. **Transport:** Mobilfunk hat eine IP, der Packet Forwarder ist mit dem LNS verbunden.
3. **Ende-zu-Ende:** Die VPN-IP wird von außen durch den Tunnel angefragt.
   - **Direkt** (Rechner selbst im VPN): `GET http://<vpn-ip>/node-red/device-info`, die **EUI in der
     Antwort muss passen**. Das erkennt doppelt vergebene IPs oder falsche Keys, nicht nur „irgendwer antwortet“.
   - **Über den Cloud-Proxy** (`VPN_PING_PROVIDER_URL`): Der Cloud-gatewayChef fragt aus dem VPN heraus an.
     Jede HTTP-Antwort des Gateways zählt als Erfolg. „No route to host“ zählt als Fehlschlag. Gewartet
     wird bis zu `--vpn-wait` Sekunden (Standard 90), weil der Tunnel nach dem Schreiben erst aufbauen muss.

## Wartbarkeit: Launcher statt EXE

**Probleme der PyInstaller-EXE:** Jede Änderung braucht einen Build auf Windows, und die Verteilung läuft
von Hand. Welche Version auf welchem PC läuft, ist unklar. **Die `.env` mit allen Zugangsdaten wird in
die EXE eingebacken** (`gatewaychef.spec`, `datas`). Wer die EXE hat, hat die Secrets.

**Lösung: `scripts/windows/gatewaychef.cmd` + `gatewaychef.ps1`**

- Installiert beim ersten Start `uv`. Das ist eine einzelne Datei, die Python mitbringt; auf dem PC muss
  kein Python installiert sein.
- Holt bei jedem Start `main` (oder `-Ref <tag>`) nach `%LOCALAPPDATA%\GatewayChef\app`. **Release =
  Merge auf `main`**, es gibt keinen Build und keine Verteilung mehr. Die Version wird beim Start angezeigt.
- Die Abhängigkeiten werden von `uv` gecacht. Ab dem zweiten Start dauert das Sekunden.
- Die `.env` liegt in `%LOCALAPPDATA%\GatewayChef\.env`, **außerhalb des Codes**
  (`GATEWAYCHEF_ENV_FILE`). Ein Update überschreibt sie nie.
- `-Offline` startet den vorhandenen Stand ohne Update.
- Voraussetzung: `git` mit Zugriff auf `ball-b-lab/gatewayChef` (Git Credential Manager, einmalige Anmeldung).

Die EXE bleibt bis zur Ablösung lauffähig, wird aber nicht weiterentwickelt.

**Stufe 2 (nächster Schritt):** Auf dem Operator-PC liegen dann keine Secrets mehr. Lokal nötig ist nur,
was ins LAN des Gateways muss (Gateway-Login, Profil schreiben, LAN-Checks). DB, Webservice,
Milesight und ChirpStack laufen über den Cloud-gatewayChef (Coolify, `main`). Für das Inventar ist das
heute schon so (`ApiInventory`). Für die Registries kommt ein `ApiRegistry`-Adapter dazu, der die
vorhandenen `/api/milesight/*`- und `/api/webservice/*`-Routen der Cloud nutzt. Die Pipeline bleibt
dabei unverändert, es ändert sich nur `factory.py`.

## Erster Lauf am echten Gateway (18.11.2026, `--check`)

Das Gateway hat die EUI `24E124FFFEF783E6` und die VPN-IP `172.30.0.116`. Die Seriennummer, die ICCID
und der Name kamen aus der DB.

- Vorprüfung, Identität und Datenbank: OK.
- Gateway-Konfiguration: einzige Abweichung `country_code` CN → DE. Peer-Public-Key und WLAN-Key wurden
  nicht geprüft, weil die Werte in der `.env` fehlen.
- Netz & VPN: `wg0` aktiv mit `172.30.0.116`, Mobilfunk hat eine IP, der Packet Forwarder ist mit
  `ball-b-cs.cortex-media.de` verbunden, VPN Ende-zu-Ende über den Cloud-Proxy OK.
- Milesight: Eintrag vorhanden.
- **Warnung:** Der Node-RED-LoRa-Health meldet `LNS_DISCONNECTED` mit `seconds_since_stat` ≈ Unix-Zeit,
  hat also nie einen Stat gesehen. Der Packet Forwarder meldet dagegen `connected=1`. Der Health-Flow
  wertet vermutlich eine Quelle aus, die auf dieser Firmware nicht befüllt wird.

## Was noch fehlt (Informationen und Entscheidungen)

1. **WS2: Gerät einem Kunden zuordnen** ist in der WS2-API noch nicht spezifiziert (offen in
   `bb-protocol-workbench/docs/ws2-api-schreibseite.md`). `Ws2Webservice` legt das Gerät mit den Kennungen
   EUI, SN und ICCID an, ordnet es aber keinem Kunden zu. Das muss mit Matthias geklärt sein, bevor
   umgestellt wird. Außerdem nötig: der `deviceType`-Slug für das UG65, `WS2_URL` und die Keys.
2. **WS1-Zugang für die Automatik:** ein Service-Login (`WEBSERVICE_USER`/`WEBSERVICE_PASSWORD`) statt eines
   persönlichen Logins aus der UI.
3. **`VPN_SERVER_PUBLIC_KEY` und `GATEWAY_WIFI_KEY`** in die `.env`. Ohne sie lehnt `--apply` die
   Konfiguration ab. Offen ist auch, ob der WLAN-Key für alle Gateways gleich sein soll.
4. **SIM:** Eine neue ICCID braucht die `--sim-vendor-id`. Über `/cgi` habe ich keine Abfrage für ICCID oder
   Seriennummer gefunden. Sie kommen aus der DB, aus Milesight (SN) oder als Argument. Ein Barcode-Scanner
   ins Argument würde das Abtippen ersparen.
5. **ChirpStack:** Wird es parallel zu `ball-b-cs.cortex-media.de` noch gebraucht? Standardmäßig ist es aus.
6. **Node-RED-Flows einspielen:** Die Admin-API (`/node-red/flows`) braucht eigene Zugangsdaten. Offen ist,
   wo der Flow-Stand versioniert wird (Vorschlag: `gateway_profiles/flows/`).
7. **Node-RED-Health-Befund** (siehe oben) prüfen, bevor der Health-Status zum harten Kriterium wird.
8. **Cloud-Proxy für den VPN-Test:** `/api/network/gateway-health` sollte die EUI des Gateways
   zurückgeben, damit der Proxy-Weg auch die Identität prüft. Direkt im VPN geschieht das bereits.

## Sicherheitsbefunde (nebenbei)

- Die EXE enthält die `.env` mit allen Secrets. Mit dem Launcher entfällt das.
- `services/provisioning_service.py` hat das DB-Ergebnis **inklusive WireGuard-Private-Key** ins Log
  geschrieben. **Behoben.**
- Das Gateway-Admin-Passwort steht im Klartext in `templates/index.html`. Offen.
- Die Milesight-Auto-Provisionierung ist am Gateway aktiv, schlägt aber fehl. Offen.
