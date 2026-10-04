"""
The folders the UI uses, found from this file so the portable folder can live anywhere.
"""
import sys
from pathlib import Path


ROOT = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
CONF_DIR = CONFIG_DIR / "conf"
DEFAULT_YAML = CONFIG_DIR / "default.yaml"
OUTPUTS_DIR = ROOT / "outputs"     # Hydra date hierarchy: outputs/YYYY-MM-DD/HH-MM-SS/images_out/

# The embedded Python is two levels up from app/ (portable/python/python.exe)
PORTABLE_ROOT = ROOT.parent
EMBEDDED_PYTHON = PORTABLE_ROOT / "python" / "python.exe"
# Models and Video Source conversions (cache/models, cache/video); install.bat keeps pip's
# downloads here too
CACHE_DIR = PORTABLE_ROOT / "cache"
# Fallback: system Python (for dev use)
PYTHON_EXE = EMBEDDED_PYTHON if EMBEDDED_PYTHON.exists() else Path(sys.executable)
