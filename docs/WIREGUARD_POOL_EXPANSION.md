# WireGuard Pool erweitern

Dieses Repo kann neue VPN-IPs fuer `gateway_inventory` und passende WireGuard-Server-Peers aus einem oder mehreren IP-Bereichen generieren. Dabei werden Profile fuer `gateway` und `workstation` unterschieden.

## Voraussetzungen

- `wg` CLI ist installiert und im `PATH` verfuegbar.
- Der Zielbereich ist im WireGuard-Server-Routing vorgesehen.

## Empfohlene Netztrennung

- `172.30.1.0/24`, `172.30.2.0/24`, ... fuer Gateways
- `172.30.100.0/24` fuer Rechner, Admin-Notebooks, Support-Clients

Der wichtige Unterschied:

- `gateway`-Profile werden in `gateway_inventory.sql` aufgenommen
- `workstation`-Profile werden **nicht** in `gateway_inventory` aufgenommen

Damit bleibt `172.30.100.0/24` auf dem WireGuard-Server reserviert und GatewayChef kann diesen Bereich nie als freie Gateway-IP vergeben.

## Beispiel

```bash
python3 scripts/generate_wireguard_inventory.py \
  --profile-range gateway:172.30.1.1-172.30.1.254 \
  --profile-range gateway:172.30.2.1-172.30.2.254 \
  --profile-range workstation:172.30.100.1-172.30.100.50 \
  --output-dir ./out/wg-expansion \
  --skip-existing
```

Standardmaessig erzeugt das Script Peer-Bloecke passend zu deiner bestehenden Struktur:

```ini
[Peer]
# ug65_134
# profile: gateway
PublicKey = ...
AllowedIPs = 172.30.1.134/32, 192.168.1.0/24
PersistentKeepalive = 25
```

Das `workstation`-Profil erzeugt standardmaessig:

```ini
[Peer]
# ws_10
# profile: workstation
PublicKey = ...
AllowedIPs = 172.30.100.10/32
PersistentKeepalive = 25
```

Erzeugt:

- `gateway_inventory.sql`: `INSERT`s fuer `gateway_inventory`
- `wg0_extension.conf`: gemeinsame `[Peer]`-Bloecke fuer deine bestehende `wg0.conf`
- `peer_inventory.csv`: Audit-Datei mit Profil, VPN-IP, SSID, Private/Public Key

## Ablauf

1. Bereich generieren.
2. `peer_inventory.csv` direkt in GatewayChef hochladen oder alternativ `gateway_inventory.sql` importieren.
3. `wg0_extension.conf` in die Server-Konfiguration uebernehmen.
4. WireGuard auf dem Server sauber neu laden.

Host-Import ohne `psql`:

```bash
python3 scripts/import_gateway_inventory_sql.py \
  --sql-file ./out/wg-expansion/gateway_inventory.sql
```

Bevorzugt in GatewayChef:

- Im Bereich `VPN Pool Import` die generierte `peer_inventory.csv` auswaehlen
- `CSV importieren` klicken
- GatewayChef legt nur `gateway`-Profile in `gateway_inventory` an

## Hinweise

- Die App nutzt freie Eintraege aus `gateway_inventory` mit `status_overall='FREE'`.
- `workstation`-Bereiche werden absichtlich nicht in `gateway_inventory.sql` aufgenommen.
- `wifi_ssid` wird passend zur bestehenden App-Logik als `bbdbmon_<octet3>.<octet4>` erzeugt.
- Die Ausgaben enthalten Private Keys und muessen entsprechend geschuetzt behandelt werden.
