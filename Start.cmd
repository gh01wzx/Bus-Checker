@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
 call Setup.cmd
 if errorlevel 1 exit /b 1
)
if not exist ".setup-complete" (
 call Setup.cmd
 if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run dashboard.py --server.address 127.0.0.1 %*
if errorlevel 1 (pause & exit /b 1)
