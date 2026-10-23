@echo off
setlocal
title Remove Zara auto-start

echo.
echo  Removing Zara's scheduled tasks...
echo.

schtasks /delete /tn "Zara" /f >nul 2>&1
if errorlevel 1 (echo    - "Zara" logon task: not found) else (echo    - "Zara" logon task removed)

schtasks /delete /tn "Zara Watchdog" /f >nul 2>&1
if errorlevel 1 (echo    - watchdog: not found) else (echo    - watchdog removed)

powershell -NoProfile -Command ^
  "$l = Join-Path ([Environment]::GetFolderPath('Startup')) 'Zara.lnk';" ^
  "if (Test-Path $l) { Remove-Item $l -Force; Write-Host '    - old Startup shortcut removed' }" 2>nul

echo.
echo  She will no longer start or restart by herself.
echo  (If she is running right now, use STOP.bat to stop her.)
echo.
pause
