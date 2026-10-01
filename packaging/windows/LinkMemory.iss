#define AppName "Link Memory"
#define AppVersion "0.1.0"
#ifndef StageDir
  #error StageDir must point to the prepared Windows application directory.
#endif
#ifndef OutputDir
  #error OutputDir must point to an output directory.
#endif

[Setup]
AppId={{9D743801-AC30-488C-9F52-1CC6D2F5A0E7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Link Memory
DefaultDirName={localappdata}\Programs\Link Memory
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
DisableProgramGroupPage=yes
WizardStyle=modern dynamic
LicenseFile={#StageDir}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=LinkMemory-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
UninstallDisplayName={#AppName}
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\Start-Link-Memory.vbs"""; WorkingDir: "{app}"
Name: "{autoprograms}\Stop {#AppName}"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\stop.ps1"""; WorkingDir: "{app}"; Flags: runhidden
Name: "{autodesktop}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\Start-Link-Memory.vbs"""; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\Start-Link-Memory.vbs"""; WorkingDir: "{app}"; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\stop.ps1"""; WorkingDir: "{app}"; Flags: runhidden
