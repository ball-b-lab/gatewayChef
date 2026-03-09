# WireGuard bestehende Config erweitern

Wenn deine `peers`-Tabelle leer ist, ist das in diesem Setup kein Problem: die App liest **nicht** aus einer separaten WireGuard-Peers-Tabelle, sondern aus `gateway_inventory`.

Die WireGuard-Server-Seite musst du deshalb direkt ueber die bestehende Konfigurationsdatei pflegen, typischerweise `wg0.conf`.

## Ausgangspunkt

Der Generator

```bash
python3 scripts/generate_wireguard_inventory.py \
  --start-ip 172.30.1.1 \
  --end-ip 172.30.1.254 \
  --output-dir ./out/wg-172.30.1 \
  --skip-existing
```

erzeugt:

- `gateway_inventory.sql`
- `wireguard_peers.conf`
- `peer_inventory.csv`

Dabei ist `wireguard_peers.conf` genau die Datei, die du in die bestehende WireGuard-Server-Konfiguration uebernimmst.

## Was in welche Datei kommt

- `gateway_inventory.sql`
  Import in PostgreSQL. Dadurch kennt GatewayChef die neuen freien VPN-IPs.
- `wireguard_peers.conf`
  Enthae lt nur neue `[Peer]`-Bloecke fuer den WireGuard-Server.
- `peer_inventory.csv`
  Nur fuer Audit, Nachvollziehbarkeit und Notfall-Restore.

## Empfohlener sicherer Ablauf

### 1. Backup der aktuellen WireGuard-Konfiguration

Auf dem WG-Server:

```bash
sudo cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.bak-$(date +%Y%m%d-%H%M%S)
```

### 2. Neue Peer-Bloecke auf den Server kopieren

Beispiel:

```bash
scp ./out/wg-172.30.1/wireguard_peers.conf user@wg-server:/tmp/wireguard_peers.conf
```

### 3. Peer-Bloecke in die bestehende `wg0.conf` einhaengen

Am einfachsten: ans Ende der Datei anhaengen.

```bash
sudo sh -c 'cat /tmp/wireguard_peers.conf >> /etc/wireguard/wg0.conf'
```

Wichtig:

- Nichts im bestehenden `[Interface]`-Block aendern, wenn nur neue Gateways dazukommen.
- Jeder neue Peer braucht genau:
  - `PublicKey = ...`
  - `AllowedIPs = <vpn_ip>/32`

## 4. Vor dem Reload pruefen

```bash
sudo wg-quick strip /etc/wireguard/wg0.conf >/dev/null
```

Wenn der Befehl ohne Fehler durchlaeuft, ist die Syntax der Konfiguration plausibel.

## 5. WireGuard neu laden

Robust und ohne kompletten Interface-Neuaufbau:

```bash
sudo wg syncconf wg0 <(sudo wg-quick strip /etc/wireguard/wg0.conf)
```

Falls Process Substitution in deiner Shell unbequem ist, alternativ:

```bash
sudo systemctl restart wg-quick@wg0
```

`syncconf` ist fuer laufende Systeme meist die bessere Variante.

## 6. Ergebnis pruefen

```bash
sudo wg show wg0
```

Pruefe:

- die neuen Public Keys sind sichtbar
- die neuen `AllowedIPs` sind sichtbar

Optional gezielt:

```bash
sudo wg show wg0 allowed-ips
```

## 7. Neue IPs in die Datenbank importieren

Beispiel:

```bash
psql "$DATABASE_URL" -f ./out/wg-172.30.1/gateway_inventory.sql
```

Danach kann GatewayChef diese Adressen als `FREE` reservieren.

## Reihenfolge

Am sichersten ist diese Reihenfolge:

1. Peer-Bloecke auf dem WireGuard-Server einspielen
2. Funktion mit `wg show` pruefen
3. SQL in `gateway_inventory` importieren
4. Erst dann neue Gateways provisionieren

So vermeidest du, dass die App IPs ausgibt, die der WireGuard-Server noch nicht kennt.

## Typische Fehler

### Duplicate `AllowedIPs`

Wenn dieselbe `vpn_ip/32` schon in `wg0.conf` existiert, entsteht Konflikt oder unklare Zuordnung.

Pruefen:

```bash
sudo rg -n "172\\.30\\.1\\." /etc/wireguard/wg0.conf
```

### Falsche Datei importiert

`gateway_inventory.sql` gehoert in PostgreSQL.

`wireguard_peers.conf` gehoert in die WireGuard-Server-Konfiguration.

Nicht verwechseln.

### IP ist in DB, aber nicht im Tunnel

Dann wurde SQL importiert, aber `wg0.conf` noch nicht erweitert oder nicht neu geladen.

## Fuer spaeter noch robuster

Wenn du das regelmaessig machst, ist die saubere Betriebsform:

- `/etc/wireguard/wg0.conf` enthaelt nur `[Interface]`
- alle Peers liegen in einer separaten Datei wie `/etc/wireguard/wg0.peers.conf`
- bei Aenderungen baust du daraus die endgueltige `wg0.conf`

Dieses Repo erzeugt bereits den dafuer passenden Peer-Block-Teil mit `wireguard_peers.conf`.
