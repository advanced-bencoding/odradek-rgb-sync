; Inno Setup script for the Windows player app. Built by packaging\build_windows.ps1.
; Per-user install (no admin rights needed); Start-menu shortcuts; uninstall removes autostart.
#define AppName "Odradek Sync"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0B8C4A-3F2D-4B7E-9A51-0D8F2C7B1E93}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=odradek-sync contributors
DefaultDirName={autopf}\Odradek Sync
DefaultGroupName=Odradek Sync
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=OdradekSync-{#AppVersion}-setup
SetupIconFile=..\..\build\icons\odradek-sync.ico
UninstallDisplayIcon={app}\odradek-sync.exe
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "..\..\build\dist\odradek-sync\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Odradek Sync"; Filename: "{app}\odradek-sync.exe"
Name: "{group}\Stop Odradek Sync"; Filename: "{app}\odradek-sync.exe"; Parameters: "--stop"
Name: "{group}\Odradek Sync log"; Filename: "{app}\odradek-sync.exe"; Parameters: "--open-log"
Name: "{group}\Odradek Sync settings"; Filename: "{app}\odradek-sync.exe"; Parameters: "--open-settings"

[Run]
Filename: "{app}\odradek-sync.exe"; Description: "Start Odradek Sync now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\odradek-sync.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAutostart"
