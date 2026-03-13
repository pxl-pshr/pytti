"""
pytti Portable UI
=================
Run via launch.bat — do not run directly with system Python.
"""
import os
import re
import subprocess
import threading
from pathlib import Path

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# ---------------------------------------------------------------------------
# Monkey-patch gradio_client bug BEFORE importing gradio.
# gradio_client/utils.py crashes when a JSON schema value is a bool instead
# of a dict (e.g. `"additionalProperties": true`).  We wrap the two broken
# functions so they handle bool/None schemas gracefully.
# ---------------------------------------------------------------------------
import gradio_client.utils as _gc_utils

_orig_get_type = _gc_utils.get_type
def _patched_get_type(schema):
    if not isinstance(schema, dict):
        return "unknown"
    return _orig_get_type(schema)
_gc_utils.get_type = _patched_get_type

_orig_json_schema = _gc_utils._json_schema_to_python_type
def _patched_json_schema(schema, defs):
    if isinstance(schema, bool) or schema is None:
        return "Any"
    return _orig_json_schema(schema, defs)
_gc_utils._json_schema_to_python_type = _patched_json_schema
# ---------------------------------------------------------------------------

import gradio as gr
import yaml

# ---------------------------------------------------------------------------
# Tooltips
# ---------------------------------------------------------------------------
TIPS = {
    "scenes": "Text prompts separated by | — each becomes a scene. The render optimizes toward these descriptions.",
    "scene_prefix": "Prepended to every scene prompt. Useful for style keywords shared across all scenes.",
    "scene_suffix": "Appended to every scene prompt. Useful for negative or quality terms applied globally.",
    "direct_image_prompts": "Path or URL to an image used as a visual prompt (pixel-level guidance).",
    "init_image": "Starting image for the render. Blank = start from noise.",
    "direct_init_weight": "How strongly the init image guides pixel appearance at the start.",
    "semantic_init_weight": "How strongly the init image guides semantic/CLIP content at the start.",
    "image_model": "Limited Palette: fast, painterly. Unlimited Palette: photographic. VQGAN: classic neural style.",
    "vqgan_model": "Which VQGAN codebook to use when image_model is VQGAN. Only affects VQGAN mode.",
    "animation_mode": "off: single image. 2D/3D: camera moves each frame. Video Source: warp to a reference video.",
    "video_path": "Source video for Video Source animation mode.",
    "frame_stride": "How many source video frames to skip between animation frames.",
    "width": "Output image width in pixels.",
    "height": "Output image height in pixels.",
    "translate_x": "Horizontal camera movement per frame. Supports Python expressions with t (frame number).",
    "translate_y": "Vertical camera movement per frame. Supports Python expressions with t.",
    "translate_z_3d": "Forward/back camera movement per frame (3D mode). Supports Python expressions with t.",
    "rotate_2d": "Rotation in degrees per frame (2D mode). Supports Python expressions with t.",
    "rotate_3d": "Quaternion [w, x, y, z] rotation per frame (3D mode). Supports Python expressions with t.",
    "zoom_x_2d": "Horizontal zoom per frame (2D mode). Supports Python expressions with t.",
    "zoom_y_2d": "Vertical zoom per frame (2D mode). Supports Python expressions with t.",
    "lock_camera": "Freeze camera during pre-animation steps so the image develops before motion begins.",
    "field_of_view": "Camera field of view in degrees (3D mode). Lower = telephoto, higher = wide-angle.",
    "near_plane": "Near clipping plane distance (3D mode).",
    "far_plane": "Far clipping plane distance (3D mode).",
    "border_mode": "How edges are handled when the image is warped. wrap = tile, smear = stretch edge pixels.",
    "sampling_mode": "Interpolation quality when warping. bicubic is sharpest.",
    "infill_mode": "How to fill areas revealed by camera movement.",
    "steps_per_scene": "Total optimization steps for the whole scene. More = longer render, more developed image.",
    "steps_per_frame": "Optimization steps before advancing to the next animation frame.",
    "interpolation_steps": "Steps used to blend between scenes during a transition.",
    "pre_animation_steps": "Steps run before animation starts, with camera locked. Lets the image develop first.",
    "cutouts": "Number of random crops used per CLIP evaluation. More = richer gradients, slower.",
    "cut_pow": "Controls cutout size distribution. Higher = more small crops (fine detail).",
    "learning_rate": "Optimizer step size. Leave blank for auto. Lower = more stable but slower.",
    "seed": "Random seed for reproducibility. Leave blank for a random seed each run.",
    "gradient_accumulation_steps": "Accumulate gradients over N steps before updating. Higher = more stable, uses less VRAM.",
    "palette_size": "Number of colors per palette swatch (Limited Palette mode).",
    "palettes": "Number of palette swatches (Limited Palette mode).",
    "gamma": "Gamma correction applied to the palette (Limited Palette mode).",
    "hdr_weight": "Weight for HDR-like contrast enhancement (Limited Palette mode).",
    "palette_normalization_weight": "Keeps palette colors spread across the value range.",
    "random_initial_palette": "Start with a random palette instead of deriving it from the init image.",
    "lock_palette": "Prevent the palette from evolving during the render.",
    "target_palette": "Path to an image — palette colors will be pulled toward this image's colors.",
    "direct_stabilization_weight": "Resist pixel-level change between frames. Keeps the image stable.",
    "semantic_stabilization_weight": "Resist semantic/CLIP-level change between frames.",
    "depth_stabilization_weight": "Resist changes to the depth structure between frames.",
    "edge_stabilization_weight": "Resist changes to edges between frames.",
    "flow_stabilization_weight": "Optical flow stabilization — aligns each frame to the previous one.",
    "flow_long_term_samples": "How many past frames to consider for flow stabilization.",
    "input_audio": "Path to an audio file for audioreactive animation.",
    "file_namespace": "Name of the output subfolder inside images_out/. Change this for each new run.",
    "frames_per_second": "Playback FPS when assembling the final video.",
    "save_every": "Save a frame image every N optimization steps.",
    "display_every": "Update the live preview every N optimization steps.",
    "allow_overwrite": "If disabled, existing output files are kept and new ones are numbered.",
}

# ---------------------------------------------------------------------------
# Paths — all relative to this file so the portable folder can live anywhere
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
CONF_DIR = CONFIG_DIR / "conf"
DEFAULT_YAML = CONFIG_DIR / "default.yaml"
OUTPUTS_DIR = ROOT / "outputs"     # Hydra date hierarchy: outputs/YYYY-MM-DD/HH-MM-SS/images_out/

# The embedded Python is two levels up from app/ (portable/python/python.exe)
PORTABLE_ROOT = ROOT.parent
PYTHON_EXE = PORTABLE_ROOT / "python" / "python.exe"

if not PYTHON_EXE.exists():
    # Fallback: try system Python (for dev use)
    import sys
    PYTHON_EXE = Path(sys.executable)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def get_conf_files():
    files = sorted(CONF_DIR.glob("*.yaml"))
    return [f.name for f in files if not f.name.startswith("_")]


def load_defaults() -> dict:
    return load_yaml(DEFAULT_YAML)


def load_conf(name: str) -> dict:
    path = CONF_DIR / name
    if path.exists():
        return load_yaml(path)
    return {}


def merged_config(conf_name: str) -> dict:
    cfg = load_defaults()
    if conf_name:
        override = load_conf(conf_name)
        cfg.update(override)
    return cfg


# ---------------------------------------------------------------------------
# Render process management
# ---------------------------------------------------------------------------
_proc: subprocess.Popen | None = None
_log_lines: list[str] = []
_running = False


def _stream_output(proc):
    global _running
    for line in iter(proc.stdout.readline, ""):
        _log_lines.append(_ANSI_ESCAPE.sub("", line.rstrip()))
    proc.wait()
    _running = False
    _log_lines.append(f"--- process exited with code {proc.returncode} ---")


def start_render(conf_name: str):
    global _proc, _log_lines, _running
    if _running:
        return "Already running."
    _log_lines = []
    _running = True
    conf_name = conf_name.removesuffix(".yaml")
    _proc = subprocess.Popen(
        [str(PYTHON_EXE), "-m", "pytti.workhorse", f"conf='{conf_name}'"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    t = threading.Thread(target=_stream_output, args=(_proc,), daemon=True)
    t.start()
    return "Render started."


def stop_render():
    global _proc, _running
    if _proc and _running:
        _proc.terminate()
        _running = False
        return "Render stopped."
    return "No render running."


def get_log():
    return "\n".join(_log_lines[-200:])


def _all_output_pngs():
    """Yield all PNG frames from the Hydra date hierarchy."""
    yield from OUTPUTS_DIR.glob("**/images_out/**/*.png")


def get_latest_frame(namespace: str):
    frames = [p for p in _all_output_pngs() if p.parent.name == namespace or namespace in str(p)]
    if not frames:
        return None
    return str(max(frames, key=lambda p: p.stat().st_mtime))



# ---------------------------------------------------------------------------
# Save config helper
# ---------------------------------------------------------------------------

def build_conf_dict(
    scenes, scene_prefix, scene_suffix,
    direct_image_prompts, init_image, direct_init_weight, semantic_init_weight,
    image_model, vqgan_model,
    animation_mode, video_path, frame_stride,
    width, height,
    steps_per_scene, steps_per_frame, interpolation_steps, pre_animation_steps,
    translate_x, translate_y, translate_z_3d, rotate_2d, rotate_3d,
    zoom_x_2d, zoom_y_2d, lock_camera,
    cutouts, cut_pow, learning_rate, seed,
    border_mode, sampling_mode, infill_mode,
    ViTB32, ViTB16, ViTL14, ViTL14_336px, RN50, RN101, RN50x4, RN50x16,
    palette_size, palettes, gamma, hdr_weight, palette_normalization_weight,
    random_initial_palette, lock_palette, target_palette,
    frames_per_second, save_every, display_every, file_namespace, allow_overwrite,
    field_of_view, near_plane, far_plane,
    gradient_accumulation_steps,
    direct_stabilization_weight, semantic_stabilization_weight,
    depth_stabilization_weight, edge_stabilization_weight, flow_stabilization_weight,
    input_audio, flow_long_term_samples,
):
    return {
        "scenes": scenes,
        "scene_prefix": scene_prefix,
        "scene_suffix": scene_suffix,
        "direct_image_prompts": direct_image_prompts,
        "init_image": init_image.replace('"', '').replace("'", ''),
        "direct_init_weight": direct_init_weight,
        "semantic_init_weight": semantic_init_weight,
        "image_model": image_model,
        "vqgan_model": vqgan_model,
        "animation_mode": animation_mode,
        "video_path": video_path.replace('"', '').replace("'", ''),
        "frame_stride": int(frame_stride),
        "width": int(width),
        "height": int(height),
        "steps_per_scene": int(steps_per_scene),
        "steps_per_frame": int(steps_per_frame),
        "interpolation_steps": int(interpolation_steps),
        "pre_animation_steps": int(pre_animation_steps),
        "translate_x": translate_x,
        "translate_y": translate_y,
        "translate_z_3d": translate_z_3d,
        "rotate_2d": rotate_2d,
        "rotate_3d": rotate_3d,
        "zoom_x_2d": zoom_x_2d,
        "zoom_y_2d": zoom_y_2d,
        "lock_camera": lock_camera,
        "cutouts": int(cutouts),
        "cut_pow": float(cut_pow),
        "learning_rate": float(learning_rate) if learning_rate else None,
        "seed": seed,
        "border_mode": border_mode,
        "sampling_mode": sampling_mode,
        "infill_mode": infill_mode,
        "ViTB32": ViTB32,
        "ViTB16": ViTB16,
        "ViTL14": ViTL14,
        "ViTL14_336px": ViTL14_336px,
        "RN50": RN50,
        "RN101": RN101,
        "RN50x4": RN50x4,
        "RN50x16": RN50x16,
        "palette_size": int(palette_size),
        "palettes": int(palettes),
        "gamma": float(gamma),
        "hdr_weight": float(hdr_weight),
        "palette_normalization_weight": float(palette_normalization_weight),
        "random_initial_palette": random_initial_palette,
        "lock_palette": lock_palette,
        "target_palette": target_palette,
        "frames_per_second": int(frames_per_second),
        "save_every": int(save_every),
        "display_every": int(display_every),
        "file_namespace": file_namespace,
        "allow_overwrite": allow_overwrite,
        "field_of_view": int(field_of_view),
        "near_plane": int(near_plane),
        "far_plane": int(far_plane),
        "gradient_accumulation_steps": int(gradient_accumulation_steps),
        "direct_stabilization_weight": direct_stabilization_weight,
        "semantic_stabilization_weight": semantic_stabilization_weight,
        "depth_stabilization_weight": depth_stabilization_weight,
        "edge_stabilization_weight": edge_stabilization_weight,
        "flow_stabilization_weight": flow_stabilization_weight,
        "input_audio": input_audio,
        "flow_long_term_samples": int(flow_long_term_samples),
    }


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

_THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');

/* === SCANLINES === */
body::before {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(
        0deg, transparent, transparent 3px,
        rgba(0,0,0,0.10) 3px, rgba(0,0,0,0.10) 4px
    );
    pointer-events: none;
    z-index: 10000;
}

/* === BASE === */
*, *::before, *::after {
    font-family: 'Share Tech Mono', 'Courier New', monospace !important;
}
body, .gradio-container {
    background: #060f18 !important;
    color: #5fa8be !important;
}
.contain { background: #060f18 !important; }

/* === BLOCKS === */
.block, .form, .label-wrap {
    background: #030c12 !important;
    border-color: #0d3048 !important;
    border-radius: 2px !important;
}

/* === LABELS === */
label > span, .block-label span {
    color: #5fa8be !important;
    text-transform: uppercase;
    font-size: 0.72rem !important;
    letter-spacing: 0.08em;
}

/* === INPUTS === */
input:not([type="checkbox"]):not([type="radio"]), textarea, select {
    background: #020a10 !important;
    border: 1px solid #0d3048 !important;
    color: #00e5ff !important;
    border-radius: 2px !important;
}
input:not([type="checkbox"]):not([type="radio"]):focus, textarea:focus {
    border-color: #00e5ff !important;
    box-shadow: 0 0 8px rgba(0,229,255,0.2) !important;
    outline: none !important;
}
input[type="number"] { color: #00e5ff !important; }
input[type="checkbox"] { accent-color: #00e5ff; appearance: auto; }

/* === DROPDOWN === */
.wrap-inner, ul.options { background: #020a10 !important; border-color: #0d3048 !important; }
ul.options li:hover, ul.options li.selected { background: #0d3048 !important; color: #00e5ff !important; }

/* === TABS === */
.tabs > .tab-nav { background: #030c12 !important; border-bottom: 1px solid #0d3048 !important; }
.tab-nav button {
    color: #5fa8be !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.72rem !important;
    transition: color 0.15s, border-color 0.15s;
}
.tab-nav button:hover { color: #00e5ff !important; border-bottom-color: rgba(0,229,255,0.4) !important; }
.tab-nav button.selected { color: #00e5ff !important; border-bottom: 2px solid #00e5ff !important; }

/* === BUTTONS === */
button.primary {
    background: transparent !important;
    border: 1px solid #00e5ff !important;
    color: #00e5ff !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    border-radius: 2px !important;
    transition: all 0.15s;
    box-shadow: 0 0 8px rgba(0,229,255,0.15);
}
button.primary:hover { background: #00e5ff !important; color: #030c12 !important; box-shadow: 0 0 16px rgba(0,229,255,0.4); }
button.secondary {
    background: transparent !important;
    border: 1px solid #0d3048 !important;
    color: #5fa8be !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    border-radius: 2px !important;
    transition: all 0.15s;
}
button.secondary:hover { border-color: #5fa8be !important; color: #00e5ff !important; }
button.stop {
    background: transparent !important;
    border: 1px solid #ff3a3a !important;
    color: #ff3a3a !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    border-radius: 2px !important;
    transition: all 0.15s;
}
button.stop:hover { background: #ff3a3a !important; color: #030c12 !important; }

/* === HEADINGS === */
h1, h2, h3, .prose h1, .prose h2, .prose h3 {
    color: #00e5ff !important;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: normal !important;
}
p, .prose p { color: #5fa8be !important; }

/* === TOOLTIPS === */
.info { color: #ff6d00 !important; font-size: 0.7rem !important; }

/* === LOG / MONO OUTPUTS === */
#log-box textarea { color: #39ff14 !important; background: #020a10 !important; font-size: 0.75rem !important; }

/* === SCROLLBARS === */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #030c12; }
::-webkit-scrollbar-thumb { background: #0d3048; }
::-webkit-scrollbar-thumb:hover { background: #00e5ff; }
"""

_THEME = gr.themes.Base(primary_hue="cyan", neutral_hue="slate").set(
    body_background_fill="#060f18",
    body_text_color="#5fa8be",
    background_fill_primary="#030c12",
    background_fill_secondary="#020a10",
    border_color_primary="#0d3048",
    color_accent_soft="#0d3048",
    button_primary_background_fill="transparent",
    button_primary_border_color="#00e5ff",
    button_primary_text_color="#00e5ff",
    button_secondary_background_fill="transparent",
    button_secondary_border_color="#0d3048",
    button_secondary_text_color="#5fa8be",
    input_background_fill="#020a10",
    input_border_color="#0d3048",
    shadow_drop="none",
    shadow_spread="0px",
)

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def make_ui():
    cfg = load_defaults()

    with gr.Blocks(title="PyTTI", theme=_THEME, css=_THEME_CSS) as demo:
        gr.HTML("""
        <div style="display:flex; align-items:baseline; justify-content:space-between; padding:12px 0 4px; border-bottom:1px solid #0d3048; margin-bottom:16px;">
            <div>
                <span style="font-family:'Share Tech Mono',monospace; font-size:1.6rem; color:#00e5ff; letter-spacing:0.2em; text-transform:uppercase;">PyTTI</span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#ff6d00; letter-spacing:0.1em; margin-left:8px; vertical-align:super;">BETA</span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.7rem; color:#5fa8be; letter-spacing:0.15em; margin-left:16px;">NEURAL IMAGE SYNTHESIZER</span>
            </div>
        </div>
        """)
        with gr.Tabs():

            # ----------------------------------------------------------------
            # TAB: Prompts
            # ----------------------------------------------------------------
            with gr.Tab("Prompts"):
                scenes = gr.Textbox(label="Scenes", value=cfg.get("scenes", ""), lines=4,
                                    placeholder="A beautiful landscape | A surreal dreamscape",
                                    info=TIPS["scenes"])
                scene_prefix = gr.Textbox(label="Scene Prefix", value=cfg.get("scene_prefix", ""), lines=2, info=TIPS["scene_prefix"])
                scene_suffix = gr.Textbox(label="Scene Suffix", value=cfg.get("scene_suffix", ""), lines=2, info=TIPS["scene_suffix"])
                with gr.Row():
                    direct_image_prompts = gr.Textbox(label="Direct Image Prompts", value=cfg.get("direct_image_prompts", ""), info=TIPS["direct_image_prompts"])
                    init_image = gr.Textbox(label="Init Image Path", value=cfg.get("init_image", ""), info=TIPS["init_image"])
                with gr.Row():
                    direct_init_weight = gr.Textbox(label="Direct Init Weight", value=str(cfg.get("direct_init_weight", "")), info=TIPS["direct_init_weight"])
                    semantic_init_weight = gr.Textbox(label="Semantic Init Weight", value=str(cfg.get("semantic_init_weight", "")), info=TIPS["semantic_init_weight"])

            # ----------------------------------------------------------------
            # TAB: Image & Animation
            # ----------------------------------------------------------------
            with gr.Tab("Image & Animation"):
                # — Model & Mode —
                with gr.Row():
                    image_model    = gr.Dropdown(label="Image Model",    choices=["Limited Palette", "Unlimited Palette", "VQGAN"],        value=cfg.get("image_model", "Limited Palette"), info=TIPS["image_model"],    scale=2)
                    vqgan_model    = gr.Dropdown(label="VQGAN Model",    choices=["sflickr", "imagenet", "coco", "wikiart", "openimages"], value=cfg.get("vqgan_model", "sflickr"),          info=TIPS["vqgan_model"],    scale=2)
                    animation_mode = gr.Dropdown(label="Animation Mode", choices=["off", "Video Source", "2D", "3D"],                      value=cfg.get("animation_mode", "3D"),           info=TIPS["animation_mode"], scale=1)

                # — Dimensions & Video —
                with gr.Row():
                    width        = gr.Number(label="Width",        value=cfg.get("width", 512),         precision=0, info=TIPS["width"],        scale=1)
                    height       = gr.Number(label="Height",       value=cfg.get("height", 512),        precision=0, info=TIPS["height"],       scale=1)
                    frame_stride = gr.Number(label="Frame Stride", value=cfg.get("frame_stride", 1),    precision=0, info=TIPS["frame_stride"], scale=1)
                video_path = gr.Textbox(label="Video Path (Video Source mode)", value=cfg.get("video_path", ""), info=TIPS["video_path"])

                # — Camera Transforms —
                gr.Markdown("### Camera Transforms")
                with gr.Row():
                    translate_x   = gr.Textbox(label="Translate X",     value=str(cfg.get("translate_x",   "0")), info=TIPS["translate_x"])
                    translate_y   = gr.Textbox(label="Translate Y",     value=str(cfg.get("translate_y",   "0")), info=TIPS["translate_y"])
                    translate_z_3d = gr.Textbox(label="Translate Z (3D)", value=str(cfg.get("translate_z_3d", "0")), info=TIPS["translate_z_3d"])
                with gr.Row():
                    rotate_3d  = gr.Textbox(label="Rotate 3D",   value=str(cfg.get("rotate_3d", "[1, 0, 0, 0]")), info=TIPS["rotate_3d"],  scale=3)
                    rotate_2d  = gr.Textbox(label="Rotate 2D",   value=str(cfg.get("rotate_2d", "0")),             info=TIPS["rotate_2d"],  scale=1)
                    zoom_x_2d  = gr.Textbox(label="Zoom X (2D)", value=str(cfg.get("zoom_x_2d", "0")),             info=TIPS["zoom_x_2d"], scale=1)
                    zoom_y_2d  = gr.Textbox(label="Zoom Y (2D)", value=str(cfg.get("zoom_y_2d", "0")),             info=TIPS["zoom_y_2d"], scale=1)
                with gr.Row():
                    lock_camera  = gr.Checkbox(label="Lock Camera", value=cfg.get("lock_camera", True), info=TIPS["lock_camera"], scale=0)
                    field_of_view = gr.Number(label="Field of View", value=cfg.get("field_of_view", 60),    precision=0, info=TIPS["field_of_view"], scale=1)
                    near_plane    = gr.Number(label="Near Plane",    value=cfg.get("near_plane", 2000),     precision=0, info=TIPS["near_plane"],    scale=1)
                    far_plane     = gr.Number(label="Far Plane",     value=cfg.get("far_plane", 12500),     precision=0, info=TIPS["far_plane"],     scale=1)

                # — Edge Handling —
                with gr.Row():
                    border_mode   = gr.Dropdown(label="Border Mode",   choices=["clamp", "mirror", "wrap", "black", "smear"], value=cfg.get("border_mode",   "wrap"),    info=TIPS["border_mode"],   scale=1)
                    sampling_mode = gr.Dropdown(label="Sampling Mode", choices=["nearest", "bilinear", "bicubic"],            value=cfg.get("sampling_mode", "bicubic"), info=TIPS["sampling_mode"], scale=1)
                    infill_mode   = gr.Dropdown(label="Infill Mode",   choices=["mirror", "wrap", "black", "smear"],          value=cfg.get("infill_mode",   "wrap"),    info=TIPS["infill_mode"],   scale=1)

            # ----------------------------------------------------------------
            # TAB: Steps & CLIP
            # ----------------------------------------------------------------
            with gr.Tab("Steps & CLIP"):
                with gr.Row():
                    steps_per_scene = gr.Number(label="Steps per Scene", value=cfg.get("steps_per_scene", 50000), precision=0, info=TIPS["steps_per_scene"])
                    steps_per_frame = gr.Number(label="Steps per Frame", value=cfg.get("steps_per_frame", 80), precision=0, info=TIPS["steps_per_frame"])
                with gr.Row():
                    interpolation_steps = gr.Number(label="Interpolation Steps", value=cfg.get("interpolation_steps", 250), precision=0, info=TIPS["interpolation_steps"])
                    pre_animation_steps = gr.Number(label="Pre-animation Steps", value=cfg.get("pre_animation_steps", 350), precision=0, info=TIPS["pre_animation_steps"])
                with gr.Row():
                    cutouts = gr.Number(label="Cutouts", value=cfg.get("cutouts", 50), precision=0, info=TIPS["cutouts"])
                    cut_pow = gr.Number(label="Cut Power", value=cfg.get("cut_pow", 2.1), info=TIPS["cut_pow"])
                with gr.Row():
                    learning_rate = gr.Textbox(label="Learning Rate (blank = auto)", value=str(cfg.get("learning_rate", "") or ""), info=TIPS["learning_rate"])
                    seed = gr.Textbox(label="Seed (blank = random)", value=str(cfg.get("seed", "")), info=TIPS["seed"])
                gradient_accumulation_steps = gr.Number(label="Gradient Accumulation Steps", value=cfg.get("gradient_accumulation_steps", 2), precision=0, info=TIPS["gradient_accumulation_steps"])

                gr.Markdown("### CLIP Models")
                with gr.Row():
                    ViTB32 = gr.Checkbox(label="ViT-B/32", value=cfg.get("ViTB32", True))
                    ViTB16 = gr.Checkbox(label="ViT-B/16", value=cfg.get("ViTB16", True))
                    ViTL14 = gr.Checkbox(label="ViT-L/14", value=cfg.get("ViTL14", False))
                    ViTL14_336px = gr.Checkbox(label="ViT-L/14@336px", value=cfg.get("ViTL14_336px", False))
                with gr.Row():
                    RN50 = gr.Checkbox(label="RN50", value=cfg.get("RN50", False))
                    RN101 = gr.Checkbox(label="RN101", value=cfg.get("RN101", False))
                    RN50x4 = gr.Checkbox(label="RN50x4", value=cfg.get("RN50x4", True))
                    RN50x16 = gr.Checkbox(label="RN50x16", value=cfg.get("RN50x16", False))

            # ----------------------------------------------------------------
            # TAB: Palette
            # ----------------------------------------------------------------
            with gr.Tab("Palette"):
                with gr.Row():
                    palette_size = gr.Number(label="Palette Size", value=cfg.get("palette_size", 50), precision=0, info=TIPS["palette_size"])
                    palettes = gr.Number(label="Palettes", value=cfg.get("palettes", 18), precision=0, info=TIPS["palettes"])
                with gr.Row():
                    gamma = gr.Number(label="Gamma", value=cfg.get("gamma", 1.5), info=TIPS["gamma"])
                    hdr_weight = gr.Number(label="HDR Weight", value=cfg.get("hdr_weight", 0.35), info=TIPS["hdr_weight"])
                    palette_normalization_weight = gr.Number(label="Palette Normalization Weight", value=cfg.get("palette_normalization_weight", 0.75), info=TIPS["palette_normalization_weight"])
                with gr.Row():
                    random_initial_palette = gr.Checkbox(label="Random Initial Palette", value=cfg.get("random_initial_palette", False), info=TIPS["random_initial_palette"])
                    lock_palette = gr.Checkbox(label="Lock Palette", value=cfg.get("lock_palette", False), info=TIPS["lock_palette"])
                target_palette = gr.Textbox(label="Target Palette", value=cfg.get("target_palette", ""), info=TIPS["target_palette"])

            # ----------------------------------------------------------------
            # TAB: Stabilization & Audio
            # ----------------------------------------------------------------
            with gr.Tab("Stabilization & Audio"):
                with gr.Row():
                    direct_stabilization_weight = gr.Textbox(label="Direct Stabilization Weight", value=str(cfg.get("direct_stabilization_weight", "1")), info=TIPS["direct_stabilization_weight"])
                    semantic_stabilization_weight = gr.Textbox(label="Semantic Stabilization Weight", value=str(cfg.get("semantic_stabilization_weight", "")), info=TIPS["semantic_stabilization_weight"])
                with gr.Row():
                    depth_stabilization_weight = gr.Textbox(label="Depth Stabilization Weight", value=str(cfg.get("depth_stabilization_weight", "")), info=TIPS["depth_stabilization_weight"])
                    edge_stabilization_weight = gr.Textbox(label="Edge Stabilization Weight", value=str(cfg.get("edge_stabilization_weight", "")), info=TIPS["edge_stabilization_weight"])
                    flow_stabilization_weight = gr.Textbox(label="Flow Stabilization Weight", value=str(cfg.get("flow_stabilization_weight", "")), info=TIPS["flow_stabilization_weight"])
                flow_long_term_samples = gr.Number(label="Flow Long-term Samples", value=cfg.get("flow_long_term_samples", 1), precision=0, info=TIPS["flow_long_term_samples"])
                input_audio = gr.Textbox(label="Input Audio Path", value=cfg.get("input_audio", ""), info=TIPS["input_audio"])

            # ----------------------------------------------------------------
            # TAB: Output
            # ----------------------------------------------------------------
            with gr.Tab("Output"):
                with gr.Row():
                    file_namespace = gr.Textbox(label="File Namespace", value=cfg.get("file_namespace", "default"), info=TIPS["file_namespace"])
                    frames_per_second = gr.Number(label="FPS", value=cfg.get("frames_per_second", 30), precision=0, info=TIPS["frames_per_second"])
                with gr.Row():
                    save_every = gr.Number(label="Save Every N Steps", value=cfg.get("save_every", 50), precision=0, info=TIPS["save_every"])
                    display_every = gr.Number(label="Display Every N Steps", value=cfg.get("display_every", 50), precision=0, info=TIPS["display_every"])
                allow_overwrite = gr.Checkbox(label="Allow Overwrite", value=cfg.get("allow_overwrite", False), info=TIPS["allow_overwrite"])

            # ----------------------------------------------------------------
            # TAB: Run
            # ----------------------------------------------------------------
            with gr.Tab("Run"):
                gr.Markdown("### Save & Run")
                with gr.Row():
                    conf_name_input = gr.Textbox(label="Config Name", placeholder="my_run", scale=3)
                    load_conf_dropdown = gr.Dropdown(label="Load Existing Config", choices=get_conf_files(), scale=2)

                with gr.Row():
                    save_btn = gr.Button("Save Config", variant="secondary")
                    run_btn = gr.Button("Start Render", variant="primary")
                    stop_btn = gr.Button("Stop Render", variant="stop")

                status_box = gr.Textbox(label="Status", interactive=False, lines=1)

                gr.Markdown("### Live Log")
                log_box = gr.Textbox(label="Log", lines=20, interactive=False, max_lines=20, elem_id="log-box")

                gr.Markdown("### Latest Frame")
                frame_preview = gr.Image(label="Latest Frame", interactive=False)
                refresh_btn = gr.Button("Refresh")
                timer = gr.Timer(value=3, active=False)


        # ----------------------------------------------------------------
        # All config inputs in order (must match build_conf_dict signature)
        # ----------------------------------------------------------------
        all_inputs = [
            scenes, scene_prefix, scene_suffix,
            direct_image_prompts, init_image, direct_init_weight, semantic_init_weight,
            image_model, vqgan_model,
            animation_mode, video_path, frame_stride,
            width, height,
            steps_per_scene, steps_per_frame, interpolation_steps, pre_animation_steps,
            translate_x, translate_y, translate_z_3d, rotate_2d, rotate_3d,
            zoom_x_2d, zoom_y_2d, lock_camera,
            cutouts, cut_pow, learning_rate, seed,
            border_mode, sampling_mode, infill_mode,
            ViTB32, ViTB16, ViTL14, ViTL14_336px, RN50, RN101, RN50x4, RN50x16,
            palette_size, palettes, gamma, hdr_weight, palette_normalization_weight,
            random_initial_palette, lock_palette, target_palette,
            frames_per_second, save_every, display_every, file_namespace, allow_overwrite,
            field_of_view, near_plane, far_plane,
            gradient_accumulation_steps,
            direct_stabilization_weight, semantic_stabilization_weight,
            depth_stabilization_weight, edge_stabilization_weight, flow_stabilization_weight,
            input_audio, flow_long_term_samples,
        ]

        # ----------------------------------------------------------------
        # Callbacks
        # ----------------------------------------------------------------
        def save_config(*args):
            name = args[0]
            values = args[1:]
            if not name:
                return "Enter a config name first."
            if not name.endswith(".yaml"):
                name += ".yaml"
            data = build_conf_dict(*values)
            path = CONF_DIR / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                f.write("# @package _global_\n")
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
            return f"Saved to config/conf/{name}"

        def run_render(conf_name):
            if not conf_name:
                return "No config name set. Enter a name above."
            name = conf_name if conf_name.endswith(".yaml") else conf_name + ".yaml"
            if not (CONF_DIR / name).exists():
                return f"Config '{name}' not found. Click Save first."
            return start_render(conf_name)

        def refresh(namespace):
            return get_log(), get_latest_frame(namespace)

        def load_existing(name):
            if not name:
                return [gr.update()] * len(all_inputs)
            data = merged_config(name)
            return [
                data.get("scenes", ""),
                data.get("scene_prefix", ""),
                data.get("scene_suffix", ""),
                data.get("direct_image_prompts", ""),
                data.get("init_image", ""),
                str(data.get("direct_init_weight", "") or ""),
                str(data.get("semantic_init_weight", "") or ""),
                data.get("image_model", "Limited Palette"),
                data.get("vqgan_model", "sflickr"),
                data.get("animation_mode", "3D"),
                data.get("video_path", ""),
                data.get("frame_stride", 1),
                data.get("width", 512),
                data.get("height", 512),
                data.get("steps_per_scene", 10000),
                data.get("steps_per_frame", 80),
                data.get("interpolation_steps", 250),
                data.get("pre_animation_steps", 350),
                str(data.get("translate_x", "0")),
                str(data.get("translate_y", "0")),
                str(data.get("translate_z_3d", "0")),
                str(data.get("rotate_2d", "0")),
                str(data.get("rotate_3d", "[1, 0, 0, 0]")),
                str(data.get("zoom_x_2d", "0")),
                str(data.get("zoom_y_2d", "0")),
                data.get("lock_camera", True),
                data.get("cutouts", 50),
                data.get("cut_pow", 2.1),
                str(data.get("learning_rate", "") or ""),
                str(data.get("seed", "")),
                data.get("border_mode", "wrap"),
                data.get("sampling_mode", "bicubic"),
                data.get("infill_mode", "wrap"),
                data.get("ViTB32", True),
                data.get("ViTB16", True),
                data.get("ViTL14", False),
                data.get("ViTL14_336px", False),
                data.get("RN50", False),
                data.get("RN101", False),
                data.get("RN50x4", True),
                data.get("RN50x16", False),
                data.get("palette_size", 50),
                data.get("palettes", 18),
                data.get("gamma", 1.5),
                data.get("hdr_weight", 0.35),
                data.get("palette_normalization_weight", 0.75),
                data.get("random_initial_palette", False),
                data.get("lock_palette", False),
                data.get("target_palette", ""),
                data.get("frames_per_second", 30),
                data.get("save_every", 50),
                data.get("display_every", 50),
                data.get("file_namespace", "default"),
                data.get("allow_overwrite", True),
                data.get("field_of_view", 60),
                data.get("near_plane", 2000),
                data.get("far_plane", 12500),
                data.get("gradient_accumulation_steps", 2),
                str(data.get("direct_stabilization_weight", "1")),
                str(data.get("semantic_stabilization_weight", "") or ""),
                str(data.get("depth_stabilization_weight", "") or ""),
                str(data.get("edge_stabilization_weight", "") or ""),
                str(data.get("flow_stabilization_weight", "") or ""),
                data.get("input_audio", ""),
                data.get("flow_long_term_samples", 1),
            ]

        def run_and_activate_timer(conf_name):
            msg = run_render(conf_name)
            return msg, gr.Timer(active=True)

        def stop_and_deactivate_timer():
            msg = stop_render()
            return msg, gr.Timer(active=False)

        save_btn.click(fn=save_config, inputs=[conf_name_input] + all_inputs, outputs=status_box)
        run_btn.click(fn=run_and_activate_timer, inputs=[conf_name_input], outputs=[status_box, timer])
        stop_btn.click(fn=stop_and_deactivate_timer, outputs=[status_box, timer])
        refresh_btn.click(fn=refresh, inputs=[file_namespace], outputs=[log_box, frame_preview])
        timer.tick(fn=refresh, inputs=[file_namespace], outputs=[log_box, frame_preview])
        load_conf_dropdown.change(fn=load_existing, inputs=[load_conf_dropdown], outputs=all_inputs)

    return demo


if __name__ == "__main__":
    print(f"Using Python: {PYTHON_EXE}")
    demo = make_ui()
    demo.launch(inbrowser=True, show_api=False)
