@echo off
REM
cd /d "%~dp0"

:loop
    echo [%date% %time%] Starting voxcoinbot.py…
    python "%~dp0voxcoinbot.py"
    echo [%date% %time%] voxcoinbot.py has ended, restarting…
    timeout /t 5 /nobreak >nul
goto loop
