$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.package-venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw 'A Python environment with PyInstaller is required at .package-venv.' }
foreach ($folder in @('debug','debug\tmp','debug\logs','debug\cache','debug\spec','debug\build')) {
    New-Item -ItemType Directory -Force $folder | Out-Null
}
$env:TEMP = Join-Path $PSScriptRoot 'debug\tmp'
$env:TMP = $env:TEMP
$env:PYTHONPYCACHEPREFIX = Join-Path $PSScriptRoot 'debug\cache\pycache'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'debug\cache\pyinstaller'
& $python -m PyInstaller --noconfirm --onedir --windowed --name BatteryViewerDebug --icon "$PSScriptRoot\assets\lightning.ico" --runtime-hook "$PSScriptRoot\debug_runtime.py" --distpath debug --workpath debug\build --specpath debug\spec launcher.py *> debug\logs\build.log
if ($LASTEXITCODE -ne 0) { Get-Content debug\logs\build.log -Tail 30; throw 'Debug build failed.' }
Write-Output 'Debug EXE: debug\BatteryViewerDebug\BatteryViewerDebug.exe'
