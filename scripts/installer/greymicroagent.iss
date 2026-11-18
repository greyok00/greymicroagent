#define AppName "greymicroagent"
#define AppVersion "0.7.5.1"
#define AppPublisher "grey"
#define AppExeName "greymicroagent.exe"
#define BootstrapName "%WAVE_B_BOOTSTRAP_PS1%"

[Setup]
AppId={{6F2A9D3E-8C47-4B1E-9A55-2C0B10A76440}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputBaseFilename={#AppName}_{#AppVersion}_setup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "payload\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\modules\*"; DestDir: "{app}\modules"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "payload\tui\*"; DestDir: "{app}\tui"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "payload\server\{#BootstrapName}"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "config\port_policy.json"; DestDir: "{app}\config"; Flags: ignoreversion

[Dirs]
Name: "{userappdata}\greymicroagent"; Flags: uninsneveruninstall
Name: "{userappdata}\greymicroagent\models"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\server\{#BootstrapName}"" -FirstRun"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\modules"
Type: filesandordirs; Name: "{app}\tui"
