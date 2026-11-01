#define AppName "设备电量查看器"
#define AppVersion "1.0.1"

[Setup]
AppId={{C25A1A17-6EFA-4B11-B26A-539A87485182}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Clearlove0923
DefaultDirName={localappdata}\Programs\BatteryViewer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist\installer
OutputBaseFilename=BatteryViewer-Setup-{#AppVersion}
UninstallDisplayIcon={app}\BatteryViewer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
SetupIconFile=assets\lightning.ico

[Languages]
Name: "chinesesimplified"; MessagesFile: "installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: ".build-temp\installer-payload\BatteryViewer\BatteryViewer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: ".build-temp\installer-payload\BatteryViewer\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\BatteryViewer.exe"; WorkingDir: "{app}"
Name: "{group}\卸载{#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\BatteryViewer.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\BatteryViewer.exe"; Description: "启动{#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\BatteryViewer.exe"; Parameters: "--uninstall-cleanup"; Flags: runhidden waituntilterminated; RunOnceId: "Cleanup"

[UninstallDelete]
Type: files; Name: "{app}\tray_pid.txt"
