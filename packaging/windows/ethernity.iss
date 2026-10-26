; Wrap the existing PyInstaller directory. No Python installation or administrator access needed.
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif

[Setup]
AppId=MinorGlitch.Ethernity.Desktop
AppName=Ethernity
AppVersion={#AppVersion}
VersionInfoVersion={#BinaryVersion}
AppPublisher=MinorGlitch
AppPublisherURL=https://github.com/MinorGlitch/ethernity
DefaultDirName={localappdata}\Programs\Ethernity Desktop
DefaultGroupName=Ethernity
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=Local\Ethernity.Desktop
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes
WizardStyle=modern
SetupIconFile=..\..\images\ethernity.ico
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\app-{#AppVersion}\ethernity-desktop.exe
OutputBaseFilename={#OutputName}
OutputDir={#OutputDir}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}\app-{#AppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Ethernity"; Filename: "{app}\app-{#AppVersion}\ethernity-desktop.exe"; WorkingDir: "{userdocs}"
Name: "{autodesktop}\Ethernity"; Filename: "{app}\app-{#AppVersion}\ethernity-desktop.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon

[Run]
Filename: "{app}\app-{#AppVersion}\ethernity-desktop.exe"; Description: "Open Ethernity"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\.ethernity-install')) or
     FileExists(ExpandConstant('{app}\installed-version.txt')) then
    Result := 'This folder contains a command-line installation. Choose a different folder.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Entry: TFindRec;
  Directory: String;
  Marker: AnsiString;
begin
  { Remove only older runtimes marked as ours, after the new installation succeeds.
    Unrecognized folders, settings, and files outside the runtime remain untouched. }
  if (CurStep = ssPostInstall) and FindFirst(ExpandConstant('{app}\app-*'), Entry) then
  begin
    try
      repeat
        if ((Entry.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           (Entry.Name <> 'app-{#AppVersion}') then
        begin
          Directory := ExpandConstant('{app}\') + Entry.Name;
          if LoadStringFromFile(Directory + '\.ethernity-desktop', Marker) and
             (Marker = 'MinorGlitch.Ethernity.Desktop') then
            if not DelTree(Directory, True, True, True) then
              Log('Older runtime remains in use: ' + Directory);
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;
