$ErrorActionPreference = "Stop"
try {
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
} catch {}

$root = Split-Path -Parent $PSCommandPath

function Resolve-FastDeepPython {
    # A hard-coded interpreter path only exists on the machine that wrote it, so
    # try the override, then the py launcher, then PATH, then the bundled runtime.
    # A missing py launcher writes to stderr, which ErrorActionPreference = Stop
    # turns into a terminating NativeCommandError, so probing has to be quiet.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $candidates = @()
    if ($env:FASTDEEP_PYTHON_OVERRIDE) { $candidates += $env:FASTDEEP_PYTHON_OVERRIDE }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.13", "3.12", "3.11")) {
            try {
                $found = & py -$version -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $found) { $candidates += ([string]$found).Trim() }
            } catch { }
        }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    $candidates += Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) { continue }
        # datetime.UTC is used throughout the scanner, so 3.11 is the real floor.
        try {
            & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $ErrorActionPreference = $previous; return $candidate }
        } catch { }
    }
    $ErrorActionPreference = $previous
    throw "ไม่พบ Python 3.11 ขึ้นไป - ติดตั้งจาก https://www.python.org/downloads/ แล้วติ๊ก Add Python to PATH"
}

$python = Resolve-FastDeepPython
$storage = Join-Path $root "storage"
$log = Join-Path $storage "fastdeep_daily_update.log"

New-Item -ItemType Directory -Force -Path $storage | Out-Null
function Write-DailyLog([string]$Message) {
    Add-Content -LiteralPath $log -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
}

$updateMutex = [System.Threading.Mutex]::new($false, "Global\FastDeepDailyUpdate")
try {
    $updateLockAcquired = $updateMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $updateLockAcquired = $true
}
if (-not $updateLockAcquired) {
    Write-DailyLog "Another FastDeep update is already running; skipped this duplicate run."
    $updateMutex.Dispose()
    exit 0
}

Set-Location $root
$env:GIT_TERMINAL_PROMPT = "0"
$env:PYTHONUTF8 = "1"
$originalErrorPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$gitOutput = & git -C $root -c credential.interactive=never pull --ff-only origin main 2>&1
$gitExitCode = $LASTEXITCODE
$ErrorActionPreference = $originalErrorPreference
$gitOutput | ForEach-Object { Write-DailyLog "git: $_" }
if ($gitExitCode -ne 0) {
    Write-DailyLog "git: pull unavailable; continuing with the installed version"
}

try {
    & $python -m fastdeep_scanner update-universe 2>&1 | ForEach-Object { Write-DailyLog "universe: $_" }
    if ($LASTEXITCODE -ne 0) { Write-DailyLog "universe: one or more sources failed; retained their previous membership" }

    & $python -m fastdeep_scanner update-prices --universe data\fastdeep_universe.csv --out data\fastdeep_prices.csv --range 5y --interval 1d --pause 0.05 --min-success-ratio 0.97 --workers 6 --request-timeout 12 2>&1 | ForEach-Object { Write-DailyLog "prices: $_" }
    if ($LASTEXITCODE -ne 0) { throw "Price update failed with exit code $LASTEXITCODE" }

    # Valuation refuses to compare a HKD price with a CNY statement without a
    # dated rate, so FX is refreshed before anything is scored.
    & $python -m fastdeep_scanner update-fx --out data\fastdeep_fx_rates.json 2>&1 | ForEach-Object { Write-DailyLog "fx: $_" }
    if ($LASTEXITCODE -ne 0) { Write-DailyLog "fx: refresh failed, keeping previous rates" }

    # SEC updates resume daily. Fresh seven-day caches are skipped, so the first
    # successful connection fills the universe and later runs are lightweight.
    & $python -m fastdeep_scanner update-sec-financials --universe data\fastdeep_universe.csv --cache-dir data\financial_cache --groups SP500,NASDAQ100,SP400 --pause 0.20 --request-timeout 30 --cache-max-age-hours 168 --retries 2 --coverage-out data\fastdeep_financial_coverage.json --ticker-cache data\sec_company_tickers.json 2>&1 | ForEach-Object { Write-DailyLog "sec: $_" }
    if ($LASTEXITCODE -ne 0) { Write-DailyLog "sec: refresh unavailable, keeping previous verified cache" }

    # Yahoo remains the weekly fallback for markets outside SEC coverage.
    if ((Get-Date).DayOfWeek -eq [DayOfWeek]::Saturday) {
        # Hall of Fame uses compact monthly adjusted prices. Keeping this in a
        # separate file avoids loading ten years of daily bars into the scanner.
        & $python -m fastdeep_scanner update-prices --universe data\fastdeep_universe.csv --out data\fastdeep_hall_prices.csv --range 10y --interval 1mo --pause 0.05 --min-success-ratio 0.97 --workers 6 --request-timeout 12 2>&1 | ForEach-Object { Write-DailyLog "hall prices: $_" }
        if ($LASTEXITCODE -ne 0) { Write-DailyLog "hall prices: refresh failed, keeping previous monthly history" }

        & $python -m fastdeep_scanner update-financials --universe data\fastdeep_universe.csv --cache-dir data\financial_cache --pause 0.75 --workers 1 --request-timeout 20 --cache-max-age-hours 168 --retries 2 --coverage-out data\fastdeep_financial_coverage.json 2>&1 | ForEach-Object { Write-DailyLog "financials: $_" }
        if ($LASTEXITCODE -ne 0) { Write-DailyLog "financials: refresh incomplete, keeping verified cache" }
    }
    # ข้อความธุรกิจจากแบบที่ยื่น เปลี่ยนปีละครั้งตอนยื่น 10-K ใหม่ จึงพอสัปดาห์ละรอบ
    # ตัวที่มีอยู่แล้วจะถูกข้าม รอบต่อไปจึงเก็บเฉพาะบริษัทที่เพิ่งยื่นใหม่
    if ((Get-Date).DayOfWeek -eq [DayOfWeek]::Sunday) {
        & $python -m fastdeep_scanner update-filing-profiles --universe data\fastdeep_universe.csv --out data\fastdeep_filing_profiles.json --pause 0.2 2>&1 | ForEach-Object { Write-DailyLog "filings: $_" }
        if ($LASTEXITCODE -ne 0) { Write-DailyLog "filings: extraction incomplete, keeping stored text" }
    }

    & $python -m fastdeep_scanner audit-financials --universe data\fastdeep_universe.csv --cache-dir data\financial_cache --out data\fastdeep_financial_coverage.json 2>&1 | ForEach-Object { Write-DailyLog "financial audit: $_" }

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
    $updateMutex.ReleaseMutex()
    $updateMutex.Dispose()
} catch {
    Write-DailyLog "FAILED: $($_.Exception.Message)"
    try { $updateMutex.ReleaseMutex() } catch {}
    $updateMutex.Dispose()
    exit 1
}
