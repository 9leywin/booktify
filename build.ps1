param(
    [string]$Python = "python",
    [switch]$Zip
)

# Build script. Kept ASCII-only on purpose: Windows PowerShell 5.1 reads
# Cyrillic .ps1 files as ANSI and chokes on them.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "Checking PyInstaller..."
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python -c "import PyInstaller" *> $null
$hasPyInstaller = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $previous

if (-not $hasPyInstaller) {
    Write-Host "PyInstaller is not installed."
    Write-Host "Install it once:  $Python -m pip install pyinstaller"
    exit 1
}

# PyInstaller deletes dist\Booktify before building. If an older version
# kept settings/cache in userdata there, move it aside and put it back.
$exeDir = Join-Path $PSScriptRoot "dist\Booktify"
$dataDir = Join-Path $exeDir "userdata"
$backup = Join-Path $PSScriptRoot "dist\.userdata-backup"
$hadData = $false
if (Test-Path $dataDir) {
    Write-Host "Saving user data before build..."
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    Move-Item $dataDir $backup
    $hadData = $true
}

Write-Host "Drawing icon..."
& $Python tools\make_icon.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Building..."
try {
    & $Python -m PyInstaller --noconfirm --clean booktify.spec
    $code = $LASTEXITCODE
}
finally {
    if ($hadData) {
        if (Test-Path $backup) {
            if (Test-Path $dataDir) { Remove-Item $dataDir -Recurse -Force }
            Move-Item $backup $dataDir
            Write-Host "User data restored."
        }
    }
}

if ($code -ne 0) { exit $code }

$out = Join-Path $PSScriptRoot "dist\Booktify"
Write-Host "Done: $out\Booktify.exe"

if ($Zip) {
    $archive = Join-Path $PSScriptRoot "dist\Booktify.zip"
    if (Test-Path $archive) { Remove-Item $archive -Force }
    # userdata (settings and cache) stays out of the archive.
    Compress-Archive -Path (Join-Path $out "Booktify.exe"), (Join-Path $out "_internal") -DestinationPath $archive
    Write-Host "Archive: $archive"
    Write-Host "Extract it from Explorer or a normal PowerShell: extracted files get Medium integrity."
}
