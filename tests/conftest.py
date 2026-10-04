"""
Shared setup. The tests need no GPU and leave python/ alone: the patcher runs on copies of
the pristine pinned packages, which are downloaded once into tests/.cache (or the folder
PYTTI_TEST_CACHE names) and checked against their SHA-256 on every run.
"""
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

# pins.py from here; ui, patch_gradio and model_mirror from app/, as launch.bat runs them
sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent / "app")]

from pins import ENDPOINT, INSTALL_BAT, MIRROR_REPO, WHEELS_FOLDER, pinned_version, wheel_pins  # noqa: E402

CACHE = Path(os.environ.get("PYTTI_TEST_CACHE") or Path(__file__).parent / ".cache")


def pytest_configure(config):
    config.addinivalue_line("markers", "mirror: checks the files on the Hugging Face mirror (needs the network)")


def fetch(url):
    """The body at url. Tries three times, as a CI runner's connection can drop."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 2:
                raise
        except (OSError, http.client.HTTPException):
            if attempt == 2:
                raise
        time.sleep(5)


def download(url, dest, sha256):
    """url saved as dest and checked against sha256, unless dest already is that file."""
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha256:
        return dest
    data = fetch(url)
    if hashlib.sha256(data).hexdigest() != sha256:
        pytest.fail(f"{url} doesn't match the SHA-256 {sha256}", pytrace=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(data)
    os.replace(part, dest)
    return dest


def pypi_wheel(package, version):
    """The pure-Python wheel of package==version from PyPI, checked against PyPI's SHA-256."""
    cached = next(CACHE.glob(f"{package}-{version}-*.whl"), None)
    if cached:
        return cached  # checked when it was downloaded
    release = json.loads(fetch(f"https://pypi.org/pypi/{package}/{version}/json"))
    wheel = next(file for file in release["urls"] if file["filename"].endswith("-none-any.whl"))
    return download(wheel["url"], CACHE / wheel["filename"], wheel["digests"]["sha256"])


@pytest.fixture(scope="session")
def pristine(tmp_path_factory):
    """site-packages holding the pinned packages as released: the wheels install.bat installs
    from the mirror, and kornia at the version in app/constraints.txt."""
    wheels = [
        download(f"{ENDPOINT}/{MIRROR_REPO}/resolve/main/{WHEELS_FOLDER}{name}", CACHE / name, sha256)
        for name, sha256 in dict(wheel_pins(INSTALL_BAT)).items()
    ]
    wheels.append(pypi_wheel("kornia", pinned_version("kornia")))
    site = tmp_path_factory.mktemp("pristine") / "python" / "Lib" / "site-packages"
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(site)
    return site
