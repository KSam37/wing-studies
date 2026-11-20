@echo off
setlocal DisableDelayedExpansion
set "PYTHONHOME="
set "PYTHONPATH="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.14 "%~dp0tools\launch_elastic.py" %*
) else (
  python "%~dp0tools\launch_elastic.py" %*
)
if errorlevel 1 pause
