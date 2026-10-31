param([string]$Compiler = "$PSScriptRoot\.build-temp\inno\ISCC.exe")
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path $Compiler)) { throw 'Install Inno Setup 6 and pass its ISCC.exe path with -Compiler.' }
$env:TEMP = Join-Path $PSScriptRoot '.build-temp'
$env:TMP = $env:TEMP
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build-temp\pyinstaller'
& .\.package-venv\Scripts\python.exe -m PyInstaller --noconfirm `
    --distpath .build-temp\installer-payload `
    --workpath .build-temp\pyinstaller-work BatteryViewer.spec
if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
& $Compiler installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
