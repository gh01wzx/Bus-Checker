$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$python = $null
$candidates = @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'))
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) { $found = & $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null; if ($LASTEXITCODE -eq 0) { $candidates += $found } }
$command = Get-Command python -ErrorAction SilentlyContinue
if ($command) { $candidates += $command.Source }
foreach ($candidate in $candidates) {
 if (Test-Path -LiteralPath $candidate) {
  $version = & $candidate -c 'import sys; print(sys.version_info[0],sys.version_info[1],sep=chr(46))' 2>$null
  if ($LASTEXITCODE -eq 0 -and $version -eq '3.11') { $python = $candidate; break }
 }
}
if (-not $python) {
 $winget = Get-Command winget -ErrorAction SilentlyContinue
 if (-not $winget) { throw 'Install Python 3.11 (with Tcl/Tk) from python.org, then run Setup.cmd again.' }
 & $winget.Source install --id Python.Python.3.11 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
 if ($LASTEXITCODE -ne 0) { throw 'Python installation did not finish. Install Python 3.11 from python.org.' }
 $python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
 if (-not (Test-Path -LiteralPath $python)) { throw 'Restart this window after installing Python, then retry Setup.cmd.' }
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
 & $python -m venv .venv
 if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
}
& '.\.venv\Scripts\python.exe' setup.py @args
if ($LASTEXITCODE -ne 0) { throw 'Setup did not complete. Rerun it to retry.' }
