param(
    [switch]$Setup,
    [string]$Email,
    [switch]$DownloadModel,
    [switch]$DownloadSample
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

function Assert-Success([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "MT Project: $step failed (exit $LASTEXITCODE)." }
}

Push-Location $projectRoot
try {
    if ($Setup) {
        if (-not (Test-Path -LiteralPath $projectPython)) {
            python -m venv .venv
            Assert-Success 'virtual environment creation'
        }
        & $projectPython -m pip install -r backend/requirements-vision.txt
        Assert-Success 'Python dependency installation'
        Push-Location frontend
        try {
            npm.cmd ci --no-audit --no-fund
            Assert-Success 'frontend dependency installation'
            npm.cmd run build
            Assert-Success 'frontend build'
        } finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run with -Setup first.' }
    Push-Location backend
    try {
        & $projectPython -m alembic upgrade head
        Assert-Success 'database migration'
        if ($Email) {
            & $projectPython -m app.cli create-admin --email $Email
            Assert-Success 'administrator creation'
        }
        if ($DownloadModel) {
            & $projectPython scripts/download_model.py
            Assert-Success 'model download'
        }
        if ($DownloadSample) {
            & $projectPython scripts/download_sample.py
            Assert-Success 'validation recording download'
        }
        $localModel = Join-Path $projectRoot 'backend\data\models\yolo11n.pt'
        if (-not $env:MT_MODEL_PATH -and (Test-Path -LiteralPath $localModel)) { $env:MT_MODEL_PATH = $localModel }
        $env:YOLO_CONFIG_DIR = Join-Path $projectRoot 'backend\data\yolo'
        & $projectPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
        Assert-Success 'server'
    } finally { Pop-Location }
} finally { Pop-Location }
