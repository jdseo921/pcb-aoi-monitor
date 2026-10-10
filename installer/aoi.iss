; Inno Setup script of the internal Windows installer (REQ-SET-012, stage S57; ADR 0007). It wraps the one-folder
; build that installer/aoi.spec makes in dist\AOI-PoC-Inspector. From the repository, on Windows, after that build:
;
;   iscc /DAppVersion=0.x.y installer\aoi.iss  ->  dist\installer\AOI-PoC-Inspector-0.x.y-setup-x64-unsigned.exe
;
; CI compiles it with Inno Setup at the version build.yml pins, passing the version in aoi/config.py, then installs,
; self-tests and uninstalls it (tools/check_installer.py). It is unsigned and internal: it must never go to a customer
; or into a demo, since a release is a signed installer built from a tagged commit after two approvals (Engineering
; standard, "Signing"). The uninstaller removes the program files and shortcuts only: the workspace (AOI_Workspace in
; the user's folder, with settings.json), the demo workspace beside it and the keys in Credential Manager stay.

#ifndef AppVersion
  #error Pass the version in aoi/config.py: iscc /DAppVersion=<version> installer\aoi.iss
#endif
#define AppName "AOI PoC Inspector"
#define AppExe "AOI-PoC-Inspector.exe"
#ifndef BuildDir
  #define BuildDir AddBackslash(SourcePath) + "..\dist\AOI-PoC-Inspector"
#endif
#if !FileExists(BuildDir + "\" + AppExe) || !FileExists(BuildDir + "\THIRD_PARTY_NOTICES.txt")
  #error No build with its THIRD_PARTY_NOTICES.txt: run pyinstaller --noconfirm --clean installer\aoi.spec first
#endif
; What the wizard and the uninstaller say ([Messages] below): %n is a new line, %1 the app's name.
#define Welcome "This will install [name/ver] on this computer.%n%nINTERNAL TEST BUILD, NOT SIGNED. It is for " + \
  "our own tests only and must never go to a customer or into a customer demo: it is not a release. Windows " + \
  "SmartScreen and the User Account Control prompt name no publisher, because the installer is not signed.%n%n" + \
  "Uninstalling removes the program files only, never your workspace (AOI_Workspace in your user folder)."
#define Confirm "Remove %1 from this computer?%n%nOnly the program files are removed. Your workspace " + \
  "(AOI_Workspace in your user folder, or the folder you chose), the demo workspace beside it " + \
  "(AOI_Workspace-Demo), settings.json and every record and image in them stay on this computer. Delete those " + \
  "folders yourself if you no longer need them."
#define Kept "Your workspace, the demo workspace and settings.json were kept."

[Setup]
; Fixed for the life of the product: Windows finds an earlier install by it, to upgrade or remove it.
AppId={{7D122A0A-06CC-4538-A441-BD5D560E2255}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} (internal, unsigned)
; Per machine, into Program Files: only the installer needs admin rights, and the app runs as a standard user
; (Engineering standard, "Offline and least privilege"). Each user's workspace stays in their own folder.
PrivilegesRequired=admin
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
; x64 Windows from Windows 10 build 19044, the oldest the Customers & Launch platform table supports (Windows 10 IoT
; Enterprise LTSC 2021). x64compatible also lets Windows 11 on Arm run the x64 app under emulation, untested so far.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19044
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
DisableWelcomePage=no
SetupLogging=yes
OutputDir=..\dist\installer
OutputBaseFilename=AOI-PoC-Inspector-{#AppVersion}-setup-x64-unsigned

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2={#Welcome}
ConfirmUninstall={#Confirm}
UninstalledAll=%1 was removed from this computer. {#Kept}
UninstalledMost=%1 was removed, but some program files could not be: delete them from its folder yourself. {#Kept}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An upgrade starts from a clean program folder, so no file of the earlier build is left to be loaded by this one.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; The whole one-folder build: the .exe, _internal\, THIRD_PARTY_NOTICES.txt beside the .exe, and in CI's build
; BUILD-INFO.txt and SHA256SUMS.txt.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
; The demo workspace beside the station's, loaded first if it is not there (main.py --demo, REQ-SET-007)
Name: "{autoprograms}\{#AppName} (Demo)"; Filename: "{app}\{#AppExe}"; Parameters: "--demo"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
