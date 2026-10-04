"""
pytti Portable UI
=================
Run via launch.bat — do not run directly with system Python.

This file builds the page and wires up its buttons. The rest of the app is in the
modules next to it: paths.py (folders), help_text.py (tips and the FAQ tab),
presets.py (presets and their checks), render.py (running renders) and runs.py
(runs on disk and Encode Video).
"""
__version__ = "1.1.0-beta"  # install.bat and launch.bat read this line for their banners
import ctypes
import os
import sys
from pathlib import Path

# Must be set before gradio is imported: no usage telemetry, no version check and no
# message fetch at import time (gr.Blocks(analytics_enabled=False) misses that one)
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

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

# ---------------------------------------------------------------------------
# Keep gradio's requests to the UI's own address away from proxies.
# While launching, gradio requests its own page through httpx and fails when a
# proxy that can't reach this PC answers ("When localhost is not accessible, ...")
# or can't be reached at all. httpx takes its proxy from urllib, which on Windows
# falls back to the proxy set in Windows' settings and ignores its bypass list.
# NO_PROXY can't be used instead: renders inherit os.environ, and on Windows any
# *_proxy variable makes urllib skip that proxy, so model downloads behind it
# would fail.
# ---------------------------------------------------------------------------
import httpx

_THIS_PC = ("127.0.0.1", "localhost", "::1")
def _direct_to_this_pc(request):
    def wrapper(url, *args, **kwargs):
        if httpx.URL(url).host in _THIS_PC:
            kwargs.setdefault("trust_env", False)
        return request(url, *args, **kwargs)
    return wrapper
httpx.get = _direct_to_this_pc(httpx.get)
httpx.head = _direct_to_this_pc(httpx.head)
# ---------------------------------------------------------------------------

import gradio as gr

# The embedded Python doesn't add this file's folder to sys.path, so the modules next to
# it are found through this line
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths
from help_text import TIPS, _build_help_html
from presets import (
    ANIMATION_MODES, BORDER_MODES, CHOICES, CONF_FIELDS, CONF_KEYS, DEFAULTS_CHOICE,
    IMAGE_MODELS, INFILL_MODES, PresetError, SAMPLING_MODES, VQGAN_MODELS, _LEGACY_VQGAN_NAMES,
    _changed_on_disk, _conf_mtime, _conf_name, _listed_name, _not_loaded_here, _num,
    _resolve_references, _unknown_key_notes, conf_problems, load_choices, load_conf,
    load_defaults, long_prompts, missing_files, preset_base, preset_risks, write_conf,
)
import render
from render import _get_eta, get_log, resume_render, start_render, stop_render
from runs import _newest_run, encode_video, get_encodable_runs, get_latest_frame, run_fps


def _text_value(key: str, value) -> str:
    """How a preset value is shown in its textbox."""
    if key in ("scenes", "scene_prefix", "scene_suffix"):
        return " ".join(str(value or "").split())
    if key == "seed":
        return "" if value is None or str(value).startswith("${") else str(value)
    if key.endswith("_weight"):
        return str(value or "")  # 0 and blank both mean off
    return "" if value is None else str(value)  # Learning Rate: only None means auto


def _ui_value(key: str, widget, value, default):
    """Convert a preset value to what its widget shows."""
    if isinstance(widget, gr.Number):
        return _num(value, _num(default, None))
    if isinstance(widget, gr.Checkbox):
        return bool(value)
    if isinstance(widget, gr.Dropdown):
        if key == "animation_mode" and value is False:  # YAML reads a bare `off` as False
            return "off"
        return _LEGACY_VQGAN_NAMES.get(value, value) if key == "vqgan_model" and isinstance(value, str) else value
    return _text_value(key, value)


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

_THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
/* Font loads from Google Fonts; falls back to Courier New / monospace if offline */

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
label > span, .block-label span, label span, .label-wrap span {
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
    padding: 10px !important;
}
input:not([type="checkbox"]):not([type="radio"]):focus, textarea:focus, select:focus {
    border-color: #00e5ff !important;
    box-shadow: 0 0 8px rgba(0,229,255,0.2) !important;
    outline: none !important;
}
input[type="number"] { color: #00e5ff !important; }
input[type="checkbox"] { accent-color: #00e5ff; appearance: auto; }

/* === DROPDOWN === */
.wrap-inner, ul.options { background: #020a10 !important; border-color: #0d3048 !important; }
.wrap-inner span, .wrap-inner input, .secondary-wrap span { color: #00e5ff !important; }
ul.options li { color: #5fa8be !important; }
ul.options li:hover, ul.options li.selected { background: #0d3048 !important; color: #00e5ff !important; }

/* === IMAGE PREVIEW === */
.image-container, .image-frame { background: #020a10 !important; border-color: #0d3048 !important; }

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

/* === COMPACT BUTTONS === */
.btn-sm { max-height: 42px !important; min-height: 42px !important; padding: 0 12px !important; align-self: flex-end !important; }

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

_last_preset: str | None = None  # file name of the preset last loaded or saved, which a page reload brings back


def make_ui():
    cfg = load_defaults()
    # Serve preview frames straight from outputs/ instead of copying each into Gradio's temp cache
    gr.set_static_paths([str(paths.OUTPUTS_DIR)])

    # The log box relies on gr.Textbox's built-in autoscroll, which stops following when the user scrolls up
    with gr.Blocks(title="PyTTI", theme=_THEME, css=_THEME_CSS) as demo:
        version, _, stage = __version__.partition("-")
        gr.HTML(f"""
        <div style="display:flex; align-items:baseline; justify-content:space-between; padding:12px 0 4px; border-bottom:1px solid #0d3048; margin-bottom:16px;">
            <div>
                <span style="font-family:'Share Tech Mono',monospace; font-size:1.6rem; color:#00e5ff; letter-spacing:0.2em; text-transform:uppercase;">PyTTI</span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#ff6d00; letter-spacing:0.1em; margin-left:8px; vertical-align:super;">{stage.upper()}</span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.7rem; color:#5fa8be; letter-spacing:0.15em; margin-left:16px;">NEURAL IMAGE SYNTHESIZER</span>
            </div>
            <span style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#5fa8be; letter-spacing:0.1em;">v{version}</span>
        </div>
        """)
        with gr.Tabs():

            # ----------------------------------------------------------------
            # TAB: Prompts
            # ----------------------------------------------------------------
            with gr.Tab("Prompts"):
                scenes = gr.Textbox(label="Scenes", value=_text_value("scenes", cfg.get("scenes")), lines=4,
                                    placeholder="A misty forest | volumetric light || A surreal dreamscape",
                                    info=TIPS["scenes"])
                scene_prefix = gr.Textbox(label="Scene Prefix", value=_text_value("scene_prefix", cfg.get("scene_prefix")), lines=2, info=TIPS["scene_prefix"])
                scene_suffix = gr.Textbox(label="Scene Suffix", value=_text_value("scene_suffix", cfg.get("scene_suffix")), lines=2, info=TIPS["scene_suffix"])
                with gr.Row():
                    direct_image_prompts = gr.Textbox(label="Direct Image Prompts", value=_text_value("direct_image_prompts", cfg.get("direct_image_prompts")), info=TIPS["direct_image_prompts"])
                    init_image = gr.Textbox(label="Init Image Path", value=_text_value("init_image", cfg.get("init_image")), info=TIPS["init_image"])
                with gr.Row():
                    direct_init_weight = gr.Textbox(label="Direct Init Weight", value=_text_value("direct_init_weight", cfg.get("direct_init_weight")), info=TIPS["direct_init_weight"])
                    semantic_init_weight = gr.Textbox(label="Semantic Init Weight", value=_text_value("semantic_init_weight", cfg.get("semantic_init_weight")), info=TIPS["semantic_init_weight"])

            # ----------------------------------------------------------------
            # TAB: Image & Animation
            # ----------------------------------------------------------------
            with gr.Tab("Image & Animation"):
                # — Model & Mode —
                with gr.Row():
                    image_model    = gr.Dropdown(label="Image Model",    choices=IMAGE_MODELS,    value=cfg.get("image_model"),    info=TIPS["image_model"],    scale=2)
                    vqgan_model    = gr.Dropdown(label="VQGAN Model",    choices=VQGAN_MODELS,    value=cfg.get("vqgan_model"),    info=TIPS["vqgan_model"],    scale=2)
                    animation_mode = gr.Dropdown(label="Animation Mode", choices=ANIMATION_MODES, value=cfg.get("animation_mode"), info=TIPS["animation_mode"], scale=1)

                # — Dimensions & Video —
                with gr.Row():
                    width        = gr.Number(label="Width",        value=cfg.get("width"),         precision=0, info=TIPS["width"],        scale=1)
                    height       = gr.Number(label="Height",       value=cfg.get("height"),        precision=0, info=TIPS["height"],       scale=1)
                    frame_stride = gr.Number(label="Frame Stride", value=cfg.get("frame_stride"),    precision=0, info=TIPS["frame_stride"], scale=1)
                video_path = gr.Textbox(label="Video Path (Video Source mode)", value=_text_value("video_path", cfg.get("video_path")), info=TIPS["video_path"])

                # — Camera Transforms —
                gr.Markdown("### Camera Transforms")
                with gr.Row():
                    translate_x   = gr.Textbox(label="Translate X",     value=_text_value("translate_x", cfg.get("translate_x")), info=TIPS["translate_x"])
                    translate_y   = gr.Textbox(label="Translate Y",     value=_text_value("translate_y", cfg.get("translate_y")), info=TIPS["translate_y"])
                    translate_z_3d = gr.Textbox(label="Translate Z (3D)", value=_text_value("translate_z_3d", cfg.get("translate_z_3d")), info=TIPS["translate_z_3d"])
                with gr.Row():
                    rotate_3d  = gr.Textbox(label="Rotate 3D",   value=_text_value("rotate_3d", cfg.get("rotate_3d")), info=TIPS["rotate_3d"],  scale=3)
                    rotate_2d  = gr.Textbox(label="Rotate 2D",   value=_text_value("rotate_2d", cfg.get("rotate_2d")),             info=TIPS["rotate_2d"],  scale=1)
                    zoom_x_2d  = gr.Textbox(label="Zoom X (2D)", value=_text_value("zoom_x_2d", cfg.get("zoom_x_2d")),             info=TIPS["zoom_x_2d"], scale=1)
                    zoom_y_2d  = gr.Textbox(label="Zoom Y (2D)", value=_text_value("zoom_y_2d", cfg.get("zoom_y_2d")),             info=TIPS["zoom_y_2d"], scale=1)
                with gr.Row():
                    lock_camera  = gr.Checkbox(label="Lock Camera", value=cfg.get("lock_camera"), info=TIPS["lock_camera"], scale=0)
                    field_of_view = gr.Number(label="Field of View", value=cfg.get("field_of_view"),    precision=0, info=TIPS["field_of_view"], scale=1)
                    near_plane    = gr.Number(label="Near Plane",    value=cfg.get("near_plane"),     precision=0, info=TIPS["near_plane"],    scale=1)
                    far_plane     = gr.Number(label="Far Plane",     value=cfg.get("far_plane"),     precision=0, info=TIPS["far_plane"],     scale=1)

                # — Edge Handling —
                with gr.Row():
                    border_mode   = gr.Dropdown(label="Border Mode",   choices=BORDER_MODES,   value=cfg.get("border_mode"),   info=TIPS["border_mode"],   scale=1)
                    sampling_mode = gr.Dropdown(label="Sampling Mode", choices=SAMPLING_MODES, value=cfg.get("sampling_mode"), info=TIPS["sampling_mode"], scale=1)
                    infill_mode   = gr.Dropdown(label="Infill Mode",   choices=INFILL_MODES,   value=cfg.get("infill_mode"),   info=TIPS["infill_mode"],   scale=1)

            # ----------------------------------------------------------------
            # TAB: Steps & CLIP
            # ----------------------------------------------------------------
            with gr.Tab("Steps & CLIP"):
                with gr.Row():
                    steps_per_scene = gr.Number(label="Steps per Scene", value=cfg.get("steps_per_scene"), precision=0, info=TIPS["steps_per_scene"])
                    steps_per_frame = gr.Number(label="Steps per Frame", value=cfg.get("steps_per_frame"), precision=0, info=TIPS["steps_per_frame"])
                with gr.Row():
                    interpolation_steps = gr.Number(label="Interpolation Steps", value=cfg.get("interpolation_steps"), precision=0, info=TIPS["interpolation_steps"])
                    pre_animation_steps = gr.Number(label="Pre-animation Steps", value=cfg.get("pre_animation_steps"), precision=0, info=TIPS["pre_animation_steps"])
                with gr.Row():
                    cutouts = gr.Number(label="Cutouts", value=cfg.get("cutouts"), precision=0, info=TIPS["cutouts"])
                    cut_pow = gr.Number(label="Cut Power", value=cfg.get("cut_pow"), info=TIPS["cut_pow"])
                    cutout_border = gr.Number(label="Cutout Border", value=cfg.get("cutout_border"), info="Pads the image by this fraction of its size so cutouts can reach past the edges. 0 = cutouts stay inside the image.")
                with gr.Row():
                    learning_rate = gr.Textbox(label="Learning Rate (blank = auto)", value=_text_value("learning_rate", cfg.get("learning_rate")), info=TIPS["learning_rate"])
                    seed = gr.Textbox(label="Seed (blank = random)", value=_text_value("seed", cfg.get("seed")), info=TIPS["seed"])
                    reset_lr_each_frame = gr.Checkbox(label="Reset LR Each Frame", value=cfg.get("reset_lr_each_frame"), info="Reset the optimizer (Adam momentum) at the start of each frame.")
                with gr.Row():
                    gradient_accumulation_steps = gr.Number(label="Gradient Accumulation Steps", value=cfg.get("gradient_accumulation_steps"), precision=0, info=TIPS["gradient_accumulation_steps"])
                    smoothing_weight = gr.Number(label="Smoothing Weight", value=cfg.get("smoothing_weight"), info="Total variation loss weight — higher values produce smoother images, lower values preserve more detail.")

                gr.Markdown("### CLIP Models")
                with gr.Row():
                    ViTB32 = gr.Checkbox(label="ViT-B/32", value=cfg.get("ViTB32"))
                    ViTB16 = gr.Checkbox(label="ViT-B/16", value=cfg.get("ViTB16"))
                    ViTL14 = gr.Checkbox(label="ViT-L/14", value=cfg.get("ViTL14"))
                    ViTL14_336px = gr.Checkbox(label="ViT-L/14@336px", value=cfg.get("ViTL14_336px"))
                with gr.Row():
                    RN50 = gr.Checkbox(label="RN50", value=cfg.get("RN50"))
                    RN101 = gr.Checkbox(label="RN101", value=cfg.get("RN101"))
                    RN50x4 = gr.Checkbox(label="RN50x4", value=cfg.get("RN50x4"))
                    RN50x16 = gr.Checkbox(label="RN50x16", value=cfg.get("RN50x16"))
                    RN50x64 = gr.Checkbox(label="RN50x64", value=cfg.get("RN50x64"))

            # ----------------------------------------------------------------
            # TAB: Palette
            # ----------------------------------------------------------------
            with gr.Tab("Palette"):
                with gr.Row():
                    palette_size = gr.Number(label="Palette Size", value=cfg.get("palette_size"), precision=0, info=TIPS["palette_size"])
                    palettes = gr.Number(label="Palettes", value=cfg.get("palettes"), precision=0, info=TIPS["palettes"])
                    pixel_size = gr.Number(label="Pixel Size", value=cfg.get("pixel_size"), precision=0, info="Output scale: frames are saved at width × pixel_size by height × pixel_size. Palette modes get chunky pixels; uses more VRAM.")
                with gr.Row():
                    gamma = gr.Number(label="Gamma", value=cfg.get("gamma"), info=TIPS["gamma"])
                    hdr_weight = gr.Number(label="HDR Weight", value=cfg.get("hdr_weight"), info=TIPS["hdr_weight"])
                    palette_normalization_weight = gr.Number(label="Palette Normalization Weight", value=cfg.get("palette_normalization_weight"), info=TIPS["palette_normalization_weight"])
                with gr.Row():
                    random_initial_palette = gr.Checkbox(label="Random Initial Palette", value=cfg.get("random_initial_palette"), info=TIPS["random_initial_palette"])
                    lock_palette = gr.Checkbox(label="Lock Palette", value=cfg.get("lock_palette"), info=TIPS["lock_palette"])
                target_palette = gr.Textbox(label="Target Palette", value=_text_value("target_palette", cfg.get("target_palette")), info=TIPS["target_palette"])

            # ----------------------------------------------------------------
            # TAB: Stabilization & Audio
            # ----------------------------------------------------------------
            with gr.Tab("Stabilization & Audio"):
                with gr.Row():
                    direct_stabilization_weight = gr.Textbox(label="Direct Stabilization Weight", value=_text_value("direct_stabilization_weight", cfg.get("direct_stabilization_weight")), info=TIPS["direct_stabilization_weight"])
                    semantic_stabilization_weight = gr.Textbox(label="Semantic Stabilization Weight", value=_text_value("semantic_stabilization_weight", cfg.get("semantic_stabilization_weight")), info=TIPS["semantic_stabilization_weight"])
                with gr.Row():
                    depth_stabilization_weight = gr.Textbox(label="Depth Stabilization Weight", value=_text_value("depth_stabilization_weight", cfg.get("depth_stabilization_weight")), info=TIPS["depth_stabilization_weight"])
                    edge_stabilization_weight = gr.Textbox(label="Edge Stabilization Weight", value=_text_value("edge_stabilization_weight", cfg.get("edge_stabilization_weight")), info=TIPS["edge_stabilization_weight"])
                    flow_stabilization_weight = gr.Textbox(label="Flow Stabilization Weight", value=_text_value("flow_stabilization_weight", cfg.get("flow_stabilization_weight")), info=TIPS["flow_stabilization_weight"])
                flow_long_term_samples = gr.Number(label="Flow Long-term Samples", value=cfg.get("flow_long_term_samples"), precision=0, info=TIPS["flow_long_term_samples"])
                reencode_each_frame = gr.Checkbox(label="Re-encode Each Frame", value=cfg.get("reencode_each_frame"), info="Re-encode video frames through the image model each step. Disable for faster but lower quality video mode.")
                input_audio = gr.Textbox(label="Input Audio Path", value=_text_value("input_audio", cfg.get("input_audio")), info=TIPS["input_audio"])
                input_audio_offset = gr.Number(label="Audio Offset (seconds)", value=cfg.get("input_audio_offset"), info="Offset in seconds to sync audio with the animation.")

            # ----------------------------------------------------------------
            # TAB: Output
            # ----------------------------------------------------------------
            with gr.Tab("Output"):
                with gr.Row():
                    file_namespace = gr.Textbox(label="File Namespace", value=_text_value("file_namespace", cfg.get("file_namespace")), info=TIPS["file_namespace"])
                    frames_per_second = gr.Number(label="FPS", value=cfg.get("frames_per_second"), precision=0, info=TIPS["frames_per_second"])
                with gr.Row():
                    save_every = gr.Number(label="Save Every N Steps", value=cfg.get("save_every"), precision=0, info=TIPS["save_every"])
                    display_every = gr.Number(label="Display Every N Steps", value=cfg.get("display_every"), precision=0, info=TIPS["display_every"])
                with gr.Row():
                    backups = gr.Number(label="Backups", value=cfg.get("backups"), precision=0, info="Rolling backups of the image model's state, which Resume Render continues from. Renders keep at least 2 (Video Source mode needs at least 2^Flow Long-term Samples + 1 and raises it automatically).")
                    breath_mode = gr.Checkbox(label="Breath Mode", value=cfg.get("breath_mode"), info=TIPS["breath_mode"])

                gr.Markdown("### Encode or Resume a Run")
                with gr.Row(equal_height=True):
                    encode_run_dropdown = gr.Dropdown(
                        label="Run",
                        choices=[],
                        scale=2,
                        info="Select a run with saved frames, to encode it as a video or to resume it.",
                    )
                    encode_refresh_btn = gr.Button("↻", variant="secondary", scale=0, min_width=36, elem_classes=["btn-sm"])
                with gr.Row():
                    encode_fps = gr.Number(label="FPS", value=cfg.get("frames_per_second"), precision=0, scale=1, info="Output video frame rate. Set to the run's FPS when you pick a run; other values speed up or slow down its motion.")
                    encode_format = gr.Dropdown(
                        label="Format",
                        choices=["MP4 (H.264)", "ProRes 4444 (MOV)", "ProRes HQ (MOV)"],
                        value="MP4 (H.264)",
                        scale=1,
                        info="MP4 for sharing, ProRes for lossless editing.",
                    )
                with gr.Row():
                    encode_btn = gr.Button("Encode Video", variant="primary", scale=2)
                    resume_run_btn = gr.Button("Resume Render", variant="secondary", scale=1)
                encode_status = gr.Textbox(label="Status", interactive=False, lines=2)
                # The run the user picked; refreshing the list keeps it rather than jumping to the newest
                encode_choice = gr.State(None)

            # ----------------------------------------------------------------
            # TAB: Run
            # ----------------------------------------------------------------
            with gr.Tab("Run"):
                with gr.Row(equal_height=True):
                    conf_name_input = gr.Textbox(label="Config Name", placeholder="my_run", scale=2)
                    load_conf_dropdown = gr.Dropdown(label="Load Config", choices=load_choices(), scale=2)
                    refresh_configs_btn = gr.Button("↻", variant="secondary", scale=0, min_width=36, elem_classes=["btn-sm"])
                    load_btn = gr.Button("Load", variant="secondary", scale=0, min_width=70, elem_classes=["btn-sm"])
                    save_btn = gr.Button("Save", variant="secondary", scale=0, min_width=70, elem_classes=["btn-sm"])
                with gr.Row():
                    run_btn = gr.Button("Start Render", variant="primary", scale=2)
                    resume_btn = gr.Button("Resume Render", variant="secondary", scale=1)
                    stop_btn = gr.Button("Stop Render", variant="stop", scale=1)
                status_box = gr.Textbox(label="Status", interactive=False, lines=1)
                progress_box = gr.Textbox(label="Progress", interactive=False, lines=1)
                # Keys from the last loaded preset that have no widget, carried over when saving under a new name
                extras_state = gr.State({})
                # (file name, mtime_ns) of the preset as last loaded or saved here, to notice edits made
                # outside the UI and saves over a preset this page never loaded
                conf_stamp = gr.State(None)

                gr.Markdown("### Live Log")
                log_box = gr.Textbox(label="Log", lines=20, interactive=False, max_lines=20, elem_id="log-box")

                gr.Markdown("### Latest Frame")
                frame_preview = gr.Image(label="Latest Frame", interactive=False)
                refresh_btn = gr.Button("Refresh")
                timer = gr.Timer(value=3, active=False)

            # ----------------------------------------------------------------
            # TAB: Help / Wiki
            # ----------------------------------------------------------------
            with gr.Tab("FAQ"):
                gr.HTML("""
                <div style="margin-bottom:16px; padding:10px 12px; border:1px solid #0d3048; border-radius:2px; font-size:0.75rem;">
                    <span style="color:#5fa8be;">Settings reference based on the </span>
                    <a href="https://pytti-tools.github.io/pytti-book/Settings.html" target="_blank"
                       style="color:#00e5ff; text-decoration:none; border-bottom:1px solid rgba(0,229,255,0.3);">pytti-book Settings documentation</a>
                    <span style="color:#5fa8be;"> — see also the full </span>
                    <a href="https://pytti-tools.github.io/pytti-book/intro.html" target="_blank"
                       style="color:#00e5ff; text-decoration:none; border-bottom:1px solid rgba(0,229,255,0.3);">pytti-book</a>
                    <span style="color:#5fa8be;"> and </span>
                    <a href="https://github.com/pytti-tools/pytti-notebook" target="_blank"
                       style="color:#00e5ff; text-decoration:none; border-bottom:1px solid rgba(0,229,255,0.3);">pytti-notebook</a>
                    <span style="color:#5fa8be;"> for more details.</span>
                </div>
                """)
                gr.HTML(_build_help_html(cfg))

        # ----------------------------------------------------------------
        # Preset settings, keyed like build_conf_dict's parameters
        # ----------------------------------------------------------------
        fields = dict(
            scenes=scenes, scene_prefix=scene_prefix, scene_suffix=scene_suffix,
            direct_image_prompts=direct_image_prompts, init_image=init_image,
            direct_init_weight=direct_init_weight, semantic_init_weight=semantic_init_weight,
            image_model=image_model, vqgan_model=vqgan_model,
            animation_mode=animation_mode, video_path=video_path, frame_stride=frame_stride,
            width=width, height=height,
            steps_per_scene=steps_per_scene, steps_per_frame=steps_per_frame,
            interpolation_steps=interpolation_steps, pre_animation_steps=pre_animation_steps,
            translate_x=translate_x, translate_y=translate_y, translate_z_3d=translate_z_3d,
            rotate_2d=rotate_2d, rotate_3d=rotate_3d, zoom_x_2d=zoom_x_2d, zoom_y_2d=zoom_y_2d,
            lock_camera=lock_camera,
            cutouts=cutouts, cut_pow=cut_pow, cutout_border=cutout_border,
            learning_rate=learning_rate, seed=seed, reset_lr_each_frame=reset_lr_each_frame,
            border_mode=border_mode, sampling_mode=sampling_mode, infill_mode=infill_mode,
            ViTB32=ViTB32, ViTB16=ViTB16, ViTL14=ViTL14, ViTL14_336px=ViTL14_336px,
            RN50=RN50, RN101=RN101, RN50x4=RN50x4, RN50x16=RN50x16, RN50x64=RN50x64,
            palette_size=palette_size, palettes=palettes, pixel_size=pixel_size, gamma=gamma,
            hdr_weight=hdr_weight, palette_normalization_weight=palette_normalization_weight,
            random_initial_palette=random_initial_palette, lock_palette=lock_palette,
            target_palette=target_palette,
            frames_per_second=frames_per_second, save_every=save_every, display_every=display_every,
            file_namespace=file_namespace, backups=backups,
            field_of_view=field_of_view, near_plane=near_plane, far_plane=far_plane,
            gradient_accumulation_steps=gradient_accumulation_steps, smoothing_weight=smoothing_weight,
            direct_stabilization_weight=direct_stabilization_weight,
            semantic_stabilization_weight=semantic_stabilization_weight,
            depth_stabilization_weight=depth_stabilization_weight,
            edge_stabilization_weight=edge_stabilization_weight,
            flow_stabilization_weight=flow_stabilization_weight,
            reencode_each_frame=reencode_each_frame,
            input_audio=input_audio, input_audio_offset=input_audio_offset,
            flow_long_term_samples=flow_long_term_samples,
            breath_mode=breath_mode,
        )
        assert fields.keys() == CONF_KEYS, fields.keys() ^ CONF_KEYS
        all_inputs = [fields[key] for key in CONF_FIELDS]
        labels = {key: widget.label for key, widget in fields.items()}

        # ----------------------------------------------------------------
        # Callbacks
        # ----------------------------------------------------------------
        def _save_preset(name, extras, args, for_render=False):
            """Check the UI's settings and save them as the preset, for Save and Start Render.

            Returns (file name, notes) once saved, or (None, problems) if nothing was written.
            Missing input files, settings that could run code or that pytti can't evaluate,
            and prompts too long for CLIP stop only a render; Save mentions them in its notes.
            """
            name = _conf_name(name)
            values = dict(zip(CONF_FIELDS, args))
            try:
                base = preset_base(name, extras)
            except PresetError as e:
                return None, [str(e)]
            problems = conf_problems(name, values, labels)
            missing = missing_files(values, labels, base)
            risks, risk_notes = preset_risks(values, base, labels)
            risks += long_prompts(values, labels)
            if for_render:
                problems += missing + risks
            if problems:
                return None, problems
            filename = f"{name}.yaml"
            try:
                return filename, missing + risks + write_conf(filename, base, values) + risk_notes
            except OSError as e:
                return None, [f"Could not save config/conf/{filename}: {e.strerror or e}."]

        def _changed_message(filename):
            return (f"config/conf/{filename} was changed outside PyTTI since it was loaded. "
                    "Press Load to use those changes, or Save to overwrite them.")

        def _ask_before_replacing(filename):
            """Load Config set to the preset, the question, and a stamp that lets the next press through."""
            question = (f"config/conf/{filename} already exists and wasn't loaded here. "
                        "Press Load to use it, or press again to overwrite it.")
            return gr.Dropdown(choices=load_choices(), value=_listed_name(filename)), question, (filename, _conf_mtime(filename), None)

        def save_config(name, extras, stamp, *args):
            global _last_preset
            filename = f"{_conf_name(name)}.yaml"
            if _not_loaded_here(filename, stamp):
                # e.g. an existing preset's name typed in over other settings
                return _ask_before_replacing(filename)
            changed = _changed_on_disk(filename, stamp)
            if changed and changed != stamp[2]:
                # Remember the warning, so pressing Save again overwrites the file
                return gr.update(), _changed_message(filename), (stamp[0], stamp[1], changed)
            filename, status = _save_preset(name, extras, args)
            if filename is None:
                return gr.update(), " ".join(status), gr.update()
            _last_preset = _listed_name(filename)
            saved = [f"Saved to config/conf/{filename}."]
            return gr.Dropdown(choices=load_choices()), " ".join(saved + status), (filename, _conf_mtime(filename), None)

        def _live_view(namespace, running):
            """Log, latest frame, progress and timer, all from one reading of whether the render runs."""
            progress = (_get_eta() or "Starting...") if running else ""
            return get_log(), get_latest_frame(namespace), progress, gr.Timer(active=running)

        def refresh(namespace):
            # The reader appends the summary before clearing _running, so once this reads False
            # the log is final; that last tick turns polling off
            return _live_view(namespace, render._running)

        def tick(namespace, encode_pick):
            running = render._running
            view = _live_view(namespace, running)
            if running:
                return *view, gr.skip(), gr.skip()
            # The render has ended: say how, and offer its frames for encoding
            return *view, render._render_status or gr.skip(), refresh_encode_list(encode_pick)

        def load_existing(name):
            global _last_preset
            if not name:
                return [gr.update()] * (len(all_inputs) + 5)
            if name == DEFAULTS_CHOICE:
                # No config name and no stamp, so a save asks before replacing a preset
                preset, stamp = {}, None
            elif not (paths.CONF_DIR / name).exists():
                if name == _last_preset:
                    _last_preset = None
                missing = [f"{name} no longer exists.", gr.Dropdown(choices=load_choices(), value=None), gr.update()]
                return [gr.update()] * (len(all_inputs) + 2) + missing
            else:
                stamp = (name, _conf_mtime(name), None)  # taken first, so an edit made while reading isn't missed
                try:
                    preset = load_conf(name)
                except PresetError as e:
                    return [gr.update()] * (len(all_inputs) + 2) + [str(e), gr.update(), gr.update()]
            defaults = load_defaults()
            data = _resolve_references({**defaults, **preset})
            extras = {k: v for k, v in preset.items() if k not in CONF_KEYS}
            values, notes = [], []
            for key in CONF_FIELDS:
                value = _ui_value(key, fields[key], data.get(key), defaults.get(key))
                choices = CHOICES.get(key)
                if choices and value not in choices:
                    # The dropdown would show it blank but save it back, and the render would fail on it
                    fallback = _ui_value(key, fields[key], defaults.get(key), None)
                    fallback = fallback if fallback in choices else choices[0]
                    notes.append(f"{labels[key]} '{value}' isn't a valid choice; using {fallback}.")
                    value = fallback
                values.append(value)
            risks, risk_notes = preset_risks(dict(zip(CONF_FIELDS, values)), extras, labels)
            risks += long_prompts(dict(zip(CONF_FIELDS, values)), labels)
            if stamp is None:
                _last_preset = None
                status = "Loaded the defaults from config/default.yaml. Enter a Config Name to save them as a preset."
            else:
                _last_preset = name
                status = f"Loaded {name}."
            status = " ".join([status] + notes + _unknown_key_notes(preset) + risks + risk_notes)
            # Choices too: after a page reload they are the ones listed when the UI started
            dropdown = gr.Dropdown(choices=load_choices(), value=name)
            return values + [_conf_name(name) if stamp else "", extras, status, dropdown, stamp]

        def run_and_activate_timer(name, extras, stamp, *args):
            global _last_preset
            if render._running:
                # Don't overwrite a preset that may be in use; just resume live updates
                return gr.update(), "Already running.", gr.Timer(active=True), gr.update()
            filename = f"{_conf_name(name)}.yaml"
            if _not_loaded_here(filename, stamp):
                dropdown, question, stamp = _ask_before_replacing(filename)
                return dropdown, question, gr.Timer(active=False), stamp
            changed = _changed_on_disk(filename, stamp)
            if changed:
                # Never render over outside edits; a Save after this warning overwrites them
                return gr.update(), _changed_message(filename), gr.Timer(active=False), (stamp[0], stamp[1], changed)
            # Auto-save before running so the YAML always matches the UI
            filename, status = _save_preset(name, extras, args, for_render=True)
            if filename is None:
                return gr.update(), " ".join(status), gr.Timer(active=False), gr.update()
            _last_preset = _listed_name(filename)
            stamp = (filename, _conf_mtime(filename), None)
            msg = start_render(filename)
            return gr.Dropdown(choices=load_choices()), " ".join([msg] + status), gr.Timer(active=render._running), stamp

        def stop_and_deactivate_timer(namespace, encode_pick):
            msg = stop_render()
            log, frame, progress, _ = _live_view(namespace, False)
            return msg, gr.Timer(active=False), log, frame, progress, refresh_encode_list(encode_pick)

        def resume_last():
            """Resume Render on the Run tab: the last render, or after a restart the newest run."""
            run_dir = render._render_dir or _newest_run()
            if run_dir is None:
                return "There is no render to resume yet.", gr.Timer(active=False)
            msg = resume_render(run_dir, labels)
            if not render._running:
                msg += " To resume another render, pick it in the Run list on the Output tab and press Resume Render there."
            return msg, gr.Timer(active=render._running)

        def resume_picked(frames_dir):
            """Resume Render on the Output tab: the run picked in its list."""
            if not frames_dir:
                return "Select a run first.", gr.skip(), gr.skip()
            msg = resume_render(Path(frames_dir).parent.parent, labels)
            # The Run tab shows the resumed render
            return msg, msg if render._running else gr.skip(), gr.Timer(active=render._running)

        def refresh_encode_list(pick=None):
            runs = get_encodable_runs()
            paths = [path for _, path in runs]
            # Keep the run the user picked while it is still listed; otherwise show the newest
            return gr.Dropdown(choices=runs, value=pick if pick in paths else (paths[0] if paths else None))

        def encode_fps_for_run(frames_dir):
            fps = run_fps(frames_dir) if frames_dir else None
            return fps if fps else gr.skip()

        save_btn.click(fn=save_config, inputs=[conf_name_input, extras_state, conf_stamp] + all_inputs, outputs=[load_conf_dropdown, status_box, conf_stamp])
        run_btn.click(fn=run_and_activate_timer, inputs=[conf_name_input, extras_state, conf_stamp] + all_inputs, outputs=[load_conf_dropdown, status_box, timer, conf_stamp])
        stop_btn.click(fn=stop_and_deactivate_timer, inputs=[file_namespace, encode_choice], outputs=[status_box, timer, log_box, frame_preview, progress_box, encode_run_dropdown])
        resume_btn.click(fn=resume_last, outputs=[status_box, timer])
        resume_run_btn.click(fn=resume_picked, inputs=[encode_run_dropdown], outputs=[encode_status, status_box, timer])
        refresh_btn.click(fn=refresh, inputs=[file_namespace], outputs=[log_box, frame_preview, progress_box, timer])
        timer.tick(fn=tick, inputs=[file_namespace, encode_choice], outputs=[log_box, frame_preview, progress_box, timer, status_box, encode_run_dropdown])
        load_outputs = all_inputs + [conf_name_input, extras_state, status_box, load_conf_dropdown, conf_stamp]
        load_btn.click(fn=load_existing, inputs=[load_conf_dropdown], outputs=load_outputs)
        refresh_configs_btn.click(fn=lambda: gr.Dropdown(choices=load_choices()), outputs=[load_conf_dropdown])
        # A page reload resets the timer; resume live updates if a render is still going
        demo.load(fn=lambda: gr.Timer(active=render._running), outputs=[timer])
        # It also resets every field to default.yaml's values and empties Config Name; bring
        # back the preset last loaded or saved, as it is on disk
        demo.load(fn=lambda: load_existing(_last_preset), outputs=load_outputs)

        # Encode video callbacks
        encode_refresh_btn.click(fn=refresh_encode_list, inputs=[encode_choice], outputs=[encode_run_dropdown])
        # .input fires only for the user's own picks, not when the list is refreshed
        encode_run_dropdown.input(fn=lambda run: run, inputs=[encode_run_dropdown], outputs=[encode_choice])
        # Default the encode FPS to the frame rate the run was rendered for
        encode_run_dropdown.change(fn=encode_fps_for_run, inputs=[encode_run_dropdown], outputs=[encode_fps])
        encode_btn.click(fn=encode_video, inputs=[encode_run_dropdown, encode_fps, encode_format], outputs=[encode_status])
        # Auto-populate on load
        demo.load(fn=refresh_encode_list, outputs=[encode_run_dropdown])

    return demo


_instance_mutex = None  # held for the life of the process


def _claim_single_instance() -> bool:
    """Take a named Windows mutex; False if another PyTTI UI already holds it.

    A second UI knows nothing about the first one's render and could start another on
    the same GPU, running both out of memory. Windows releases the mutex when the
    process exits, even after a crash.
    """
    global _instance_mutex
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\PyTTIPortableUI")
    return not (_instance_mutex and ctypes.get_last_error() == 183)  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    if not _claim_single_instance():
        print("PyTTI is already running in another window. Use that one (its address is shown there), or close it to start PyTTI again.")
        sys.exit(0)
    print(f"Using Python: {paths.PYTHON_EXE}")
    demo = make_ui()
    # This PC only: the UI starts renders, and their motion expressions run as Python code
    demo.launch(inbrowser=True, show_api=False, server_name="127.0.0.1", share=False)
