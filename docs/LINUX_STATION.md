# Linux-Station: Einrichtung und Flotte

Ein Linux-Rechner (Mini-PC oder Raspberry Pi 5, Debian/Ubuntu) übernimmt zwei Aufgaben:

1. **Einrichtung:** Ein neues Gateway hängt per Ethernet-Kabel direkt an der Station, ohne Switch.
2. **Flotte:** Über das VPN sieht die Station alle Gateways. Sie zeigt den Status, schreibt Parameter und
   aktualisiert Node-RED (`/fleet`).

## Hardware

- Linux-Rechner mit **zwei Netzanschlüssen**: einer fürs Büronetz/Internet (LAN oder WLAN), einer fürs
  Gateway. Bei nur einer Buchse kommt ein USB-Ethernet-Adapter (rund 15 €) als Gateway-Port dazu.
- PoE-Injektor fürs UG65, falls es nicht über das Netzteil versorgt wird.

## Installation

```bash
git clone https://github.com/ball-b-lab/gatewayChef.git /tmp/gc
sudo bash /tmp/gc/scripts/linux/install.sh --gw-port <interface>   # z. B. enx00e04c680001, siehe `ip link`
```

Das Skript:
- installiert `git`, `wireguard-tools` und `uv` und legt den Systembenutzer `gatewaychef` an,
- holt den Code nach `/opt/gatewaychef/app`,
- legt `/etc/gatewaychef/env` an (Rechte 640, wird nie überschrieben),
- gibt dem Gateway-Port **192.168.1.200/24 und 192.168.23.200/24**, ohne Default-Route und ohne DNS. So ist
  das Gateway unter beiden möglichen Werksadressen erreichbar, und der Internetverkehr läuft weiter über
  den anderen Port,
- startet auf dem Gateway-Port einen **DHCP-Server** (`gatewaychef-dhcp@<port>`, dnsmasq, Bereich
  192.168.77.100–150 auf eigenem Netz 192.168.77.0/24, mit der Station als Router und NAT ins Internet, weil das UG65 ein Angebot ohne Router
  ablehnt und eth0 dann zur Hauptverbindung macht; 192.168.1.0/24 geht nicht, das nutzt das
  UG65 intern selbst und lehnt die Adresse ab). Eingerichtete Gateways haben `eth0` auf DHCP und holen sich dort
  eine Adresse, neue Gateways bleiben unter ihrer festen Werks-IP erreichbar,
- richtet `gatewaychef.service` ein (Weboberfläche auf Port 5000). Bei jedem Start holt der Dienst `main`
  (`GATEWAYCHEF_REF` im Unit-File), Release heißt also Merge auf `main` und Neustart.

Danach:
1. `/etc/gatewaychef/env` ausfüllen: Cloud-API (`DB_API_PROVIDER_URL`, `API_SERVICE_TOKEN`),
   `GATEWAY_PASSWORD`, `GATEWAY_WIFI_KEY`, `FIRMWARE_DIR` (z. B. `/opt/gatewaychef/firmware`), Milesight und Webservice. `VPN_SERVER_PUBLIC_KEY` bleibt leer,
   den liefert die Cloud.
2. **VPN für die Flotte:** Die Station ist ein Workstation-Peer im Bereich `172.30.100.0/24`, also nicht im
   Gateway-Pool. Die Konfiguration nach `/etc/wireguard/ballb.conf` legen, mit
   `AllowedIPs = 172.30.0.0/16` (nur VPN-Verkehr durch den Tunnel). Dann
   `systemctl enable --now wg-quick@ballb`.
3. `systemctl restart gatewaychef`

## Ein Gateway einrichten (ohne Switch)

Gateway an den Gateway-Port stecken und warten, bis es hochgefahren ist (rund 2 Minuten). Dann:

```bash
sudo -H -u gatewaychef gatewaychef setup                     # Dry-Run
sudo -H -u gatewaychef gatewaychef setup --new --apply --client-id 10999 --iccid 8949... --sim-vendor-id 2
```

Das Setup (und die Weboberfläche) sucht das Gateway automatisch (`utils/gateway_lan.py`): zuerst die neuesten
DHCP-Leases der Station (`/var/lib/gatewaychef/dhcp-lan.leases`, je Station-Port `dhcp-gcp<N>.leases`), dann
`GATEWAY_LAN_CANDIDATES` (Standard `192.168.1.1,192.168.23.150`). Genommen wird die erste Adresse, deren
Node-RED `/device-info` antwortet. „Gateway Login“ und „Copy & Open“ zeigen dann auf diese Adresse. Danach das Gateway abziehen und das nächste anstecken.

**Am Gerät zu prüfen:** welche Werksadresse der Ethernet-Port des UG65 hat und ob er per DHCP eine Adresse
holt. Bisher lief alles über `192.168.1.1`. Mit einem VLAN-Switch für mehrere Gateways gleichzeitig wird
die Station später erweitert (siehe `GATEWAY_SETUP_KONZEPT.md`).

## Mehrere Gateways gleichzeitig (`/station`)

Alle UG65 kommen mit derselben festen Werks-IP und ohne DHCP. Im selben Netz würden sie sich gegenseitig
stören. Deshalb bekommt jeder Einrichtungs-Port ein eigenes Linux-Network-Namespace (`gcp<N>`). Darin sieht
die Station genau ein Gateway unter seiner Werks-IP. Cloud-API, Milesight und VPN laufen per veth und NAT
über den Host (`scripts/linux/ports.sh`, Dienst `gatewaychef-ports`).

**Aufbau, zwei Varianten:**
- **USB-Ethernet-Adapter je Gateway** (rund 15 € pro Stück, am besten an einem aktiven USB-Hub).
  `/etc/gatewaychef/ports`: `1 enx00e04c680001`, `2 enx00e04c680002`, …
- **VLAN-Switch** (Port-VLAN, z. B. Netgear GS308E): Jeder Switch-Port ist ein eigenes untagged VLAN, der
  Uplink zur Station ist getaggt. `/etc/gatewaychef/ports`: `1 enp2s0 11`, `2 enp2s0 12`, …

Danach `systemctl restart gatewaychef-ports` und `sudo /opt/gatewaychef/app/scripts/linux/ports.sh list`:
Das zeigt je Port, ob ein Gateway antwortet.

**Bedienung:** `http://<station>:5000/station`  (auf einer Station mit Ports leitet `/` automatisch dorthin, die alte
Einzel-Einrichtung mit Copy & Paste entfällt; Aussehen wie die Cloud-App `/fleet`)
- Steht die EUI des erkannten Gateways in der Datenbank, zeigt die Karte Name, VPN-IP, Seriennummer, ICCID, SIM,
  Kunde und DB-Status und füllt die Felder damit vor (Kunden-Nr. und -name aus dem Namen `<x.y> <Nr> - <Kunde>`).
  Unbekannte Gateways sind als „neu“ markiert, „neues Gateway (VPN-IP aus dem Pool)“ ist dann vorausgewählt.
- Eine Karte je Port: erkanntes Gateway (EUI), Felder für Kunden-Nr., SIM-Anbieter, ICCID und Name, dazu
  „neues Gateway“. Die Knöpfe heißen Dry-Run, Einrichten und Prüfen. Die Läufe der Ports laufen parallel,
  die VPN-IP wird in der DB atomar reserviert.
- **Vorgänge:** alle laufenden und fertigen Einrichtungen sowie Flotten-Updates (Node-RED, Firmware, Patch)
  mit Stand (letzter Schritt), Dauer und Ergebnis. Ein Klick zeigt das Protokoll, damit man von Hand
  nacharbeiten kann. Die Protokolle der Einrichtungen liegen zusätzlich in `/var/log/gatewaychef/`.
- Die Liste lebt im Speicher des Dienstes: Ein Neustart leert sie, die Protokolldateien bleiben.

Technik: Die Weboberfläche startet `sudo -n /usr/local/sbin/gatewaychef-port <N> setup --live …`. Der Helfer
erlaubt nur `setup` und `probe` und läuft im Namespace als Benutzer `gatewaychef` (sudoers-Regel aus
`install.sh`).

## Flotte

Weboberfläche `http://<station>:5000/fleet` oder Kommandozeile:

```bash
gatewaychef fleet status                       # alle vergebenen Gateways: über VPN erreichbar? richtige EUI?
gatewaychef fleet status --deep                # zusätzlich Firmware, WLAN-Region, Node-RED-Flow-Version
gatewaychef fleet patch wifi-country-de --ip 172.30.0.116            # prüfen
gatewaychef fleet patch wifi-country-de --all --apply                # schreiben
gatewaychef fleet nodered --all                                      # welche Gateways brauchen ein Update?
gatewaychef fleet nodered --ip 172.30.0.116 --apply                  # aktualisieren, mit Nachtest
gatewaychef fleet firmware --version 60.0.0.49 --host 192.168.1.1   # Firmware an der Station (LAN)
gatewaychef fleet firmware --version 60.0.0.49 --ip 172.30.0.116 --apply  # über VPN, mit Nachtest
gatewaychef fleet profile-check --host 192.168.1.1                   # neue Firmware: Entwurf eines Profils
gatewaychef fleet qualify --host 192.168.1.1 --approve              # neue Firmware ab Werk: pruefen + Profil freigeben
```

Wie die Flotte arbeitet, steht in `GATEWAY_SETUP_KONZEPT.md`, Abschnitt „Flotte“.

## Fehlersuche

- `journalctl -u gatewaychef -f`: Log der Weboberfläche.
- `ip addr show <gw-port>` muss `192.168.1.200` und `192.168.23.200` zeigen.
- `cat /var/lib/gatewaychef/dhcp-lan.leases`: hat sich ein Gateway per DHCP eine Adresse geholt?
  `journalctl -u gatewaychef-dhcp@<gw-port>` zeigt die DHCP-Anfragen.
- `wg show`: Handshake zum VPN-Server vorhanden?
- `GATEWAYCHEF_OFFLINE=1 gatewaychef ...`: startet ohne Code-Update.

Die Installation ist bisher nur auf Syntax geprüft. Ein Lauf auf einem echten Linux-Rechner steht noch aus.

## Monitoring auf `/fleet`

Ab Flow 1.1.0 zeigt die Flottenseite pro Gateway zusätzlich:
- **Flow:** aktive Flow-Version (`alt (< 1.1)`, wenn das Gateway noch keinen `/driveby/health` hat).
- **Empfang:** Alter der letzten Packet-Forwarder-Statistik und des letzten Funkpakets, grün bei stat < 65 s.
- **dbmonitor zuletzt:** wann die Drive-by-App zuletzt `/status` abgeholt hat (Tooltip: Zeit, Client-IP, Anzahl Abrufe). Fett grün bei < 5 min.

Die Häkchen-Option „alle 30 s“ lädt den Schnellstatus automatisch neu. Kommandozeile: `gatewaychef fleet status` und `gatewaychef fleet driveby`.
