@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Start CodeHubb Assistant

echo.
echo  ============================================
echo    Starting CodeHubb Assistant + enabling auto-start
echo  ============================================
echo.

REM --- 1. make sure it's installed ---
if not exist ".venv\Scripts\python.exe" (
  echo  First time here - installing. This takes a couple of minutes...
  echo.
  call install.bat
)
if not exist ".venv\Scripts\python.exe" (
  echo  [X] Install did not complete. Run install.bat and watch for errors.
  echo.
  pause
  exit /b 1
)

REM --- 2. check .env is filled in (shows a clear reason if not) ---
echo  Checking your settings...
".venv\Scripts\python.exe" -c "from agent.config import validate; import sys; p=validate(); [print('   - '+x) for x in p]; sys.exit(1 if p else 0)"
if errorlevel 1 (
  echo.
  echo  [X] Fix the item(s) above in your .env file, then double-click this again.
  echo.
  notepad ".env"
  pause
  exit /b 1
)
echo  Settings look good.
echo.

REM --- 3. add to Windows startup so she launches hidden every time you log in ---
echo  Enabling auto-start at login...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$link = Join-Path ([Environment]::GetFolderPath('Startup')) 'Zara.lnk';" ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "$s = $w.CreateShortcut($link);" ^
  "$s.TargetPath = 'wscript.exe';" ^
  "$s.Arguments = '\"%~dp0lappilot-hidden.vbs\"';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.Description = 'Zara laptop agent';" ^
  "$s.Save()" >nul 2>&1
echo  Done - she'll start on her own every login from now on.
echo.

REM --- 4. start her right now, hidden (no window to keep open) ---
echo  Starting Zara now...
wscript.exe "%~dp0lappilot-hidden.vbs"

REM --- 5. confirm she actually came up ---
timeout /t 8 /nobreak >nul
tasklist /fi "imagename eq python.exe" 2>nul | find /i "python.exe" >nul
if errorlevel 1 (
  echo.
  echo  [!] Could not confirm Zara is running. Open a normal window with run.bat
  echo      to see any error message.
) else (
  echo.
  echo  ============================================
  echo    Zara is RUNNING in the background.
  echo  ============================================
  echo.
  echo  - Open Discord on your phone and DM the bot:  /help
  echo  - She will auto-start every time you log in.
  echo  - To stop her:            double-click  STOP.bat
  echo  - To stop auto-starting:  double-click  DISABLE_AUTOSTART.bat
)

echo.
echo  You can close this window now.
echo.
pause
