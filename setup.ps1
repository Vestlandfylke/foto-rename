# ABOUTME: Eingongs-oppsett for NB foto-namngivar: sjekkar Python, lagar venv og installerer alle avhengnader.
# ABOUTME: Køyrast normalt via Installer.bat (dobbeltklikk). Tilbyr GPU-torch om eit NVIDIA-kort finst.
[CmdletBinding()]
param(
    [ValidateSet("auto", "ja", "nei")]
    [string]$Gpu = "auto"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"

function Write-Steg($t) { Write-Host ""; Write-Host ">> $t" -ForegroundColor Cyan }

Write-Host "=== Oppsett for NB foto-namngivar ===" -ForegroundColor Green

# 1) Finn ein brukbar Python (3.9-3.13; RapidOCR/onnxruntime manglar wheels for 3.14).
Write-Steg "Leitar etter Python 3.13 ..."
$pyLauncher = $null
$pyArgs = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        & py -3.13 --version *> $null
        if ($LASTEXITCODE -eq 0) { $pyLauncher = "py"; $pyArgs = @("-3.13") }
    } catch {}
}
if (-not $pyLauncher -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $ver = (& python --version) 2>&1
    if ($ver -match "Python 3\.(9|10|11|12|13)\b") { $pyLauncher = "python"; $pyArgs = @() }
}

if (-not $pyLauncher) {
    Write-Host ""
    Write-Host "Fann ikkje Python 3.9-3.13." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Prøver å installere Python 3.13 via winget ..."
        winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
        Write-Host ""
        Write-Host "Python er installert. Lukk dette vindauget og køyr Installer.bat ein gong til" -ForegroundColor Yellow
        Write-Host "(slik at den nye PATH-en blir lest inn)."
        exit 0
    }
    Write-Host "Installer Python 3.13 frå https://www.python.org/downloads/ og hugs a krysse av for"
    Write-Host "'Add python.exe to PATH'. Køyr deretter Installer.bat på nytt." -ForegroundColor Yellow
    exit 1
}

# 2) Lag virtuelt miljø om det ikkje finst.
if (-not (Test-Path $python)) {
    Write-Steg "Lagar virtuelt Python-miljø i .venv ..."
    & $pyLauncher @pyArgs -m venv $venv
} else {
    Write-Steg "Virtuelt miljø finst alt."
}

# 3) Installer avhengnader.
Write-Steg "Installerer avhengnader (dette kan ta nokre minutt) ..."
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root "requirements.txt")

# 4) GPU: tilby torch med CUDA om eit NVIDIA-kort er til stades.
$hasNvidia = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    try { & nvidia-smi *> $null; if ($LASTEXITCODE -eq 0) { $hasNvidia = $true } } catch {}
}

$installGpu = $false
if ($Gpu -eq "ja") { $installGpu = $true }
elseif ($Gpu -eq "nei") { $installGpu = $false }
elseif ($hasNvidia) {
    Write-Host ""
    Write-Host "Eit NVIDIA-grafikkort vart funne. GPU gjer OCR mykje raskare," -ForegroundColor Green
    Write-Host "men nedlastinga er stor (rundt 2-3 GB)."
    $svar = Read-Host "Vil du installere GPU-akselerasjon no? (j/N)"
    if ($svar -match "^(j|ja|y|yes)$") { $installGpu = $true }
}

if ($installGpu) {
    Write-Steg "Installerer torch med CUDA (stor nedlasting) ..."
    & $python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
}

Write-Host ""
Write-Host "=== Ferdig! ===" -ForegroundColor Green
Write-Host "Start appen ved a dobbeltklikke 'Start NB foto-namngivar.bat'."
