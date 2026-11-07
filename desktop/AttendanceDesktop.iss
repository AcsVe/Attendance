; Inno Setup script - AttendanceDesktopSetup.exe (the desktop edition of IAJ Attendance)
; Build (after PyInstaller):  iscc /DMyAppVersion=2026.11.7 desktop\AttendanceDesktop.iss
; - installs for the current user only (no administrator rights needed) in %LOCALAPPDATA%\Programs
; - the data (%LOCALAPPDATA%\IAJ Attendance) is never touched by an update or by uninstalling
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "IAJ Attendance"
#define MyAppPublisher "AcsVe"
#define MyAppExe "AttendanceDesktop.exe"

[Setup]
AppId={{5C1F7E2A-9B43-4D8E-A6C2-3E7B1D9F4A25}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AttendanceDesktopSetup
SetupIconFile=..\static\icons\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\Arabic.isl")
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
arabic.NetworkShortcut=الحضور والانصراف (للأجهزة على الشبكة)
english.NetworkShortcut=IAJ Attendance (devices on the network)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AttendanceDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "_internal\static\uploads\*"

[Dirs]
Name: "{app}\_internal\static\uploads"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{cm:NetworkShortcut}"; Filename: "{app}\{#MyAppExe}"; Parameters: "--lan"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
