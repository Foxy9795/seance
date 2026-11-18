# Starts Séance with GnuCOBOL on PATH and opens the browser. Run from anywhere:  .\scripts\run.ps1
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'env.ps1')
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'Missing .venv. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
    exit 1
}
if (-not (Get-Command cobc -ErrorAction SilentlyContinue)) {
    Write-Host 'cobc not found. Put GnuCOBOL in tools\gnucobol (see README).'
    exit 1
}
Set-Location $root
Start-Job { Start-Sleep 3; Start-Process 'http://127.0.0.1:8000' } | Out-Null
& $py -m uvicorn seance.api:app --host 127.0.0.1 --port 8000
