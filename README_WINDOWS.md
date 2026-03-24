# Windows Build README

## Ziel

Dieses Repo enthaelt zwei Windows-Build-Skripte:

- `build_windows.ps1`
  - baut den aktuellen lokalen Stand
- `build_windows_pull.ps1`
  - wechselt auf `main`, zieht den neuesten Stand und baut danach

## Voraussetzungen

- Windows mit PowerShell
- `git` im `PATH`
- `python` im `PATH`

## Schnellstart

Aktuellen Stand von `main` holen und sauber bauen:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_pull.ps1 -Clean
```

Ohne Clean-Build:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_pull.ps1
```

## Nur lokalen Stand bauen

Wenn bereits der richtige Git-Stand ausgecheckt ist:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1 -Clean
```

## Optionaler Port

Standard ist `5000`. Anderen Port setzen:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_pull.ps1 -Port 5011 -Clean
```

## Was das Pull-Build-Skript macht

`build_windows_pull.ps1` fuehrt nacheinander aus:

1. `git switch main` falls noetig
2. `git pull origin main`
3. Aufruf von `build_windows.ps1`

## Output

Erwartete EXE:

```text
dist\GatewayChef\GatewayChef.exe
```

## Hinweise

- Wenn lokale uncommittete Aenderungen mit `git pull` kollidieren, bricht das Skript absichtlich ab.
- Wenn PowerShell-Skripte blockiert sind:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
