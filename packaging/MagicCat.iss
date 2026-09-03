; MagicCat Inno Setup 安装脚本（M7）
; 使用：先运行 scripts\build_package.ps1 产出 dist\MagicCat\，再用 ISCC 编译本文件。
; ISCC 路径示例：C:\Program Files (x86)\Inno Setup 6\ISCC.exe packaging\MagicCat.iss

#define AppName "MagicCat"
#define AppVersion "0.1.0"
#define AppPublisher "MagicCat"
#define AppExeName "MagicCat.exe"

[Setup]
AppId={{8F2A0C0E-3B0A-4D1A-9F2A-2C1E0A0B0C0D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\MagicCat
DefaultGroupName=MagicCat
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist\installer
OutputBaseFilename=MagicCat-Setup-{#AppVersion}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\MagicCat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 MagicCat"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 保留用户数据（%APPDATA%\MagicCat）不删除
