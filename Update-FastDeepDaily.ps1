$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSCommandPath
$python = "C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$storage = Join-Path $root "storage"
$log = Join-Path $storage "fastdeep_daily_update.log"

New-Item -ItemType Directory -Force -Path $storage | Out-Null
function Write-DailyLog([string]$Message) {
    Add-Content -LiteralPath $log -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
}

Set-Location $root
$env:GIT_TERMINAL_PROMPT = "0"
& git -C $root -c credential.interactive=never pull --ff-only origin main 2>&1 | ForEach-Object { Write-DailyLog "git: $_" }

try {
    & $python -m fastdeep_scanner update-prices --universe data\fastdeep_universe.csv --out data\fastdeep_prices.csv --range 5y --interval 1d --pause 0.05 --min-success-ratio 0.97 --workers 6 --request-timeout 12 2>&1 | ForEach-Object { Write-DailyLog "prices: $_" }
    if ($LASTEXITCODE -ne 0) { throw "Price update failed with exit code $LASTEXITCODE" }

    if ((Get-Date).DayOfWeek -eq [System.DayOfWeek]::Sunday) {
        & $python -m fastdeep_scanner update-financials --universe data\fastdeep_universe.csv --pause 0.15 --workers 4 --request-timeout 8 2>&1 | ForEach-Object { Write-DailyLog "financials: $_" }
        if ($LASTEXITCODE -ne 0) { throw "Weekly financial refresh failed with exit code $LASTEXITCODE" }
    }

    & $python -m fastdeep_scanner daily-scan --out storage\fastdeep_daily_scan_summary.json --timeframe D 2>&1 | ForEach-Object { Write-DailyLog "scan: $_" }
    if ($LASTEXITCODE -ne 0) { throw "Daily scan failed with exit code $LASTEXITCODE" }
    Write-DailyLog "Daily FastDeep update completed."
} catch {
    Write-DailyLog "FAILED: $($_.Exception.Message)"
    exit 1
}
