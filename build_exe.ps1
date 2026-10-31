$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.package-venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw 'Create .package-venv and install PyInstaller first.' }
New-Item -ItemType Directory -Force .build-temp | Out-Null
$env:TEMP = Join-Path $PSScriptRoot '.build-temp'
$env:TMP = $env:TEMP
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build-temp\pyinstaller'
& $python -m PyInstaller --noconfirm --clean --onedir --windowed --icon assets\lightning.ico --name BatteryViewer launcher.py
if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
