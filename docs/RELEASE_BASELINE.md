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
- PyInstaller spec: `gatewaychef.spec`
- Expected output: `dist/GatewayChef/GatewayChef.exe`
