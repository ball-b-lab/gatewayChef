# WireGuard bestehende Config erweitern

Wenn deine `peers`-Tabelle leer ist, ist das in diesem Setup kein Problem: die App liest **nicht** aus einer separaten WireGuard-Peers-Tabelle, sondern aus `gateway_inventory`.

Die WireGuard-Server-Seite musst du deshalb direkt ueber die bestehende Konfigurationsdatei pflegen, typischerweise `wg0.conf`.

## Ausgangspunkt

Der Generator

```bash
python3 scripts/generate_wireguard_inventory.py \
  --profile-range gateway:172.30.1.1-172.30.1.254 \
  --profile-range gateway:172.30.2.1-172.30.2.254 \
  --profile-range workstation:172.30.100.1-172.30.100.50 \
  --output-dir ./out/wg-expansion \
  --skip-existing
```

erzeugt:

- `gateway_inventory.sql`
- `wg0_extension.conf`
- `peer_inventory.csv`

Dabei ist `wg0_extension.conf` genau die Datei, die du in die bestehende WireGuard-Server-Konfiguration uebernimmst.

Wichtig:

- `gateway`-Profile landen in `gateway_inventory.sql`
- `workstation`-Profile landen nur in `wg0_extension.conf` und `peer_inventory.csv`

So kannst du z. B. `172.30.100.0/24` auf dem WG-Server freihalten, ohne dass GatewayChef daraus Gateway-Adressen vergibt.

## Was in welche Datei kommt

- `gateway_inventory.sql`
  Import in PostgreSQL. Dadurch kennt GatewayChef die neuen freien Gateway-VPN-IPs.
- `wg0_extension.conf`
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
scp ./out/wg-expansion/wg0_extension.conf user@wg-server:/tmp/wg0_extension.conf
```

### 3. Peer-Bloecke in die bestehende `wg0.conf` einhaengen

Am einfachsten: ans Ende der Datei anhaengen.

```bash
sudo sh -c 'cat /tmp/wg0_extension.conf >> /etc/wireguard/wg0.conf'
```

Wichtig:

- Nichts im bestehenden `[Interface]`-Block aendern, wenn nur neue Gateways dazukommen.
- Jeder neue Peer braucht genau:
  - `PublicKey = ...`
  - `AllowedIPs = <vpn_ip>/32, 192.168.1.0/24`
  - `PersistentKeepalive = 25`

Das Generatorskript erzeugt dieses Format jetzt standardmaessig passend zu deiner aktuellen `wg0.conf`.

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
python3 scripts/import_gateway_inventory_sql.py \
  --sql-file ./out/wg-expansion/gateway_inventory.sql
```

Danach kann GatewayChef diese Adressen als `FREE` reservieren.

Sauberer im Tagesbetrieb:

- In GatewayChef im Bereich `VPN Pool Import` die generierte `peer_inventory.csv` hochladen
- Der Import-Endpunkt legt nur `gateway`-Profile in `gateway_inventory` an
- `workstation`-Profile bleiben bewusst nur in der WireGuard-Konfiguration

Das Script nutzt dieselbe DB-Konfiguration wie die App:

- `DATABASE_URL=postgresql://...`
- oder `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`

Vorab testen ohne Import:

```bash
python3 scripts/import_gateway_inventory_sql.py \
  --sql-file ./out/wg-expansion/gateway_inventory.sql \
  --dry-run
```

## Reihenfolge

Am sichersten ist diese Reihenfolge:

1. Peer-Bloecke auf dem WireGuard-Server einspielen
2. Funktion mit `wg show` pruefen
3. SQL in `gateway_inventory` importieren
4. Erst dann neue Gateways provisionieren

So vermeidest du, dass die App IPs ausgibt, die der WireGuard-Server noch nicht kennt.

Hinweis:

Wenn `gateway_inventory.sql` nur einen Kommentar enthaelt statt `INSERT`s, hast du nur `workstation`-Bereiche erzeugt. Das ist korrekt.

## Typische Fehler

### Duplicate `AllowedIPs`

Wenn dieselbe `vpn_ip/32` schon in `wg0.conf` existiert, entsteht Konflikt oder unklare Zuordnung.

Pruefen:

```bash
sudo rg -n "172\\.30\\.1\\." /etc/wireguard/wg0.conf
```

### Falsche Datei importiert

`gateway_inventory.sql` gehoert in PostgreSQL.

`wg0_extension.conf` gehoert in die WireGuard-Server-Konfiguration.

Nicht verwechseln.

### IP ist in DB, aber nicht im Tunnel

Dann wurde SQL importiert, aber `wg0.conf` noch nicht erweitert oder nicht neu geladen.

## Fuer spaeter noch robuster

Wenn du das regelmaessig machst, ist die saubere Betriebsform:

- `/etc/wireguard/wg0.conf` enthaelt nur `[Interface]`
- alle Peers liegen in einer separaten Datei wie `/etc/wireguard/wg0.peers.conf`
- bei Aenderungen baust du daraus die endgueltige `wg0.conf`

Dieses Repo erzeugt bereits den dafuer passenden Peer-Block-Teil mit `wg0_extension.conf`.
