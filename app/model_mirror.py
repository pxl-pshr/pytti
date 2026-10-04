"""
model_mirror.py
---------------
Fetches the models a render needs from PyTTI Portable's mirror on Hugging Face
before pytti loads them.

Each file is saved where the library that uses it looks first (CLIP, AdaBins,
torch.hub, pytti's VQGAN loader), so that library finds it and skips its own
download. A file is moved into place only after its size and SHA-256 match.
Anything that can't be fetched is left to the library, which downloads it from
its original source as before.

patch_gradio.py copies this file into pytti-core as pytti/model_mirror.py, and its
workhorse.py patch calls prefetch_models() before CLIP is loaded.
"""
import contextlib
import hashlib
import os
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from loguru import logger

# HF_ENDPOINT is huggingface_hub's setting for reaching Hugging Face through another host
MIRROR = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/") + "/pxlpshr/pytti-models/resolve/main/"

# Set when the mirror can't be reached at all, so the remaining files go straight to their
# original sources instead of each waiting out the connection timeout
_unreachable = False

# Each file: (path in the mirror repo, SHA-256, size in bytes)
CLIP_MODELS = {  # pytti setting -> file, saved as ~/.cache/clip/<file name>
    "ViTB32": (
        "clip/40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt",
        "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af",
        353976522,
    ),
    "ViTB16": (
        "clip/5806e77cd80f8b59890b7e101eabd078d9fb84e6937f9e85e4ecb61988df416f/ViT-B-16.pt",
        "5806e77cd80f8b59890b7e101eabd078d9fb84e6937f9e85e4ecb61988df416f",
        350837078,
    ),
    "ViTL14": (
        "clip/b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836/ViT-L-14.pt",
        "b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836",
        932768134,
    ),
    "ViTL14_336px": (
        "clip/3035c92b350959924f9f00213499208652fc7ea050643e8b385c2dac08641f02/ViT-L-14-336px.pt",
        "3035c92b350959924f9f00213499208652fc7ea050643e8b385c2dac08641f02",
        934088680,
    ),
    "RN50": (
        "clip/afeb0e10f9e5a86da6080e35cf09123aca3b358a0c3e3b6c78a7b63bc04b6762/RN50.pt",
        "afeb0e10f9e5a86da6080e35cf09123aca3b358a0c3e3b6c78a7b63bc04b6762",
        255827503,
    ),
    "RN101": (
        "clip/8fa8567bab74a42d41c5915025a8e4538c3bdbe8804a470a72f30b0d94fab599/RN101.pt",
        "8fa8567bab74a42d41c5915025a8e4538c3bdbe8804a470a72f30b0d94fab599",
        291791292,
    ),
    "RN50x4": (
        "clip/7e526bd135e493cef0776de27d5f42653e6b4c8bf9e0f653bb11773263205fdd/RN50x4.pt",
        "7e526bd135e493cef0776de27d5f42653e6b4c8bf9e0f653bb11773263205fdd",
        421854225,
    ),
    "RN50x16": (
        "clip/52378b407f34354e150460fe41077663dd5b39c54cd0bfd2b27167a4a06ec9aa/RN50x16.pt",
        "52378b407f34354e150460fe41077663dd5b39c54cd0bfd2b27167a4a06ec9aa",
        661125706,
    ),
    "RN50x64": (
        "clip/be1cfb55d75a9666199fb2206c106743da0f6468c9d327f3e0d0a543a9919d9c/RN50x64.pt",
        "be1cfb55d75a9666199fb2206c106743da0f6468c9d327f3e0d0a543a9919d9c",
        1353500174,
    ),
}
ADABINS = (
    "adabins/AdaBins_nyu.pt",
    "3c917d1b86d058918d4055e70b2cdb9696ec4967bb2d8f05c0051263c1ac9641",
    940558786,
)
# AdaBins builds its encoder with torch.hub from gen-efficientnet: the weights file and
# a snapshot of the repo, unpacked as the folder torch.hub would download it to
EFFICIENTNET = (
    "torch_hub/checkpoints/tf_efficientnet_b5_ap-9e82fae8.pth",
    "9e82fae840d76e8d3d64d363b3dca7678a597e1d086b9affdb78eb3f38a3da16",
    122403150,
)
GEN_EFFICIENTNET = (
    "torch_hub/gen-efficientnet-pytorch-771ce082b2ce6d033f55b3d47c1f77389ad3c180.zip",
    "9d37b77cc82c794d9818ba745124e455af31308f3c4422853eeca491b9a468c1",
    70087,
)
VQGAN_MODELS = {  # vqgan_model -> (config, checkpoint), saved as <name>.yaml and <name>.ckpt
    "coco": (
        (
            "vqgan/coco_first_stage.yaml",
            "17d0c2d9fda59eccade2a6070d833804b759dc817da42c2268be8cf1eb047676",
            458,
        ),
        (
            "vqgan/coco_first_stage.ckpt",
            "106cc20fde571df14afc4349d62218d8213cf47177c682ecaa78a8c28b12f9de",
            296030214,
        ),
    ),
}


def prefetch_models(params):
    """Fetch the mirrored models this render needs that aren't on disk yet."""
    cache = Path.home() / ".cache"
    for key, file in CLIP_MODELS.items():
        if params.get(key):
            _fetch(file, cache / "clip" / Path(file[0]).name, exact=True)

    # pytti loads AdaBins for 3D camera moves, and for depth stabilization when a camera
    # move or an init image gives it a frame to compare against
    mode = params.get("animation_mode")
    depth_weight = str(params.get("depth_stabilization_weight") or "").strip()
    if mode == "3D" or (depth_weight not in ("", "0") and (mode != "off" or params.get("init_image"))):
        import torch

        hub = Path(torch.hub.get_dir())
        _fetch(ADABINS, cache / "adabins" / "AdaBins_nyu.pt", exact=True)
        _fetch(EFFICIENTNET, hub / "checkpoints" / Path(EFFICIENTNET[0]).name, exact=True)
        _fetch_repo(GEN_EFFICIENTNET, hub / "rwightman_gen-efficientnet-pytorch_master")

    name = params.get("vqgan_model")
    if params.get("image_model") == "VQGAN" and name in VQGAN_MODELS:
        folder = Path(params.get("models_parent_dir") or cache) / "vqgan"
        config, checkpoint = VQGAN_MODELS[name]
        _fetch(config, folder / f"{name}.yaml")
        _fetch(checkpoint, folder / f"{name}.ckpt")


def _size(n):
    return f"{n / 2**20:.0f} MB" if n >= 2**20 else f"{max(1, n // 1024)} KB"


def _fetch(file, target, label=None, exact=False):
    """Download one mirrored file to target unless it's already there. Returns True if
    target exists afterwards.

    exact: the file at target must be this one (CLIP, AdaBins, EfficientNet), so one of
    another size is a cut-off download and is replaced.
    """
    global _unreachable
    path, sha256, size = file
    target = Path(target)
    if target.exists() and not (exact and target.is_file() and target.stat().st_size != size):
        return True
    if _unreachable:
        return False
    label = label or target.name
    part = target.with_name(target.name + ".mirror-part")
    logger.info(f"Downloading {label} ({_size(size)}) from the PyTTI model mirror")
    digest, done, shown = hashlib.sha256(), 0, time.monotonic()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(MIRROR + path, timeout=60) as response, open(part, "wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if time.monotonic() - shown > 15:
                    logger.info(f"{label}: {done * 100 // size}% of {_size(size)}")
                    shown = time.monotonic()
        if done != size or digest.hexdigest() != sha256:
            raise ValueError("the download doesn't match its checksum")
        os.replace(part, target)
        return True
    except Exception as e:  # network, disk or checksum: the library's own download takes over
        with contextlib.suppress(OSError):
            part.unlink()
        # No connection at all (DNS, refused, connect timeout, TLS, proxy): skip the rest.
        # An HTTP error or a bad download only affects this file.
        if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
            _unreachable = True
        logger.warning(
            f"Could not get {label} from the PyTTI model mirror ({e}). "
            "It will be downloaded from its original source."
        )
        return False


def _fetch_repo(file, repo_dir):
    """Unpack a mirrored torch.hub code snapshot as the folder torch.hub caches it in.
    AdaBins asks for the master branch (patched in patch_gradio.py), so torch.hub then
    uses this folder without contacting GitHub."""
    if repo_dir.exists():
        return
    try:
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=repo_dir.parent) as temp:
            archive = Path(temp) / "snapshot.zip"
            if not _fetch(file, archive, label=f"{repo_dir.name} code"):
                return
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(temp)
            top = next(p for p in Path(temp).iterdir() if p.is_dir())
            os.replace(top, repo_dir)
    except Exception as e:
        logger.warning(
            f"Could not unpack {repo_dir.name} from the PyTTI model mirror ({e}). "
            "It will be downloaded from its original source."
        )
