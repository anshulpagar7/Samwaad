; Inno Setup 6 script — Samwaad installer for Windows on ARM64 (Snapdragon) and x64.
; 1) pyinstaller packaging\samwaad.spec   2) python tools\fetch_models.py   3) compile this file with ISCC.exe
#define AppName "Samwaad"
#define AppVersion "1.0.0"

[Setup]
AppId={{8C3F7B1E-5A2D-4E4B-9F7A-5A1D3C0B2E61}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Anshul Pagar
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=Samwaad-Setup-{#AppVersion}
SetupIconFile=..\samwaad\web\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=arm64 x64compatible
ArchitecturesInstallIn64BitMode=arm64 x64compatible
PrivilegesRequired=lowest

[Files]
Source: "..\dist\Samwaad\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; ship the models fetched by tools\fetch_models.py so the app works offline from first launch
Source: "..\models\*"; DestDir: "{app}\models"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Samwaad.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Samwaad.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\Samwaad.exe"; Description: "Launch Samwaad"; Flags: nowait postinstall skipifsilent
