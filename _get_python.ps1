# Put a private copy of Python inside the project folder.
#
# Installing Python by hand was the step students got wrong most often - the
# PATH checkbox, an old version, a Store stub. The embeddable package needs no
# installer and no admin rights, and living under .\python it cannot collide
# with anything else on the machine. If the download fails, setup falls back to
# whatever Python is already installed, so this step can only help.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
$target = Join-Path $root "python"
$python = Join-Path $target "python.exe"
$deps = Join-Path $root "storage\python-deps"

$version = "3.12.10"
$url = "https://www.python.org/ftp/python/$version/python-$version-embed-amd64.zip"
# Recorded from python.org over HTTPS; a mismatch means a truncated or altered file.
$sha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

# The index membership files are Excel workbooks. These readers are pure Python,
# so their wheels unpack as plain zips - the embeddable build has no pip to
# install them. Hashes are the ones PyPI publishes for these exact files.
$wheels = @(
    @{ Module = "openpyxl"; Url = "https://files.pythonhosted.org/packages/c0/da/977ded879c29cbd04de313843e76868e6e13408a94ed6b987245dc7c8506/openpyxl-3.1.5-py2.py3-none-any.whl"; Sha = "5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2" },
    @{ Module = "et_xmlfile"; Url = "https://files.pythonhosted.org/packages/c1/8b/5fe2cc11fee489817272089c4203e679c63b570a5aaeb18d852ae3cbba6a/et_xmlfile-2.0.0-py3-none-any.whl"; Sha = "7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa" },
    @{ Module = "xlrd"; Url = "https://files.pythonhosted.org/packages/1a/62/c8d562e7766786ba6587d09c5a8ba9f718ed3fa8af7f4553e8f91c36f302/xlrd-2.0.2-py2.py3-none-any.whl"; Sha = "ea762c3d29f4cca48d82df517b6d89fbce4db3107f9d78713e48cd321d5c9aa9" }
)

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

function Get-Verified([string]$Source, [string]$Expected, [string]$Destination) {
    Invoke-WebRequest -Uri $Source -OutFile $Destination -UseBasicParsing -TimeoutSec 180
    $actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $Expected) {
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        throw "checksum mismatch for $Source"
    }
}

function Test-Bundled {
    if (-not (Test-Path -LiteralPath $python)) { return $false }
    Push-Location $root
    try {
        & $python -c "import fastdeep_scanner, ssl, sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        Pop-Location
    }
}

$status = "ready"
try {
    if (-not (Test-Path -LiteralPath $python)) {
        $archive = Join-Path $env:TEMP "fastdeep-python-$version.zip"
        try {
            Get-Verified $url $sha256 $archive
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
            Expand-Archive -LiteralPath $archive -DestinationPath $target -Force
            $status = "installed"
        } finally {
            if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue }
        }
    }

    # The embeddable build ignores PYTHONPATH and the working directory and reads
    # its search path only from this file. Without "..", "python -m
    # fastdeep_scanner" cannot find the package; without the deps folder, the
    # Excel readers are invisible to anything that imports them directly.
    $pth = Get-ChildItem -LiteralPath $target -Filter "python*._pth" | Select-Object -First 1
    [IO.File]::WriteAllLines($pth.FullName, @("python312.zip", ".", "..", "..\storage\python-deps"))

    if (-not (Test-Bundled)) { throw "bundled Python failed its self-test" }
} catch {
    Write-Output "failed: $($_.Exception.Message)"
    exit 1
}

# A missing Excel reader only stops index membership from refreshing; prices,
# statements and scanning all still work, so this never fails the step.
New-Item -ItemType Directory -Force -Path $deps | Out-Null
foreach ($wheel in $wheels) {
    if (Test-Path -LiteralPath (Join-Path $deps $wheel.Module)) { continue }
    $file = Join-Path $env:TEMP ("fastdeep-" + $wheel.Module + ".zip")
    try {
        Get-Verified $wheel.Url $wheel.Sha $file
        Expand-Archive -LiteralPath $file -DestinationPath $deps -Force
    } catch {
        $status = "$status (index reader $($wheel.Module) not installed)"
    } finally {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
    }
}

Write-Output $status
exit 0
