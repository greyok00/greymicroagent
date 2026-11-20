# greymicroagent - Windows launcher.
# Opens the product in Windows Terminal when present, otherwise PowerShell.
# It runs package\greymicroagent.exe when built, else package\run.ps1.
# The Linux twin is launch.sh.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$exe = Join-Path $root "package\greymicroagent.exe"
$runner = Join-Path $root "package\run.ps1"

if (Test-Path $exe) {
    $target = "& '$exe'"
} elseif (Test-Path $runner) {
    $target = "& '$runner'"
} else {
    Write-Host "greymicroagent: neither package\greymicroagent.exe nor package\run.ps1 was found." -ForegroundColor Red
    exit 1
}

if (Get-Command wt.exe -ErrorAction SilentlyContinue) {
    Start-Process wt.exe -ArgumentList @("powershell.exe", "-NoExit", "-NoProfile", "-Command", $target)
} else {
    Start-Process powershell.exe -ArgumentList @("-NoExit", "-NoProfile", "-Command", $target)
}
