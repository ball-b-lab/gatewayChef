param(
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [string]$Port = "5000",
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "== GatewayChef Windows Pull + Build ==" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$currentBranch = (git branch --show-current).Trim()
if ($currentBranch -ne $Branch) {
    Write-Host ".. Switching branch to $Branch" -ForegroundColor Yellow
    git switch $Branch
    if ($LASTEXITCODE -ne 0) {
        throw "Git switch to $Branch failed."
    }
}

Write-Host ".. Pulling latest from $Remote/$Branch" -ForegroundColor Yellow
git pull $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    throw "Git pull from $Remote/$Branch failed."
}

if ($Clean) {
    & "$scriptDir\build_windows.ps1" -Port $Port -Clean
} else {
    & "$scriptDir\build_windows.ps1" -Port $Port
}

if ($LASTEXITCODE -ne 0) {
    throw "Windows build failed."
}

Write-Host "== Pull + Build complete ==" -ForegroundColor Green
