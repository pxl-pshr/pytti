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

# ── pytti-core patches ──────────────────────────────────────────────────────

PYTTI_TARGET = SITE_PACKAGES / "pytti" / "workhorse.py"

PYTTI_PATCHES = [
    # Suppress redundant _settings.txt dump (UI saves configs as YAML presets)
    (
        '        settings_path = f"{OUTPATH}/{params.file_namespace}/{base_name}_settings.txt"\n'
        '        logger.info(f"Settings saved to {settings_path}")\n'
        '        save_settings(params, settings_path)',
        '        # settings_path = f"{OUTPATH}/{params.file_namespace}/{base_name}_settings.txt"\n'
        '        # logger.info(f"Settings saved to {settings_path}")\n'
        '        # save_settings(params, settings_path)  # suppressed — UI saves YAML presets',
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
        else:
            print(f"  Already patched or not found: {old[:60].strip()!r}...")
    if changed:
        target.write_text(text, encoding="utf-8")
        print(f"  {label} patch complete.")
    else:
        print(f"  {label} already up to date.")


if __name__ == "__main__":
    print("Patching gradio_client...")
    apply_patches(GRADIO_TARGET, GRADIO_PATCHES, "gradio_client")
    print("Patching pytti-core...")
    apply_patches(PYTTI_TARGET, PYTTI_PATCHES, "pytti-core")
