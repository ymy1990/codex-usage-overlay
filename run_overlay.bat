@echo off
setlocal
cd /d "%~dp0"
if exist "CodexUsageOverlay.exe" (
  wscript.exe //nologo "launch_overlay.vbs"
  goto :eof
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0codex_usage_overlay.py"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    start "" python "%~dp0codex_usage_overlay.py"
  ) else (
    wscript.exe //nologo "%~dp0launch_overlay.vbs"
  )
)
