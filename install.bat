@echo off
setlocal
cd /d "%~dp0"

:: Enable ANSI escape codes (Windows 10+)
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

set "CYAN=%ESC%[96m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "RED=%ESC%[91m"
set "DIM=%ESC%[90m"
set "BOLD=%ESC%[1m"
set "R=%ESC%[0m"

:: The version lives in app\ui.py
for /f "tokens=2 delims== " %%v in ('findstr /b /c:"__version__" app\ui.py') do set "VERSION=%%~v"

cls
echo.
echo  %CYAN%######  #   # ##### ##### ###%R%
echo  %CYAN%#    #  #  #    #     #    # %R%
echo  %CYAN%######   ##     #     #    # %R%
echo  %CYAN%#        #      #     #    # %R%
echo  %CYAN%#        #      #     #   ###%R%
echo.
echo %DIM%  Neural Image Synthesizer  %YELLOW%v%VERSION%%R%
echo.
echo %DIM%  ----------------------------------------%R%
echo.

if exist python\.install-complete goto :already_installed
if not exist python\python.exe goto :install

:: python\ exists without the completion marker: an install made before the marker
:: existed, or one that stopped partway through
python\python.exe -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ['gradio', 'torch', 'pytti']) else 1)" >nul 2>&1
if not errorlevel 1 (
    type nul > python\.install-complete
    goto :already_installed
)
echo %YELLOW%  A previous install did not finish.%R%
echo.
choice /c YN /m "  Delete the python folder and start over"
if errorlevel 2 exit /b 1
rmdir /s /q python
if exist python (
    echo %RED%  Could not delete the python folder. Close PyTTI if it is running and try again.%R%
    echo.
    pause
    exit /b 1
)
goto :install

:already_installed
echo %YELLOW%  Already installed.%R%
echo %DIM%  Delete the python\ folder to reinstall.%R%
echo.
pause
exit /b 0

:install
:: Keep pip away from packages in the user's own Python (AppData), so the install
:: neither depends on them nor uninstalls them
set "PYTHONNOUSERSITE=1"

:: Opening install.bat from inside a ZIP in Explorer extracts only the .bat itself
if not exist app\system_check.ps1 (
    echo %RED%  ERROR: The app folder is missing.%R%
    echo %DIM%  If you opened install.bat from inside a ZIP file, extract the whole ZIP first.%R%
    echo.
    pause
    exit /b 1
)

:: Stop now, not an hour of downloads later, if this PC can't run PyTTI
echo   %BOLD%Checking your system%R%
powershell -NoProfile -ExecutionPolicy Bypass -File app\system_check.ps1
set "CHECK=%errorlevel%"
if "%CHECK%"=="0" goto :checks_passed
echo.
if "%CHECK%"=="20" goto :checks_failed
if "%CHECK%"=="10" (
    choice /c YN /m "  Continue anyway"
) else (
    echo %YELLOW%  The system check could not run.%R%
    echo.
    choice /c YN /m "  Install without checking"
)
if errorlevel 2 exit /b 1
goto :checks_passed

:checks_failed
echo %RED%  This PC can't run PyTTI yet. Fix the problems marked FAIL, then run install.bat again.%R%
echo.
pause
exit /b 1

:checks_passed

:: ---------------------------------------------------------------------------
call :step 1 6 "Downloading Python 3.10.11"
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip' -OutFile 'python-embed.zip'"
if errorlevel 1 goto :error
call :ok

:: ---------------------------------------------------------------------------
call :step 2 6 "Extracting Python"
powershell -Command "Expand-Archive -Path 'python-embed.zip' -DestinationPath 'python' -Force"
if errorlevel 1 goto :error
del python-embed.zip
call :ok

:: ---------------------------------------------------------------------------
call :step 3 6 "Configuring Python"
(
  echo python310.zip
  echo .
  echo Lib\site-packages
  echo.
  echo import site
) > python\python310._pth
if errorlevel 1 goto :error
call :ok

:: ---------------------------------------------------------------------------
call :step 4 6 "Installing pip"
:: The versioned URL appears once pip drops Python 3.10; until then use the current one
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/pip/3.10/get-pip.py' -OutFile 'get-pip.py' } catch { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py' }"
if errorlevel 1 goto :error
python\python.exe get-pip.py
if errorlevel 1 goto :error
del get-pip.py
call :ok

:: ---------------------------------------------------------------------------
call :step 5 6 "Installing packages"
echo.
echo %DIM%       This will take 20-60 minutes.%R%
echo %DIM%       PyTorch alone is ~4GB - please be patient.%R%
echo.

echo %DIM%       [+] setuptools%R%
python\python.exe -m pip install --no-warn-script-location "setuptools<70"
if errorlevel 1 goto :error

echo %DIM%       [+] numpy%R%
python\python.exe -m pip install --no-warn-script-location numpy==1.23.5
if errorlevel 1 goto :error

echo %DIM%       [+] PyTorch + CUDA 11.7%R%
python\python.exe -m pip install --no-warn-script-location torch==2.0.0 torchvision==0.15.1 torchaudio==2.0.0 --index-url https://download.pytorch.org/whl/cu117
if errorlevel 1 goto :error

echo %DIM%       [+] dependencies%R%
:: fastapi/pydantic pinned to versions gradio 4.44.1 works with: newer ones pull in
:: starlette 1.x, which breaks gradio's main page
python\python.exe -m pip install --no-warn-script-location ipython scipy requests gradio==4.44.1 fastapi==0.112.4 pydantic==2.10.6 pyyaml omegaconf==2.3.0 hydra-core==1.3.2 pytorch-lightning==2.0.1 kornia==0.6.11 einops==0.6.0 imageio-ffmpeg==0.4.8 transformers==4.24.0 ftfy==6.1.1 regex tqdm loguru Pillow==9.4.0 imageio==2.27.0 matplotlib==3.7.1 matplotlib-label-lines==0.5.1 pandas==1.5.3 seaborn==0.12.2 scikit-learn==1.2.2 adjustText==0.8 exrex gdown==4.7.1 PyGLM tensorflow==2.10.0
if errorlevel 1 goto :error

echo %DIM%       [+] AdaBins%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/AdaBins.git
if errorlevel 1 goto :error

echo %DIM%       [+] GMA%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/GMA.git
if errorlevel 1 goto :error

echo %DIM%       [+] taming-transformers%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/taming-transformers.git
if errorlevel 1 goto :error

echo %DIM%       [+] CLIP%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/openai/CLIP.git
if errorlevel 1 goto :error

echo %DIM%       [+] pytti-core%R%
:: Pinned: app\patch_gradio.py patches this exact version
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/pytti-core.git@b5070aaeab05204f6eee0ff81c657bc486b9cdce
if errorlevel 1 goto :error

call :ok

:: ---------------------------------------------------------------------------
call :step 6 6 "Applying patches"
python\python.exe app\patch_gradio.py
if errorlevel 1 goto :error
type nul > python\.install-complete
call :ok

:: ---------------------------------------------------------------------------
echo.
echo.
echo %GREEN%  ========================================%R%
echo %GREEN%  ^|                                      ^|%R%
echo %GREEN%  ^|       Installation complete!          ^|%R%
echo %GREEN%  ^|       Run launch.bat to start.        ^|%R%
echo %GREEN%  ^|                                      ^|%R%
echo %GREEN%  ========================================%R%
echo.
pause
exit /b 0

:: ---------------------------------------------------------------------------
:step
echo.
echo   %CYAN%[%~1/%~2]%R% %BOLD%%~3%R%
exit /b 0

:ok
echo   %GREEN%      done.%R%
exit /b 0

:error
echo.
echo %RED%  ========================================%R%
echo %RED%  ^|  ERROR: Something went wrong.        ^|%R%
echo %RED%  ^|  See above for details.               ^|%R%
echo %RED%  ^|                                      ^|%R%
echo %RED%  ^|  Copy the error and report it.        ^|%R%
echo %RED%  ========================================%R%
echo.
pause
exit /b 1
