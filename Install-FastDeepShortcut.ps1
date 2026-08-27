[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
$launcher = Join-Path $root "Launch-FastDeepScanner.ps1"
if (-not (Test-Path -LiteralPath $launcher)) { throw "FastDeep launcher was not found: $launcher" }
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$shell = New-Object -ComObject WScript.Shell
$destinations = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("Programs")
)
foreach ($directory in $destinations) {
    if (-not (Test-Path -LiteralPath $directory)) { throw "Shortcut directory was not found: $directory" }
    $path = Join-Path $directory "FastDeep Scanner.lnk"
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`" -AppWindow"
    $shortcut.WorkingDirectory = $root
    $shortcut.WindowStyle = 7
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
    $shortcut.Description = "Open FastDeep Scanner in its own Chrome window and start the local server."
    $shortcut.Save()
    Write-Output "Installed: $path"
}
