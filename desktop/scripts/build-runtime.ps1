# ABOUTME: Byggjer eit sjølvstendig Python-miljø i desktop\runtime, som blir pakka inn i installasjonsfila.
# ABOUTME: Brukar den offisielle "embeddable" Python-distribusjonen, så maskina som installerer appen ikkje treng Python.
[CmdletBinding()]
param(
    # Same Python-serie som .venv i utvikling. RapidOCR/onnxruntime har ikkje wheels for 3.14.
    [string]$PythonVersion = "3.13.0",
    [ValidateSet("cpu", "gpu")]
    [string]$Device = "cpu",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$desktopDir = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $desktopDir
$runtime = Join-Path $desktopDir "runtime"
$python = Join-Path $runtime "python.exe"
$work = Join-Path ([System.IO.Path]::GetTempPath()) "nbr-runtime"

function Write-Steg($t) { Write-Host ""; Write-Host ">> $t" -ForegroundColor Cyan }

if (Test-Path $runtime) {
    if (-not $Force) {
        Write-Host "$runtime finst alt. Bruk -Force for a byggje på nytt." -ForegroundColor Yellow
        exit 1
    }
    Write-Steg "Fjernar gammal runtime ..."
    Remove-Item $runtime -Recurse -Force
}

New-Item -ItemType Directory -Path $runtime, $work -Force | Out-Null

# 1) Hent og pakk ut den innebygde Python-distribusjonen (ca. 11 MB).
Write-Steg "Lastar ned Python $PythonVersion (embeddable, amd64) ..."
$zip = Join-Path $work "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zip
}
Expand-Archive -Path $zip -DestinationPath $runtime -Force

# 2) Opne opp sys.path: slå på site-packages og gjer nbrenamer-pakken importerbar.
#    Ein ._pth-fil definerer sys.path fullstendig, så cwd blir IKKJE lagt til automatisk.
#    Difor må stien til backend-mappa (resources\backend, ved sida av resources\runtime) stå her.
Write-Steg "Konfigurerer sys.path ..."
$pth = Get-ChildItem -Path $runtime -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "Fann ikkje ._pth-fila i $runtime" }
$stdlibZip = (Get-ChildItem -Path $runtime -Filter "python*.zip" | Select-Object -First 1).Name
@(
    $stdlibZip
    "."
    "Lib\site-packages"
    "..\backend"
    "import site"
) | Set-Content -Path $pth.FullName -Encoding ascii

# 3) Bootstrap pip.
Write-Steg "Installerer pip ..."
$getPip = Join-Path $work "get-pip.py"
if (-not (Test-Path $getPip)) {
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
}
& $python $getPip --no-warn-script-location
& $python -m pip install --upgrade setuptools wheel --no-warn-script-location

# 4) Avhengnader for OCR-pipeline og web-backend.
Write-Steg "Installerer avhengnader (dette tek nokre minutt) ..."
& $python -m pip install -r (Join-Path $projectRoot "requirements.txt") --no-warn-script-location

if ($Device -eq "gpu") {
    Write-Steg "Installerer torch med CUDA (stor nedlasting, ca. 3 GB) ..."
    & $python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 --no-warn-script-location
}

# 5) Legg OCR-modellane inn på førehand. Programmappa kan vere skriveverna når appen er
#    installert, så RapidOCR må ikkje trenge å laste dei ned ved fyrste køyring.
Write-Steg "Legg inn OCR-modellar ..."
$modelTarget = Join-Path $runtime "Lib\site-packages\rapidocr\models"
$modelSource = Join-Path $projectRoot ".venv\Lib\site-packages\rapidocr\models"
New-Item -ItemType Directory -Path $modelTarget -Force | Out-Null
if (Test-Path $modelSource) {
    # Sparer nedlasting når utviklingsmiljøet alt har modellane.
    Copy-Item -Path (Join-Path $modelSource "*") -Destination $modelTarget -Recurse -Force
    Write-Host "   Kopierte modellar frå .venv."
}
# Hentar det som framleis manglar. Tek med både CPU- og GPU-modellane, sidan GPU kan bli
# slått på lenge etter installasjonen.
& $python (Join-Path $PSScriptRoot "fetch_models.py") --target $modelTarget

# 6) Trim bort det som ikkje trengst i ein installasjon.
Write-Steg "Ryddar ..."
Get-ChildItem -Path $runtime -Include "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$size = [math]::Round((Get-ChildItem $runtime -Recurse -File | Measure-Object Length -Sum).Sum / 1GB, 2)
Write-Host ""
Write-Host "=== Ferdig! runtime er $size GB ===" -ForegroundColor Green
Write-Host "Bygg installasjonsfila med: npm run dist   (i mappa desktop)"
