# greymicroagent Windows launcher: installs dependencies, then starts the
# agent console (greymicroagent.exe) or builds it first if missing.
$ErrorActionPreference = "Stop"

$pkgRoot = $PSScriptRoot
$projRoot = Split-Path -Parent $pkgRoot
Set-Location $projRoot

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

if (-not (Have python)) {
  Write-Host "greymicroagent: installing Python 3.13 (winget)..."
  winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
  $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}
if (-not (Have node)) {
  Write-Host "greymicroagent: installing Node.js LTS (winget)..."
  winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
  $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}

Write-Host "greymicroagent: installing python dependencies"
python -m pip install -r (Join-Path $pkgRoot "requirements.txt")

$exe = Join-Path $pkgRoot "greymicroagent.exe"
if (Test-Path $exe) {
  Write-Host "greymicroagent: launching $exe"
  & $exe @args
} else {
  Write-Host "greymicroagent.exe not found in package/ - building it now"
  & (Join-Path $pkgRoot "build-windows.ps1")
  if (Test-Path $exe) {
    & $exe @args
  } else {
    Write-Host "greymicroagent: build did not produce greymicroagent.exe; see package/README.md" -ForegroundColor Yellow
  }
}
