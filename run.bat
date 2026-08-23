@echo off
REM Thin wrapper -- all the logic lives in run.py so Windows/macOS/Linux behave identically.
cd /d "%~dp0"
where py >nul 2>nul && (py run.py %*) || (python run.py %*)
