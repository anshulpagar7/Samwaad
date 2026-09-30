# Samwaad one-time setup for Windows - Snapdragon X (ARM64) or any x64 laptop.
# Run by scripts\setup.bat (double-click), or:  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
#   -Cpu      also install faster-whisper (CPU speech recognition / benchmark baseline)
#   -Quality  also install IndicTrans2 (best-quality translation, ~1 GB)
param([switch]$Cpu, [switch]$Quality, [switch]$NoShortcut)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Step($m) { Write-Host "`n>> $m" -ForegroundColor Cyan }

$arch = $env:PROCESSOR_ARCHITECTURE
$cpuName = (Get-CimInstance Win32_Processor).Name
$snapdragon = ($arch -eq "ARM64") -or ($cpuName -match "Snapdragon|Qualcomm")
Write-Host "Samwaad setup  |  $cpuName  |  $arch" -ForegroundColor White
if ($snapdragon) { Write-Host "Snapdragon detected - models will run on the Hexagon NPU." -ForegroundColor Green }

Step "Python"
$pyExe = $null; $pyArgs = @()
foreach ($c in @(@("py", "-3.12"), @("py", "-3.11"), @("py", "-3"), @("python"))) {
  $exe = $c[0]; $pa = @($c | Select-Object -Skip 1)
  if (Get-Command $exe -ErrorAction SilentlyContinue) {
    try {
      $v = & $exe @pa -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
      if ($LASTEXITCODE -eq 0 -and [int]$v -ge 310) { $pyExe = $exe; $pyArgs = $pa; break }
    } catch {}
  }
}
if (-not $pyExe) { throw "Python 3.10+ not found. Install it from python.org (on Snapdragon pick the 'Windows installer (ARM64)')." }
$pyArch = & $pyExe @pyArgs -c "import platform;print(platform.machine())"
Write-Host "Using $pyExe $pyArgs ($pyArch)"
if ($snapdragon -and $pyArch -ne "ARM64") {
  Write-Warning "This is x64 Python running under emulation - it cannot use the NPU. Install ARM64 Python from python.org and re-run."
}

Step "Virtual environment"
if (-not (Test-Path ".venv")) { & $pyExe @pyArgs -m venv .venv }
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet

Step "Packages"
& $vpy -m pip install -r requirements.txt --quiet
if ($snapdragon) { & $vpy -m pip install -r requirements-snapdragon.txt --quiet }
if ($Cpu -or -not $snapdragon) { & $vpy -m pip install "faster-whisper>=1.0" --quiet }
if ($Quality) { & $vpy -m pip install torch IndicTransToolkit --quiet }

Step "Models (one-time download - afterwards Samwaad runs with Wi-Fi off)"
$fetchArgs = @()
if ($Cpu) { $fetchArgs += "--cpu" }
if ($Quality) { $fetchArgs += "--quality" }
& $vpy tools\fetch_models.py @fetchArgs

Step "System check"
& $vpy -m samwaad doctor

if (-not $NoShortcut) {
  Step "Shortcuts"
  $ws = New-Object -ComObject WScript.Shell
  foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = $ws.CreateShortcut((Join-Path $dir "Samwaad.lnk"))
    $lnk.TargetPath = Join-Path $Root "scripts\Samwaad.bat"
    $lnk.WorkingDirectory = $Root
    $lnk.WindowStyle = 7   # minimized console; the app opens in its own window
    $lnk.IconLocation = Join-Path $Root "samwaad\web\icon.ico"
    $lnk.Description = "Samwaad - offline classroom AI"
    $lnk.Save()
  }
  Write-Host "Desktop + Start menu shortcuts created."
}

Write-Host "`nDone! Launching Samwaad..." -ForegroundColor Green
Start-Process -FilePath (Join-Path $Root "scripts\Samwaad.bat") -WorkingDirectory $Root -WindowStyle Minimized
