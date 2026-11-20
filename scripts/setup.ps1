# One-time setup on Windows, from a fresh clone:  .\scripts\setup.ps1
#   1. a Python 3.12 virtual environment in .venv, with Séance installed into it (the `seance` command)
#   2. GnuCOBOL 3.1.2 in tools\gnucobol: downloaded (82 MB), checked against a fixed SHA-256, then unpacked
#   3. a setup check (python -m seance doctor)
# -McpConfig also writes .kiro\settings\mcp.json with this folder's paths, so Kiro can start the MCP server.
# Safe to run again: what is already there is kept.
param([switch]$McpConfig)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host 'Creating .venv'
    $made = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv 2>$null
        $made = ($LASTEXITCODE -eq 0) -and (Test-Path $py)
    }
    if (-not $made) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) {
            Write-Host 'Could not create .venv. Install Python 3.12 or newer from python.org and run this again.'
            exit 1
        }
    }
}

Write-Host 'Installing Séance and its packages into .venv'
& $py -m pip install --disable-pip-version-check -q -e .
if ($LASTEXITCODE -ne 0) { Write-Host 'pip failed (see above).'; exit 1 }

$setupArgs = @('setup')
if ($McpConfig) { $setupArgs += '--mcp-config' }
& $py -m seance @setupArgs
if ($LASTEXITCODE -ne 0) { exit 1 }

& $py -m seance doctor
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host ''
Write-Host 'Start the app with: .\scripts\run.ps1'
