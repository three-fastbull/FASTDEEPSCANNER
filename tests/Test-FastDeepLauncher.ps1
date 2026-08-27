$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$errors = @()
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $root "Launch-FastDeepScanner.ps1"), [ref]$null, [ref]$errors
)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @("Stop-FastDeepServer", "Test-FastDeepServer")) {
    $definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    . ([scriptblock]::Create($definition.Extent.Text))
}

$script:listeners = @()
$script:stopped = @()
$script:owner = $null
$script:response = $null
$script:offline = $false
$url = "http://127.0.0.1:8765"
function Get-NetTCPConnection { param($State, $LocalPort, $ErrorAction) return $script:listeners }
function Get-CimInstance { param($ClassName, $Filter) return $script:owner }
function Stop-Process { param($Id, [switch]$Force) $script:stopped += $Id }
function Write-LauncherLog { param($Message) }
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec)
    if ($script:offline) { throw "Offline" }
    return $script:response
}
function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    Write-Output "PASS: $Message"
}

Stop-FastDeepServer
Assert-True ($script:stopped.Count -eq 0) "No listener does not stop a process"

$script:listeners = @([pscustomobject]@{ OwningProcess = 123 })
$script:owner = [pscustomobject]@{ ProcessId = 123; CommandLine = "python -m unrelated_server --port 8765" }
$blocked = $false
try { Stop-FastDeepServer } catch { $blocked = $true }
Assert-True ($blocked -and $script:stopped.Count -eq 0) "Unrelated process on the port is protected"

$script:owner.CommandLine = "python -m fastdeep_scanner serve --host 127.0.0.1 --port 8765"
Stop-FastDeepServer
Assert-True ($script:stopped.Count -eq 1 -and $script:stopped[0] -eq 123) "Only the FastDeep listener is stopped"

$script:response = [pscustomobject]@{ StatusCode = 200; Content = "<title>Another app</title>" }
Assert-True (-not (Test-FastDeepServer)) "An unrelated HTTP 200 is not readiness"
$script:response.Content = "<title>FastDeep Intelligence Platform</title>"
Assert-True (Test-FastDeepServer) "FastDeep HTML confirms readiness"
$script:offline = $true
Assert-True (-not (Test-FastDeepServer)) "A connection failure is not readiness"
