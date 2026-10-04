"""
app/patch_gradio.py against the pristine packages it patches.

launch.bat runs the patcher on every start, and a pytti-core patch that stops applying
stops every launch. Most tests here run a copy of the patcher in a folder laid out like an
install, with app/ beside python/Lib/site-packages, which holds the files it patches.
"""
import os
import shutil
import stat
import subprocess
import sys

import pytest

import patch_gradio
from pins import APP

REQUIRED = patch_gradio.TARGETS
OPTIONAL = patch_gradio.OPTIONAL_TARGETS  # kornia's speed patches, skipped when they don't match
ALL = REQUIRED + OPTIONAL


def label(entry):
    return entry[2]


def relative(target):
    """A file's path in site-packages."""
    return target.relative_to(patch_gradio.SITE_PACKAGES)


def alternatives(olds):
    """A patch's old texts: a single text, or a tuple of alternatives."""
    return (olds,) if isinstance(olds, str) else olds


class Install:
    """A folder laid out like an install, holding a copy of the patcher and of the pristine
    files it patches."""

    def __init__(self, root, pristine):
        self.root = root
        self.site = root / "python" / "Lib" / "site-packages"
        for target, _, _ in ALL:
            self.path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pristine / relative(target), self.path(target))
        app = root / "app"
        app.mkdir()
        shutil.copyfile(APP / "patch_gradio.py", app / "patch_gradio.py")
        for source, _, _ in patch_gradio.ADDED_FILES:
            shutil.copyfile(source, app / source.relative_to(APP))

    def path(self, target):
        """Where this folder keeps a file that patch_gradio.py names."""
        return self.site / relative(target)

    def patch(self, *args):
        """Run the patcher as launch.bat does: (exit code, what it printed)."""
        result = subprocess.run(
            [sys.executable, str(self.root / "app" / "patch_gradio.py"), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return result.returncode, result.stdout + result.stderr

    def files(self):
        """{path: contents} of every file in the folder, to tell whether a run changed any."""
        return {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}


@pytest.fixture
def install(tmp_path, pristine):
    return Install(tmp_path, pristine)


@pytest.fixture(scope="session")
def patched(pristine):
    """{target: its text with every patch applied}, as plan_patches works it out."""
    texts = {}
    for target, patches, name in ALL:
        texts[target], problems = patch_gradio.plan_patches(pristine / relative(target), patches, name)
        assert not problems, problems
    return texts


def alter(path, patches):
    """Change the text one of the patches looks for, as another version of the package might."""
    text = path.read_text(encoding="utf-8")
    for olds, new in patches:
        old = next(old for old in alternatives(olds) if old in text)
        if new not in text:
            middle = len(old) // 2
            path.write_text(text.replace(old, old[:middle] + "# changed\n" + old[middle:]), encoding="utf-8")
            return
    raise AssertionError(f"{path.name}: the pristine file has the new text of every patch")


@pytest.mark.parametrize("entry", ALL, ids=label)
def test_each_patch_applies_once_to_the_pristine_file(pristine, entry):
    target, patches, name = entry
    text = (pristine / relative(target)).read_text(encoding="utf-8")
    for number, (olds, new) in enumerate(patches, 1):
        counts = {old: text.count(old) for old in alternatives(olds)}
        found = [old for old, count in counts.items() if count]
        first_line = alternatives(olds)[0].strip().splitlines()[0]
        assert [counts[old] for old in found] == [1], (
            f"{name}, patch {number} ({first_line!r}): one old text should be found once, "
            f"but its old texts are found {list(counts.values())} times"
        )
        text = text.replace(found[0], new)
    compile(text, str(target), "exec")  # the patched file is still Python
    assert patch_gradio.plan_patches(pristine / relative(target), patches, name) == (text, [])


def test_no_old_text_occurs_in_its_new_text():
    """Such a patch would be applied again on every run."""
    repeated = [
        f"{name}, patch {number}"
        for _, patches, name in ALL
        for number, (olds, new) in enumerate(patches, 1)
        if any(old in new for old in alternatives(olds))
    ]
    assert repeated == []


@pytest.mark.parametrize("entry", ALL, ids=label)
def test_every_old_text_upgrades_to_the_same_result(tmp_path, patched, entry):
    """A file with all patches but one applied, and that one missing or as an earlier version
    of it was written, is patched the same as a pristine file. This is how new and changed
    patches reach an install after a git pull."""
    target, patches, name = entry
    final = patched[target]
    path = tmp_path / target.name
    for number, (olds, new) in enumerate(patches, 1):
        assert final.count(new) == 1, f"{name}, patch {number}: its new text should occur once in the patched file"
        for alternative, old in enumerate(alternatives(olds), 1):
            path.write_text(final.replace(new, old), encoding="utf-8")
            result = patch_gradio.plan_patches(path, patches, name)
            assert result == (final, []), f"{name}, patch {number}, old text {alternative}: {result[1]}"


def test_patching_twice_changes_nothing(install, patched):
    code, output = install.patch()
    assert code == 0, output
    for target, _, name in ALL:
        assert install.path(target).read_text(encoding="utf-8") == patched[target], name
    for source, destination, name in patch_gradio.ADDED_FILES:
        assert install.path(destination).read_text(encoding="utf-8") == source.read_text(encoding="utf-8"), name

    files = install.files()
    code, output = install.patch()
    assert (code, output.strip()) == (0, "All patches already applied.")
    code, output = install.patch("--quiet")  # as launch.bat runs it
    assert (code, output) == (0, "")
    assert install.files() == files


@pytest.mark.parametrize("entry", REQUIRED, ids=label)
def test_a_required_file_that_doesnt_match_changes_nothing(install, entry):
    """pytti-core's patches depend on each other, so one that doesn't apply stops them all."""
    target, patches, name = entry
    alter(install.path(target), patches)
    files = install.files()
    code, output = install.patch()
    assert code == 1, output
    assert name in output  # which file doesn't match
    assert install.files() == files


def test_a_missing_required_file_changes_nothing(install):
    target, _, name = REQUIRED[-1]
    install.path(target).unlink()
    files = install.files()
    code, output = install.patch()
    assert code == 1, output
    assert name in output
    assert install.files() == files


@pytest.mark.parametrize("entry", OPTIONAL, ids=label)
def test_a_kornia_file_that_doesnt_match_is_skipped(install, patched, entry):
    target, patches, name = entry
    alter(install.path(target), patches)
    altered = install.path(target).read_bytes()
    code, output = install.patch()
    assert code == 0, output
    assert name in output  # which speed patch was skipped
    assert install.path(target).read_bytes() == altered
    for other, _, other_name in ALL:
        if other != target:
            assert install.path(other).read_text(encoding="utf-8") == patched[other], other_name


def test_a_read_only_file_changes_nothing(install):
    # The last required file, so the files before it have been written to temp files, which
    # must be deleted again
    path = install.path(REQUIRED[-1][0])
    os.chmod(path, stat.S_IREAD)
    try:
        if os.access(path, os.W_OK):
            pytest.skip("can't make a file read-only here")  # e.g. as root on Linux
        files = install.files()
        code, output = install.patch()
        assert code == 2, output
        assert install.files() == files
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_an_unreadable_file_changes_nothing(install):
    path = install.path(REQUIRED[0][0])
    path.unlink()
    path.mkdir()  # a folder can't be read as a file, like a file another program has locked
    files = install.files()
    code, output = install.patch()
    assert code == 2, output
    assert install.files() == files
