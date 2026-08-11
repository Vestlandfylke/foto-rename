# ABOUTME: Startar den lokale browser-appen for NB foto-namngivar og opnar nettlesaren automatisk.
# ABOUTME: Køyrast normalt via 'Start NB foto-namngivar.bat' (dobbeltklikk). Stopp med Ctrl+C eller lukk vindauget.
[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$url = "http://127.0.0.1:$Port"

if (-not (Test-Path $python)) {
    Write-Host "Appen er ikkje sett opp enno." -ForegroundColor Yellow
    Write-Host "Dobbeltklikk 'Installer.bat' fyrst, og prøv så igjen."
    Read-Host "Trykk Enter for a lukke"
    exit 1
}

# Opne nettlesaren litt etter at serveren har starta.
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep -Seconds 3
    Start-Process $u
} -ArgumentList $url | Out-Null

Write-Host "Startar NB foto-namngivar ..." -ForegroundColor Green
Write-Host "Opnar $url i nettlesaren. Lat dette vindauget stå ope medan du brukar appen."
Write-Host "Stopp appen med Ctrl+C eller ved a lukke vindauget." -ForegroundColor DarkGray
Write-Host ""

& $python -m uvicorn nbrenamer.webapp:app --host 127.0.0.1 --port $Port
