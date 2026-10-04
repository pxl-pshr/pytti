@echo off
setlocal
cd /d "%~dp0"

:: Use only the packages in python\, not ones from the user's own Python (AppData)
set "PYTHONNOUSERSITE=1"

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
:: Installs made before the completion marker existed: accept them if the key packages are
:: there. || also catches a python.exe that can't start (a negative exit code), unlike
:: "if errorlevel 1"
python\python.exe -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ['gradio', 'torch', 'pytti']) else 1)" >nul 2>&1 || (
    echo  %RED%The install did not finish. Run install.bat again.%R%
    echo.
    pause
    exit /b 1
)
type nul > python\.install-complete

:patch
:: Apply any pytti-core patches added since install, e.g. after a git pull
python\python.exe app\patch_gradio.py --quiet
set "PATCH=%errorlevel%"
if "%PATCH%"=="0" goto :check_packages
:: patch_gradio.py exits with 2 when it can't read or write a file, and with 1 when
:: pytti-core doesn't match the version its patches expect. In the printed command, -s and
:: --isolated keep the user's own Python packages and pip settings out, as install.bat does
echo.
if "%PATCH%"=="2" (
    echo  %RED%Could not patch pytti-core: a file could not be read or written.%R%
    echo  %DIM%Close other PyTTI windows, or wait a minute if antivirus is scanning, then run launch.bat again.%R%
) else (
    echo  %RED%Could not patch pytti-core. To reinstall it, open a command prompt in the pytti folder and run:%R%
    echo    python\python.exe -s -m pip install --isolated --force-reinstall --no-deps "pyttitools-core @ https://huggingface.co/pxlpshr/pytti-models/resolve/main/wheels/pyttitools_core-0.0.1-py3-none-any.whl#sha256=b8c5c4f5f3187cf5700861fc7b776f5a79a0e85e8f66ad5b7eb065c17d108267"
    echo  %DIM%Then run launch.bat again. If that fails, delete the python folder and run install.bat again.%R%
)
echo.
pause
exit /b 1

:check_packages
:: install.bat copies app\deps_rev.txt into the marker, so a different number means the
:: packages PyTTI needs have changed since, e.g. after a git pull
fc /b app\deps_rev.txt python\.install-complete >nul 2>&1
if errorlevel 1 (
    echo  %YELLOW%The installed packages are out of date. Run install.bat to update them.%R%
    echo.
)

echo  %DIM%Starting...%R%
echo.
python\python.exe app\ui.py
pause
