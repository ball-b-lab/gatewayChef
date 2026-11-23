# UG65 Parameter-Review (Stand 2026-11-23, Referenz JK_Test 172.30.0.116, FW 60.0.0.50)

Live gelesen per CGI (nur lesend). Bewertung gegen unsere Anwendung: Klasse-A-Sensoren, EU868,
Cortex-ChirpStack, Drive-by per WLAN, Fernwartung über WireGuard, Anbindung per LTE (Tele2 IoT).

| Bereich | Ist | Bewertung |
|---|---|---|
| Frequenzplan (`yruo_loragw/radios`) | EU868, 8 Kanäle 867.1–868.5, LoRa-Std 868.3, FSK 868.8 | ✓ passt zu ChirpStack EU868 |
| CRC-Weitergabe (`advanced`) | nur gültige CRC weiterleiten | ✓ |
| Beacon / LBT | aus | ✓ (Klasse A, EU braucht kein LBT) |
| `full_duplex` | `true` | ? UG65 sendet nur halbduplex; Wert scheint wirkungslos, beobachten |
| Keepalive / Stat | 10 s / 30 s | ✓; Keepalive 30 s würde LTE-Daten sparen, bringt aber langsamere Downlink-Wiederherstellung |
| Forwarder-Ziele | Node-RED 127.0.0.1:1702, Cortex 1700, intern aus | ✓ Standard |
| Mobilfunk | APN `wsim`, Roaming an, keine Auth | ✓ (Tele2 IoT braucht Roaming) |
| SIM2-Profile | aktiviert, leer | egal (keine SIM2) |
| WireGuard | Endpoint 88.99.172.109, Keepalive 25, AllowedIPs 172.30.0.0/20 | ✓ |
| WLAN | AP, WPA2, Region DE, 192.168.1.1/24 | ✓ |
| Zeit | Europe/Berlin, NTP pool.ntp.org + 0.de.pool | ✓ |
| SSH / Telnet | aus | ✓ |
| Weboberfläche | HTTP **und** HTTPS mit `*_remote = 1` (auch über Mobilfunk-WAN) | ⚠ hinter Provider-NAT kaum erreichbar, trotzdem unnötig offen. Abschalten erst testen: Zugriff über wg0 darf nicht wegfallen |
| Watchdog (Ping-Erkennung / geplanter Neustart) | nicht per CGI auffindbar | ⚠ für hängendes Mobilfunkmodem wichtig; in der Weboberfläche prüfen |
| SIM-Datenverbrauch | 494 MiB (Zähler des Modems, Zeitraum unklar) | beobachten; Kandidaten: Keepalives, Node-RED, Statistik |

Folge-Kandidaten für das Profil: Web-Remote-Zugriff auf HTTPS-only/VPN begrenzen, Watchdog standardisieren.
