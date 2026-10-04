"""
Which folder each model loads from (app/model_mirror.py): the pytti folder's cache/models, or
the user's .cache folder when an earlier version downloaded the model there. And that the
summary a render starts with lists the files the render then fetches. Nothing is downloaded.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

import model_mirror
import presets
import render


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """An empty cache/models and an empty .cache folder, and small sizes for every model file
    (model n is 100 + n bytes), so the tests can put complete and cut-off files in place."""
    sizes = iter(range(100, 1000))

    def small(file):
        return (file[0], file[1], next(sizes))

    clip = {key: small(file) for key, file in model_mirror.CLIP_MODELS.items()}
    monkeypatch.setattr(model_mirror, "CLIP_MODELS", clip)
    monkeypatch.setattr(model_mirror, "_CLIP_SIZES", {Path(file[0]).name: file[2] for file in clip.values()})
    for name in ("ADABINS", "EFFICIENTNET", "GEN_EFFICIENTNET"):
        monkeypatch.setattr(model_mirror, name, small(getattr(model_mirror, name)))
    monkeypatch.setattr(model_mirror, "VQGAN_MODELS", {
        name: (small(config), small(checkpoint)) for name, (config, checkpoint) in model_mirror.VQGAN_MODELS.items()})

    models, user_cache = tmp_path / "pytti" / "cache" / "models", tmp_path / "home" / ".cache"
    monkeypatch.setattr(model_mirror, "MODELS", models)
    monkeypatch.setattr(model_mirror, "USER_CACHE", user_cache)
    # torch.hub's own folder, as torch works it out
    monkeypatch.setenv("TORCH_HOME", str(user_cache / "torch"))
    # The summary uses this module, as render.py would load it with PYTTI_CACHE set
    monkeypatch.setattr(render, "_mirror", model_mirror)
    return SimpleNamespace(models=models, user_cache=user_cache)


def place(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def clip_file(key="ViTB32"):
    path, _, size = model_mirror.CLIP_MODELS[key]
    return Path(path).name, size


# ── Where each model loads from ─────────────────────────────────────────────


@pytest.mark.parametrize("in_user_cache, in_models, loads_from", [
    pytest.param(None, None, "models", id="nowhere yet: downloads to cache/models"),
    pytest.param(0, None, "user_cache", id="complete in .cache: used there"),
    pytest.param(-1, None, "models", id="cut off in .cache: downloads to cache/models"),
    pytest.param(0, 0, "models", id="in both: cache/models"),
    pytest.param(None, -1, "models", id="cut off in cache/models: downloads there again"),
])
def test_clip_folder(folders, in_user_cache, in_models, loads_from):
    """in_user_cache, in_models: None if the file isn't there, else how many bytes it is short."""
    name, size = clip_file()
    for root, short in ((folders.user_cache, in_user_cache), (folders.models, in_models)):
        if short is not None:
            place(root / "clip" / name, size + short)
    assert model_mirror._clip_folder(name) == getattr(folders, loads_from) / "clip"


def test_without_pytti_cache_models_stay_in_dot_cache(folders, monkeypatch):
    """Renders started without the UI, which sets PYTTI_CACHE, use the .cache folder as pytti does."""
    monkeypatch.setattr(model_mirror, "MODELS", None)
    assert model_mirror._clip_folder(clip_file()[0]) == folders.user_cache / "clip"
    assert model_mirror.adabins_folder() == folders.user_cache / "adabins"


def test_depth_model_folders(folders):
    assert model_mirror.adabins_folder() == folders.models / "adabins"
    assert model_mirror.hub_folder() == folders.models / "torch" / "hub"
    place(folders.user_cache / "adabins" / "AdaBins_nyu.pt", model_mirror.ADABINS[2])
    place(folders.user_cache / "torch" / "hub" / "checkpoints" / Path(model_mirror.EFFICIENTNET[0]).name,
          model_mirror.EFFICIENTNET[2])
    assert model_mirror.adabins_folder() == folders.user_cache / "adabins"
    assert model_mirror.hub_folder() == folders.user_cache / "torch" / "hub"


def test_vqgan_folder(folders, tmp_path):
    assert model_mirror.vqgan_folder({"vqgan_model": "coco"}) == folders.models / "vqgan"
    # A preset's own models_parent_dir is used as it is
    own = {"vqgan_model": "coco", "models_parent_dir": str(tmp_path / "models")}
    assert model_mirror.vqgan_folder(own) == tmp_path / "models" / "vqgan"


def test_vqgan_model_an_earlier_version_downloaded(folders):
    place(folders.user_cache / "vqgan" / "coco.ckpt", model_mirror.VQGAN_MODELS["coco"][1][2])
    assert model_mirror.vqgan_folder({"vqgan_model": "coco"}) == folders.user_cache.resolve() / "vqgan"


# ── The summary lists what the render fetches ───────────────────────────────


@pytest.fixture
def fetched(monkeypatch):
    """The files prefetch_models would download, recorded instead."""
    targets = []
    monkeypatch.setattr(model_mirror, "_fetch", lambda file, target, label=None, exact=False: targets.append(Path(target)) or True)
    monkeypatch.setattr(model_mirror, "_fetch_repo", lambda file, repo_dir: targets.append(Path(repo_dir)))
    return targets


def test_the_summary_lists_what_the_render_fetches(folders, fetched):
    settings = {**presets.load_defaults(), "animation_mode": "3D", "ViTL14": True,
                "image_model": "VQGAN", "vqgan_model": "coco"}
    listed = [folder / name for name, _, folder in render._downloads(settings)]
    # The render gets models_parent_dir as Hydra fills in ${user_cache:}
    model_mirror.prefetch_models({**settings, "models_parent_dir": str(folders.user_cache.resolve())})
    assert listed and sorted(listed) == sorted(fetched)


def test_the_summary_leaves_out_models_already_downloaded(folders):
    name, size = clip_file()
    place(folders.user_cache / "clip" / name, size)
    settings = {**presets.load_defaults(), "ViTB32": True}
    assert name not in [listed for listed, _, _ in render._downloads(settings)]
