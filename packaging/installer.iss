; Inno Setup script for Step Converter. Build the folder app first:
;   pyinstaller packaging\step_converter.spec
;   iscc /DAppVersion=0.2.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C3E2A51-9B0F-4C7B-8E44-3F5D2B9A7C10}
AppName=Step Converter
AppVersion={#AppVersion}
AppPublisher=Step Converter
AppPublisherURL=https://github.com/shaguru/Step-Converter
DefaultDirName={autopf}\Step Converter
DefaultGroupName=Step Converter
UninstallDisplayIcon={app}\StepConverter.exe
OutputDir=..\dist
OutputBaseFilename=StepConverter-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\StepConverter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\samples\monkeyGeo.fbx"; DestDir: "{app}\samples"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\tools\README.txt"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{group}\Step Converter"; Filename: "{app}\StepConverter.exe"
Name: "{group}\Example model (monkey)"; Filename: "{app}\samples"
Name: "{group}\Uninstall Step Converter"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Step Converter"; Filename: "{app}\StepConverter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\StepConverter.exe"; Description: "{cm:LaunchProgram,Step Converter}"; Flags: nowait postinstall skipifsilent
