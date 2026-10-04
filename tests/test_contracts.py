"""Names and values that several files must agree on."""
import ast
from pathlib import PurePosixPath

import model_mirror
import patch_pytti
import ui
from pins import INSTALL_BAT, LAUNCH_BAT, wheel_pins


def assigned(path, name):
    """The literal value a module assigns to name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == name for target in node.targets)
    )


def test_vqgan_models_match_pytti_and_the_mirror(pristine):
    """pytti stops a render with a VQGAN model it doesn't list."""
    pytti_names = assigned(pristine / "pytti" / "image_models" / "vqgan.py", "VQGAN_MODEL_NAMES")
    assert sorted(ui.VQGAN_MODELS) == sorted(pytti_names) == sorted(model_mirror.VQGAN_MODELS)
    # The patched vqgan.py looks up each model's (config, checkpoint) pair by name
    for name, (config, checkpoint) in model_mirror.VQGAN_MODELS.items():
        assert config[0].endswith(".yaml") and checkpoint[0].endswith(".ckpt"), name


def test_clip_models_match_pytti_and_the_mirror(pristine):
    """pytti reads each CLIP model's setting under its name in CLIP's list, without / and - and
    with _ for @ (_sanitize_for_config in pytti/Notebook.py). CLIP uses a model file the mirror
    saved only if it has the SHA-256 that CLIP's own URL for it gives."""
    urls = assigned(pristine / "clip" / "clip.py", "_MODELS")
    settings = {name.replace("/", "").replace("-", "").replace("@", "_"): url for name, url in urls.items()}
    assert sorted(ui.CLIP_MODELS) == sorted(settings) == sorted(model_mirror.CLIP_MODELS)
    for key, (path, sha256, _) in model_mirror.CLIP_MODELS.items():
        assert settings[key].endswith(f"/{sha256}/{PurePosixPath(path).name}"), key


def test_the_ui_reads_the_video_end_the_patch_logs():
    """The Progress box ends at the step the patched workhorse.py logs for a short source video."""
    new = next(new for _, patches, _ in patch_pytti.TARGETS for _, new in patches if "render will end at step" in new)
    match = ui._VIDEO_END_RE.search(new.replace("{n_frames}", "12").replace("{end_step}", "345"))
    assert match and match.group(1) == "345"


def test_reinstall_commands_name_the_wheels_install_bat_installs():
    """When pytti-core can't be patched, install.bat and launch.bat print a command that reinstalls it."""
    installed, printed = wheel_pins(INSTALL_BAT), wheel_pins(LAUNCH_BAT)
    hashes = {}
    for name, sha256 in installed + printed:
        hashes.setdefault(name, set()).add(sha256)
    assert {name: found for name, found in hashes.items() if len(found) > 1} == {}
    assert printed and set(printed) <= set(installed)
