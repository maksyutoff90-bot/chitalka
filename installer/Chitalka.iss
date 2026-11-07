; Inno Setup script for Chitalka.
; Build the app first: python tools/build_exe.py
; Then open this file in Inno Setup Compiler and compile.
; The installer places the app in Program Files; data will be stored in
; %APPDATA%\Chitalka because Program Files is not writable for normal users.

#define MyAppName "Читалка"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Chitalka"
#define MyAppExeName "Chitalka.exe"

[Setup]
AppId={{6F2A5D8E-2F1B-4C6A-9B8E-3D7A6C5B4E21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Chitalka
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename=Chitalka-Setup-{#MyAppVersion}
SetupIconFile=..\data\app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно"; Flags: unchecked

[Files]
Source: "..\dist\Chitalka\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
