# AGENTS

## Scope

This repository contains one supported GatewayChef application. Treat `main` as the only release baseline.

## Current Architecture

- Flask app entry: `app.py`
- Main UI: `templates/index.html` plus `static/js/*`
- DB/API routes: `routes/db.py`
- Provisioning logic: `services/provisioning_service.py`
- Inventory persistence helpers: `repositories/gateway_inventory_repository.py`
- Windows packaging: `build_windows.ps1` and `gatewaychef.spec`

## Hard Rules For Later Changes

- Do not reintroduce `gatewaychef_v2` or parallel UI/API stacks.
- Keep Coolify deployment pointed at `main`.
- If a change affects DB inventory import or cloud table behavior, update:
  - `docs/api.md`
  - `docs/WIREGUARD_POOL_EXPANSION.md`
  - `docs/WIREGUARD_EXISTING_CONFIG_UPDATE.md`
- If a change affects packaging or release flow, update:
  - `docs/DEPLOYMENT.md`
  - `docs/RELEASE_BASELINE.md`

## Required Verification

- Run targeted unit tests for touched backend areas.
- Run `python3 -m py_compile` on edited Python entrypoints.
- For UI changes, verify the Cloud Table tab and main provisioning flow manually.

## Release Practice

- Build features on short-lived branches.
- Merge to `main`.
- Deploy only `main`.
