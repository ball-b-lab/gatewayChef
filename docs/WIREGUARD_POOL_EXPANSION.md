# WireGuard Pool erweitern

Dieses Repo kann neue VPN-IPs fuer `gateway_inventory` und passende WireGuard-Server-Peers aus einem IP-Bereich generieren.

## Voraussetzungen

- `wg` CLI ist installiert und im `PATH` verfuegbar.
- Der Zielbereich ist im WireGuard-Server-Routing vorgesehen.

## Beispiel

```bash
python3 scripts/generate_wireguard_inventory.py \
  --start-ip 172.30.1.1 \
  --end-ip 172.30.1.254 \
  --output-dir ./out/wg-172.30.1 \
  --skip-existing
```

Erzeugt:

- `gateway_inventory.sql`: `INSERT`s fuer `gateway_inventory`
- `wireguard_peers.conf`: `[Peer]`-Bloecke fuer den WG-Server
- `peer_inventory.csv`: Audit-Datei mit VPN-IP, SSID, Private/Public Key

## Ablauf

1. Bereich generieren.
2. `gateway_inventory.sql` in PostgreSQL importieren.
3. `wireguard_peers.conf` in die Server-Konfiguration uebernehmen.
4. WireGuard auf dem Server sauber neu laden.

## Hinweise

- Die App nutzt freie Eintraege aus `gateway_inventory` mit `status_overall='FREE'`.
- `wifi_ssid` wird passend zur bestehenden App-Logik als `bbdbmon_<octet3>.<octet4>` erzeugt.
- Die Ausgaben enthalten Private Keys und muessen entsprechend geschuetzt behandelt werden.
