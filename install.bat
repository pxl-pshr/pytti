@echo off
setlocal
cd /d "%~dp0"

:: Keep pip away from packages in the user's own Python (AppData), so the install
:: neither depends on them nor uninstalls them
set "PYTHONNOUSERSITE=1"

:: Ignore pip settings meant for the user's own Python, which can make every pip step
:: fail: all pip.ini files (pip skips them only for a lowercase nul) and variables that
:: require a virtualenv or install somewhere else
set "PIP_CONFIG_FILE=nul"
set "PIP_REQUIRE_VIRTUALENV="
set "PIP_REQUIRE_VENV="
set "PIP_USER="
set "PIP_TARGET="
set "PIP_PREFIX="

:: Set further down when updating an existing install. An inherited value would make a
:: new install skip steps 1-4
set "PYTTI_UPDATE="

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

:: Opening install.bat from inside a ZIP in Explorer extracts only the .bat itself. Step 6
:: needs deps_rev.txt, so check for it now rather than after the downloads
set "APP_OK=1"
if not exist app\system_check.ps1 set "APP_OK="
if not exist app\deps_rev.txt set "APP_OK="
if not defined APP_OK (
    echo %RED%  ERROR: The app folder is missing or incomplete.%R%
    echo %DIM%  If you opened install.bat from inside a ZIP file, extract the whole ZIP first.%R%
    echo.
    pause
    exit /b 1
)

if not exist python\python.exe goto :install

:: A finished install copies app\deps_rev.txt into its marker, so a different number
:: means the packages in step 5 have changed since
fc /b app\deps_rev.txt python\.install-complete >nul 2>&1
if not errorlevel 1 goto :already_installed

:: Updating in place re-runs steps 5 and 6, which need the pip from step 4. Here and below,
:: || and && treat a negative exit code (a python.exe that can't start) as a failure, which
:: "if errorlevel 1" doesn't
python\python.exe -m pip --version >nul 2>&1 || goto :unfinished
if exist python\.install-complete goto :outdated

:: No marker: an install made before the marker existed, or one that stopped partway through
python\python.exe -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ['gradio', 'torch', 'pytti']) else 1)" >nul 2>&1 && goto :outdated
echo %YELLOW%  A previous install did not finish.%R%
echo.
choice /c YN /m "  Resume it"
if errorlevel 2 goto :start_over
goto :update

:outdated
echo %YELLOW%  The installed packages are out of date.%R%
echo %DIM%  Close PyTTI first if it is running.%R%
echo.
choice /c YN /m "  Update them now"
if errorlevel 2 exit /b 1
goto :update

:unfinished
echo %YELLOW%  A previous install did not finish.%R%
echo.
:start_over
choice /c YN /m "  Delete the python folder and start over"
if errorlevel 2 exit /b 1
rmdir /s /q python
if exist python (
    echo %RED%  Could not delete the python folder. Close PyTTI if it is running and try again.%R%
    echo.
    pause
    exit /b 1
)
echo.
goto :install

:already_installed
echo %YELLOW%  Already installed.%R%
echo %DIM%  Delete the python\ folder to reinstall.%R%
echo.
pause
exit /b 0

:update
:: pip skips the packages already installed at the pinned versions; also remove the
:: downloads an interrupted install can leave behind
set "PYTTI_UPDATE=1"
del /q python-embed.zip get-pip.py 2>nul
echo.

:install
:: Stop now, not an hour of downloads later, if this PC can't run PyTTI. Updates are checked
:: too, as new packages can need a newer driver; -Update leaves out the disk space check
echo   %BOLD%Checking your system%R%
set "CHECK_ARGS="
if defined PYTTI_UPDATE set "CHECK_ARGS=-Update"
powershell -NoProfile -ExecutionPolicy Bypass -File app\system_check.ps1 %CHECK_ARGS%
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
if defined PYTTI_UPDATE echo %DIM%  Your install has not been changed.%R%
echo.
pause
exit /b 1

:checks_passed
:: An update keeps the Python and pip from steps 1-4
if defined PYTTI_UPDATE goto :packages

:: ---------------------------------------------------------------------------
call :step 1 6 "Downloading Python 3.10.11"
:: Downloads here and in step 4 turn off the progress bar, which slows Windows PowerShell
:: down a lot, and turn on TLS 1.2 (3072) for PCs whose .NET still defaults to older protocols
powershell -NoProfile -Command "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip' -OutFile 'python-embed.zip'"
if errorlevel 1 goto :error
call :ok

:: ---------------------------------------------------------------------------
call :step 2 6 "Extracting Python"
powershell -NoProfile -Command "Expand-Archive -Path 'python-embed.zip' -DestinationPath 'python' -Force"
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
powershell -NoProfile -Command "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; try { Invoke-WebRequest -UseBasicParsing -Uri 'https://bootstrap.pypa.io/pip/3.10/get-pip.py' -OutFile 'get-pip.py' } catch { Invoke-WebRequest -UseBasicParsing -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py' }"
if errorlevel 1 goto :error
python\python.exe get-pip.py --no-warn-script-location
if errorlevel 1 goto :error
del get-pip.py
call :ok

:: ---------------------------------------------------------------------------
:: Bump app\deps_rev.txt whenever a pip line in this step changes, so existing installs
:: are offered the update
:packages
call :step 5 6 "Installing packages"
echo.
if defined PYTTI_UPDATE (
    echo %DIM%       Packages that are already up to date are skipped.%R%
) else (
    echo %DIM%       This will take 20-60 minutes.%R%
    echo %DIM%       PyTorch alone is a 3.3 GB download - please be patient.%R%
)
echo.

echo %DIM%       [+] setuptools, wheel%R%
:: The git packages below are built with these. setuptools before 70.1 gets its
:: bdist_wheel command from wheel, which newer wheel releases are set to remove
python\python.exe -m pip install --no-warn-script-location "setuptools<70" wheel==0.48.0
if errorlevel 1 goto :error

echo %DIM%       [+] numpy%R%
python\python.exe -m pip install --no-warn-script-location numpy==1.23.5
if errorlevel 1 goto :error

echo %DIM%       [+] PyTorch + CUDA 12.8%R%
python\python.exe -m pip install --no-warn-script-location torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto :error

echo %DIM%       [+] dependencies%R%
:: Pinned to the versions this release was tested with, numpy again so this step can't
:: move it. fastapi/pydantic: newer ones pull in starlette 1.x, which breaks gradio's
:: main page
python\python.exe -m pip install --no-warn-script-location numpy==1.23.5 ipython==8.39.0 scipy==1.15.3 requests==2.34.2 gradio==4.44.1 fastapi==0.112.4 pydantic==2.10.6 pyyaml==6.0.3 omegaconf==2.3.0 hydra-core==1.3.2 pytorch-lightning==2.0.1 kornia==0.6.11 einops==0.6.0 imageio-ffmpeg==0.4.8 transformers==4.24.0 ftfy==6.1.1 regex==2026.9.29 tqdm==4.70.1 loguru==0.7.3 Pillow==9.4.0 imageio==2.27.0 matplotlib==3.7.1 matplotlib-label-lines==0.5.1 pandas==1.5.3 seaborn==0.12.2 scikit-learn==1.2.2 adjustText==0.8 exrex==0.12.0 gdown==4.7.1 PyGLM==2.8.3 tensorboard==2.10.1
if errorlevel 1 goto :error

:: The git packages are pinned to commits. pip keeps an installed git package whose
:: version matches, even from another commit, so a new commit here reaches existing
:: installs only if the package's version changes too
echo %DIM%       [+] AdaBins%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/AdaBins.git@9b57712c1257d95df2966018952f4b8151cdf88a
if errorlevel 1 goto :error

echo %DIM%       [+] GMA%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/GMA.git@27e8b4ee10067a86f63523ef6a35b4566c296526
if errorlevel 1 goto :error

echo %DIM%       [+] taming-transformers%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/taming-transformers.git@f44c0b1e5b15020054e5e1ca10c465d832fd911b
if errorlevel 1 goto :error

echo %DIM%       [+] CLIP%R%
python\python.exe -m pip install --no-warn-script-location git+https://github.com/openai/CLIP.git@d05afc436d78f1c48dc0dbf8e5980a9d471f35f6
if errorlevel 1 goto :error

echo %DIM%       [+] pytti-core%R%
:: Pinned: app\patch_gradio.py patches this exact version
python\python.exe -m pip install --no-warn-script-location git+https://github.com/pytti-tools/pytti-core.git@b5070aaeab05204f6eee0ff81c657bc486b9cdce
if errorlevel 1 goto :error

call :ok

:: ---------------------------------------------------------------------------
call :step 6 6 "Applying patches"
python\python.exe app\patch_gradio.py
set "PATCH=%errorlevel%"
if not "%PATCH%"=="0" goto :patch_failed
:: copy reports its errors on stdout, so >nul hides them
copy /y app\deps_rev.txt python\.install-complete >nul
if errorlevel 1 (
    echo %RED%  Could not write python\.install-complete.%R%
    goto :error
)
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

:patch_failed
:: patch_gradio.py exits with 2 when it can't read or write a file, and with 1 when
:: pytti-core doesn't match the version its patches expect. The printed command runs
:: without the settings at the top of this file, so -s and --isolated keep the user's own
:: Python packages and pip settings out. --no-build-isolation builds with the setuptools
:: from step 5 instead of starting a second pip, which would read those settings again
echo.
if "%PATCH%"=="2" (
    echo %RED%  Could not patch pytti-core: a file could not be read or written.%R%
    echo %DIM%  Close other PyTTI windows, or wait a minute if antivirus is scanning, then run install.bat again.%R%
) else (
    echo %RED%  Could not patch pytti-core. To reinstall it, open a command prompt in the pytti folder and run:%R%
    echo     python\python.exe -s -m pip install --isolated --no-build-isolation --force-reinstall --no-deps git+https://github.com/pytti-tools/pytti-core.git@b5070aaeab05204f6eee0ff81c657bc486b9cdce
    echo %DIM%  Then run install.bat again. If that fails, delete the python folder and run install.bat again.%R%
)
goto :error

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
