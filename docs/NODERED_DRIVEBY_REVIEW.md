# Review: Node-RED-Flows auf dem UG65 (Drive-by)

Stand: 20.11.2026 · Grundlage: `91_Werkstatt/Milesight_GW_Config/20260421-ug65-node-red-flows-PROD.json`
(77 Nodes, Flow-Version „1.0“ vom 20.01.2026). Gelesen ist nur der Export. Nichts davon lief am Gerät.

## Wie der Flow heute arbeitet

**Tab `send_lora_pkg_log`, der Datenweg für die Drive-by-App:**

```
tail /etc/urlog/lora-pkt-fwd.log
 ├─ "JSON up 0:" + {"stat"   → lastStatReceived             → /lora/health
 ├─ "JSON up 0:" + {"stat"/{"rxpk" → Buffer (statusLog, 500 / 24 h) → GET /status?since=<seq>&boot_id=
 ├─ PULL_ACK (cortex-media)  → lastPullAck, Lückenpuffer     → /lora/health, /lora/gaps, /lora/gaps/graph
 └─ PUSH_ACK                 → lastPushAck (wird nirgends ausgewertet)
```

Die Drive-by-App fragt `GET /node-red/status?since=<seq>` ab. Sie bekommt dann die rohen Logzeilen mit
`{"rxpk":[...]}`.

**Tab `Configuration`:**
- `/device-info` liefert MAC, EUI, SSID und die Netz-Schnittstellen aus `ifconfig`.
- `/device-info-lora` meldet sich an der internen API an (`:8080/api/internal/login`) und liest die
  Packet-Forwarder-Server.

## Befunde

### Kritisch

1. **Der Datenweg hängt am Textformat einer Logdatei.** Pfad (`/etc/urlog/lora-pkt-fwd.log`), Präfix
   (`JSON up 0:`) und Logstufe sind keine Schnittstelle von Milesight. Ändert eine Firmware eines davon,
   kommen still keine Daten mehr an. Es gibt weder einen Fehler noch einen Alarm, `/status` liefert nur
   noch leere Listen. An dieser Stelle seid ihr schon einmal gestolpert.

2. **Möglicher Ausfall auf 60.0.0.49, am Gerät prüfen.** Beim Setup-Lauf vom 18.11. meldete
   `/lora/health` `seconds_since_stat` ≈ Unix-Zeit. `lastStatReceived` wurde also nie gesetzt, das heißt der
   Filter hat **keine einzige** `stat`-Zeile erkannt.

   **Vermutung:** Die `0` in `JSON up 0:` ist der Index des Servers im Packet Forwarder. Auf 60.0.0.49 ist
   Server 0 der eingebaute `localhost`/`ursalink`, Cortex ist Server 1.

   Damit wären nicht nur `stat`, sondern auch die **Funkpakete (`rxpk`) betroffen**, und die Drive-by-App
   bekäme von diesem Gerät nichts.

   **Prüfen:** `fleet driveby --host 192.168.1.1` und `tail` der Logdatei am Gerät. Bestätigt sich das, muss
   der Filter jeden Index akzeptieren (Regex `JSON up \d+:`), oder besser Empfehlung A umsetzen.

3. **Das Gateway-Admin-Passwort steht im Flow.** Die Funktion „set login credentials“ enthält es
   AES-„verschlüsselt“, mit dem festen Schlüssel aus der Weboberfläche des Gateways (`1111…`/`2222…`).
   Das lässt sich ohne Aufwand umkehren. Wer einen Flow-Export hat, hat also das Admin-Passwort. Ein Export
   gehört deshalb nicht ungeändert ins Repo (`gateway_profiles/flows/`). **Lösung:** Das Passwort aus einer
   Umgebungsvariablen von Node-RED oder einem Credentials-Feld lesen, oder `/device-info-lora` ersetzen
   (siehe Empfehlung C).

### Wichtig

4. **`stat` verdrängt Funkpakete im Puffer.** `stat` kommt alle 30 s, also 2.880 Einträge am Tag, und landet
   im selben Puffer wie `rxpk`. Bei `MAX_COUNT = 500` hält der Puffer damit nur rund 4 Stunden statt 24.
   Steht die Drive-by-App länger, sind Funkpakete weg, und sie bekommt nur `dropped: true`. **Fix:** nur
   `rxpk` puffern oder `stat` getrennt halten.

5. **Ein Prozess je Logzeile.** Ausgang 3 startet für jede `stat`- und `rxpk`-Zeile `exec uptime -s`. Weil
   `exec` asynchron läuft, bekommt der Puffer außerdem die Meta-Daten der **vorherigen** Zeile. **Fix:**
   `uptime` einmal beim Start lesen.

6. **Der Puffer liegt nur im Speicher.** Nach einem Neustart von Node-RED oder des Gateways ist er leer. Die
   `boot_id` meldet das zwar korrekt, Daten aus der Zeit vor dem Neustart sind aber verloren. Für Drive-by ist
   das meist in Ordnung, man sollte es nur wissen.

7. **Das Zeitfenster passt nicht zu den Intervallen.** `/lora/health` erlaubt 31 s ohne `PULL_ACK`, der
   Keepalive steht auf 10 s. `stat` muss in 65 s kommen, das Intervall ist 30 s. Das passt, ist aber fest im
   Code. Ändert sich `stat_interval` im Profil, meldet Health falsch. **Fix:** die Werte aus der
   Konfiguration lesen oder als Flow-Variable setzen.

8. **Eine Lücke erscheint erst, wenn sie vorbei ist.** `/lora/gaps` trägt eine Lücke erst ein, wenn das
   nächste `PULL_ACK` kommt. Ein gerade laufender Ausfall ist dort unsichtbar. Außerdem nennt die Antwort
   `threshold_s: 10` und `window: "last ~60 minutes"`, obwohl die Schwelle 15 s ist und der Puffer 24 h
   umfasst.

9. **Der Servername ist fest eingetragen.** Die Filter erkennen `ball-b-cs.cortex-media.de`. Ein Umzug des
   LNS ändert also auch den Flow.

### Klein

10. `/lora/gaps/graph`: In den Buttons steht `\${hours === …}` maskiert. Die Hervorhebung des aktiven
    Zeitfensters funktioniert deshalb nie. Chart.js kommt ungepinnt vom CDN.
11. `/device-info` liest MAC und SSID über die Flow-Variablen `temp_mac` und `ssid`. Bei gleichzeitigen
    Anfragen können sich die Werte mischen. Die EUI wird aus der MAC berechnet (MAC mit `FFFE` in der Mitte),
    nicht aus dem Packet Forwarder gelesen. Bisher passt das, sicher ist es aber nicht.
12. `/device-info` wertet die BusyBox-Ausgabe von `ifconfig` aus (`Link encap`, `inet addr:`). **60.0.0.50
    bringt Kernel 6.12.** Wird dabei die Userspace-Umgebung erneuert (iproute2 statt BusyBox-`ifconfig`),
    melden VPN-IP, Mobilfunk und Status falsche Werte. Darauf baut die Einrichtung und die Flotte auf.
13. Die Version steckt in einer Funktion (`flowVersion = "1.0"`), es gibt keinen Kommentar-Node. Für die
    Flotte bitte zusätzlich den Kommentar-Node `gatewaychef-flow <version>` anlegen und die Version in
    `/device-info` mit ausgeben.
14. Es gibt 14 Debug-Nodes, manche hängen an jeder Logzeile. Im Betrieb abschalten.

## Umgesetzt: Flow 1.1.0 (20.11.2026)

`gateway_profiles/flows/1.1.0.json` ist aus dem PROD-Export abgeleitet:

- **Empfehlung A umgesetzt:** Drive-by-Daten kommen per UDP vom Packet Forwarder (`udp in` :1702,
  Semtech-Protokoll mit `PUSH_ACK`/`PULL_ACK`), nicht mehr aus dem Log. Der Log-Filter `JSON up 0:` ist
  entfernt (Befunde 1 und 2).
- **`/status` bleibt unverändert.** `payload` ist das Semtech-JSON als Text. Die db_monitor-App liest es
  ohne Änderung, ihr Parser nimmt alles vom ersten `{` bis zum letzten `}`. Das ist geprüft.
- **`/lora/health`** bekommt `stat` jetzt aus dem UDP-Empfang (Befund 2 behoben). Die ACK-Erkennung für die
  Verbindung zum LNS liest weiter das Log. Eine andere Quelle für die ACKs von Cortex gibt es nicht.
- **Neu: `GET /node-red/driveby/health`:**
  - `seconds_since_stat`, `seconds_since_rxpk`,
  - Zähler und die EUI aus dem UDP-Kopf,
  - Flow-Version.

  `fleet driveby` und der Nachtest nach einem Firmware-Update nutzen diesen Endpunkt.
- **Passwort entfernt (Befund 3):** Der Flow enthält nur `{{gateway_login_password_enc}}`. GatewayChef setzt
  den Wert erst beim Deploy aus `GATEWAY_PASSWORD` ein.
- `uptime` wird nur noch beim Start gelesen (Befund 5).
- Graph-Buttons und die Angaben in `/lora/gaps` korrigiert (Befunde 8 und 10).
- `flow_version` steht in `/device-info`. Der Kommentar-Node `gatewaychef-flow 1.1.0` ist angelegt
  (Befund 13).
- Alle Debug-Nodes sind ausgeschaltet (Befund 14).
- Bewusst nicht geändert ist der Puffer (Befund 4). Die App liest live mit.

**Geprüft:** Der Code der Funktions-Nodes läuft unter Node.js gegen echte Semtech-Pakete
(`tests/nodered/flow_functions.test.js`). Dabei geprüft:
- ACK mit Token,
- PULL_ACK,
- kaputte Pakete,
- `/status` im App-Format,
- `/driveby/health`,
- `/lora/health`,
- Graph.

Ein vollständiges Node-RED lief dabei nicht.

**Ausrollen, Reihenfolge wichtig:**
1. `fleet patch driveby-udp-forward --ip <test-gw> --apply`: trägt das 3. Ziel im Packet Forwarder ein.
   Neue Gateways bekommen es über das Profil.
2. `fleet nodered --ip <test-gw> --version 1.1.0 --apply`: mit Sicherung, Hash-Vergleich, Nachtest und
   Rollback.
3. `fleet driveby --ip <test-gw> --need-rxpk` mit Testsender, danach die db_monitor-App gegen das Gateway
   laufen lassen.
4. Danach die Flotte.

**Am Gerät zu bestätigen:**
- Akzeptiert der Packet Forwarder ein drittes Ziel?
- Passen die Feldnamen von `servs` beim Schreiben?
- Bleibt der Flow-Hash nach dem Deploy gleich? Wenn Node-RED beim Speichern Felder ergänzt, meldet der
  Hash-Vergleich einen Fehler und rollt zurück. Das wäre sicher, aber unnötig.

## Empfehlungen

**A. Daten direkt vom Packet Forwarder statt aus dem Log. Umgesetzt in Flow 1.1.0.** Der Packet Forwarder des UG65
unterstützt mehrere Ziele. Das Profil zeigt schon zwei: `servs` mit `localhost/ursalink` und Cortex.

Ein drittes Ziel `semtech → 127.0.0.1:1702` schickt jedes empfangene Paket über das dokumentierte
Semtech-UDP-Protokoll an Node-RED. Dort nimmt ein `udp in` auf 1702 `PUSH_DATA` an: 12 Byte Kopf, danach das
JSON mit `rxpk` und `stat`. Ein `udp out` antwortet mit `PUSH_ACK`.

Vorteile:
- Die Daten haben **genau** das Format, das auch der LNS bekommt.
- Nichts hängt mehr an Logformat, Logstufe oder Server-Index.
- Es braucht keine Datei und keine Prozesse.

`/status` bleibt für die Drive-by-App gleich, nur die Quelle ändert sich. Umsetzung:
- ein Patch `gateway_profiles/patches/` für den dritten Server. Er berührt `yruo_loragw`, ist also nicht
  VPN-kritisch,
- ein neues Flow-Bundle,
- `fleet driveby --need-rxpk` als Abnahme.

Am Gerät zu bestätigen: Wie viele Ziele erlaubt das Gerät? Gilt der Paketfilter auch für das dritte Ziel?

**B. Eine Logzeile, eine Auswertung.** Falls das Log bleibt: einen Parser-Node mit Regex `JSON up \d+: (\{.*\})`
und `JSON.parse` verwenden, danach nach `stat`/`rxpk` verzweigen. Ein Zähler „Zeilen ohne Treffer seit X min“
geht in `/lora/health` ein. So fällt ein geändertes Format sofort auf und nicht erst in der Drive-by-App.

**C. Gateway-Infos aus der API statt aus Shell-Ausgaben.** `/device-info` sollte EUI, VPN-IP und Mobilfunk
aus der internen API lesen (`:8080/api/...`, wie `/device-info-lora` es schon tut) oder aus `ip -j addr`,
und nicht aus der Textausgabe von `ifconfig`. Das Passwort dafür kommt dann aus einem Credentials-Feld
(Befund 3).

**D. Versionieren und ausrollen über GatewayChef.**
1. Den bereinigten Flow (ohne Passwort, mit Kommentar-Node) als `gateway_profiles/flows/1.1.0.json`
   ablegen.
2. Ausrollen mit `fleet nodered --apply`, mit Nachtest und Rollback.

## Neue Firmware: Was prüfen wir automatisch?

Neu in GatewayChef ist `checks.check_driveby`. Es prüft den ganzen Datenweg vom Packet Forwarder über das Log
und Node-RED bis zum `/status`-Puffer und wartet dabei nur auf **neue** Einträge:

| Stufe | Voraussetzung | Aussage |
|---|---|---|
| `stat` kommt an | keine, alle 30 s | Logpfad, Format und Filter funktionieren |
| `rxpk` kommt an | LoRa-Gerät sendet in der Nähe | Funkpakete erreichen die Drive-by-Schnittstelle |

Die Prüfung läuft an drei Stellen:
- in der Einrichtung, Schritt „Netz & VPN“:
  - kein `stat` → `FEHL`,
  - nur `stat` → `WARN` mit dem Hinweis auf den Testsender,
- im Nachtest jedes Firmware-Updates (`fleet firmware`),
- von Hand mit `fleet driveby --ip <vpn-ip> --need-rxpk`, zum Beispiel an der Station mit Testsender.

**Testsender an der Station:** ein beliebiges LoRaWAN-Gerät mit kurzem Sendeintervall, zum Beispiel ein
eigener Sensor im Testmodus. Es muss bei keinem LNS angemeldet sein, denn der Forwarder loggt auch Pakete
fremder Geräte. Damit wird `--need-rxpk` bei jeder Freigabe einer neuen Firmware zur Pflicht.

## Firmware-Lage bei Milesight (Stand 20.11.2026)

- **Neueste Version 60.0.0.50**, laut Release Notes vom 12.08.2026:
  - Kernel 6.12 LTS,
  - Upgrade nur ab 60.0.0.45 oder neuer,
  - Downgrade nur mit aktivierter Reset-Funktion,
  - das alte Python-SDK entfällt (neues SDK v2.0.1),
  - der Everynet-Packet-Forwarder entfällt.

  Zu Node-RED oder zum Packet-Forwarder-Log steht dort nichts, das muss am Gerät geprüft werden. Wegen des
  neuen Kernels sind Befund 12 und der Drive-by-Test hier besonders wichtig.
- **60.0.0.49-r2**, laut Release Notes vom 16.07.2026: Hinweise in der Packet-Forwarder-Konfiguration, und
  Basic Station zeigt das Weiterleitungsziel an. Dazu ein Fix für den SMS-Versand aus Node-RED. Bei uns läuft
  60.0.0.49 ohne `-r2`. Laut einem Fremdprojekt auf GitHub gibt es auch ein `-r3`.
- Node-RED wurde zuletzt in 60.0.0.42 auf 3.0.2 gebracht. Eine neuere Fassung für den UG65 ist nicht
  genannt.
- Nicht gefunden habe ich eine offizielle Schnittstelle für rohe Funkpakete in Node-RED. Laut Milesight-FAQ
  soll so etwas über Node-RED gelöst werden, und genau das tut Empfehlung A mit dem dokumentierten
  Semtech-Protokoll.

**Vorgehen für 60.0.0.50:**
1. Ein Test-Gateway an der Station mit Testsender betreiben.
2. `fleet firmware --version 60.0.0.50 --host 192.168.1.1 --apply`. Der Nachtest umfasst Schnittstelle,
   Flows und Drive-by.
3. `fleet driveby --host 192.168.1.1 --need-rxpk`.
4. `/device-info` von Hand prüfen (Befund 12).
5. Erst danach einzelne Gateways im Feld aktualisieren.

Quellen: [Milesight Release Notes](https://www.milesight.com/iot/resources/download/release-note/),
[Milesight Firmware-Download](https://www.milesight.com/support/resources/firmware),
[ChirpStack: Milesight-Gateway, Multi-Destination](https://chirpstack.io/docs/gateway-configuration/milesight.html),
[UG65 cloudflared (Firmware-Revisionen)](https://github.com/fmk24000/milesight-ug65-cloudflared).

## LNS-Reihenfolge: Node-RED zuerst (22.11.2026)

Bisher war Ziel 1 der interne LNS (`ursalink`, localhost). Er war nur an, damit der Forwarder immer ein
antwortendes Ziel hat und sein Log weiterschreibt, auch wenn der Cloud-LNS weg ist. Seit Flow 1.1.1
bestätigt Node-RED `PUSH_DATA` und `PULL_DATA` selbst, und zwar vom Port 1702. Vorher ging die Antwort
von einem Zufallsport weg und der Forwarder verwarf sie: `connected 0`, `ackr 0.0`.

Neue Reihenfolge (Patch `lns-nodered-first`, in den Profilen 60.0.0.49 und 60.0.0.50):
1. `127.0.0.1:1702` semtech (Node-RED, Drive-by-Datenweg)
2. `ball-b-cs.cortex-media.de:1700` semtech (Cloud-LNS)
3. interner LNS `ursalink`: aus

Getestet an JK_Test (60.0.0.50): Ziel 1 und 2 `connected 1`, `ackr 100`, Empfang läuft weiter,
`/lora/health` ONLINE (Cortex-ACK 6 s alt).
Reihenfolge beim Ausrollen: erst Flow 1.1.1, dann der Patch.

> **Stand 24.11.2026:** Standard für die LNS-Ziele ist wieder **driveby-udp-forward** (interner LNS, Cortex,
> Node-RED 127.0.0.1:1702 als drittes Ziel) — in den Profilen, beim Einrichten und beim „Auf Standard bringen“.
> `lns-nodered-first` bleibt als Patch, schreiben dürfen ihn nur Admins (`OIDC_ADMIN_GROUP`).
