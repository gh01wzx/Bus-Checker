$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:BUS_BACKEND = 'duckdb'
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Install dependencies into .venv first; see README.'
}
& $pythonExe -m streamlit run dashboard.py --server.address 127.0.0.1
