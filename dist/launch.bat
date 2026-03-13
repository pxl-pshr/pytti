@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: Enable ANSI escape codes (Windows 10+)
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

set "CYAN=%ESC%[96m"
set "YELLOW=%ESC%[93m"
set "RED=%ESC%[91m"
set "DIM=%ESC%[90m"
set "R=%ESC%[0m"

echo.
echo  %CYAN%######  #   # ##### ##### ###%R%
echo  %CYAN%#    #  #  #    #     #    # %R%
echo  %CYAN%######   ##     #     #    # %R%
echo  %CYAN%#        #      #     #    # %R%
echo  %CYAN%#        #      #     #   ###%R%
echo.
echo  %DIM%Neural Image Synthesizer  %YELLOW%v1.0.0-beta%R%
echo.

if not exist python\python.exe (
    echo  %RED%Not installed yet. Please run install.bat first.%R%
    echo.
    pause
    exit /b 1
)

echo  %DIM%Starting...%R%
echo.
python\python.exe app\ui.py
pause
