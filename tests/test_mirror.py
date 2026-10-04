"""
The files PyTTI Portable downloads from its mirror on Hugging Face: every model
app/model_mirror.py lists and every wheel install.bat installs must be there, with the
listed size and SHA-256. .github/workflows/mirror.yml runs these weekly, on demand and when
those lists change.

    python -m pytest tests -m mirror
"""
import hashlib
import json
import re
import urllib.request

import pytest

import model_mirror
from pins import ENDPOINT, INSTALL_BAT, MIRROR_REPO, WHEELS_FOLDER, wheel_pins

pytestmark = pytest.mark.mirror


def listed_files():
    """[(path on the mirror, SHA-256, size or None)] of every file model_mirror.py and
    install.bat list. model_mirror.py lists each as (path, SHA-256, size), wherever it keeps it."""
    files = {}

    def collect(value):
        if (isinstance(value, tuple) and len(value) == 3 and isinstance(value[0], str)
                and isinstance(value[1], str) and re.fullmatch(r"[0-9a-f]{64}", value[1]) and isinstance(value[2], int)):
            files[value[0]] = value[1:]
        elif isinstance(value, (tuple, list)):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    for name, value in vars(model_mirror).items():
        if not name.startswith("_"):
            collect(value)
    for wheel, sha256 in wheel_pins(INSTALL_BAT):
        files[WHEELS_FOLDER + wheel] = (sha256, None)  # install.bat doesn't give sizes
    return sorted((path, sha256, size) for path, (sha256, size) in files.items())


@pytest.fixture(scope="module")
def mirror():
    """{path: entry} of every file on the mirror, from Hugging Face's tree API. Files stored with
    Git LFS list their SHA-256 there; the others only a git hash."""
    url = f"{ENDPOINT}/api/models/{MIRROR_REPO}/tree/main?recursive=true"
    files = {}
    while url:
        with urllib.request.urlopen(url, timeout=60) as response:
            files.update((entry["path"], entry) for entry in json.load(response) if entry["type"] == "file")
            # A long listing comes in pages, each linking to the next
            following = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("Link") or "")
        url = following and following.group(1)
    return files


FILES = listed_files()


@pytest.mark.parametrize("path, sha256, size", FILES, ids=[path for path, _, _ in FILES])
def test_file_is_on_the_mirror(mirror, path, sha256, size):
    entry = mirror.get(path)
    assert entry, f"{path} isn't on the mirror"
    if size is not None:
        assert entry["size"] == size
    if "lfs" in entry:
        assert entry["lfs"]["oid"] == sha256
    else:
        with urllib.request.urlopen(f"{ENDPOINT}/{MIRROR_REPO}/resolve/main/{path}", timeout=60) as response:
            data = response.read()
        assert len(data) == entry["size"]
        assert hashlib.sha256(data).hexdigest() == sha256
