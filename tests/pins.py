"""Where the tests find the repo, and the versions it pins."""
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
INSTALL_BAT = REPO / "install.bat"
LAUNCH_BAT = REPO / "launch.bat"

# PyTTI Portable's mirror on Hugging Face, reached through HF_ENDPOINT as install.bat and
# model_mirror.py reach it. install.bat installs the wheels in its wheels folder.
ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
MIRROR_REPO = "pxlpshr/pytti-models"
WHEELS_FOLDER = "wheels/"


def wheel_pins(path):
    """[(wheel file name, SHA-256)] of every wheel a batch file names, in order."""
    return re.findall(r"([\w.+-]+\.whl)#sha256=([0-9a-f]{64})", path.read_text(encoding="utf-8"))


def pinned_version(package):
    """The version app/constraints.txt pins package to."""
    text = (APP / "constraints.txt").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(package)}==(\S+)", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        raise LookupError(f"app/constraints.txt doesn't pin {package}")
    return match.group(1)
