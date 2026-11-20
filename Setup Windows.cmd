@echo off
setlocal DisableDelayedExpansion
where py >nul 2>nul
if not errorlevel 1 (
  py -3.14 "%~dp0tools\setup_windows.py" %*
) else (
  python "%~dp0tools\setup_windows.py" %*
)
if errorlevel 1 (
  echo.
  echo Setup failed. Install 64-bit Python 3.14 from https://www.python.org/downloads/windows/ and retry.
  pause
  exit /b 1
)
echo.
echo Ready. Open Run Span Flex Study.cmd, or run tools\wingstudy.cmd --help.
pause
