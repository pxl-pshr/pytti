@echo off
setlocal
cd /d "%~dp0"

:: Enable ANSI escape codes (Windows 10+)
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

set "CYAN=%ESC%[96m"
set "YELLOW=%ESC%[93m"
set "RED=%ESC%[91m"
set "DIM=%ESC%[90m"
set "R=%ESC%[0m"

:: The version lives in app\ui.py
for /f "tokens=2 delims== " %%v in ('findstr /b /c:"__version__" app\ui.py') do set "VERSION=%%~v"

echo.
echo  %CYAN%######  #   # ##### ##### ###%R%
echo  %CYAN%#    #  #  #    #     #    # %R%
echo  %CYAN%######   ##     #     #    # %R%
echo  %CYAN%#        #      #     #    # %R%
echo  %CYAN%#        #      #     #   ###%R%
echo.
echo  %DIM%Neural Image Synthesizer  %YELLOW%v%VERSION%%R%
echo.

if not exist python\python.exe (
    echo  %RED%Not installed yet. Please run install.bat first.%R%
    echo.
    pause
    exit /b 1
)

if exist python\.install-complete goto :patch
:: Installs made before the completion marker existed: accept them if the key packages are there
python\python.exe -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ['gradio', 'torch', 'pytti']) else 1)" >nul 2>&1
if errorlevel 1 (
    echo  %RED%The install did not finish. Run install.bat again.%R%
    echo.
    pause
    exit /b 1
)
type nul > python\.install-complete

:patch
:: Apply any pytti-core patches added since install, e.g. after a git pull
python\python.exe app\patch_gradio.py --quiet
if errorlevel 1 (
    echo.
    echo  %RED%Could not patch pytti-core. Delete the python folder and run install.bat again.%R%
    echo.
    pause
    exit /b 1
)

echo  %DIM%Starting...%R%
echo.
python\python.exe app\ui.py
pause
