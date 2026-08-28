$ErrorActionPreference = 'Stop'
$python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$target = Join-Path $PSScriptRoot 'storage\python-deps'
& $python -m pip install --disable-pip-version-check --target $target 'xlrd==2.0.2' 'openpyxl>=3.1,<4'
if ($LASTEXITCODE -ne 0) { throw 'Index data reader installation failed.' }
Write-Output 'Index data readers are ready. Run: python -m fastdeep_scanner update-universe'
