# Builds dist\Samwaad-Setup-1.0.0.exe — run on the Snapdragon laptop for a native ARM64 installer.
# Needs: scripts\setup.bat done once, and Inno Setup 6 (winget install JRSoftware.InnoSetup)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
& $vpy -m pip install pyinstaller --quiet
& $vpy -m PyInstaller packaging\samwaad.spec --noconfirm --distpath dist --workpath build
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Write-Warning "Inno Setup not found - the app folder is in dist\Samwaad (zip it, or install Inno Setup 6 and re-run)."; exit 0 }
& $iscc packaging\installer.iss
Write-Host "Installer: dist\Samwaad-Setup-1.0.0.exe" -ForegroundColor Green
