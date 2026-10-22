@echo off
if not exist "%~dp0outputs\master_runs.xlsx" (
  echo Open Run Master Catalog.cmd once to build the workbook.
  pause
  exit /b 1
)
start "" "%~dp0outputs\master_runs.xlsx"
