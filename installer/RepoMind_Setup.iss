; RepoMind Setup script (Inno Setup 6).
;
; Build: scripts/build_installer.ps1  (or: ISCC.exe "installer\RepoMind_Setup.iss")
;
; This file MUST stay UTF-8 with a BOM so the Chinese strings below compile to
; Unicode. The portable compiler (6.0.5) used on the dev machine has no Chinese
; language pack, so the wizard messages are English; the finish-page caption is
; our own Chinese string from the [Code] section.
;
; Key design decisions (see docs/后续开发指导/2026-08-06_MCP_ZERO_CONFIG_INSTALLER_PLAN):
;   - PrivilegesRequired=lowest: installs per-user into {localappdata}\RepoMind,
;     no UAC elevation, %USERPROFILE% resolves correctly for both install and uninstall.
;   - Post-install registration is done by a bundled PowerShell script (merge +
;     .bak + atomic, never overwrites the whole config), so no Python is needed.
;   - Uninstall only removes files under {app}; it never touches .claude.json /
;     .claude/settings.json / .codex/config.toml (user data stays put).
;   - No PATH change: configs store the absolute exe path.

#define MyAppName "RepoMind"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "RepoMind"
#define MyAppExeName "repomind-backend.exe"

[Setup]
AppId={{9C3F5E2B-8D1A-4C7E-B3F9-6A0D4E7B2C81}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\RepoMind
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer-output
OutputBaseFilename=RepoMindSetup-{#MyAppVersion}
SetupLogging=yes
Compression=lzma2
SolidCompression=yes
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; 后端 exe 自带预建 demo 索引（阶段 A2），开箱即可 list_repositories。
Source: "..\backend-dist\repomind-backend.exe"; DestDir: "{app}"; Flags: ignoreversion
; 安装后注册脚本（纯 ASCII PowerShell，merge + .bak + 原子写）。
Source: "..\scripts\register_repomind.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
; 内置 demo 源码，方便用户直接查看 10 个演示文件。
; Excludes 与 package_windows.ps1 的"打包 demo 纯净性"检查保持一致（拒绝 __pycache__/pyc/.git）。
; 注意：Excludes 用逗号分隔（Inno Setup 语法），不是分号。
Source: "..\demo\repomind-demo\*"; DestDir: "{app}\demo\repomind-demo"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__,*.pyc,.git"

[UninstallDelete]
; registration-status.txt 是安装时由 register_repomind.ps1 运行时生成的，
; 不在安装清单里，卸载器不会自动删；这里显式删除，避免 {app} 留下空壳文件。
Type: files; Name: "{app}\registration-status.txt"

[Run]
; 安装完成前自动注册到 Claude Code / Codex（-Force 让重装时把 command 更新为当前安装路径）。
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\register_repomind.ps1"" -Force"; WorkingDir: "{app}"; StatusMsg: "正在注册到 Claude Code 与 Codex ..."; Flags: runhidden waituntilterminated

[Code]
var
  RepoMindStatus: String;

function ReadRepoMindStatus: String;
var
  StatusPath: String;
  Lines: TStringList;
  i: Integer;
begin
  Result := 'missing';
  StatusPath := ExpandConstant('{app}\registration-status.txt');
  if not FileExists(StatusPath) then Exit;
  Lines := TStringList.Create;
  try
    Lines.LoadFromFile(StatusPath);
    for i := 0 to Lines.Count - 1 do begin
      if Pos('overall=', Lines[i]) = 1 then begin
        Result := Copy(Lines[i], 9, MaxInt);
        Exit;
      end;
    end;
  finally
    Lines.Free;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    RepoMindStatus := ReadRepoMindStatus;
    if RepoMindStatus = 'ok' then
      WizardForm.FinishedLabel.Caption := 'RepoMind 已安装，并已注册到 Claude Code 与 Codex。' + #13#10 + '请重开 Claude Code / Codex 会话后生效。'
    else
      WizardForm.FinishedLabel.Caption := 'RepoMind 已安装。自动注册未完全成功，' + #13#10 + '请查看 ' + ExpandConstant('{app}\registration-status.txt');
  end;
end;
