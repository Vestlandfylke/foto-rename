# ABOUTME: PowerShell-wrapper som set opp Python 3.13-venv, installerer avhengnader og køyrer nb-photo-renamer.py.
# ABOUTME: Bruk -Setup første gong for å installere; elles sendast alle argument vidare til Python-skriptet.
[CmdletBinding()]
param(
    [switch]$Setup,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Forward
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$script = Join-Path $root "nb-photo-renamer.py"

# RapidOCR/onnxruntime støttar ikkje Python 3.14, difor 3.13.
if (-not (Test-Path $python)) {
    Write-Host "Lagar Python 3.13-venv i $venv ..."
    py -3.13 -m venv $venv
    $Setup = $true
}

if ($Setup) {
    Write-Host "Installerer avhengnader ..."
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

if (-not $Forward -or $Forward.Count -eq 0) {
    Write-Host ""
    Write-Host "Bruk:"
    Write-Host "  .\run-nb-renamer.ps1 -Setup                 # installer avhengnader"
    Write-Host "  .\run-nb-renamer.ps1 test --file <bilete>"
    Write-Host "  .\run-nb-renamer.ps1 discover --input-dir <mappe> --report report.csv --workers 4"
    Write-Host "  .\run-nb-renamer.ps1 execute --report report.csv --output-dir <ut> --organize-by-year"
    exit 0
}

& $python $script @Forward
exit $LASTEXITCODE
