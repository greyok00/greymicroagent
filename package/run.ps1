# greymicroagent Windows launcher: model -> RAG gate -> terminal UI.
# Installs the free runtime pieces when missing; no compiler is required.
$ErrorActionPreference = "Stop"

$pkgRoot = $PSScriptRoot
$projRoot = Split-Path -Parent $pkgRoot
Set-Location $projRoot
$logDir = Join-Path $projRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function PortFree($port) {
    try {
        $client = New-Object Net.Sockets.TcpClient
        $task = $client.ConnectAsync("127.0.0.1", $port)
        [void]$task.Wait(400)
        $free = -not $client.Connected
        $client.Close()
        return $free
    } catch { return $true }
}

function Wait-Health($url, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try {
            $reply = Invoke-RestMethod -Uri $url -TimeoutSec 2
            if ($reply.status -eq "ok") { return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $false
}

if (-not (Have python)) {
    Write-Host "greymicroagent: installing Python 3.13 (winget)..."
    winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
    $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
}

if (-not (Have node)) {
    Write-Host "greymicroagent: installing Node.js (winget)..."
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
    $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
}

$vcruntime = Join-Path $env:SystemRoot "System32\VCRUNTIME140_1.dll"
if (-not (Test-Path $vcruntime)) {
    Write-Host "greymicroagent: installing the Microsoft C++ runtime (winget)..."
    winget install --id Microsoft.VCRedist.2015+.x64 -e --accept-source-agreements --accept-package-agreements
}

Write-Host "greymicroagent: installing python dependencies"
python -m pip install --quiet --disable-pip-version-check --upgrade pip
python -m pip install --quiet --disable-pip-version-check -r (Join-Path $pkgRoot "requirements.txt")
$ErrorActionPreference = "Continue"
python -m patchright install chromium
$ErrorActionPreference = "Stop"

$model = $env:GREYMICROAGENT_MODEL_PATH
if (-not $model) {
    $model = Join-Path $env:USERPROFILE ".greymicroagent\models\qwen3.5-2b-abliterated.gguf"
}
if (-not (Test-Path $model)) {
    Write-Host "greymicroagent: model missing at $model" -ForegroundColor Red
    Write-Host "greymicroagent: download qwen3.5-2b-abliterated.gguf from the release and put it there." -ForegroundColor Red
    exit 1
}
$arch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
$archDir = if ($arch -eq "ARM64") { "arm64" } else { "x64" }
$gpuDir = Join-Path $projRoot "vendor\win\$archDir-vulkan"
$cpuDir = Join-Path $projRoot "vendor\win\$archDir-cpu"

function Find-Engine($dir) {
    if (-not (Test-Path $dir)) { return $null }
    return Get-ChildItem -Path $dir -Filter *.exe -File | Select-Object -First 1
}

$gpuEngine = Find-Engine $gpuDir
$cpuEngine = Find-Engine $cpuDir
if (-not $cpuEngine) {
    Write-Host "greymicroagent: no Windows engine for $archDir in vendor\win" -ForegroundColor Red
    Write-Host "greymicroagent: download the release again so vendor\win is complete." -ForegroundColor Red
    exit 1
}

$useGpu = $false
if ($gpuEngine) {
    try {
        $devices = & $($gpuEngine.FullName) --list-devices 2>&1 | Out-String
        if ($devices -match "Vulkan") { $useGpu = $true }
    } catch {
        $useGpu = $false
    }
}
$template = Join-Path $projRoot "model\qwen3-chat-template.jinja"

$modelPort = $null
$gatePort = $null
foreach ($pair in @(@(7640, 7641), @(7643, 7644))) {
    if ((PortFree $pair[0]) -and (PortFree $pair[1])) {
        $modelPort = $pair[0]
        $gatePort = $pair[1]
        break
    }
}
if (-not $modelPort) {
    Write-Host "greymicroagent: all sessions in use (7640-7647 block) - close one first" -ForegroundColor Red
    exit 1
}

$env:GREYAGENT_MODEL_PORT = "$modelPort"
$env:GREYAGENT_LANE_PORT = "$gatePort"
$env:RAG_GATE_PORT = "$gatePort"
$env:GREYMICROAGENT_UPSTREAM = "http://127.0.0.1:$modelPort"
$env:GREYMICROAGENT_DBS = "commands,general"
$env:GREYMICROAGENT_DBS_ROOT = Join-Path $env:USERPROFILE ".greymicroagent\dbs"
$env:GREYMICROAGENT_RAG_FLOOR = "7.5"
$env:GREYMICROAGENT_MODEL_PATH = $model
$env:GREYAGENT_LOCAL_BASE = "http://127.0.0.1:$gatePort/v1"
$env:GREYAGENT_MODEL_HEALTH_URL = "http://127.0.0.1:$modelPort/health"
$env:GREYAGENT_HOME = $projRoot
$env:GREYAGENT_ROOT = $projRoot
$env:GREYAGENT_CODING_AGENT_DIR = Join-Path $env:USERPROFILE ".greymicroagent\agent"
$env:CORTEXAGENT_MEMORY_DIR = Join-Path $env:USERPROFILE ".greymicroagent\memory"
$env:CORTEXAGENT_STATE_DIR = Join-Path $env:USERPROFILE ".greymicroagent\state"
$env:CORTEXAGENT_STATUS_DIR = Join-Path $env:USERPROFILE ".greymicroagent\mcp-status"
$env:GREYAGENT_MEMORY_DIR = $env:CORTEXAGENT_MEMORY_DIR
$env:GREYAGENT_PLATFORM = "greymicroagent"
$env:GREYAGENT_TEMP = "0.1"
$env:GREYAGENT_TOP_P = "0.95"
$env:GREYAGENT_UBATCH = "4096"
$env:GREYAGENT_THINKING = "off"
$env:GREYAGENT_OFFLINE = "1"
$env:GREYAGENT_SKIP_VERSION_CHECK = "1"
$env:CORTEX_OFFLINE = "1"
$env:CORTEX_SKIP_VERSION_CHECK = "1"
$env:CORTEX_TELEMETRY = "0"
$env:PYTHONPATH = $projRoot

foreach ($dir in @(
        (Join-Path $env:USERPROFILE ".greymicroagent\models"),
        $env:GREYMICROAGENT_DBS_ROOT,
        $env:GREYAGENT_CODING_AGENT_DIR,
        $env:CORTEXAGENT_MEMORY_DIR,
        $env:CORTEXAGENT_STATE_DIR,
        $env:CORTEXAGENT_STATUS_DIR)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

$threads = [Math]::Max(2, [Environment]::ProcessorCount - 2)
if ($env:GREYAGENT_THREADS -and $env:GREYAGENT_THREADS.Trim() -ne "") {
    $threads = [int]$env:GREYAGENT_THREADS
}

function Start-Engine($exe, $ngl, $tag) {
    $engineArgs = @(
        "--model", ('"' + $model + '"'),
        "--host", "127.0.0.1",
        "--port", "$modelPort",
        "--ctx-size", "65536",
        "--n-gpu-layers", "$ngl",
        "--temp", "0.1",
        "--top-p", "0.95",
        "--top-k", "10",
        "--threads", "$threads",
        "--flash-attn", "on",
        "--parallel", "1",
        "--ubatch-size", "4096",
        "--cache-type-k", "q4_0",
        "--cache-type-v", "q4_0",
        "--metrics",
        "--jinja",
        "--chat-template-file", ('"' + $template + '"'),
        "--reasoning", "off",
        "--alias", "greymicroagent"
    ) -join " "
    Write-Host "greymicroagent: starting the model on :$modelPort ($tag)"
    return Start-Process -FilePath $exe.FullName -ArgumentList $engineArgs -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "model-$modelPort-$tag.log") `
        -RedirectStandardError (Join-Path $logDir "model-$modelPort-$tag.err.log")
}

function Wait-Model($proc, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if ($proc.HasExited) { return $false }
        try {
            $reply = Invoke-RestMethod -Uri "http://127.0.0.1:$modelPort/health" -TimeoutSec 2
            if ($reply.status -eq "ok") { return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $false
}

$ngl = "0"
if ($useGpu) { $ngl = "999" }
if ($env:GREYAGENT_NGL -and $env:GREYAGENT_NGL.Trim() -ne "") { $ngl = $env:GREYAGENT_NGL }
$engine = $cpuEngine
$backend = "cpu"
if ($useGpu) { $engine = $gpuEngine; $backend = "vulkan" }

$modelProc = Start-Engine $engine $ngl $backend
$ready = Wait-Model $modelProc 300
if (-not $ready -and $useGpu) {
    Write-Host "greymicroagent: the Vulkan engine did not start; falling back to CPU" -ForegroundColor Yellow
    Stop-Process -Id $modelProc.Id -Force -ErrorAction SilentlyContinue
    $ngl = "0"
    $backend = "cpu"
    $modelProc = Start-Engine $cpuEngine $ngl $backend
    $ready = Wait-Model $modelProc 300
}
if (-not $ready) {
    Write-Host "greymicroagent: the model did not answer on :$modelPort (see logs)" -ForegroundColor Red
    Stop-Process -Id $modelProc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "greymicroagent: model ready, backend $backend, offloaded layers $ngl"

Write-Host "greymicroagent: starting the knowledge gate on :$gatePort"
$gateProc = Start-Process -FilePath "python" -ArgumentList ('"' + (Join-Path $projRoot "services\rag_gate.py") + '"') `
    -WorkingDirectory $projRoot -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir "gate-$gatePort.log") `
    -RedirectStandardError (Join-Path $logDir "gate-$gatePort.err.log")
if (-not (Wait-Health "http://127.0.0.1:$gatePort/health" 40)) {
    Write-Host "greymicroagent: the gate did not answer; answers will use the model directly" -ForegroundColor Yellow
    $env:GREYAGENT_LOCAL_BASE = "http://127.0.0.1:$modelPort/v1"
}

$card = Join-Path $projRoot "model\greymicroagent.txt"
if (-not (Test-Path $card)) { $card = Join-Path $projRoot "model\greymicroagent.md" }
$cardText = Get-Content -Raw -Path $card
# Windows PowerShell 5.1 (what launch.ps1 invokes) does not escape embedded
# double quotes when building a native command line, so the card's quotes
# would truncate --system-prompt. Pre-escape them for CommandLineToArgvW;
# PowerShell 7.3+ escapes on its own and passes the card through unchanged.
$cardArg = $cardText
if ($PSVersionTable.PSVersion -lt [version]"7.3.0") {
    $cardArg = $cardText.Replace('"', '\"')
}
$cli = Join-Path $projRoot "tui\packages\coding-agent\dist\cli.js"

try {
    Write-Host "greymicroagent: ready"
    & node $cli --no-skills --no-builtin-tools --system-prompt $cardArg @args
} finally {
    if ($gateProc) { Stop-Process -Id $gateProc.Id -Force -ErrorAction SilentlyContinue }
    if ($modelProc) { Stop-Process -Id $modelProc.Id -Force -ErrorAction SilentlyContinue }
}
