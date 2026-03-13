"""
build_portable.py
=================
Assembles the small (~50MB) distributable folder.
Run this on your machine to produce the dist/ folder, then zip and share it.

The dist/ folder contains NO packages — end users run install.bat once
which downloads everything (~6-8GB) onto their machine.

End user requirements:
    - Windows 10/11
    - NVIDIA GPU (GTX 10xx or newer, RTX 50xx not supported)
    - Git installed (git-scm.com)
    - Internet connection for first-time install

Usage:
    python build_portable.py
"""

import shutil
from pathlib import Path

HERE     = Path(__file__).parent
APP_SRC  = HERE / "app"
DIST_DIR = HERE / "dist"

# ---------------------------------------------------------------------------

def main():
    print("Building distributable...")

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir()

    # Copy app files
    shutil.copytree(APP_SRC, DIST_DIR / "app")
    (DIST_DIR / "app" / "images_out").mkdir(exist_ok=True)
    (DIST_DIR / "app" / "outputs").mkdir(exist_ok=True)
    print("  Copied app/")

    # Write install.bat
    _write_install_bat()
    print("  Wrote install.bat")

    # Write launch.bat
    launch = DIST_DIR / "launch.bat"
    launch.write_text(
        "@echo off\n"
        "cd /d \"%~dp0\"\n"
        "if not exist python\\python.exe (\n"
        "    echo Not installed yet. Please run install.bat first.\n"
        "    pause\n"
        "    exit /b 1\n"
        ")\n"
        "echo Starting pytti...\n"
        "python\\python.exe app\\ui.py\n"
        "pause\n"
    )
    print("  Wrote launch.bat")

    # Write README
    readme = DIST_DIR / "README.txt"
    readme.write_text(
        "pytti Portable\n"
        "==============\n\n"
        "REQUIREMENTS\n"
        "  - Windows 10 or 11\n"
        "  - NVIDIA GPU (GTX 10xx series or newer)\n"
        "    Note: RTX 50xx (Blackwell) is not supported\n"
        "  - Up-to-date NVIDIA drivers\n"
        "  - Git  (https://git-scm.com)\n\n"
        "FIRST TIME SETUP\n"
        "  1. Double-click install.bat\n"
        "  2. Wait ~30-60 minutes (downloads ~6GB of packages)\n"
        "  3. When it says 'Installation complete', close the window\n\n"
        "RUNNING\n"
        "  Double-click launch.bat\n"
        "  A browser window opens automatically\n\n"
        "FIRST RENDER NOTE\n"
        "  The first time you use a VQGAN model it will download\n"
        "  automatically (~1-4GB). Cached after that.\n\n"
        "OUTPUT\n"
        "  Frames are saved to: app\\images_out\\\n"
    )
    print("  Wrote README.txt")

    print(f"\nDone. Distributable folder: {DIST_DIR}")
    print("Zip the 'dist' folder to share.")


def _write_install_bat():
    lines = [
        "@echo off",
        "cd /d \"%~dp0\"",
        "echo.",
        "echo pytti Installer",
        "echo ===============",
        "echo.",
        "",
        "if exist python\\python.exe (",
        "    echo Already installed. Delete the python\\ folder to reinstall.",
        "    pause",
        "    exit /b 0",
        ")",
        "",
        ":: Check git is available",
        "git --version >nul 2>&1",
        "if errorlevel 1 (",
        "    echo ERROR: git is not installed or not on PATH.",
        "    echo Please install git from https://git-scm.com and try again.",
        "    pause",
        "    exit /b 1",
        ")",
        "",
        "echo [1/5] Downloading Python 3.10.11...",
        "powershell -Command \"Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip' -OutFile 'python-embed.zip'\"",
        "if errorlevel 1 goto :error",
        "",
        "echo [2/5] Extracting Python...",
        "powershell -Command \"Expand-Archive -Path 'python-embed.zip' -DestinationPath 'python' -Force\"",
        "if errorlevel 1 goto :error",
        "del python-embed.zip",
        "",
        "echo [3/5] Configuring Python...",
        ":: Write the .pth file directly — enables Lib\\site-packages so pip and packages are found",
        "(",
        "  echo python310.zip",
        "  echo .",
        "  echo Lib\\site-packages",
        "  echo.",
        "  echo import site",
        ") > python\\python310._pth",
        "if errorlevel 1 goto :error",
        "",
        "echo [4/5] Installing pip...",
        "powershell -Command \"Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py'\"",
        "if errorlevel 1 goto :error",
        "python\\python.exe get-pip.py",
        "if errorlevel 1 goto :error",
        "del get-pip.py",
        "",
        "echo [5/5] Installing packages (this will take 20-60 minutes)...",
        "echo      PyTorch is ~4GB - please be patient.",
        "echo.",
        "",
        "echo   Installing setuptools (pinned <70 so pkg_resources is available)...",
        "python\\python.exe -m pip install \"setuptools<70\"",
        "if errorlevel 1 goto :error",
        "",
        "echo   Installing numpy (must be pinned before other packages)...",
        "python\\python.exe -m pip install numpy==1.23.5",
        "if errorlevel 1 goto :error",
        "",
        "echo   Installing PyTorch with CUDA 11.7...",
        "python\\python.exe -m pip install torch==2.0.0 torchvision==0.15.1 torchaudio==2.0.0 --index-url https://download.pytorch.org/whl/cu117",
        "if errorlevel 1 goto :error",
        "",
        "echo   Installing dependencies...",
        (
            "python\\python.exe -m pip install "
            "ipython "
            "scipy "
            "requests "
            "gradio==4.44.1 "
            "pyyaml "
            "omegaconf==2.3.0 "
            "hydra-core==1.3.2 "
            "pytorch-lightning==2.0.1 "
            "kornia==0.6.11 "
            "einops==0.6.0 "
            "imageio-ffmpeg==0.4.8 "
            "transformers==4.24.0 "
            "ftfy==6.1.1 "
            "regex "
            "tqdm "
            "loguru "
            "Pillow==9.4.0 "
            "imageio==2.27.0 "
            "matplotlib==3.7.1 "
            "matplotlib-label-lines==0.5.1 "
            "pandas==1.5.3 "
            "seaborn==0.12.2 "
            "scikit-learn==1.2.2 "
            "adjustText==0.8 "
            "exrex "
            "gdown==4.7.1 "
            "PyGLM "
            "tensorflow==2.10.0"
        ),
        "if errorlevel 1 goto :error",
        "",
        "echo   Installing pytti and model backends (requires git)...",
        "python\\python.exe -m pip install git+https://github.com/pytti-tools/AdaBins.git",
        "if errorlevel 1 goto :error",
        "python\\python.exe -m pip install git+https://github.com/pytti-tools/GMA.git",
        "if errorlevel 1 goto :error",
        "python\\python.exe -m pip install git+https://github.com/pytti-tools/taming-transformers.git",
        "if errorlevel 1 goto :error",
        "python\\python.exe -m pip install git+https://github.com/openai/CLIP.git",
        "if errorlevel 1 goto :error",
        "python\\python.exe -m pip install git+https://github.com/pytti-tools/pytti-core.git",
        "if errorlevel 1 goto :error",
        "",
        "echo   Patching gradio_client schema-parsing bugs...",
        "python\\python.exe app\\patch_gradio.py",
        "if errorlevel 1 goto :error",
        "",
        "echo.",
        "echo ===============================",
        "echo  Installation complete!",
        "echo  You can now run launch.bat",
        "echo ===============================",
        "echo.",
        "pause",
        "exit /b 0",
        "",
        ":error",
        "echo.",
        "echo ERROR: Something went wrong. See above for details.",
        "echo If you need help, copy the error message and report it.",
        "echo.",
        "pause",
        "exit /b 1",
    ]

    (DIST_DIR / "install.bat").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
