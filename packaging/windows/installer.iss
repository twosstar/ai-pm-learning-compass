#define AppName "AI PM 学习罗盘"
#define AppExe "AI PM Learning Compass.exe"
#define Publisher "AI PM Learning Compass"

[Setup]
AppId={{8C976D95-C869-4C27-9244-78186FC29F2C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={localappdata}\Programs\AI PM Learning Compass
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutputDir}
OutputBaseFilename=AI-PM-Learning-Compass-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\cloud-compass-icon.ico
Uninstallable=yes
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#StageDir}\AI PM Learning Compass.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\AI PM Learning Compass Update.exe"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Icons]
Name: "{group}\AI PM 学习罗盘"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\AI PM 学习罗盘"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "启动 AI PM 学习罗盘"; Flags: postinstall nowait skipifsilent; Check: not IsUpdateInstall

[Code]
function IsUpdateInstall: Boolean;
begin
  Result := (ParamCount > 0) and (Uppercase(ParamStr(1)) = '/UPDATE');
end;

function IsWebView2Installed: Boolean;
var
  Version: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
    Result := (Version <> '') and (Version <> '0.0.0.0');
  if not Result and RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
    Result := (Version <> '') and (Version <> '0.0.0.0');
  if not Result and RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
    Result := (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := IsWebView2Installed;
  if not Result then
  begin
    MsgBox('需要 Microsoft Edge WebView2 Runtime 才能打开应用。请先安装 WebView2 Runtime，再重新运行此安装程序。', mbInformation, MB_OK);
    ShellExec('open', 'https://developer.microsoft.com/microsoft-edge/webview2/', '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;

// No uninstall deletion rules: learner data in %LOCALAPPDATA%\AI PM Learning Compass is preserved.
