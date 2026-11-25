<#
GatewayChef Launcher (Windows) - ersetzt die PyInstaller-EXE.

Was er tut, bei jedem Start:
  1. uv installieren, falls nicht vorhanden (eine Datei, bringt Python selbst mit)
  2. Code nach %LOCALAPPDATA%\GatewayChef\app holen bzw. auf origin/main (oder -Ref) aktualisieren
  3. Abhaengigkeiten aus requirements.txt in eine gecachte Umgebung (Sekunden, ab dem 2. Start)
  4. starten: Web-UI (Standard) oder das Setup-CLI

Die .env liegt in %LOCALAPPDATA%\GatewayChef\.env - ausserhalb des Codes, wird nie ueberschrieben.
Fehlt sie und liegt eine .env neben gatewaychef.cmd, wird diese beim ersten Start uebernommen.

Aufruf:
  gatewaychef.cmd                      # Web-UI
  gatewaychef.cmd setup                # Gateway pruefen (Dry-Run)
  gatewaychef.cmd setup --apply ...    # Gateway einrichten
  gatewaychef.cmd -Ref v2026.11.18     # bestimmten Release-Tag starten
  gatewaychef.cmd -Offline             # ohne Update starten
#>
param(
    [string]$Ref = "main",
    [switch]$Offline,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$Rest
)
$ErrorActionPreference = "Stop"
$Repo = if ($env:GATEWAYCHEF_REPO) { $env:GATEWAYCHEF_REPO } else { "https://github.com/ball-b-lab/gatewayChef.git" }
$Home_ = Join-Path $env:LOCALAPPDATA "GatewayChef"
$App = Join-Path $Home_ "app"
$EnvFile = Join-Path $Home_ ".env"
New-Item -ItemType Directory -Force -Path $Home_ | Out-Null

function Need($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

if (-not (Need "uv")) {
    Write-Host ".. installiere uv" -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Need "git")) { throw "git fehlt. Installieren: winget install Git.Git" }

if (-not (Test-Path (Join-Path $App ".git"))) {
    Write-Host ".. lade GatewayChef ($Ref)" -ForegroundColor Yellow
    git clone --quiet $Repo $App
}
if (-not $Offline) {
    Push-Location $App
    try {
        git fetch --quiet --tags origin
        if ($LASTEXITCODE -ne 0) { Write-Warning "Update nicht moeglich (offline?), starte vorhandenen Stand." }
        else {
            $target = if (git rev-parse --verify --quiet "refs/tags/$Ref") { $Ref } else { "origin/$Ref" }
            git reset --quiet --hard $target
        }
    } finally { Pop-Location }
}
$Version = (git -C $App describe --tags --always).Trim()
Write-Host "== GatewayChef $Version ==" -ForegroundColor Cyan

$Beside = Join-Path $PSScriptRoot ".env"
if ((-not (Test-Path $EnvFile)) -and (Test-Path $Beside)) {
    Copy-Item $Beside $EnvFile
    Write-Host ".. .env neben dem Launcher uebernommen -> $EnvFile" -ForegroundColor Yellow
}
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $App ".env.example") $EnvFile
    Write-Host "!! $EnvFile angelegt - bitte Zugangsdaten eintragen und neu starten." -ForegroundColor Red
    notepad $EnvFile
    exit 1
}
$env:GATEWAYCHEF_ENV_FILE = $EnvFile

Push-Location $App
try {
    $uvArgs = @("run", "--quiet", "--python", "3.12", "--no-project", "--with-requirements", "requirements.txt")
    if ($Rest.Count -gt 0 -and $Rest[0] -eq "setup") {
        $cliArgs = if ($Rest.Count -gt 1) { $Rest[1..($Rest.Count - 1)] } else { @() }
        & uv @uvArgs python scripts/gateway_setup.py @cliArgs
    } else {
        & uv @uvArgs python app.py @Rest
    }
    exit $LASTEXITCODE
} finally { Pop-Location }
