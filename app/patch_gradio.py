"""
patch_gradio.py
---------------
Post-install patches for known bugs in dependencies.

Run once after pip-installing all packages:
    python patch_gradio.py
"""
import pathlib
import sys

SITE_PACKAGES = pathlib.Path(__file__).parent.parent / "python" / "Lib" / "site-packages"

# ── Gradio patches ──────────────────────────────────────────────────────────

GRADIO_TARGET = SITE_PACKAGES / "gradio_client" / "utils.py"

GRADIO_PATCHES = [
    # Patch 1: get_type() guard — returns "unknown" instead of crashing on bool
    (
        'def get_type(schema: dict):\n    if "const" in schema:',
        'def get_type(schema: dict):\n    if not isinstance(schema, dict):\n        return "unknown"\n    if "const" in schema:',
    ),
    # Patch 2: _json_schema_to_python_type() guard — bool/None schema → "Any"
    (
        'def _json_schema_to_python_type(schema: Any, defs) -> str:\n    """Convert the json schema into a python type hint"""\n    if schema == {}:\n        return "Any"',
        'def _json_schema_to_python_type(schema: Any, defs) -> str:\n    """Convert the json schema into a python type hint"""\n    if isinstance(schema, bool) or schema is None:\n        return "Any"\n    if schema == {}:\n        return "Any"',
    ),
]

# ── pytti-core patches: workhorse.py ───────────────────────────────────────

PYTTI_WORKHORSE = SITE_PACKAGES / "pytti" / "workhorse.py"

PYTTI_WORKHORSE_PATCHES = [
    # Suppress redundant _settings.txt dump (UI saves configs as YAML presets)
    (
        '        settings_path = f"{OUTPATH}/{params.file_namespace}/{base_name}_settings.txt"\n'
        '        logger.info(f"Settings saved to {settings_path}")\n'
        '        save_settings(params, settings_path)',
        '        # settings_path = f"{OUTPATH}/{params.file_namespace}/{base_name}_settings.txt"\n'
        '        # logger.info(f"Settings saved to {settings_path}")\n'
        '        # save_settings(params, settings_path)  # suppressed — UI saves YAML presets',
    ),
    # save_every=0 auto-resolves to steps_per_frame
    (
        '    def do_run():\n'
        '\n'
        '        # Phase 1 - reset state\n'
        '        ########################\n'
        '        # clear_rotoscopers()  # what a silly name\n'
        '        ROTOSCOPERS.clear_rotoscopers()',
        '    def do_run():\n'
        '\n'
        '        # Phase 1 - reset state\n'
        '        ########################\n'
        '\n'
        '        # Resolve save_every=0 to match steps_per_frame (auto-sync)\n'
        '        if params.save_every is not None and int(params.save_every) <= 0:\n'
        '            with open_dict(params):\n'
        '                params.save_every = params.steps_per_frame\n'
        '            logger.info(f"save_every auto-set to steps_per_frame ({params.steps_per_frame})")\n'
        '\n'
        '        # clear_rotoscopers()  # what a silly name\n'
        '        ROTOSCOPERS.clear_rotoscopers()',
    ),
    # Pass init_image_pil to DirectImageGuide for breath mode
    (
        '            init_augs=init_augs,\n'
        '            semantic_init_prompt=semantic_init_prompt,\n'
        '        )',
        '            init_augs=init_augs,\n'
        '            semantic_init_prompt=semantic_init_prompt,\n'
        '            init_image_pil=init_image_pil,\n'
        '        )',
    ),
]

# ── pytti-core patches: ImageGuide.py ──────────────────────────────────────

PYTTI_IMAGEGUIDE = SITE_PACKAGES / "pytti" / "ImageGuide.py"

PYTTI_IMAGEGUIDE_PATCHES = [
    # Accept init_image_pil in constructor
    (
        '        init_augs=None,\n'
        '        **optimizer_params,',
        '        init_augs=None,\n'
        '        init_image_pil=None,\n'
        '        **optimizer_params,',
    ),
    # Store init_image_pil
    (
        '        self.init_augs = init_augs\n'
        '\n'
        '    def run_steps(',
        '        self.init_augs = init_augs\n'
        '        self.init_image_pil = init_image_pil\n'
        '\n'
        '    def run_steps(',
    ),
    # Forward init_image_pil in run_steps
    (
        '                semantic_init_prompt=self.semantic_init_prompt,\n'
        '            )',
        '                semantic_init_prompt=self.semantic_init_prompt,\n'
        '                init_image_pil=self.init_image_pil,\n'
        '            )',
    ),
]

# ── pytti-core patches: update_func.py ─────────────────────────────────────

PYTTI_UPDATEFUNC = SITE_PACKAGES / "pytti" / "update_func.py"

PYTTI_UPDATEFUNC_PATCHES = [
    # Accept init_image_pil parameter
    (
        '    init_augs=None,\n'
        '    semantic_init_prompt=None,\n'
        '):',
        '    init_augs=None,\n'
        '    semantic_init_prompt=None,\n'
        '    init_image_pil=None,\n'
        '):',
    ),
    # Zero-pad frame filenames + breath mode blend
    (
        '        filename = f"{OUTPATH}/{file_namespace}/{base_name}_{n}.png"\n'
        '        im.save(filename)',
        '        filename = f"{OUTPATH}/{file_namespace}/{base_name}_{n:04d}.png"\n'
        '\n'
        '        # Breath mode: blend init image with optimized output\n'
        '        breath_mode = getattr(params, "breath_mode", False) if params else False\n'
        '        if breath_mode and init_image_pil is not None:\n'
        '            num_scenes = max(1, len([s for s in params.scenes.split("||") if s.strip()]))\n'
        '            total_frames = max(1, (num_scenes * params.steps_per_scene) // save_every)\n'
        '            progress = min(n / total_frames, 1.0)\n'
        '            init_resized = init_image_pil.resize(im.size, Image.LANCZOS)\n'
        '            im = Image.blend(init_resized, im, alpha=progress)\n'
        '\n'
        '        im.save(filename)',
    ),
]

# ── pytti-core patches: LossOrchestratorClass.py ─────────────────────────────

PYTTI_LOSSORCH = SITE_PACKAGES / "pytti" / "LossAug" / "LossOrchestratorClass.py"

PYTTI_LOSSORCH_PATCHES = [
    # Fix Windows path colons breaking the prompt parser —
    # don't embed full init_image path in loss name
    (
        '                f"init image ({params.init_image})",',
        '                f"init image",',
    ),
]

# ── Apply patches ───────────────────────────────────────────────────────────

def apply_patches(target, patches, label):
    if not target.exists():
        print(f"  SKIP: {target} not found — is {label} installed?")
        return
    text = target.read_text(encoding="utf-8")
    changed = False
    for old, new in patches:
        if old in text:
            text = text.replace(old, new)
            changed = True
            print(f"  Applied: {old[:60].strip()!r}...")
        elif new in text:
            print(f"  Already patched: {old[:60].strip()!r}...")
        else:
            print(f"  NOT FOUND: {old[:60].strip()!r}...")
    if changed:
        target.write_text(text, encoding="utf-8")
        print(f"  {label} patch complete.")
    else:
        print(f"  {label} already up to date.")


if __name__ == "__main__":
    print("Patching gradio_client...")
    apply_patches(GRADIO_TARGET, GRADIO_PATCHES, "gradio_client")
    print("Patching workhorse.py...")
    apply_patches(PYTTI_WORKHORSE, PYTTI_WORKHORSE_PATCHES, "workhorse.py")
    print("Patching ImageGuide.py...")
    apply_patches(PYTTI_IMAGEGUIDE, PYTTI_IMAGEGUIDE_PATCHES, "ImageGuide.py")
    print("Patching update_func.py...")
    apply_patches(PYTTI_UPDATEFUNC, PYTTI_UPDATEFUNC_PATCHES, "update_func.py")
    print("Patching LossOrchestratorClass.py...")
    apply_patches(PYTTI_LOSSORCH, PYTTI_LOSSORCH_PATCHES, "LossOrchestratorClass.py")
