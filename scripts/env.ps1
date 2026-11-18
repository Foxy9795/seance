# Source this from the repo root: . .\scripts\env.ps1
$root = Split-Path -Parent $PSScriptRoot
$b = Join-Path $root 'tools\gnucobol\gnucobol-3.1.2-windows-mingw-x64'
$env:PATH = "$b\bin;$env:PATH"
$env:COB_CONFIG_DIR = "$b\share\gnucobol\config"
$env:COB_COPY_DIR = "$b\share\gnucobol\copy"
$env:COB_LIBRARY_PATH = "$b\bin"
