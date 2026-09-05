[CmdletBinding()]
param(
    [switch]$AppWindow,
    [switch]$SkipUpdate,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSCommandPath
$runtime = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies"

function Resolve-FastDeepPython {
    # The bundled runtime only exists on the author's machine. Students install
    # Python normally, so search the usual places and fall back to the bundle.
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
    $candidates += Join-Path $runtime "python\python.exe"

    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) { continue }
        # datetime.UTC is used throughout the scanner, so 3.11 is the real floor.
        try {
            & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $ErrorActionPreference = $previous; return $candidate }
        } catch { }
    }
    $ErrorActionPreference = $previous
    return $null
}

$python = Resolve-FastDeepPython
$url = "http://127.0.0.1:8765"
$storage = Join-Path $root "storage"
$metadataPath = Join-Path $root "data\fastdeep_prices_source.json"

function Write-LauncherLog([string]$Message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath (Join-Path $storage "fastdeep_launcher.log") -Value "[$timestamp] $Message"
}

function Stop-FastDeepServer {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)
    foreach ($ownerId in @($listeners.OwningProcess | Select-Object -Unique)) {
        $server = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId"
        if ($server.CommandLine -notmatch "fastdeep_scanner\s+serve" -or $server.CommandLine -notmatch "--port\s+8765") {
            throw "Port 8765 is already in use by another application. That application has not been stopped."
        }
        Stop-Process -Id $server.ProcessId -Force
        Write-LauncherLog "Stopped previous FastDeep server process $($server.ProcessId)."
    }
}

function Test-FastDeepServer {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -match "<title>FastDeep Intelligence Platform</title>"
    } catch {
        return $false
    }
}

function Update-FastDeepCode {
    if ($SkipUpdate) { return }
    $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
    $gitCandidates = @($gitCommand.Source, (Join-Path $runtime "native\git\cmd\git.exe"))
    $git = $gitCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $git -or -not (Test-Path -LiteralPath (Join-Path $root ".git"))) {
        Write-LauncherLog "Git update unavailable; opening the installed local version."
        return
    }
    $branch = & $git -C $root branch --show-current
    if ($branch -ne "main") {
        Write-LauncherLog "Git update skipped on branch $branch."
        return
    }

    $env:GIT_TERMINAL_PROMPT = "0"
    # Bound only the network fetch. Never interrupt a local merge or reset local work.
    $fetch = Start-Process -FilePath $git -ArgumentList @(
        "-C", "`"$root`"", "-c", "credential.interactive=never", "fetch", "--no-tags", "origin", "main"
    ) -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $storage "fastdeep_git_update.out.log") `
        -RedirectStandardError (Join-Path $storage "fastdeep_git_update.err.log")
    # Windows PowerShell needs a retained handle to report ExitCode after a fast exit.
    $null = $fetch.Handle
    if (-not $fetch.WaitForExit(12000)) {
        $fetch.Kill()
        $fetch.WaitForExit()
        Write-LauncherLog "Git fetch timed out; opening the installed local version."
        return
    }
    if ($fetch.ExitCode -ne 0) {
        Write-LauncherLog "Git fetch failed; opening the installed local version."
        return
    }
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $mergeOutput = & $git -C $root merge --ff-only FETCH_HEAD 2>&1 | Out-String
        Write-LauncherLog "Git update exit ${LASTEXITCODE}: $mergeOutput"
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

function Start-PriceUpdateIfStale {
    # -SkipUpdate used to skip only the git pull, so passing it still fired a
    # 5-year price download in the background. When the provider throttles, that
    # download hangs holding the price lock and takes the session down with it.
    if ($SkipUpdate) {
        Write-LauncherLog "Price update skipped by -SkipUpdate."
        return
    }
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
$mutex = New-Object System.Threading.Mutex($false, "Local\FastDeepScannerLauncher8765")
$ownsMutex = $false
$exitCode = 0
try {
    try { $ownsMutex = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { return }
    if (-not $python) {
        throw "ไม่พบ Python 3.11 ขึ้นไป - ติดตั้งจาก https://www.python.org/downloads/ แล้วติ๊ก ""Add Python to PATH"" จากนั้นเปิดโปรแกรมใหม่"
    }
    try { Update-FastDeepCode } catch { Write-LauncherLog "Git update skipped: $($_.Exception.Message)" }

    Stop-FastDeepServer
    $server = Start-Process -FilePath $python `
        -ArgumentList "-m", "fastdeep_scanner", "serve", "--host", "127.0.0.1", "--port", "8765" `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $storage "fastdeep_server.out.log") `
        -RedirectStandardError (Join-Path $storage "fastdeep_server.err.log")

    for ($attempt = 0; $attempt -lt 30; $attempt += 1) {
        if ($server.HasExited) { throw "FastDeep server stopped before it was ready. See storage\fastdeep_server.err.log." }
        if (Test-FastDeepServer) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-FastDeepServer)) { throw "FastDeep server did not become ready at $url." }
    try { Start-PriceUpdateIfStale } catch { Write-LauncherLog "Price refresh skipped: $($_.Exception.Message)" }

    if (-not $NoBrowser) {
        $chromeCandidates = @(@(
            "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })
        if ($chromeCandidates.Count -gt 0) {
            $browserArgs = if ($AppWindow) { @("--new-window", "--app=$url/") } else { @("--new-window", "$url/") }
            Start-Process -FilePath $chromeCandidates[0] -ArgumentList $browserArgs
        } else {
            Start-Process "$url/"
        }
        Write-LauncherLog "Opened FastDeep Scanner. App window: $AppWindow."
    }
} catch {
    $exitCode = 1
    Write-LauncherLog "Launch failed: $($_.Exception.Message)"
    if (-not $NoBrowser) {
        $shell = New-Object -ComObject WScript.Shell
        $shell.Popup("FastDeep could not start.`n`n$($_.Exception.Message)`n`nLog: $storage\fastdeep_launcher.log", 0, "FastDeep Scanner", 16) | Out-Null
    }
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
exit $exitCode
