@echo off
setlocal DisableDelayedExpansion
set "PYTHONHOME="
set "PYTHONPATH="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.14 "%~dp0tools\launch_elastic.py" --frontier --run --scope preserved --workers 4 %*
) else (
  python "%~dp0tools\launch_elastic.py" --frontier --run --scope preserved --workers 4 %*
)
if errorlevel 1 pause
