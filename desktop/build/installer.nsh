; ABOUTME: Tillegg til NSIS-installasjonsprogrammet som lagar snarvegane på nytt ved kvar installasjon.
; ABOUTME: Utan dette forsvinn snarvegane og app-identiteten når appen oppdaterer seg sjølv.

; Ved ei automatisk oppdatering køyrer electron-updater installasjonsfila med --updated.
; Då slettar avinstallasjonssteget både snarvegane og AppUserModelID-registreringa, medan
; installasjonssteget hoppar over å lage dei på nytt (sjå ${ifNot} ${isUpdated} i
; app-builder-lib\templates\nsis\include\installer.nsh). Resultatet er ein app utan snarveg
; på skrivebordet og i startmenyen, og eit oppgåvelinje-ikon Windows ikkje klarar å kople
; til appen. customInstall køyrer heilt til slutt i installasjonen, så her kan me rette det opp.
!macro customInstall
  CreateShortCut "$DESKTOP\${SHORTCUT_NAME}.lnk" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" 0 "" "" "${APP_DESCRIPTION}"
  ClearErrors
  WinShell::SetLnkAUMI "$DESKTOP\${SHORTCUT_NAME}.lnk" "${APP_ID}"

  CreateShortCut "$SMPROGRAMS\${SHORTCUT_NAME}.lnk" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" 0 "" "" "${APP_DESCRIPTION}"
  ClearErrors
  WinShell::SetLnkAUMI "$SMPROGRAMS\${SHORTCUT_NAME}.lnk" "${APP_ID}"

  ; Be skalet lese snarvegane på nytt, slik at ikonet blir oppdatert med ein gong.
  System::Call 'Shell32::SHChangeNotify(i 0x8000000, i 0, i 0, i 0)'
!macroend
