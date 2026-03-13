"""
patch_gradio.py
---------------
Fixes two bugs in gradio_client/utils.py that crash the ASGI app when
schema values are booleans (valid JSON Schema) rather than dicts.

Run once after pip-installing gradio:
    python patch_gradio.py
"""
import pathlib
import sys

TARGET = pathlib.Path(__file__).parent.parent / "python" / "Lib" / "site-packages" / "gradio_client" / "utils.py"

PATCHES = [
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

if not TARGET.exists():
    print(f"ERROR: {TARGET} not found — is gradio installed?")
    sys.exit(1)

text = TARGET.read_text(encoding="utf-8")
changed = False
for old, new in PATCHES:
    if old in text:
        text = text.replace(old, new)
        changed = True
        print(f"  Applied: {old[:50].strip()!r}...")
    else:
        print(f"  Already patched or not found: {old[:50].strip()!r}...")

if changed:
    TARGET.write_text(text, encoding="utf-8")
    print("gradio_client patch complete.")
else:
    print("gradio_client already up to date.")
