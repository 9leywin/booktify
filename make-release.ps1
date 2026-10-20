param(
    [string]$Python = "python",
    [string]$Version = "1.0.0"
)

# Собирает обе версии Booktify и складывает их в release\.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "Сборка приложения…"
& $Python -m PyInstaller --noconfirm --clean --distpath dist-next --workpath build-next booktify.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Сборка установщика…"
& $Python -m PyInstaller --noconfirm --clean --distpath dist-setup --workpath build-setup booktify-installer.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

New-Item -ItemType Directory -Force release | Out-Null
Get-ChildItem release -File | Remove-Item -Force

$portable = Join-Path $PSScriptRoot "release\Booktify-$Version-portable-win64.zip"
Compress-Archive -Path "dist-next\Booktify\Booktify.exe", "dist-next\Booktify\_internal" -DestinationPath $portable

$setup = Join-Path $PSScriptRoot "release\Booktify-$Version-setup.exe"
Copy-Item "dist-setup\BooktifySetup.exe" $setup -Force

Get-FileHash $portable, $setup -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)" } |
    Set-Content -Encoding ASCII (Join-Path $PSScriptRoot "release\SHA256SUMS.txt")

Write-Host "Готово:"
Get-ChildItem release | Select-Object Name, @{n = "МБ"; e = { [math]::Round($_.Length / 1MB, 1) } }
