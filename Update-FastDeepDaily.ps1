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
$env:PYTHONUTF8 = "1"
& git -C $root -c credential.interactive=never pull --ff-only origin main 2>&1 | ForEach-Object { Write-DailyLog "git: $_" }

try {
    & $python -m fastdeep_scanner update-prices --universe data\fastdeep_universe.csv --out data\fastdeep_prices.csv --range 5y --interval 1d --pause 0.05 --min-success-ratio 0.97 --workers 6 --request-timeout 12 2>&1 | ForEach-Object { Write-DailyLog "prices: $_" }
    if ($LASTEXITCODE -ne 0) { throw "Price update failed with exit code $LASTEXITCODE" }

    # Valuation refuses to compare a HKD price with a CNY statement without a
    # dated rate, so FX is refreshed before anything is scored.
    & $python -m fastdeep_scanner update-fx --out data\fastdeep_fx_rates.json 2>&1 | ForEach-Object { Write-DailyLog "fx: $_" }
    if ($LASTEXITCODE -ne 0) { Write-DailyLog "fx: refresh failed, keeping previous rates" }

    Write-DailyLog "Financial statements refresh on demand when an analyst selects a symbol. Bulk Yahoo refresh is intentionally disabled because the public endpoint throttles large jobs."

    & $python -m fastdeep_scanner daily-scan --out storage\fastdeep_daily_scan_summary.json --timeframe D 2>&1 | ForEach-Object { Write-DailyLog "scan: $_" }
    if ($LASTEXITCODE -ne 0) { throw "Daily scan failed with exit code $LASTEXITCODE" }

    # The event studies gate which patterns may be called candidates. They take
    # several minutes over the full universe, so they refresh once a week.
    if ((Get-Date).DayOfWeek -eq [DayOfWeek]::Saturday) {
        & $python -m fastdeep_scanner backtest --timeframe D --out storage\fastdeep_event_study_D.json --horizons 5,10,20 --cost-bps 30 --summary-only 2>&1 | ForEach-Object { Write-DailyLog "study D: $_" }
        & $python -m fastdeep_scanner backtest --timeframe W --out storage\fastdeep_event_study_W.json --horizons 5,10,20 --cost-bps 30 --cooldown-bars 8 --summary-only 2>&1 | ForEach-Object { Write-DailyLog "study W: $_" }
        & $python -m fastdeep_scanner backtest --timeframe M --out storage\fastdeep_event_study_M.json --horizons 3,6,12 --cost-bps 30 --cooldown-bars 4 --summary-only 2>&1 | ForEach-Object { Write-DailyLog "study M: $_" }
    }

    Write-DailyLog "Daily FastDeep update completed."
} catch {
    Write-DailyLog "FAILED: $($_.Exception.Message)"
    exit 1
}
