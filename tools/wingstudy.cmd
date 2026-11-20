@echo off
rem Run "python -m wingstudy <command>" in this checkout's registered Ptera environment.
rem   tools\wingstudy.cmd --help        lists the commands
rem   tools\wingstudy.cmd frontier      for example
setlocal DisableDelayedExpansion
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "MPLBACKEND=Agg"
set "MPLCONFIGDIR=%~dp0..\outputs\cache\matplotlib"
set "NUMBA_CACHE_DIR=%LOCALAPPDATA%\WingStudies\numba"
set "OMP_NUM_THREADS=1"
set "OPENBLAS_NUM_THREADS=1"
set "NUMBA_NUM_THREADS=1"
where py >nul 2>nul
if not errorlevel 1 (
  py -3.14 "%~dp0setup_windows.py" --launch %*
) else (
  python "%~dp0setup_windows.py" --launch %*
)
if errorlevel 1 pause
