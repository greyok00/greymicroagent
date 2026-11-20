# greymicroagent Windows launcher.
# Opens the product in Windows Terminal when present, otherwise PowerShell.
# It runs package\run.ps1, which installs any missing runtime pieces and
# starts the console client.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runner = Join-Path $root "package\run.ps1"

if (-not (Test-Path $runner)) {
    Write-Host "greymicroagent: package\run.ps1 was not found." -ForegroundColor Red
    exit 1
}

$target = "& '$runner'"
if (Get-Command wt.exe -ErrorAction SilentlyContinue) {
    Start-Process wt.exe -ArgumentList @("powershell.exe", "-NoExit", "-NoProfile", "-Command", $target)
} else {
    Start-Process powershell.exe -ArgumentList @("-NoExit", "-NoProfile", "-Command", $target)
}
