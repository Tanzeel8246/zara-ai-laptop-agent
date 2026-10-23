; CodeHubb Assistant — Inno Setup script (Phase 5).
;
; Per-user install (no admin rights needed) of the PyInstaller onedir
; build produced by packaging\codehubb_assistant.spec:
;   dist\CodeHubbAssistant\  ->  {localappdata}\Programs\CodeHubb Assistant
; Output: dist\CodeHubbAssistant-Setup-<version>.exe
;
; AppVersion MUST match agent\version.py — packaging\build_windows.ps1
; refuses to build when they disagree, and tests\test_version.py checks
; it in CI as well.

#define AppName "CodeHubb Assistant"
#define AppVersion "1.0.9"
#define AppPublisher "CodeHubb"
#define AppExeName "CodeHubbAssistant.exe"

[Setup]
AppId={{B7E2C4D1-5A3F-4C8E-9D2B-1F6A0E5C39D7}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\CodeHubb Assistant
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\dist
OutputBaseFilename=CodeHubbAssistant-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; The whole PyInstaller onedir tree (exe + _internal with sidecar,
; .env.example, tray assets, bundled Chromium, apply_update.ps1).
Source: "..\dist\CodeHubbAssistant\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
