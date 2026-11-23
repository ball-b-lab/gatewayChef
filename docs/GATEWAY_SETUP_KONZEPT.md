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
| `MILESIGHT_ENABLED` | `true`/`false` | `false` (Schreiben an die Milesight-Plattform geht derzeit nicht) |
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

## VPN-Daten: Pool, Reservierung, Server-Key

**Wo die Daten stehen:** in `gateway_inventory`. Jede Zeile ist ein vorbereiteter Platz mit VPN-IP und
WireGuard-Private-Key. Beim Einrichten wird die EUI an den Platz gebunden. Eine Datei mit vorbereiteten
VPN-Daten ist bewusst nicht vorgesehen: Sie würde Doppelvergaben nicht verhindern und Keys als Klartext
verteilen.

- **Atomare Reservierung:** `POST /api/db/reserve-ip {eui}` bindet den nächsten freien Platz in einer
  einzigen Anweisung an die EUI (`FOR UPDATE SKIP LOCKED`). Mehrere Arbeitsplätze können gleichzeitig
  einrichten. Derselbe Aufruf für dieselbe EUI liefert denselben Platz. Der Dry-Run zeigt nur eine
  Vorschau (`fetch-ip`) und reserviert nichts. Vorher hat `fetch-ip` die Sperre sofort wieder
  freigegeben, sodass zwei Plätze dieselbe IP bekommen konnten.
- **Server-Key zentral:** `VPN_SERVER_PUBLIC_KEY` wird nur in der Cloud gesetzt. Die API liefert ihn mit
  jedem Key aus. Steht er zusätzlich in der lokalen `.env` und weicht ab, bricht die Identitätsprüfung ab.
- **Pool auffüllen:** `scripts/pool_refill.py` meldet, wenn weniger als `POOL_MIN_FREE` Plätze frei sind.
  Es erzeugt neue Schlüssel und die `[Peer]`-Blöcke für den Server. Erst wenn die Peers am Server aktiv
  sind, importiert es die Plätze als `FREE`. Details: `docs/WIREGUARD_POOL_EXPANSION.md`.

## Mehrere Gateways gleichzeitig: Einrichtungsstation

Gewünscht: Fünf Gateways stecken per Ethernet an einem Switch, ein Rechner richtet alle ein. WLAN
entfällt.

**Das Problem:** Alle UG65 haben ab Werk dieselbe LAN-IP. Im selben Netz antworten sie durcheinander
(ARP-Konflikt). Ein einfacher Switch reicht also nur, wenn die Geräte nacheinander angesteckt werden.

**Lösung je nach Werkseinstellung des Ethernet-Ports. Das ist am Gerät noch zu prüfen:**

1. **Der Port bezieht seine Adresse per DHCP:** Dann ist es einfach. Die Station verteilt Adressen per
   DHCP (dnsmasq), jedes Gateway bekommt eine eigene IP, und die Pipeline läuft parallel mit
   `--host <ip>` je Gerät. Zugeordnet wird über die MAC-Adresse beziehungsweise die EUI, die die Pipeline
   ohnehin ausliest.
2. **Der Port hat eine feste Werks-IP:** Dann braucht es einen **VLAN-fähigen Switch** (Port-VLAN, z. B.
   Netgear GS308E, rund 35 €). Jeder Port ist ein eigenes VLAN und kommt als getaggtes Netz an der
   Station an. Die Station legt je Port ein eigenes Linux-Network-Namespace an. Darin sieht jedes
   Gateway seine Werks-IP ungestört. Pro Namespace läuft ein Setup-Prozess, der Internetzugang für
   Cloud-API und Proxy läuft über NAT aus dem Namespace. Ohne Switch geht dasselbe mit einem
   USB-Ethernet-Adapter je Gateway.

Die Station bekommt eine Weboberfläche mit einer Spalte je Port: angesteckt → Dry-Run → Freigabe →
`--apply` → Prüfungen → fertig, dazu der Ausdruck des Etiketts. Bedient wird sie per Browser von jedem
PC aus.

**Entscheidung (20.11.2026):** Gebaut wird mit einem Linux-Rechner, zuerst ohne Switch: ein Gateway nach
dem anderen, per Kabel direkt am Gateway-Port der Station. Installation und Bedienung:
`docs/LINUX_STATION.md`.

**Stand (23.11.2026):** Eingerichtete Gateways stehen mit `eth0` auf DHCP. Die Station verteilt deshalb auf
jedem Gateway-Port Adressen (dnsmasq, 192.168.77.100–150, Station als Router mit NAT – ohne Router nimmt das UG65 die Adresse nicht an) und sucht das Gateway zuerst unter
der neuesten Lease, dann unter den Werks-IPs (`utils/gateway_lan.py`).

**Stand (21.11.2026):** Die Werks-IP ist fest, ohne DHCP. Gebaut ist deshalb Variante 2: ein Namespace je
Port (USB-Adapter oder VLAN-Switch) und die Seite `/station` mit Port-Karten und Vorgangsliste (laufend,
fertig, Fehler, Protokoll). Am fertig eingerichteten Referenzgerät hängt `eth0` als WAN per DHCP im Büronetz
(`192.168.0.x`). Das Profil schreibt `eth0` nicht, neue Gateways behalten also die Werkseinstellung.

## Flotte: Status, Fern-Parameter, Node-RED

Läuft auf einem Rechner im VPN, normalerweise der Station als Workstation-Peer. Weboberfläche `/fleet`,
Kommandozeile `scripts/fleet.py`, Logik in `services/fleet.py`.

**Status:** Alle vergebenen Gateways aus der DB (`GET /api/db/gateways`, ohne Keys) werden parallel über
ihre VPN-IP abgefragt (`/node-red/device-info`). Antwortet eine andere EUI als in der DB, gilt das Gateway
als Fehler, nicht als online. Der tiefe Status meldet sich zusätzlich an und liest Firmware, ob es ein
Profil dazu gibt, die WLAN-Region und die Node-RED-Flow-Version.

**Parameter aus der Ferne (Patches):** `gateway_profiles/patches/<name>.json` hat dasselbe Format wie das
Profil, enthält aber nur die zu ändernden Felder (Beispiel `wifi-country-de`). Ablauf je Gateway:
1. Identität prüfen,
2. Firmware gegen die Liste im Patch prüfen,
3. Plan,
4. Schreiben,
5. warten, bis das Gateway wieder über VPN antwortet,
6. zurücklesen.

Patches auf `yruo_wireguard`, `yruo_cell`, `yruo_network` und `yruo_upgrade` können das Gateway vom VPN
trennen. Sie werden abgelehnt, außer mit `allow_risky`, und dann nur, wenn jemand vor Ort ist.

**Node-RED:**
- **Bundles:** `gateway_profiles/flows/<version>.json` enthält den Flow-Export. Ein Kommentar-Node
  `gatewaychef-flow <version>` markiert die Version.
- **Installierte Version:** Erkannt wird sie über einen Hash der Flow-Logik; Layout und Reihenfolge zählen
  nicht. Passt der Hash zu keinem Bundle, ist der Kommentar-Node da aber vorhanden, gilt die Version als
  „geändert“, das heißt am Gerät angepasst. Das ist die Versionsanzeige für den Drive-by-Monitor.
- **Update:**
  1. Flows sichern (`FLEET_BACKUP_DIR/<EUI>/`).
  2. Vollständig deployen, über die Admin-API von Node-RED.
  3. Die Flows erneut lesen und den Hash vergleichen.
  4. Nachtest: Das Gateway antwortet über VPN mit der richtigen EUI, und `/node-red/lora/health`
     antwortet.
  5. Bei einem Fehler wird automatisch auf die Sicherung zurückgerollt, dann folgt ein zweiter Nachtest.
- **Node-IDs:** Sie bleiben zwischen den Versionen gleich, dann behält Node-RED die gespeicherten
  Zugangsdaten.

**Test nach einem Update.** Drei Ebenen:
1. **Automatisch je Gateway:**
   - nach einem Patch: zurücklesen und Erreichbarkeit,
   - nach Node-RED: Hash, Identität und Health, bei einem Fehler Rollback.
2. **Vor dem Ausrollen:** zuerst ein Gateway im Büro (Test-Gateway), dann 2–3 Gateways im Feld, dann alle.
   Die Oberfläche arbeitet die markierten Zeilen nacheinander ab, der Ablauf ist also steuerbar.
3. **Fachlich (Drive-by):** Nach dem Update muss der Drive-by-Monitor wieder Daten vom Gateway sehen. Die
   Prüfung hängt am Drive-by-Monitor und ist noch nicht angebunden (offen).

## Neue Firmware: Schnittstelle prüfen, nur Deltas melden

Meist bleibt die Schnittstelle zwischen Firmware-Versionen gleich. Deshalb wird bei unbekannter Firmware
nicht mehr pauschal blockiert. Stattdessen wird automatisch geprüft:

1. Gibt es ein Profil für genau diese Firmware (`ug65-<fw>.json`), wird es verwendet.
2. Sonst wird das neueste Profil genommen und **jeder Abschnitt am Gerät gelesen**: Gibt es die Abschnitte
   noch? Die Felder? Haben sie denselben Typ? Das geschieht im selben Lauf, ohne eigenen Schritt.
3. Ergebnis:
   - **kompatibel**, also nichts fehlt und nur neue Felder sind dazugekommen: Das Profil wird verwendet.
     Die Vorprüfung steht auf `WARN`, die neuen Felder erscheinen als Info-Deltas.
   - **inkompatibel**, also ein Abschnitt oder Feld fehlt oder ein Typ hat sich geändert: Es wird nicht
     geschrieben. Die Deltas stehen in der Ausgabe.
4. `FIRMWARE_POLICY=strict` stellt das alte Verhalten wieder her: nur Firmware mit eigenem Profil.

Dasselbe gilt für Fern-Patches: Läuft ein Gateway mit einer Firmware, die nicht in der Liste des Patches
steht, wird der Patch geschrieben, wenn seine Felder am Gerät vorhanden sind. Sonst wird er übersprungen.
Der tiefe Status in `/fleet` zeigt für Firmware ohne eigenes Profil `compatible` oder `incompatible` samt
Deltas.

Ein eigenes Profil braucht es nur noch, wenn die Firmware wirklich inkompatibel ist:
`fleet profile-check --host <ip>` schreibt dann einen Entwurf `ug65-<fw>.json.draft`. Den prüfen, die
umbenannten Felder ergänzen, die Datei umbenennen und einen Dry-Run ohne Abweichung abwarten.

## Firmware-Update aus der Ferne

`fleet firmware --version 60.0.0.49 --ip <vpn-ip> --apply` (oder `--host <lan-ip>` an der Station, oder der
Button in `/fleet`). Die Images liegen in `FIRMWARE_DIR` als `*<version>[-rN].bin`, zum Beispiel
`UG65 60.0.0.49-r4.bin` aus `91_Werkstatt/Milesight_GW_Config`.

Ablauf je Gateway:
1. Die richtige EUI antwortet. Die aktuelle Firmware wird gelesen und der Hash der Node-RED-Flows gemerkt.
2. Upload über `POST /cgi-bin/file-import`, so wie es die Weboberfläche des Gateways tut. Der Upload
   startet das Upgrade.
3. Warten, bis das Gateway einmal weg und wieder da ist (`FIRMWARE_UPGRADE_WAIT`, Standard 20 Minuten).
4. Nachtest:
   - Firmware entspricht der Zielversion,
   - `upgrade_error` ist 0,
   - die richtige EUI antwortet über VPN,
   - die Schnittstelle ist mit dem Profil kompatibel (siehe oben),
   - die Node-RED-Flows sind unverändert,
   - der Drive-by-Datenweg liefert neue Einträge (`checks.check_driveby`, siehe
     `docs/NODERED_DRIVEBY_REVIEW.md`).
5. `--all` und die Weboberfläche arbeiten nacheinander und **stoppen beim ersten Fehler**. Vorgehen: erst
   das Test-Gateway, dann einzelne Gateways im Feld, dann der Rest.

Nicht automatisch möglich ist ein Rollback. Ein Downgrade ist ein weiteres Update mit dem alten Image, und
das entscheidet ein Mensch.

**Formularwerte (am Gerät ermittelt 22.11.2026, FW 60.0.0.49):** `type=upgrade&file=firmware.bin`, die
Einstellungen bleiben erhalten. Mit Werksreset wäre es `upgrade_with_reset`. Beides steht als Standard im
Code (`FIRMWARE_UPLOAD_TYPE`/`FIRMWARE_UPLOAD_FILE` überschreiben).

**Nachprüfung über VPN:** Läuft der Upload über das WLAN des Gateways, verliert der Rechner das WLAN mit dem
Neustart. Deshalb gilt das Gateway auch als zurück, wenn es auf seiner VPN-IP antwortet (`fallback_hosts`,
aus `/device-info`). Alle Nachtests laufen dann dort.

**Erst-Update 22.11.2026:** JK_Test 60.0.0.49 → 60.0.0.50 über WLAN; Flows, Einstellungen und
LoRa-Empfang danach unverändert.

## Firmware immer zuerst auf die neueste (seit 21.11.2026)

Das Setup beginnt mit dem Schritt **Firmware**: Ist das Gateway älter als das neueste Image in
`FIRMWARE_DIR`, wird es zuerst hochgezogen (Dry-Run meldet `49 -> 50`), erst danach konfiguriert.
`FIRMWARE_AUTO_UPGRADE=0` schaltet das ab.

## Gateway kommt ab Werk mit neuerer, ungeprüfter Firmware

`gatewaychef fleet qualify --host <ip>` prüft sofort:
- die Schnittstelle gegen das neueste Profil (Abschnitte, Felder, Typen; neue Felder sind nur Info),
- die Netz-Interfaces `eth0`, `cellular0`, `wlan0` (müssen da sein; `wg0`, Route und VPN-IP sind ab Werk
  noch leer und nur Info),

und gibt eine Zusammenfassung. Passt alles, legt `--approve` das Profil `ug65-<fw>.json` an
(Entwurf = Profil der Vorgänger-Version, nur mit den Feldern, die das Gerät kennt). Danach im Repo
committen. So entstand `ug65-60.0.0.50.json`.

**Weitere Punkte:**
- **Datenvolumen:** Ein Image hat rund 140 MB. Über das VPN läuft das über die SIM des Gateways. Bei
  IoT-Tarifen mit kleinem Volumen das Update besser an der Station im LAN machen (`--host`) oder vor Ort.
- **Session-ID:** Gesucht wird sie in der Login-Antwort und im Cookie `td`. Am Gerät bestätigen.

## Fernwartung: Abgleich mit dem Standard (/fleet)

„Standard prüfen“ vergleicht jedes markierte Gateway mit dem Profil seiner Firmware und dem neuesten
Node-RED-Flow. VPN, Mobilfunk und Netz-Abschnitte bleiben außen vor (gerätespezifisch, Risiko VPN-Verlust),
Firmware wird nur angezeigt. „An Standard angleichen“ ändert ein Gateway nur, wenn es gerade stabil ist
(mehrmals erreichbar, Latenz ok, Cloud-LNS laut Packet Forwarder verbunden), und arbeitet in fester Reihenfolge: Flow, Einzelparameter,
LNS-Ziele zuletzt mit Nachtest und automatischem Rollback. Mehrere Gateways laufen nacheinander, Stopp beim
ersten Fehler. Details: `docs/api.md` (`/api/fleet/compare`, `/api/fleet/align`).

Stand 22.11.2026: 8 Gateways online. JK_Test entspricht dem Standard. Die anderen 7 brauchen Flow 1.1.1,
die neue LNS-Reihenfolge und WLAN-Land DE. Die Node-RED-Anzeige `/lora/health` ist dafür kein
verlässliches Signal: Sie liest Cortex-ACK-Zeilen aus dem Forwarder-Log und meldet auf älteren Flows
UNKNOWN/LNS_DISCONNECTED, auf 172.30.0.115 (FW 48-r2, Flow 1.1.1) seit dem Flow-Update OFFLINE, obwohl der
Forwarder überall `connected 1` meldet und Daten fließen. Stabilitätsprüfung und LNS-Nachtest nutzen deshalb
den Forwarder-Status; alle 8 Gateways sind damit stabil.

## Plattform-Empfehlung

| Teil | Plattform | Warum |
|---|---|---|
| Einrichtungsstation | **Linux-Mini-PC** (Debian, Intel N100, ab ca. 150 €). Ein Raspberry Pi 5 geht auch. | Network-Namespaces, VLANs und dnsmasq gibt es nur unter Linux. Läuft als systemd-Dienst ohne Anmeldung, Updates per `git pull`. Der Mini-PC hat eine SSD und x86, ist also robuster als die SD-Karte des Pi. |
| Cloud-Teil (DB-API, Proxy, später die Register) | Coolify, `main` | wie heute; die Secrets bleiben in der Cloud |
| Einzelplatz und Notfall | Windows-Launcher (`gatewaychef.cmd`) | ein Gateway, ohne Zusatzhardware |
| PyInstaller-EXE | auslaufen lassen | Build-Aufwand, die Secrets sind eingebacken |

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
3. **`VPN_SERVER_PUBLIC_KEY`** in die Cloud-`.env` (Coolify) eintragen und **`GATEWAY_WIFI_KEY`** in die
   lokale `.env`. Ohne diese Werte lehnt `--apply` die Konfiguration ab. Offen ist auch, ob der WLAN-Key
   für alle Gateways gleich sein soll.
4. **SIM:** Eine neue ICCID braucht die `--sim-vendor-id`. Über `/cgi` habe ich keine Abfrage für ICCID oder
   Seriennummer gefunden. Sie kommen aus der DB, aus Milesight (SN) oder als Argument. Ein Barcode-Scanner
   ins Argument würde das Abtippen ersparen.
5. **ChirpStack:** Wird es parallel zu `ball-b-cs.cortex-media.de` noch gebraucht? Standardmäßig ist es aus.
6. **Node-RED-Flows einspielen:** Die Admin-API (`/node-red/flows`) braucht eigene Zugangsdaten. Offen ist,
   wo der Flow-Stand versioniert wird (Vorschlag: `gateway_profiles/flows/`).
7. **Node-RED-Health-Befund** (siehe oben) prüfen, bevor der Health-Status zum harten Kriterium wird.
8. **Cloud-Proxy für den VPN-Test:** `/api/network/gateway-health` sollte die EUI des Gateways
   zurückgeben, damit der Proxy-Weg auch die Identität prüft. Direkt im VPN geschieht das bereits.

9. **Ethernet-Werkseinstellung des UG65** (DHCP oder feste IP) am Gerät prüfen. Davon hängt der Aufbau der
   Station ab, siehe oben.
10. **`192.168.1.0/24` in den `AllowedIPs` am VPN-Server:** Das Netz hängt heute an jedem Gateway-Peer, wirkt
    aber nur beim letzten. Beim nächsten Server-Reload bereinigen.

11. **Node-RED-Admin-API am UG65 prüfen:** Gebaut ist gegen die Standard-API unter `/node-red`
    (`/auth/login`, `/auth/token`, `/flows` v2). Pfad und Login (`NODERED_USER`/`NODERED_PASSWORD`) am Gerät
    bestätigen und dann das erste Bundle vom Referenzgerät exportieren (`fleet nodered-export`).
12. **`/cgi` über VPN:** Für Patches muss die Weboberfläche des Gateways über die VPN-IP erreichbar sein.
    Am Gerät prüfen.
13. **Drive-by-Prüfung nach Updates:** Welche Größe zeigt, dass der Drive-by-Monitor wieder Daten bekommt,
    und wo lässt sie sich abfragen?
14. **Firmware-Update:** Formularwerte, Session-ID und Datenvolumen klären (siehe Abschnitt Firmware-Update).
15. **Drive-by-Flow:** Review mit Befunden und Empfehlungen in `docs/NODERED_DRIVEBY_REVIEW.md`. Vor allem zu
    prüfen: Kommen auf 60.0.0.49 überhaupt `stat`/`rxpk` an (Filter `JSON up 0:`)?

## Sicherheitsbefunde (nebenbei)

- Die EXE enthält die `.env` mit allen Secrets. Mit dem Launcher entfällt das.
- `services/provisioning_service.py` hat das DB-Ergebnis **inklusive WireGuard-Private-Key** ins Log
  geschrieben. **Behoben.**
- Das Gateway-Admin-Passwort steht im Klartext in `templates/index.html`. Offen.
- Die Milesight-Auto-Provisionierung ist am Gateway aktiv, schlägt aber fehl. Offen.
