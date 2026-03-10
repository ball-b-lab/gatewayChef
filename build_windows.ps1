param(
    [string]$Port = "5000",
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "== GatewayChef Windows Build ==" -ForegroundColor Cyan

# Ensure we are in the repository root
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if ($Clean) {
    Write-Host ".. Cleaning previous build artifacts" -ForegroundColor Yellow
    if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
    if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
}

# Execution policy hint
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq "Restricted") {
    Write-Host "!! PowerShell ExecutionPolicy is Restricted. Run:" -ForegroundColor Red
    Write-Host "   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned" -ForegroundColor Yellow
    Write-Host "   Then re-run this script." -ForegroundColor Yellow
    exit 1
}

# Create venv if missing
if (!(Test-Path ".venv")) {
    Write-Host ".. Creating venv in .venv" -ForegroundColor Yellow
    python -m venv .venv
}

# Activate venv
Write-Host ".. Activating venv" -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Upgrade pip tooling
Write-Host ".. Upgrading pip/setuptools/wheel" -ForegroundColor Yellow
python -m pip install --upgrade pip setuptools wheel

# Install dependencies
if (Test-Path "requirements.txt") {
    Write-Host ".. Installing requirements.txt" -ForegroundColor Yellow
    pip install -r requirements.txt
}

# Install PyInstaller if missing
$pyi = python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host ".. Installing PyInstaller" -ForegroundColor Yellow
    pip install pyinstaller
}

# Ensure .env exists and has PORT
if (!(Test-Path ".env")) {
    Write-Host ".. Creating .env from .env.example" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

$envContent = Get-Content ".env" -ErrorAction SilentlyContinue
if ($envContent -notmatch "^PORT=") {
    Add-Content ".env" "PORT=$Port"
} else {
    $envContent = $envContent -replace "^PORT=.*", "PORT=$Port"
    Set-Content ".env" $envContent
}
Write-Host ".. Using PORT=$Port" -ForegroundColor Green

# Basic Python syntax validation before packaging
Write-Host ".. Running compileall validation" -ForegroundColor Yellow
python -m compileall app.py auth db repositories routes scripts services tests utils | Out-Null

# Build with PyInstaller
Write-Host ".. Building EXE (PyInstaller)" -ForegroundColor Yellow
pyinstaller --noconfirm gatewaychef.spec

Write-Host "== Done ==" -ForegroundColor Green
Write-Host "Output: dist\\GatewayChef\\GatewayChef.exe"
