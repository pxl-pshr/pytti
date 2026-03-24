"""
pytti Portable UI
=================
Run via launch.bat — do not run directly with system Python.
"""
__version__ = "1.0.0-alpha"
import os
import random
import re
import subprocess
import threading
import time
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
    "save_every": "Save a frame every N steps. 0 = auto-match steps_per_frame (recommended). Set manually to override.",
    "breath_mode": "Gradually blend from init image to CLIP-optimized. Frame 1 = init image, last frame = fully optimized. Requires init image.",
    "display_every": "Update the live preview every N optimization steps.",
    "allow_overwrite": "If disabled, existing output files are kept and new ones are numbered.",
}

# ---------------------------------------------------------------------------
# Help / Wiki data — grouped settings with extended descriptions
# ---------------------------------------------------------------------------
HELP_SECTIONS = [
    ("Prompts", [
        ("scenes", "Text prompts that describe what the image should look like. Separate prompts within a scene with <code>|</code> and weight them with <code>:weight</code> (e.g. <code>forest:2</code> for double weight). Use <code>||</code> to separate scenes — the render transitions between them using <code>interpolation_steps</code> via linear interpolation in CLIP semantic space. Negative weights push the image <em>away</em> from a concept (e.g. <code>blurry:-1</code>). You can also set a <code>:stop</code> value to freeze a prompt after a threshold is reached.", "string"),
        ("scene_prefix", "Text prepended to every scene prompt. Useful for global style keywords like <code>oil painting |</code> or <code>highly detailed |</code> that you want applied everywhere without repeating them in each scene.", "string"),
        ("scene_suffix", "Text appended to every scene prompt. Commonly used for negative prompts like <code>| text:-1 | watermark:-1</code> to suppress unwanted elements globally across all scenes.", "string"),
        ("direct_image_prompts", "Path or URL to an image used as a direct (pixel-level) visual prompt. CLIP compares the render against this image literally — useful for style transfer. Supports <code>weight_mask</code> syntax: e.g. <code>image.png:1.5_mask.png</code>. Video masks must be MP4.", "path"),
        ("init_image", "Path to a starting image. The render begins from this instead of random noise, creating an initial focal point and layout. Leave blank for a random start. Tip: use with <code>semantic_init_weight</code> to keep the output resembling the init image throughout.", "path"),
        ("direct_init_weight", "Treats the init image as a direct image prompt with this weight (pixel-level MSE loss). Default: <code>0</code>. Higher = stays closer to original pixels. <strong>Warning:</strong> filenames with underscores can cause parsing errors — use <code>semantic_init_weight</code> instead for complex filenames.", "weight"),
        ("semantic_init_weight", "Treats the init image as a semantic (CLIP-level) prompt with this weight. Default: <code>0</code>. The render will <em>feel like</em> the init image without being pixel-locked to it. Safer than <code>direct_init_weight</code> with complex filenames. Mask paths go in <code>[ ]</code> brackets.", "weight"),
    ]),
    ("Image Model", [
        ("image_model", "<strong>Limited Palette</strong>: fast, painterly look using discrete color swatches — total colors = <code>palette_size × palettes</code>. <strong>Unlimited Palette</strong>: per-pixel color, more photographic. <strong>VQGAN</strong>: classic neural art using a pretrained codebook (set <code>pixel_size: 1</code> with VQGAN to avoid VRAM issues).", "choice"),
        ("vqgan_model", "Which VQGAN codebook to use. Only matters when <code>image_model</code> is VQGAN. Options: <code>sflickr</code>, <code>imagenet</code>, <code>coco</code>, <code>wikiart</code>, <code>openimages</code>. Each has a different visual style bias.", "choice"),
    ]),
    ("Animation", [
        ("animation_mode", "<strong>off</strong>: single image, no animation. <strong>2D</strong>: pan/zoom/rotate the canvas each frame. <strong>3D</strong>: full 3D camera with MiDaS depth estimation. <strong>Video Source</strong>: warp frames of a source video using optical flow.", "choice"),
        ("translate_x", "Horizontal camera shift per frame (pixels). Accepts Python expressions using <code>t</code> (time in seconds, scaled by <code>frames_per_second</code>), e.g. <code>10*sin(t/30)</code>.", "expression"),
        ("translate_y", "Vertical camera shift per frame (pixels). Same expression support — <code>t</code> is time in seconds.", "expression"),
        ("translate_z_3d", "Forward/backward camera movement per frame (3D mode only). Positive = move forward into the scene. Expressions with <code>t</code> supported.", "expression"),
        ("rotate_3d", "Quaternion rotation per frame in 3D mode: <code>[w, x, y, z]</code>. Use <code>cos(radians(N))</code> and <code>sin(radians(N))</code> for smooth rotations. <code>t</code> is time in seconds.", "expression"),
        ("rotate_2d", "Rotation in degrees per frame (2D mode). Expressions with <code>t</code> (time in seconds) supported.", "expression"),
        ("zoom_x_2d", "Horizontal zoom per frame (2D mode). <code>0</code> = no zoom. Expressions with <code>t</code> supported.", "expression"),
        ("zoom_y_2d", "Vertical zoom per frame (2D mode). <code>0</code> = no zoom. Expressions with <code>t</code> supported.", "expression"),
        ("lock_camera", "Prevents camera scrolling/drifting during <code>pre_animation_steps</code>. Stabilizes 3D rotations. The image develops before motion begins.", "bool"),
        ("field_of_view", "Vertical FOV in degrees (3D mode). Lower values (30–40) give a telephoto look; higher (80–100) give wide-angle distortion.", "number"),
        ("near_plane", "Near clipping plane distance in pixels (3D mode). Objects closer than this are clipped from the depth buffer.", "number"),
        ("far_plane", "Far clipping plane distance in pixels (3D mode). Objects beyond this are clipped from the depth buffer.", "number"),
        ("video_path", "Path to an MP4 source video (Video Source mode). Each frame of this video guides one animation frame via optical flow.", "path"),
        ("frame_stride", "Video frames to advance per output frame. <code>1</code> = use every frame, <code>2</code> = every other. Only used in Video Source mode.", "number"),
    ]),
    ("Canvas & Edges", [
        ("width", "Output width in pixels. Larger = more detail but slower and more VRAM. Set to <code>-1</code> to auto-derive from init image aspect ratio.", "number"),
        ("height", "Output height in pixels. Same considerations as width. Set to <code>-1</code> to auto-derive from init image aspect ratio.", "number"),
        ("border_mode", "How cutouts handle pixels beyond the image edge: <code>wrap</code> = tile, <code>mirror</code> = reflect, <code>clamp</code> = stretch edge, <code>black</code> = fill with black, <code>smear</code> = extend edge colors.", "choice"),
        ("sampling_mode", "Pixel sampling during animation warping: <code>nearest</code> (sharp/pixelated), <code>bilinear</code> (smooth), <code>bicubic</code> (sharpest).", "choice"),
        ("infill_mode", "How to fill newly revealed areas after camera movement: <code>wrap</code>, <code>mirror</code>, <code>black</code>, or <code>smear</code>.", "choice"),
    ]),
    ("Steps & Timing", [
        ("steps_per_scene", "Total optimization steps per scene. Frames generated = <code>steps_per_scene / steps_per_frame</code>. Must be at least <code>interpolation_steps</code>. More steps = more refined image and more frames.", "number"),
        ("steps_per_frame", "Optimization steps between each animation frame. Lower = more frames (smoother video) but less refinement per frame. Default: <code>50</code>.", "number"),
        ("interpolation_steps", "Steps for smooth crossfade between scenes (using <code>||</code> separator). Uses linear interpolation in CLIP semantic space. Default: <code>200</code>. Set to <code>0</code> to cut between scenes instantly.", "number"),
        ("pre_animation_steps", "Steps to run before animation begins, with camera locked. Lets the image develop from noise before motion starts. Default: <code>250</code> (pytti-book) / <code>50</code> (this UI).", "number"),
    ]),
    ("CLIP & Optimization", [
        ("cutouts", "Number of random crops (glimpses) per CLIP evaluation. More cutouts = richer gradients and better quality, but slower and less VRAM-efficient. 40–60 is typical.", "number"),
        ("cut_pow", "Controls cutout size distribution. Default: <code>1</code>. Higher (2–3) = more small crops emphasizing fine detail but can be unstable. Lower = more large crops emphasizing global composition.", "number"),
        ("cutout_border", "Fraction of each cutout devoted to border padding. Default: <code>0.25</code>. Higher = more context around each crop, which can improve coherence but reduces the effective crop area. <code>0</code> = no padding.", "number"),
        ("learning_rate", "Optimizer step size. Leave blank for auto-tuning. Lower (0.05–0.1) = more stable but slower. Higher (0.2–0.5) = faster but can overshoot.", "number"),
        ("reset_lr_each_frame", "Reset the optimizer at each animation frame boundary. Default: <code>true</code>. Clears Adam momentum buffers so each frame optimizes fresh. Disable to carry optimizer state across frames — can reduce color shifts but may cause instability.", "bool"),
        ("smoothing_weight", "Total variation loss weight — penalizes sharp pixel-to-pixel differences. Higher = smoother, more painterly images. Lower = more detail and texture but potentially noisy. Default varies by image model.", "number"),
        ("seed", "Pseudorandom seed for reproducibility. A fixed seed increases determinism — same seed + same config = similar output. Leave blank for a random seed each run.", "number"),
        ("gradient_accumulation_steps", "Batch cutout processing over N mini-steps before updating. Must divide <code>cutouts</code> evenly. Higher = smoother optimization and less VRAM per step, but slower overall. Default: <code>1</code>.", "number"),
        ("ViTB32", "Enable the ViT-B/32 CLIP model. Fast, good at composition. Recommended as a baseline. Each CLIP model requires significant VRAM.", "bool"),
        ("ViTB16", "Enable the ViT-B/16 CLIP model. More detail-sensitive than B/32. Slightly slower.", "bool"),
        ("ViTL14", "Enable the ViT-L/14 CLIP model. High quality but significantly slower and uses more VRAM.", "bool"),
        ("ViTL14_336px", "ViT-L/14 at 336px input resolution. Highest quality CLIP model but very heavy on VRAM.", "bool"),
        ("RN50", "Enable the ResNet-50 CLIP model. Different texture/style bias than ViT models — can add complementary detail.", "bool"),
        ("RN101", "Enable the ResNet-101 CLIP model. Similar to RN50 but slightly better quality.", "bool"),
        ("RN50x4", "Enable the ResNet-50x4 CLIP model. Good balance of quality and speed. Complements ViT models well.", "bool"),
        ("RN50x16", "Enable the ResNet-50x16 CLIP model. High quality but heavy on VRAM.", "bool"),
        ("RN50x64", "Enable the ResNet-50x64 CLIP model. Highest quality ResNet variant. Extremely heavy on VRAM — only use with plenty of GPU memory.", "bool"),
    ]),
    ("Limited Palette", [
        ("palette_size", "Number of colors per palette swatch. Total colors = <code>palette_size × palettes</code>. Lower (3–6) = more stylized/posterized. Higher (20–50) = smoother gradients.", "number"),
        ("palettes", "Number of independent palette swatches. More palettes = more color variety across the image. 12–30 is typical. Total colors = <code>palette_size × palettes</code>.", "number"),
        ("gamma", "Relative gamma value for the palette. Default: <code>1</code>. Higher = darker with more contrast. Lower = brighter midtones.", "number"),
        ("hdr_weight", "Strength of gamma maintenance — pushes the palette toward higher dynamic range. <code>0</code> = disabled, 0.3–0.5 = subtle, 1.0+ = strong contrast boost.", "number"),
        ("palette_normalization_weight", "Keeps palette colors spread across the full brightness range, preventing individual palettes from being lost or going muddy/washed-out.", "number"),
        ("random_initial_palette", "Start with random colors instead of grayscale. Without this, palettes start grayscale and develop color during optimization. Good for abstract work.", "bool"),
        ("lock_palette", "Freeze the palette so colors don't change during the render. Most useful when restoring from a backup — otherwise tends to produce grayscale output.", "bool"),
        ("target_palette", "Path to an image whose colors the palette will be pulled toward. The model extracts a color scheme from this image and uses it as a target.", "path"),
        ("pixel_size", "Size of each pixel block in the output. <code>1</code> = full resolution. Higher values (2, 4, 8) create a chunky pixel-art look with larger 'pixels'. Affects all image models but most noticeable with Limited Palette.", "number"),
    ]),
    ("Stabilization", [
        ("direct_stabilization_weight", "Keeps the current frame as a direct (pixel-level) image prompt for the next frame. Higher = less flicker but more ghosting. <code>1</code> is a good default. Supports <code>weight_mask</code> syntax.", "weight"),
        ("semantic_stabilization_weight", "Keeps the current frame as a semantic (CLIP-level) prompt for the next frame. Prevents the <em>meaning</em> from drifting between frames. Supports masks.", "weight"),
        ("depth_stabilization_weight", "Maintains depth model consistency between frames (3D mode). Prevents depth map flickering. <strong>Steep performance cost</strong> — use sparingly. Supports masks.", "weight"),
        ("edge_stabilization_weight", "Preserves image contours/edges between frames. Reduces shimmer on hard edges. Low performance cost. Supports masks.", "weight"),
        ("flow_stabilization_weight", "Optical flow alignment — warps each frame to match previous motion. Prevents flickering in 3D and Video Source modes. High cost for 3D, slight cost for Video Source.", "weight"),
        ("flow_long_term_samples", "Number of past frames sampled for flow stabilization. The earliest sampled frame is <code>2^N</code> frames in the past. Higher = more temporal coherence but slower. Default: <code>0</code>.", "number"),
        ("reencode_each_frame", "Re-encode video source frames through the image model each step (Video Source mode). Enabled = higher quality but slower. Disabled = faster, uses raw video frames directly.", "bool"),
    ]),
    ("Audio (Experimental)", [
        ("input_audio", "Path to a WAV/MP3 file for audioreactive animation. Audio features are extracted and can modulate camera and style parameters via bandpass filters defined in the config.", "path"),
        ("input_audio_offset", "Offset in seconds into the audio file. Use to sync audio features with a specific point in the animation. Default: <code>0</code>.", "number"),
    ]),
    ("Output", [
        ("file_namespace", "Subfolder name inside <code>images_out/</code>. Use a unique name per run to keep outputs organized. All frames for a run go in this folder.", "string"),
        ("frames_per_second", "Playback FPS for the final video — also controls how <code>t</code> is scaled in motion expressions. 12–15 for dreamy, 24–30 for smooth.", "number"),
        ("save_every", "Save a PNG frame every N optimization steps. <strong>0 = auto-match steps_per_frame</strong> (recommended). Set a value manually to override.", "number"),
        ("display_every", "Update the live preview every N steps. Lower = more frequent updates but slightly slower.", "number"),
        ("allow_overwrite", "If enabled, existing frames are overwritten on re-run. If disabled, new frames get incremented filenames to avoid data loss.", "bool"),
        ("backups", "Number of rolling <code>.bak</code> backup files to keep per run. These store image model weights. <code>0</code> = no backups. <code>3</code> is a good default — keeps the last 3 frames' state.", "number"),
        ("breath_mode", "When enabled, saved frames linearly crossfade from the <code>init_image</code> to the CLIP-optimized output. Frame 1 is nearly 100% the init image; the final frame is 100% optimized. Requires <code>init_image</code> to be set. Works with all animation modes.", "bool"),
    ]),
]

def _build_help_html():
    """Generate the full HTML for the help/wiki tab."""
    type_badges = {
        "string": ("STR", "#5fa8be"),
        "path": ("PATH", "#ff6d00"),
        "weight": ("WEIGHT", "#ff6d00"),
        "expression": ("EXPR", "#a855f7"),
        "number": ("NUM", "#39ff14"),
        "bool": ("BOOL", "#00e5ff"),
        "choice": ("CHOICE", "#00e5ff"),
    }
    rows = []
    for section, fields in HELP_SECTIONS:
        rows.append(f'<tr class="wiki-section" data-search="{section.lower()}"><td colspan="3" style="padding:14px 8px 6px; color:#00e5ff; font-size:0.85rem; letter-spacing:0.12em; text-transform:uppercase; border-bottom:1px solid #0d3048;">{section}</td></tr>')
        for name, desc, ftype in fields:
            badge_label, badge_color = type_badges.get(ftype, ("?", "#5fa8be"))
            rows.append(
                f'<tr class="wiki-row" data-search="{name.lower()} {section.lower()} {desc.lower()}">'
                f'<td style="padding:8px; color:#00e5ff; white-space:nowrap; vertical-align:top; width:1%; font-size:0.8rem;">{name}</td>'
                f'<td style="padding:8px 10px; vertical-align:top; width:1%;"><span style="background:{badge_color}22; color:{badge_color}; padding:1px 6px; border-radius:2px; font-size:0.65rem; letter-spacing:0.05em;">{badge_label}</span></td>'
                f'<td style="padding:8px; color:#5fa8be; font-size:0.78rem; line-height:1.5;">{desc}</td>'
                f'</tr>'
            )
    table = "\n".join(rows)
    return f"""
    <div id="wiki-container">
        <input type="text" id="wiki-search" placeholder="Search settings..."
               style="width:100%; padding:10px; margin-bottom:12px; background:#020a10; border:1px solid #0d3048;
                      color:#00e5ff; font-family:'Share Tech Mono',monospace; font-size:0.8rem; border-radius:2px;
                      outline:none;"
               onfocus="this.style.borderColor='#00e5ff'; this.style.boxShadow='0 0 8px rgba(0,229,255,0.2)';"
               onblur="this.style.borderColor='#0d3048'; this.style.boxShadow='none';"
               oninput="
                   let q = this.value.toLowerCase();
                   let rows = document.querySelectorAll('#wiki-table .wiki-row');
                   let sections = document.querySelectorAll('#wiki-table .wiki-section');
                   rows.forEach(r => r.style.display = (!q || r.dataset.search.includes(q)) ? '' : 'none');
                   sections.forEach(s => {{
                       let next = s.nextElementSibling;
                       let anyVisible = false;
                       while (next && !next.classList.contains('wiki-section')) {{
                           if (next.style.display !== 'none') anyVisible = true;
                           next = next.nextElementSibling;
                       }}
                       s.style.display = (!q || anyVisible) ? '' : 'none';
                   }});
               ">
        <table id="wiki-table" style="width:100%; border-collapse:collapse;">
            {table}
        </table>
    </div>
    """

_HELP_HTML = _build_help_html()

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
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
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
_log_lock = threading.Lock()
_running = False
_render_its: float = 0.0          # latest observed it/s from tqdm
_render_step: int = 0             # current step within tqdm bar
_render_step_total: int = 0       # total steps in current tqdm bar
_render_scene: int = 0            # completed scenes count
_scene_prompt_count: int = 0     # how many "Running prompt:" lines we've seen
_render_conf: dict | None = None  # config snapshot for ETA calc
_render_start: float = 0.0       # time.time() when render started
_stop_requested: bool = False
_summary_appended: bool = False


_LOG_NOISE = re.compile(r"\| DEBUG\s+\||UserWarning:|warnings\.warn\(")
# Match tqdm output like "  5%|▌         | 500/10000 [00:33<10:30, 15.08it/s]"
_TQDM_RE = re.compile(r"(\d+)/(\d+)\s+\[.*?,\s*([\d.]+)(?:s/it|it/s)")
_SCENE_RE = re.compile(r"Running prompt:", re.IGNORECASE)

def _append_summary(label: str):
    """Append render summary to log. Only runs once per render."""
    global _summary_appended
    if _summary_appended:
        return
    _summary_appended = True
    elapsed = time.time() - _render_start if _render_start else 0
    conf = _render_conf or {}
    num_scenes = max(1, len([s for s in conf.get("scenes", "").split("||") if s.strip()]))
    steps_per_scene = conf.get("steps_per_scene", 10000)
    total_steps = num_scenes * steps_per_scene
    done = (_render_scene * steps_per_scene) + _render_step
    save_every = conf.get("save_every", 0) or conf.get("steps_per_frame", 50)
    if save_every <= 0:
        save_every = conf.get("steps_per_frame", 50)
    frames = done // save_every if save_every > 0 else 0
    avg_sps = done / elapsed if elapsed > 0 else 0
    avg_spf = elapsed / frames if frames > 0 else 0
    lines = [
        "=" * 50,
        label,
        "-" * 50,
        f"  Steps:         {done} / {total_steps}",
        f"  Frames saved:  {frames}",
        f"  Total time:    {_format_eta(elapsed)}",
    ]
    if avg_sps > 0:
        lines.append(f"  Avg speed:     {avg_sps:.2f} step/s")
    if frames > 0:
        lines.append(f"  Avg per frame: {_format_eta(avg_spf)}")
    lines.append("=" * 50)
    with _log_lock:
        _log_lines.extend(lines)


def _stream_output(proc):
    global _running, _render_its, _render_step, _render_step_total, _render_scene, _scene_prompt_count
    for line in iter(proc.stdout.readline, ""):
        # tqdm uses \r to overwrite; keep only the last segment
        parts = line.split("\r")
        text = parts[-1].rstrip()
        clean = _ANSI_ESCAPE.sub("", text)
        if not clean.strip() or _LOG_NOISE.search(clean):
            continue
        # Extract tqdm progress
        m = _TQDM_RE.search(clean)
        if m:
            _render_step = int(m.group(1))
            _render_step_total = int(m.group(2))
            rate = float(m.group(3))
            # tqdm may report "s/it" (slow) or "it/s" (fast)
            _render_its = (1.0 / rate) if "s/it" in clean else rate
        # Track scene transitions (pytti logs "Running prompt:" for each scene)
        if _SCENE_RE.search(clean):
            _scene_prompt_count += 1
            # First "Running prompt:" is scene 0 starting; subsequent ones mean prior scene completed
            _render_scene = max(0, _scene_prompt_count - 1)
        with _log_lock:
            _log_lines.append(clean)
    proc.wait()
    if not _stop_requested:
        if proc.returncode == 0:
            _append_summary("RENDER COMPLETE")
        else:
            _append_summary(f"RENDER ENDED (exit code {proc.returncode})")
    _running = False
    _render_its = 0.0


def _format_eta(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


def _get_eta() -> str:
    """Calculate and return an ETA string based on observed it/s and config."""
    if not _running or _render_its <= 0:
        return ""
    conf = _render_conf or {}
    num_scenes = max(1, len([s for s in conf.get("scenes", "").split("||") if s.strip()]))
    steps_per_scene = conf.get("steps_per_scene", 10000)
    total_steps = num_scenes * steps_per_scene
    # Steps completed so far: completed scenes + current bar progress
    done = (_render_scene * steps_per_scene) + _render_step
    remaining = max(0, total_steps - done)
    if remaining == 0:
        return "ETA: finishing..."
    eta_sec = remaining / _render_its
    return f"ETA: ~{_format_eta(eta_sec)} remaining ({_render_its:.1f} it/s, {done}/{total_steps} steps)"


def start_render(conf_name: str):
    global _proc, _running, _render_its, _render_step, _render_step_total, _render_scene, _scene_prompt_count, _render_conf, _render_start, _stop_requested, _summary_appended
    if _running:
        return "Already running."
    with _log_lock:
        _log_lines.clear()
    _running = True
    _stop_requested = False
    _summary_appended = False
    _render_its = 0.0
    _render_step = 0
    _render_step_total = 0
    _render_scene = 0
    _scene_prompt_count = 0
    _render_start = time.time()
    # Snapshot config for ETA calculations
    name = conf_name if conf_name.endswith(".yaml") else conf_name + ".yaml"
    _render_conf = load_conf(name) if (CONF_DIR / name).exists() else {}
    conf_name = conf_name.removesuffix(".yaml")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    _proc = subprocess.Popen(
        [str(PYTHON_EXE), "-W", "ignore", "-m", "pytti.workhorse", f"conf='{conf_name}'"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    t = threading.Thread(target=_stream_output, args=(_proc,), daemon=True)
    t.start()
    return "Render started."


def get_encodable_runs():
    """Scan outputs/ for runs that have PNG frames."""
    runs = []
    if not OUTPUTS_DIR.exists():
        return runs
    for day_dir in sorted(OUTPUTS_DIR.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        for time_dir in sorted(day_dir.iterdir(), reverse=True):
            if not time_dir.is_dir():
                continue
            images_out = time_dir / "images_out"
            if not images_out.exists():
                continue
            for ns_dir in sorted(images_out.iterdir()):
                if not ns_dir.is_dir():
                    continue
                pngs = list(ns_dir.glob("*.png"))
                if pngs:
                    label = f"{day_dir.name}/{time_dir.name} ({ns_dir.name}) — {len(pngs)} frames"
                    runs.append((label, str(ns_dir)))
    return runs


def encode_video(frames_dir: str, fps: int, fmt: str):
    """Encode a PNG frame sequence to video using ffmpeg."""
    if not frames_dir:
        return "Select a run first."
    frames_path = Path(frames_dir)
    if not frames_path.exists():
        return f"Directory not found: {frames_dir}"

    # Find the frame pattern and count
    pngs = sorted(frames_path.glob("*.png"))
    if not pngs:
        return "No PNG frames found."

    # Detect naming pattern from first file (e.g. default_0001.png or default_1.png)
    first = pngs[0].name
    m = re.match(r"^(.+_)(\d+)\.png$", first)
    if not m:
        return f"Cannot parse frame naming pattern from: {first}"
    prefix = m.group(1)
    digits = len(m.group(2))
    # Use zero-padded format if frames are padded (e.g. %04d), otherwise %d
    fmt = f"%0{digits}d" if digits > 1 else "%d"
    pattern = str(frames_path / f"{prefix}{fmt}.png")

    # Find start number
    numbers = []
    for p in pngs:
        nm = re.search(r"_(\d+)\.png$", p.name)
        if nm:
            numbers.append(int(nm.group(1)))
    start_num = min(numbers) if numbers else 1

    # Output path
    run_dir = frames_path.parent.parent  # up from images_out/namespace/
    if fmt == "ProRes 4444 (MOV)":
        ext = ".mov"
        codec_args = ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le"]
    elif fmt == "ProRes HQ (MOV)":
        ext = ".mov"
        codec_args = ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
    else:  # MP4
        ext = ".mp4"
        codec_args = ["-c:v", "libx264", "-crf", "17", "-preset", "slow", "-pix_fmt", "yuv420p"]

    out_file = run_dir / f"{frames_path.name}_{fps}fps{ext}"

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-start_number", str(start_num),
        "-i", pattern,
    ] + codec_args + [str(out_file)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            return f"ffmpeg error:\n{result.stderr[-500:]}"
        return f"Encoded {len(pngs)} frames → {out_file.name}\nSaved to: {out_file}"
    except FileNotFoundError:
        return "ffmpeg not found. Install ffmpeg and ensure it's on your PATH."
    except subprocess.TimeoutExpired:
        return "Encoding timed out (>10 minutes)."


def stop_render():
    global _proc, _running, _stop_requested
    if _proc and _running:
        _stop_requested = True
        _append_summary("RENDER STOPPED")
        _running = False
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
        return "Render stopped."
    return "No render running."


def get_log():
    with _log_lock:
        return "\n".join(_log_lines[-200:])


def get_latest_frame(namespace: str):
    """Find the most recent PNG for the given namespace without scanning the entire tree."""
    if not namespace:
        return None
    # Look for namespace dirs directly: outputs/**/images_out/<namespace>/*.png
    candidates = list(OUTPUTS_DIR.glob(f"**/images_out/{namespace}/*.png"))
    if not candidates:
        return None
    return str(max(candidates, key=lambda p: p.stat().st_mtime))



# ---------------------------------------------------------------------------
# Save config helper
# ---------------------------------------------------------------------------

def _num(value, default):
    """Safely convert a value to a number, returning default for Hydra resolver strings like ${...}."""
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _clean_prompt_field(text, leading_pipe=False, trailing_pipe=False):
    """Collapse whitespace and ensure proper | delimiters."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    if trailing_pipe and not cleaned.endswith("|"):
        cleaned += " |"
    if leading_pipe and not cleaned.startswith("|"):
        cleaned = "| " + cleaned
    return cleaned


def build_conf_dict(
    scenes, scene_prefix, scene_suffix,
    direct_image_prompts, init_image, direct_init_weight, semantic_init_weight,
    image_model, vqgan_model,
    animation_mode, video_path, frame_stride,
    width, height,
    steps_per_scene, steps_per_frame, interpolation_steps, pre_animation_steps,
    translate_x, translate_y, translate_z_3d, rotate_2d, rotate_3d,
    zoom_x_2d, zoom_y_2d, lock_camera,
    cutouts, cut_pow, cutout_border, learning_rate, seed, reset_lr_each_frame,
    border_mode, sampling_mode, infill_mode,
    ViTB32, ViTB16, ViTL14, ViTL14_336px, RN50, RN101, RN50x4, RN50x16, RN50x64,
    palette_size, palettes, pixel_size, gamma, hdr_weight, palette_normalization_weight,
    random_initial_palette, lock_palette, target_palette,
    frames_per_second, save_every, display_every, file_namespace, allow_overwrite, backups,
    field_of_view, near_plane, far_plane,
    gradient_accumulation_steps, smoothing_weight,
    direct_stabilization_weight, semantic_stabilization_weight,
    depth_stabilization_weight, edge_stabilization_weight, flow_stabilization_weight,
    reencode_each_frame,
    input_audio, input_audio_offset, flow_long_term_samples,
    breath_mode,
):
    return {
        "scenes": " ".join(scenes.split()),
        "scene_prefix": _clean_prompt_field(scene_prefix, trailing_pipe=True),
        "scene_suffix": _clean_prompt_field(scene_suffix, leading_pipe=True),
        "direct_image_prompts": direct_image_prompts.strip().strip("\"'()"),
        "init_image": init_image.strip().strip("\"'()"),
        "direct_init_weight": direct_init_weight,
        "semantic_init_weight": semantic_init_weight,
        "image_model": image_model,
        "vqgan_model": vqgan_model,
        "animation_mode": animation_mode,
        "video_path": video_path.strip().strip("\"'()"),
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
        "cutout_border": float(cutout_border),
        "learning_rate": float(learning_rate) if learning_rate else None,
        "seed": int(seed) if str(seed).strip().isdigit() else random.randint(0, 2**32 - 1),
        "reset_lr_each_frame": reset_lr_each_frame,
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
        "RN50x64": RN50x64,
        "pixel_size": int(pixel_size),
        "palette_size": int(palette_size),
        "palettes": int(palettes),
        "gamma": float(gamma),
        "hdr_weight": float(hdr_weight),
        "palette_normalization_weight": float(palette_normalization_weight),
        "random_initial_palette": random_initial_palette,
        "lock_palette": lock_palette,
        "target_palette": target_palette.strip().strip("\"'()"),
        "frames_per_second": int(frames_per_second),
        "save_every": int(save_every),
        "display_every": int(display_every),
        "file_namespace": file_namespace,
        "allow_overwrite": allow_overwrite,
        "backups": int(backups),
        "field_of_view": int(field_of_view),
        "near_plane": int(near_plane),
        "far_plane": int(far_plane),
        "gradient_accumulation_steps": int(gradient_accumulation_steps),
        "smoothing_weight": float(smoothing_weight),
        "direct_stabilization_weight": direct_stabilization_weight,
        "semantic_stabilization_weight": semantic_stabilization_weight,
        "depth_stabilization_weight": depth_stabilization_weight,
        "edge_stabilization_weight": edge_stabilization_weight,
        "flow_stabilization_weight": flow_stabilization_weight,
        "reencode_each_frame": reencode_each_frame,
        "input_audio": input_audio.strip().strip("\"'()"),
        "input_audio_offset": float(input_audio_offset),
        "flow_long_term_samples": int(flow_long_term_samples),
        "breath_mode": breath_mode,
    }


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

def make_ui():
    cfg = load_defaults()

    _AUTO_SCROLL_JS = """
    () => {
        const obs = new MutationObserver(() => {
            const el = document.querySelector('#log-box textarea');
            if (el) el.scrollTop = el.scrollHeight;
        });
        const target = document.getElementById('log-box');
        if (target) obs.observe(target, {childList: true, subtree: true, characterData: true});
    }
    """
    with gr.Blocks(title="PyTTI", theme=_THEME, css=_THEME_CSS, js=_AUTO_SCROLL_JS) as demo:
        gr.HTML("""
        <div style="display:flex; align-items:baseline; justify-content:space-between; padding:12px 0 4px; border-bottom:1px solid #0d3048; margin-bottom:16px;">
            <div>
                <span style="font-family:'Share Tech Mono',monospace; font-size:1.6rem; color:#00e5ff; letter-spacing:0.2em; text-transform:uppercase;">PyTTI</span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#ff6d00; letter-spacing:0.1em; margin-left:8px; vertical-align:super;">BETA</span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.7rem; color:#5fa8be; letter-spacing:0.15em; margin-left:16px;">NEURAL IMAGE SYNTHESIZER</span>
            </div>
            <span style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#5fa8be; letter-spacing:0.1em;">v1.0.0</span>
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
                    vqgan_model    = gr.Dropdown(label="VQGAN Model",    choices=["sflickr", "imagenet", "coco", "wikiart", "openimages", "faceshq"], value=cfg.get("vqgan_model", "coco"),          info=TIPS["vqgan_model"],    scale=2)
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
                    steps_per_scene = gr.Number(label="Steps per Scene", value=cfg.get("steps_per_scene", 10000), precision=0, info=TIPS["steps_per_scene"])
                    steps_per_frame = gr.Number(label="Steps per Frame", value=cfg.get("steps_per_frame", 80), precision=0, info=TIPS["steps_per_frame"])
                with gr.Row():
                    interpolation_steps = gr.Number(label="Interpolation Steps", value=cfg.get("interpolation_steps", 250), precision=0, info=TIPS["interpolation_steps"])
                    pre_animation_steps = gr.Number(label="Pre-animation Steps", value=cfg.get("pre_animation_steps", 50), precision=0, info=TIPS["pre_animation_steps"])
                with gr.Row():
                    cutouts = gr.Number(label="Cutouts", value=cfg.get("cutouts", 50), precision=0, info=TIPS["cutouts"])
                    cut_pow = gr.Number(label="Cut Power", value=cfg.get("cut_pow", 2.1), info=TIPS["cut_pow"])
                    cutout_border = gr.Number(label="Cutout Border", value=cfg.get("cutout_border", 0.25), info="Border width for cutouts. Controls how much padding is added around each cutout.")
                with gr.Row():
                    learning_rate = gr.Textbox(label="Learning Rate (blank = auto)", value=str(cfg.get("learning_rate", "") or ""), info=TIPS["learning_rate"])
                    seed = gr.Textbox(label="Seed (blank = random)", value=str(cfg.get("seed", "")), info=TIPS["seed"])
                    reset_lr_each_frame = gr.Checkbox(label="Reset LR Each Frame", value=cfg.get("reset_lr_each_frame", True), info="Reset the learning rate at the start of each frame.")
                with gr.Row():
                    gradient_accumulation_steps = gr.Number(label="Gradient Accumulation Steps", value=cfg.get("gradient_accumulation_steps", 2), precision=0, info=TIPS["gradient_accumulation_steps"])
                    smoothing_weight = gr.Number(label="Smoothing Weight", value=cfg.get("smoothing_weight", 0.02), info="Total variation loss weight — higher values produce smoother images, lower values preserve more detail.")

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
                    RN50x64 = gr.Checkbox(label="RN50x64", value=cfg.get("RN50x64", False))

            # ----------------------------------------------------------------
            # TAB: Palette
            # ----------------------------------------------------------------
            with gr.Tab("Palette"):
                with gr.Row():
                    palette_size = gr.Number(label="Palette Size", value=cfg.get("palette_size", 50), precision=0, info=TIPS["palette_size"])
                    palettes = gr.Number(label="Palettes", value=cfg.get("palettes", 18), precision=0, info=TIPS["palettes"])
                    pixel_size = gr.Number(label="Pixel Size", value=cfg.get("pixel_size", 4), precision=0, info="Size of each pixel block in Limited Palette mode. Higher = more pixelated.")
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
                reencode_each_frame = gr.Checkbox(label="Re-encode Each Frame", value=cfg.get("reencode_each_frame", True), info="Re-encode video frames through the image model each step. Disable for faster but lower quality video mode.")
                input_audio = gr.Textbox(label="Input Audio Path", value=cfg.get("input_audio", ""), info=TIPS["input_audio"])
                input_audio_offset = gr.Number(label="Audio Offset (seconds)", value=cfg.get("input_audio_offset", 0), info="Offset in seconds to sync audio with the animation.")

            # ----------------------------------------------------------------
            # TAB: Output
            # ----------------------------------------------------------------
            with gr.Tab("Output"):
                with gr.Row():
                    file_namespace = gr.Textbox(label="File Namespace", value=cfg.get("file_namespace", "default"), info=TIPS["file_namespace"])
                    frames_per_second = gr.Number(label="FPS", value=cfg.get("frames_per_second", 15), precision=0, info=TIPS["frames_per_second"])
                with gr.Row():
                    save_every = gr.Number(label="Save Every N Steps", value=cfg.get("save_every", 0), precision=0, info=TIPS["save_every"])
                    display_every = gr.Number(label="Display Every N Steps", value=cfg.get("display_every", 50), precision=0, info=TIPS["display_every"])
                with gr.Row():
                    allow_overwrite = gr.Checkbox(label="Allow Overwrite", value=cfg.get("allow_overwrite", True), info=TIPS["allow_overwrite"])
                    backups = gr.Number(label="Backups", value=cfg.get("backups", 0), precision=0, info="Number of backup copies to keep for each frame. 0 = no backups.")
                breath_mode = gr.Checkbox(label="Breath Mode", value=cfg.get("breath_mode", False), info=TIPS["breath_mode"])

                gr.Markdown("### Encode Video")
                with gr.Row(equal_height=True):
                    encode_run_dropdown = gr.Dropdown(
                        label="Run",
                        choices=[],
                        scale=2,
                        info="Select a run with saved frames.",
                    )
                    encode_refresh_btn = gr.Button("↻", variant="secondary", scale=0, min_width=36, elem_classes=["btn-sm"])
                with gr.Row():
                    encode_fps = gr.Number(label="FPS", value=30, precision=0, scale=1, info="Output video frame rate.")
                    encode_format = gr.Dropdown(
                        label="Format",
                        choices=["MP4 (H.264)", "ProRes 4444 (MOV)", "ProRes HQ (MOV)"],
                        value="MP4 (H.264)",
                        scale=1,
                        info="MP4 for sharing, ProRes for lossless editing.",
                    )
                with gr.Row():
                    encode_btn = gr.Button("Encode Video", variant="primary", scale=2)
                encode_status = gr.Textbox(label="Encode Status", interactive=False, lines=2)

            # ----------------------------------------------------------------
            # TAB: Run
            # ----------------------------------------------------------------
            with gr.Tab("Run"):
                with gr.Row(equal_height=True):
                    conf_name_input = gr.Textbox(label="Config Name", placeholder="my_run", scale=2)
                    load_conf_dropdown = gr.Dropdown(label="Load Config", choices=get_conf_files(), scale=2)
                    refresh_configs_btn = gr.Button("↻", variant="secondary", scale=0, min_width=36, elem_classes=["btn-sm"])
                    load_btn = gr.Button("Load", variant="secondary", scale=0, min_width=70, elem_classes=["btn-sm"])
                    save_btn = gr.Button("Save", variant="secondary", scale=0, min_width=70, elem_classes=["btn-sm"])
                with gr.Row():
                    run_btn = gr.Button("Start Render", variant="primary", scale=2)
                    stop_btn = gr.Button("Stop Render", variant="stop", scale=1)
                status_box = gr.Textbox(label="Status", interactive=False, lines=1)

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
                gr.HTML(_HELP_HTML)

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
            cutouts, cut_pow, cutout_border, learning_rate, seed, reset_lr_each_frame,
            border_mode, sampling_mode, infill_mode,
            ViTB32, ViTB16, ViTL14, ViTL14_336px, RN50, RN101, RN50x4, RN50x16, RN50x64,
            palette_size, palettes, pixel_size, gamma, hdr_weight, palette_normalization_weight,
            random_initial_palette, lock_palette, target_palette,
            frames_per_second, save_every, display_every, file_namespace, allow_overwrite, backups,
            field_of_view, near_plane, far_plane,
            gradient_accumulation_steps, smoothing_weight,
            direct_stabilization_weight, semantic_stabilization_weight,
            depth_stabilization_weight, edge_stabilization_weight, flow_stabilization_weight,
            reencode_each_frame,
            input_audio, input_audio_offset, flow_long_term_samples,
            breath_mode,
        ]

        # ----------------------------------------------------------------
        # Callbacks
        # ----------------------------------------------------------------
        def save_config(*args):
            name = args[0]
            values = args[1:]
            if not name:
                return gr.update(), "Enter a config name first."
            if not name.endswith(".yaml"):
                name += ".yaml"
            data = build_conf_dict(*values)
            path = CONF_DIR / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("# @package _global_\n")
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
            return gr.Dropdown(choices=get_conf_files()), f"Saved to config/conf/{name}"

        def run_render(conf_name):
            if not conf_name:
                return "No config name set. Enter a name above."
            name = conf_name if conf_name.endswith(".yaml") else conf_name + ".yaml"
            if not (CONF_DIR / name).exists():
                return f"Config '{name}' not found. Click Save first."
            return start_render(conf_name)

        def refresh(namespace):
            eta = _get_eta()
            log = get_log()
            if eta:
                log = f"[{eta}]\n{log}"
            return log, get_latest_frame(namespace)

        def load_existing(name):
            if not name:
                return [gr.update()] * (len(all_inputs) + 1)
            data = merged_config(name)
            conf_display = name.removesuffix(".yaml")
            return [
                " ".join(data.get("scenes", "").split()),
                " ".join(data.get("scene_prefix", "").split()),
                " ".join(data.get("scene_suffix", "").split()),
                data.get("direct_image_prompts", ""),
                data.get("init_image", ""),
                str(data.get("direct_init_weight", "") or ""),
                str(data.get("semantic_init_weight", "") or ""),
                data.get("image_model", "Limited Palette"),
                data.get("vqgan_model", "coco"),
                data.get("animation_mode", "3D"),
                data.get("video_path", ""),
                _num(data.get("frame_stride", 1), 1),
                _num(data.get("width", 512), 512),
                _num(data.get("height", 512), 512),
                _num(data.get("steps_per_scene", 10000), 10000),
                _num(data.get("steps_per_frame", 80), 80),
                _num(data.get("interpolation_steps", 250), 250),
                _num(data.get("pre_animation_steps", 50), 50),
                str(data.get("translate_x", "0")),
                str(data.get("translate_y", "0")),
                str(data.get("translate_z_3d", "0")),
                str(data.get("rotate_2d", "0")),
                str(data.get("rotate_3d", "[1, 0, 0, 0]")),
                str(data.get("zoom_x_2d", "0")),
                str(data.get("zoom_y_2d", "0")),
                data.get("lock_camera", True),
                _num(data.get("cutouts", 50), 50),
                _num(data.get("cut_pow", 2.1), 2.1),
                _num(data.get("cutout_border", 0.25), 0.25),
                str(data.get("learning_rate", "") or ""),
                str(data.get("seed", "")),
                data.get("reset_lr_each_frame", True),
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
                data.get("RN50x64", False),
                _num(data.get("palette_size", 50), 50),
                _num(data.get("palettes", 18), 18),
                _num(data.get("pixel_size", 4), 4),
                _num(data.get("gamma", 1.5), 1.5),
                _num(data.get("hdr_weight", 0.35), 0.35),
                _num(data.get("palette_normalization_weight", 0.75), 0.75),
                data.get("random_initial_palette", False),
                data.get("lock_palette", False),
                data.get("target_palette", ""),
                _num(data.get("frames_per_second", 15), 15),
                _num(data.get("save_every", 0), 0),
                _num(data.get("display_every", 50), 50),
                data.get("file_namespace", "default"),
                data.get("allow_overwrite", True),
                _num(data.get("backups", 0), 0),
                _num(data.get("field_of_view", 60), 60),
                _num(data.get("near_plane", 2000), 2000),
                _num(data.get("far_plane", 12500), 12500),
                _num(data.get("gradient_accumulation_steps", 2), 2),
                _num(data.get("smoothing_weight", 0.02), 0.02),
                str(data.get("direct_stabilization_weight", "1")),
                str(data.get("semantic_stabilization_weight", "") or ""),
                str(data.get("depth_stabilization_weight", "") or ""),
                str(data.get("edge_stabilization_weight", "") or ""),
                str(data.get("flow_stabilization_weight", "") or ""),
                data.get("reencode_each_frame", True),
                data.get("input_audio", ""),
                _num(data.get("input_audio_offset", 0), 0),
                _num(data.get("flow_long_term_samples", 1), 1),
                data.get("breath_mode", False),
                conf_display,
            ]

        def run_and_activate_timer(*args):
            # Auto-save before running so the YAML always matches the UI
            save_result = save_config(*args)
            conf_name = args[0]
            msg = run_render(conf_name)
            return save_result[0], msg, gr.Timer(active=True)

        def stop_and_deactivate_timer(namespace):
            msg = stop_render()
            log, frame = refresh(namespace)
            return msg, gr.Timer(active=False), log, frame

        save_btn.click(fn=save_config, inputs=[conf_name_input] + all_inputs, outputs=[load_conf_dropdown, status_box])
        run_btn.click(fn=run_and_activate_timer, inputs=[conf_name_input] + all_inputs, outputs=[load_conf_dropdown, status_box, timer])
        stop_btn.click(fn=stop_and_deactivate_timer, inputs=[file_namespace], outputs=[status_box, timer, log_box, frame_preview])
        refresh_btn.click(fn=refresh, inputs=[file_namespace], outputs=[log_box, frame_preview])
        timer.tick(fn=refresh, inputs=[file_namespace], outputs=[log_box, frame_preview])
        load_btn.click(fn=load_existing, inputs=[load_conf_dropdown], outputs=all_inputs + [conf_name_input])
        refresh_configs_btn.click(fn=lambda: gr.Dropdown(choices=get_conf_files()), outputs=[load_conf_dropdown])

        # Encode video callbacks
        def refresh_encode_list():
            runs = get_encodable_runs()
            choices = [(lbl, path) for lbl, path in runs]
            return gr.Dropdown(choices=choices, value=choices[0][1] if choices else None)

        encode_refresh_btn.click(fn=refresh_encode_list, outputs=[encode_run_dropdown])
        encode_btn.click(fn=encode_video, inputs=[encode_run_dropdown, encode_fps, encode_format], outputs=[encode_status])
        # Auto-populate on load
        demo.load(fn=refresh_encode_list, outputs=[encode_run_dropdown])

    return demo


if __name__ == "__main__":
    print(f"Using Python: {PYTHON_EXE}")
    demo = make_ui()
    demo.launch(inbrowser=True, show_api=False)
