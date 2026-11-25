# Release Baseline

Stand: 2026-03-10

## Release Source

- Deploy branch: `main`
- Coolify should track `main`
- Feature branches may exist temporarily, but only merged `main` is release baseline

## Supported Runtime

- Main Flask UI under `/`
- Cloud DB/API mode via `APP_MODE=cloud_api`
- Local runner mode via `APP_MODE=local`
- WireGuard inventory generation and CSV import are part of the supported baseline

## Explicitly Removed

- `gatewaychef_v2`
- parallel v2 migrations, v2 UI, v2 API and v2 docs

## Release Checks

1. `python3 -m unittest tests.test_provisioning_service tests.test_db_table_view tests.test_gateway_inventory_import_route`
2. `python3 -m py_compile app.py routes/db.py services/provisioning_service.py scripts/generate_wireguard_inventory.py`
3. Verify `GET /api/version`
4. Verify cloud table loads and VPN pool CSV import route responds

## Windows Packaging

- Primary build entry: `build_windows.ps1`
- Pull + build helper: `build_windows_pull.ps1`
- PyInstaller spec: `gatewaychef.spec`
- Expected output: `dist/GatewayChef/GatewayChef.exe`
- Windows operator note: see `README_WINDOWS.md`
- Die Spec packt `gateway_profiles/` und die Setup-Module (`services`, `utils`, `scripts.gateway_setup`, `scripts.gateway_probe`) mit ein, weil `/station` im WLAN-Modus das Setup in-process startet.

## Windows Launcher (Nachfolger der EXE)

- `scripts/windows/gatewaychef.cmd` + `gatewaychef.ps1`: installiert `uv`, holt `main` (oder einen Tag via `-Ref`)
  nach `%LOCALAPPDATA%\GatewayChef\app`, startet UI oder `setup`-CLI.
- `.env` liegt in `%LOCALAPPDATA%\GatewayChef\.env` (ausserhalb des Codes, `GATEWAYCHEF_ENV_FILE`).
- Release = Merge auf `main`; optional Tag `vJJJJ.MM.TT` zum Festhalten. Kein Build-Schritt.
- Die EXE (`build_windows.ps1`, `gatewaychef.spec`) bleibt bis zur Abloesung lauffaehig, wird aber nicht mehr weiterentwickelt.
- Release-Check zusaetzlich: `python3 -m unittest tests.test_gateway_config tests.test_gateway_setup`

## Linux-Station

Die Station holt `main` bei jedem Dienststart (`systemctl restart gatewaychef`). Ein Release ist also Merge
auf `main` und danach ein Neustart auf der Station. Für einen festen Stand `GATEWAYCHEF_REF=<tag>` im
Unit-File setzen.

- 24.11.2026: alte Einrichtungsseite unter `/einrichtung`; `/` → `/fleet` (außer Windows-App, siehe DEPLOYMENT.md).

## Code-Stand oben auf jeder Seite

Jede Seite zeigt oben „Stand <commit> · <zeit>“ (`/api/version`). Station/Mac: Commit und Commit-Zeit aus git.
Cloud (Docker): der Build schreibt `.build_commit` (Build-Arg `SOURCE_COMMIT`, setzt Coolify) und `.build_time`;
ohne `SOURCE_COMMIT` steht dort nur die Build-Zeit. Im Tooltip steht zusätzlich, wann die App gestartet ist.
