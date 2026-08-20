$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSCommandPath
$python = "C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$url = "http://127.0.0.1:8765"
$storage = Join-Path $root "storage"
$metadataPath = Join-Path $root "data\fastdeep_prices_source.json"

function Write-LauncherLog([string]$Message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath (Join-Path $storage "fastdeep_launcher.log") -Value "[$timestamp] $Message"
}

function Stop-FastDeepServer {
    $servers = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        $_.CommandLine -match "fastdeep_scanner\s+serve" -and $_.CommandLine -match "--port\s+8765"
    }
    foreach ($server in $servers) {
        Stop-Process -Id $server.ProcessId -Force -ErrorAction SilentlyContinue
        Write-LauncherLog "Stopped previous FastDeep server process $($server.ProcessId)."
    }
}

function Test-FastDeepServer {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Start-PriceUpdateIfStale {
    $lastUpdate = $null
    if (Test-Path -LiteralPath $metadataPath) {
        try {
            $updatedAt = (Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json).updated_at
            if ($updatedAt -is [DateTime]) {
                $lastUpdate = $updatedAt.ToLocalTime().Date
            } else {
                $lastUpdate = [DateTimeOffset]::Parse([string]$updatedAt).ToLocalTime().Date
            }
        } catch {
            $lastUpdate = $null
        }
    }
    if ($lastUpdate -eq (Get-Date).Date) {
        return
    }

    Start-Process -FilePath $python `
        -ArgumentList "-m", "fastdeep_scanner", "update-prices", "--universe", "data\fastdeep_universe.csv", "--out", "data\fastdeep_prices.csv", "--range", "5y", "--interval", "1d", "--pause", "0.05", "--min-success-ratio", "0.97", "--workers", "6", "--request-timeout", "12" `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $storage "fastdeep_price_update.out.log") `
        -RedirectStandardError (Join-Path $storage "fastdeep_price_update.err.log")
    Write-LauncherLog "Started background 5-year price update. Python lock prevents duplicate runs."
}

New-Item -ItemType Directory -Force -Path $storage | Out-Null

$env:GIT_TERMINAL_PROMPT = "0"
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pullOutput = & git -C $root -c credential.interactive=never pull --ff-only origin main 2>&1 | Out-String
$pullExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
if ($pullExitCode -eq 0) {
    Write-LauncherLog "Git update: $pullOutput"
} else {
    Write-LauncherLog "Git update skipped: $pullOutput"
}

Stop-FastDeepServer
Start-Process -FilePath $python `
    -ArgumentList "-m", "fastdeep_scanner", "serve", "--host", "127.0.0.1", "--port", "8765" `
    -WorkingDirectory $root `
    -WindowStyle Hidden

for ($attempt = 0; $attempt -lt 12; $attempt += 1) {
    Start-Sleep -Milliseconds 500
    if (Test-FastDeepServer) {
        break
    }
}

if (-not (Test-FastDeepServer)) {
    Write-LauncherLog "FastDeep server did not become ready."
    exit 1
}

Start-PriceUpdateIfStale

$chromeCandidates = @(@(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })

if ($chromeCandidates) {
    Start-Process -FilePath $chromeCandidates[0] -ArgumentList "--new-window", $url
} else {
    Start-Process $url
}

Write-LauncherLog "Opened FastDeep Scanner in browser."
