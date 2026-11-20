# Builds greymicroagent.exe on a Windows machine.
# Produces: package/greymicroagent.exe (+ _internal), plus the Windows model
# server binary (vendor/win/greymicroagent-server.exe) from the vendored
# llama.cpp fork source. Needs Visual Studio Build Tools + CMake.
$ErrorActionPreference = "Stop"

$pkgRoot = $PSScriptRoot
$projRoot = Split-Path -Parent $pkgRoot
Set-Location $projRoot

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

if (-not (Have python)) {
  Write-Host "installing Python (winget)..."
  winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
  $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}
if (-not (Have cmake)) {
  Write-Host "installing CMake (winget)..."
  winget install --id Kitware.CMake -e --accept-source-agreements --accept-package-agreements
  $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}
if (-not (Have cl) -and -not (Have "clang")) {
  Write-Host "installing Visual Studio Build Tools (winget) - this is a large download"
  winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-source-agreements --accept-package-agreements
}

Write-Host "== 1. python deps =="
python -m pip install -r (Join-Path $pkgRoot "requirements.txt")
python -m pip install pyinstaller

Write-Host "== 2. windows model server from vendored llama.cpp fork =="
if (-not (Test-Path "vendor\win\greymicroagent-server.exe")) {
  $llamaSrc = "vendor\llamacpp"
  if (-not (Test-Path (Join-Path $llamaSrc "CMakeLists.txt"))) {
    Write-Host "vendor\llamacpp has no CMakeLists - clone the fork source there, then rerun"
    exit 1
  }
  cmake -S $llamaSrc -B build\llamacpp-win -DCMAKE_BUILD_TYPE=Release
  cmake --build build\llamacpp-win --config Release --target llama-server
  New-Item -ItemType Directory -Force vendor\win | Out-Null
  $built = Get-ChildItem -Recurse -Filter "llama-server.exe" build\llamacpp-win | Select-Object -First 1
  if ($null -eq $built) { Write-Host "llama-server.exe not produced; check cmake output"; exit 1 }
  Copy-Item $built.FullName "vendor\win\greymicroagent-server.exe"
}

Write-Host "== 3. freeze the console entry =="
python -m PyInstaller --clean -y `
  --name greymicroagent `
  --distpath package `
  --workpath build\pyinstaller `
  --specpath build `
  --collect-all requests `
  package\entry.py
# onedir layout: move exe next to launcher name
$dist = "package\greymicroagent"
if (Test-Path $dist) {
  Move-Item "$dist\greymicroagent.exe" "package\greymicroagent.exe" -Force
  if (Test-Path "package\_internal") { Remove-Item "package\_internal" -Recurse -Force -ErrorAction SilentlyContinue }
  Move-Item "$dist\_internal" "package\_internal" -Force
  Remove-Item $dist -Recurse -Force
}

Write-Host "greymicroagent.exe built in package/ - start it with run.ps1"
