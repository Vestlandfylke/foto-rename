# ABOUTME: Startar den lokale browser-appen for NB foto-namngivar (FastAPI + uvicorn) i Python 3.13-venv.
# ABOUTME: Opnar på http://127.0.0.1:8000. Bruk -Setup første gong for å installere avhengnader.
[CmdletBinding()]
param(
    [switch]$Setup,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Lagar Python 3.13-venv ..."
    py -3.13 -m venv $venv
    $Setup = $true
}

if ($Setup) {
    Write-Host "Installerer avhengnader ..."
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $root "requirements.txt")
    Write-Host "For GPU: kjør òg"
    Write-Host "  & '$python' -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124"
}

Write-Host "Opnar http://127.0.0.1:$Port  (Ctrl+C for å stoppe)"
& $python -m uvicorn nbrenamer.webapp:app --host 127.0.0.1 --port $Port --reload
