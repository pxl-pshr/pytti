"""
pytti Portable UI
=================
Run via launch.bat — do not run directly with system Python.
"""
__version__ = "1.1.0-beta"  # install.bat and launch.bat read this line for their banners
import ast
import atexit
import contextlib
import ctypes
import difflib
import html
import importlib.util
import inspect
import io
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

# Must be set before gradio is imported: no usage telemetry, no version check and no
# message fetch at import time (gr.Blocks(analytics_enabled=False) misses that one)
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

# Colors and cursor moves (tqdm moves up and down between nested bars)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

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
import yaml

# ---------------------------------------------------------------------------
# Tooltips
# ---------------------------------------------------------------------------
TIPS = {
    "scenes": "Text prompts the render optimizes toward. Prompts separated by | are combined within a scene; use || to start a new scene.",
    "scene_prefix": "Prepended to every scene prompt. Useful for style keywords shared across all scenes.",
    "scene_suffix": "Appended to every scene prompt. Useful for negative or quality terms applied globally.",
    "direct_image_prompts": "Path or URL of an image the render is pulled toward pixel by pixel (no CLIP). Add :weight, and _maskpath for a mask.",
    "init_image": "Starting image for the render. Blank = start from noise.",
    "direct_init_weight": "How strongly the init image guides pixel appearance at the start.",
    "semantic_init_weight": "How strongly the init image guides semantic/CLIP content at the start.",
    "image_model": "Limited Palette: fast, painterly. Unlimited Palette: photographic. VQGAN: classic neural style.",
    "vqgan_model": "Which VQGAN codebook to use when image_model is VQGAN. Only affects VQGAN mode. Each downloads once, on first use: 0.3 to 4.3 GB (see the FAQ tab).",
    "animation_mode": "off: single image. 2D/3D: camera moves each frame. Video Source: warp to a reference video.",
    "video_path": "Source video for Video Source animation mode.",
    "frame_stride": "Source video frames to advance per animation frame. 1 = every frame.",
    "width": "Output image width in pixels.",
    "height": "Output image height in pixels.",
    "translate_x": "Horizontal camera movement per frame. Supports Python expressions with t (time in seconds).",
    "translate_y": "Vertical camera movement per frame. Supports Python expressions with t (time in seconds).",
    "translate_z_3d": "Forward/back camera movement per frame (3D mode). Supports Python expressions with t (time in seconds).",
    "rotate_2d": "Rotation in degrees per frame (2D mode). Supports Python expressions with t (time in seconds).",
    "rotate_3d": "Quaternion [w, x, y, z] rotation per frame (3D mode). Supports Python expressions with t (time in seconds).",
    "zoom_x_2d": "Horizontal zoom per frame (2D mode). Supports Python expressions with t (time in seconds).",
    "zoom_y_2d": "Vertical zoom per frame (2D mode). Supports Python expressions with t (time in seconds).",
    "lock_camera": "3D only: cancels the average movement every frame, so Translate X/Y and turning leave only parallax. Turn off to pan or turn; rolls and Translate Z are not affected.",
    "field_of_view": "Camera field of view in degrees (3D mode), between 0 and 180. Lower = telephoto, higher = wide-angle.",
    "near_plane": "3D only: the depth model's 0-10 m range is spread from Near Plane to Far Plane, in pixels. Higher values push the scene farther away and weaken all movement; nothing is clipped.",
    "far_plane": "3D only: where the depth model's 10 m lands, in pixels (see Near Plane). Higher values push distant scenery farther away; nothing is clipped.",
    "border_mode": "How CLIP cutouts treat the area past the image edge (camera moves use Infill Mode). clamp keeps cutouts inside the image, wrap tiles, mirror reflects, black pads with black, smear repeats edge pixels.",
    "sampling_mode": "Interpolation quality when warping. bicubic is sharpest.",
    "infill_mode": "How to fill areas revealed by camera movement.",
    "steps_per_scene": "Total optimization steps for the whole scene. More = longer render, more developed image.",
    "steps_per_frame": "Optimization steps before advancing to the next animation frame.",
    "interpolation_steps": "Steps used to blend between scenes during a transition.",
    "pre_animation_steps": "Steps run before any camera movement starts. Lets the image develop first.",
    "cutouts": "Number of random crops used per CLIP evaluation. More = richer gradients, slower.",
    "cut_pow": "Controls cutout size distribution. Higher = more small crops (fine detail).",
    "learning_rate": "Optimizer step size. Leave blank for auto (0.02 for the palette models, about 0.1 for VQGAN). Lower = more stable but slower.",
    "seed": "Random seed for reproducibility. Leave blank for a new random seed each run; the seed used is shown in the log.",
    "gradient_accumulation_steps": "Split each step's cutouts into N smaller batches. 1 is fastest; 2 or more uses less VRAM. Same result either way. Must divide Cutouts evenly.",
    "palette_size": "Number of colors per palette swatch (Limited Palette mode).",
    "palettes": "Number of palette swatches (Limited Palette mode).",
    "gamma": "Gamma correction applied to the palette (Limited Palette mode).",
    "hdr_weight": "Weight for HDR-like contrast enhancement (Limited Palette mode).",
    "palette_normalization_weight": "Keeps palette colors spread across the value range.",
    "random_initial_palette": "Start the palette from random colors instead of grayscale.",
    "lock_palette": "Prevent the palette from evolving during the render.",
    "target_palette": "Path to an image — palette colors will be pulled toward this image's colors.",
    "direct_stabilization_weight": "Resist pixel-level change between frames. Keeps the image stable.",
    "semantic_stabilization_weight": "Resist semantic/CLIP-level change between frames.",
    "depth_stabilization_weight": "Resist changes to the depth structure between frames.",
    "edge_stabilization_weight": "Resist changes to edges between frames.",
    "flow_stabilization_weight": "Optical flow stabilization — aligns each frame to the previous one.",
    "flow_long_term_samples": "How many past frames to consider for flow stabilization.",
    "input_audio": "Path to an audio file for audioreactive animation. Only used when input_audio_filters are defined in the preset YAML.",
    "file_namespace": "Name for the frame files. Each render is saved to outputs/<date>/<time>/images_out/<namespace>/ inside the app folder.",
    "frames_per_second": "Playback FPS when assembling the final video.",
    "save_every": "Save a frame every N steps. 0 = auto-match steps_per_frame (recommended). Set manually to override.",
    "breath_mode": "Gradually blend from init image to CLIP-optimized. Frame 1 = init image, last frame = fully optimized. Requires init image; best with little camera motion.",
    "display_every": "No visible effect in this UI: pytti reports losses only at debug level, which the log leaves out. The Latest Frame preview updates whenever a frame is saved.",
}

# ---------------------------------------------------------------------------
# Help / Wiki data — grouped settings with extended descriptions
# ---------------------------------------------------------------------------
HELP_SECTIONS = [
    ("Prompts", [
        ("scenes", "Text prompts that describe what the image should look like. Separate prompts within a scene with <code>|</code> and weight them with <code>:weight</code> (e.g. <code>forest:2</code> for double weight). Use <code>||</code> to separate scenes — the render transitions between them using <code>interpolation_steps</code> via linear interpolation in CLIP semantic space. Negative weights push the image <em>away</em> from a concept (e.g. <code>blurry:-1</code>). You can also set a <code>:stop</code> value to freeze a prompt after a threshold is reached.", "string"),
        ("scene_prefix", "Text prepended to every scene prompt. Useful for global style keywords like <code>oil painting |</code> or <code>highly detailed |</code> that you want applied everywhere without repeating them in each scene.", "string"),
        ("scene_suffix", "Text appended to every scene prompt. Commonly used for negative prompts like <code>| text:-1 | watermark:-1</code> to suppress unwanted elements globally across all scenes.", "string"),
        ("direct_image_prompts", "Path or URL of an image used as a pixel-level target: the render is pulled toward this picture by an HSV loss (a latent loss with VQGAN), without CLIP. Local paths such as <code>C:\\images\\ref.png</code> work; relative paths are looked up from the pytti folder. Separate several images with <code>|</code>. Supports <code>weight_mask</code> syntax with an absolute mask path, e.g. <code>C:\\images\\ref.png:1.5_C:\\masks\\mask.png</code>; a relative mask path is not found. Video masks must end in <code>.mp4</code>.", "path"),
        ("init_image", "Path to a starting image. The render begins from this instead of random noise, creating an initial focal point and layout. Leave blank for a random start. Tip: use with <code>semantic_init_weight</code> to keep the output resembling the init image throughout.", "path"),
        ("direct_init_weight", "Treats the init image as a direct image prompt with this weight (pixel-level MSE loss). Higher = stays closer to original pixels.", "weight"),
        ("semantic_init_weight", "Treats the init image as a semantic (CLIP-level) prompt with this weight. The render will <em>feel like</em> the init image without being pixel-locked to it. Mask paths go in <code>[ ]</code> brackets.", "weight"),
    ]),
    ("Image Model", [
        ("image_model", "<strong>Limited Palette</strong>: fast, painterly look using discrete color swatches — total colors = <code>palette_size × palettes</code>. <strong>Unlimited Palette</strong>: per-pixel color, more photographic. <strong>VQGAN</strong>: classic neural art using a pretrained codebook (set <code>pixel_size: 1</code> with VQGAN to avoid VRAM issues).", "choice"),
        ("vqgan_model", "Which VQGAN codebook to use. Only matters when <code>image_model</code> is VQGAN. Options: <code>imagenet</code>, <code>coco</code>, <code>wikiart</code>, <code>sflckr</code>, <code>openimages</code>. Each has a different visual style bias. A model downloads once, on first use: <code>coco</code> 0.3 GB, <code>openimages</code> 0.4 GB, <code>imagenet</code> 1.0 GB, <code>wikiart</code> 1.0 GB, <code>sflckr</code> 4.3 GB.", "choice"),
    ]),
    ("Animation", [
        ("animation_mode", "<strong>off</strong>: single image, no animation. <strong>2D</strong>: pan/zoom/rotate the canvas each frame. <strong>3D</strong>: full 3D camera with AdaBins depth estimation. <strong>Video Source</strong>: warp frames of a source video using optical flow.", "choice"),
        ("translate_x", "Horizontal camera shift per frame (pixels). Accepts Python expressions using <code>t</code> (time in seconds, scaled by <code>frames_per_second</code>), e.g. <code>10*sin(t/30)</code>.", "expression"),
        ("translate_y", "Vertical camera shift per frame (pixels). Same expression support — <code>t</code> is time in seconds.", "expression"),
        ("translate_z_3d", "Forward/backward camera movement per frame (3D mode only). Positive = move forward into the scene. Expressions with <code>t</code> supported. In 3D mode, motion expressions can also use the depth of the current frame in pixels: <code>r</code> (nearest point), <code>R</code> (farthest point) and <code>mu</code> (typical depth).", "expression"),
        ("rotate_3d", "Quaternion rotation per frame in 3D mode: <code>[w, x, y, z]</code>. Use <code>cos(radians(N))</code> and <code>sin(radians(N))</code> for smooth rotations. <code>t</code> is time in seconds; <code>r</code>, <code>R</code> and <code>mu</code> (see <code>translate_z_3d</code>) work here too.", "expression"),
        ("rotate_2d", "Rotation in degrees per frame (2D mode). Expressions with <code>t</code> (time in seconds) supported.", "expression"),
        ("zoom_x_2d", "Horizontal zoom per frame (2D mode). <code>0</code> = no zoom. Expressions with <code>t</code> supported.", "expression"),
        ("zoom_y_2d", "Vertical zoom per frame (2D mode). <code>0</code> = no zoom. Expressions with <code>t</code> supported.", "expression"),
        ("lock_camera", "3D mode only. Subtracts the average movement from every frame so the view doesn't drift. That cancels <code>translate_x</code>, <code>translate_y</code> and looking up, down, left or right, leaving only the parallax between near and far objects: turn it off to pan or turn. Rolls and <code>translate_z_3d</code> are not affected. It does nothing during <code>pre_animation_steps</code>, when the camera doesn't move yet.", "bool"),
        ("field_of_view", "Vertical FOV in degrees (3D mode), more than 0 and less than 180. Lower values (30–40) give a telephoto look; higher (80–100) give wide-angle distortion.", "number"),
        ("near_plane", "3D mode. The depth model measures 0 to 10 meters, and <code>near_plane</code> and <code>far_plane</code> spread that range over pixels: with the defaults (1 and 10000) something 1 meter away sits about 1000 pixels from the camera. 3D moves shrink with depth, so raising <code>near_plane</code> pushes everything farther away, which weakens all movement and flattens the parallax. Nothing is clipped.", "number"),
        ("far_plane", "3D mode. Where the depth model's 10 meters lands, in pixels (see <code>near_plane</code>). Higher values push distant scenery farther away, so camera moves shift it less. Nothing is clipped.", "number"),
        ("video_path", "Path to an MP4 source video (Video Source mode). Each frame of this video guides one animation frame via optical flow.", "path"),
        ("frame_stride", "Video frames to advance per output frame. <code>1</code> = use every frame, <code>2</code> = every other. Only used in Video Source mode.", "number"),
    ]),
    ("Canvas & Edges", [
        ("width", "Output width in pixels. Larger = more detail but slower and more VRAM. Set to <code>-1</code> to derive it from the init image's (or source video's) aspect ratio. 3D mode and depth stabilization need a frame of at least about 384x384: <code>width × pixel_size ÷ 32</code> times <code>height × pixel_size ÷ 32</code>, each rounded down, must be at least 129, so 512x288 works and 512x256 does not.", "number"),
        ("height", "Output height in pixels. Same considerations as width, including the 3D minimum size. Set to <code>-1</code> to derive it from the init image's (or source video's) aspect ratio.", "number"),
        ("border_mode", "How CLIP's cutouts treat the area past the image edge; camera moves use <code>infill_mode</code> instead. <code>clamp</code> keeps cutouts inside the image, <code>wrap</code> tiles the image, <code>mirror</code> reflects it, <code>black</code> pads with black and <code>smear</code> repeats the edge pixels.", "choice"),
        ("sampling_mode", "Pixel sampling during animation warping: <code>nearest</code> (sharp/pixelated), <code>bilinear</code> (smooth), <code>bicubic</code> (sharpest).", "choice"),
        ("infill_mode", "How to fill newly revealed areas after camera movement: <code>wrap</code>, <code>mirror</code>, <code>black</code>, or <code>smear</code>.", "choice"),
    ]),
    ("Steps & Timing", [
        ("steps_per_scene", "Total optimization steps per scene. Frames generated = <code>steps_per_scene / steps_per_frame</code>. Keep it at least <code>interpolation_steps</code>, or the crossfade into the next scene never finishes. More steps = more refined image and more frames.", "number"),
        ("steps_per_frame", "Optimization steps between each animation frame. Lower = more frames (smoother video) but less refinement per frame.", "number"),
        ("interpolation_steps", "Steps for smooth crossfade between scenes (using <code>||</code> separator). Uses linear interpolation in CLIP semantic space. Set to <code>0</code> to cut between scenes instantly.", "number"),
        ("pre_animation_steps", "Steps to run before any camera movement begins. Lets the image develop from noise before motion starts.", "number"),
    ]),
    ("CLIP & Optimization", [
        ("cutouts", "Number of random crops (glimpses) per CLIP evaluation. More cutouts = richer gradients and better quality, but slower and less VRAM-efficient. 40–60 is typical.", "number"),
        ("cut_pow", "Controls cutout size distribution. Higher (2–3) = more small crops emphasizing fine detail but can be unstable. Lower = more large crops emphasizing global composition.", "number"),
        ("cutout_border", "Pads the whole image by this fraction of its size so cutouts can reach past the edges, into padding filled as <code>border_mode</code> says. <code>0</code> = cutouts stay inside the image. With <code>clamp</code> cutouts always stay inside, and the padding only places more of them at the edges.", "number"),
        ("learning_rate", "Optimizer step size. Leave blank to use the image model's own rate: 0.02 for Limited and Unlimited Palette, about 0.1 for VQGAN. For the palette models try 0.01–0.04; higher values change the image faster but can overshoot. Must be more than 0.", "number"),
        ("reset_lr_each_frame", "Reset the optimizer at each animation frame boundary. Clears Adam momentum buffers so each frame optimizes fresh. Disable to carry optimizer state across frames — can reduce color shifts but may cause instability.", "bool"),
        ("smoothing_weight", "Total variation loss weight — penalizes sharp pixel-to-pixel differences. Higher = smoother, more painterly images. Lower = more detail and texture but potentially noisy.", "number"),
        ("seed", "Pseudorandom seed for reproducibility. A fixed seed increases determinism — same seed + same config = similar output. Leave blank for a new random seed each run; the seed each render used is printed at the top of its log, so you can enter it here to repeat that render.", "number"),
        ("gradient_accumulation_steps", "Splits each step's cutouts into N smaller batches that are summed into one update; it does not change the result. Must divide <code>cutouts</code> evenly. 1 is fastest, and 2 or more uses less GPU memory. With the default settings a render uses about 9 GB at 2 and about 17 GB at 1, so 1 suits GPUs with 24 GB or more.", "number"),
        ("ViTB32", "Enable the ViT-B/32 CLIP model. Fast, good at composition. Recommended as a baseline. Each CLIP model requires significant VRAM. Downloads once, on first use: 338 MB.", "bool"),
        ("ViTB16", "Enable the ViT-B/16 CLIP model. More detail-sensitive than B/32. Slightly slower. Downloads once, on first use: 335 MB.", "bool"),
        ("ViTL14", "Enable the ViT-L/14 CLIP model. High quality but significantly slower and uses more VRAM. Downloads once, on first use: 890 MB.", "bool"),
        ("ViTL14_336px", "ViT-L/14 at 336px input resolution. Highest quality CLIP model but very heavy on VRAM. Downloads once, on first use: 891 MB.", "bool"),
        ("RN50", "Enable the ResNet-50 CLIP model. Different texture/style bias than ViT models — can add complementary detail. Downloads once, on first use: 244 MB.", "bool"),
        ("RN101", "Enable the ResNet-101 CLIP model. Similar to RN50 but slightly better quality. Downloads once, on first use: 278 MB.", "bool"),
        ("RN50x4", "Enable the ResNet-50x4 CLIP model. Good balance of quality and speed. Complements ViT models well. Downloads once, on first use: 402 MB.", "bool"),
        ("RN50x16", "Enable the ResNet-50x16 CLIP model. High quality but heavy on VRAM. Downloads once, on first use: 630 MB.", "bool"),
        ("RN50x64", "Enable the ResNet-50x64 CLIP model. Highest quality ResNet variant. Extremely heavy on VRAM — only use with plenty of GPU memory. Downloads once, on first use: 1.3 GB.", "bool"),
    ]),
    ("Limited Palette", [
        ("palette_size", "Number of colors per palette swatch. Total colors = <code>palette_size × palettes</code>. Lower (3–6) = more stylized/posterized. Higher (20–50) = smoother gradients.", "number"),
        ("palettes", "Number of independent palette swatches. More palettes = more color variety across the image. 12–30 is typical. Total colors = <code>palette_size × palettes</code>.", "number"),
        ("gamma", "Relative gamma value for the palette. Higher = darker with more contrast. Lower = brighter midtones.", "number"),
        ("hdr_weight", "Strength of gamma maintenance — pushes the palette toward higher dynamic range. <code>0</code> = disabled, 0.3–0.5 = subtle, 1.0+ = strong contrast boost.", "number"),
        ("palette_normalization_weight", "Keeps palette colors spread across the full brightness range, preventing individual palettes from being lost or going muddy/washed-out.", "number"),
        ("random_initial_palette", "Start with random colors instead of grayscale. Without this, palettes start grayscale and develop color during optimization. Good for abstract work.", "bool"),
        ("lock_palette", "Freeze the palette so colors don't change during the render. Palettes start grayscale, so this tends to produce grayscale output unless <code>random_initial_palette</code> or <code>target_palette</code> is used.", "bool"),
        ("target_palette", "Path to an image whose colors the palette will be pulled toward. The model extracts a color scheme from this image and uses it as a target.", "path"),
        ("pixel_size", "Output scale factor. The image is optimized at <code>width × height</code> and saved at <code>(width × pixel_size) × (height × pixel_size)</code>. With Limited/Unlimited Palette each optimized pixel becomes a <code>pixel_size</code>-wide block (chunky pixel-art look); with VQGAN it renders a larger image. Higher values use more VRAM.", "number"),
    ]),
    ("Stabilization", [
        ("direct_stabilization_weight", "Keeps the current frame as a direct (pixel-level) image prompt for the next frame. Higher = less flicker but more ghosting. <code>1</code> is a good default. Supports <code>weight_mask</code> syntax.", "weight"),
        ("semantic_stabilization_weight", "Keeps the current frame as a semantic (CLIP-level) prompt for the next frame. Prevents the <em>meaning</em> from drifting between frames. Supports masks.", "weight"),
        ("depth_stabilization_weight", "Keeps the depth map consistent between frames, using the depth model of 3D mode, so it needs the same minimum frame size (see <code>width</code>). Prevents depth map flickering. <strong>Steep performance cost</strong> — use sparingly. Supports masks.", "weight"),
        ("edge_stabilization_weight", "Preserves image contours/edges between frames. Reduces shimmer on hard edges. Low performance cost. Supports masks.", "weight"),
        ("flow_stabilization_weight", "Optical flow alignment — warps each frame to match previous motion. Prevents flickering in 3D and Video Source modes. High cost for 3D, slight cost for Video Source.", "weight"),
        ("flow_long_term_samples", "Number of past frames sampled for flow stabilization. The earliest sampled frame is <code>2^N</code> frames in the past. Higher = more temporal coherence but slower. In Video Source mode these frames are reloaded from backups, so <code>backups</code> must be at least <code>2^N + 1</code> (raised automatically).", "number"),
        ("reencode_each_frame", "Re-encode video source frames through the image model each step (Video Source mode). Enabled = higher quality but slower. Disabled = faster, uses raw video frames directly.", "bool"),
    ]),
    ("Audio (Experimental)", [
        ("input_audio", "Path to a WAV/MP3 file for audioreactive animation. Audio features are extracted through bandpass filters and exposed as variables for motion expressions. The filters are not editable in this UI: add an <code>input_audio_filters</code> list to the preset YAML in <code>config/conf/</code>, otherwise the audio is ignored.", "path"),
        ("input_audio_offset", "Offset in seconds into the audio file. Use to sync audio features with a specific point in the animation.", "number"),
    ]),
    ("Output", [
        ("file_namespace", "Name for the frame files and their folder. Each render gets its own timestamped folder, <code>app/outputs/&lt;date&gt;/&lt;time&gt;/images_out/&lt;namespace&gt;/</code>, so earlier renders are never overwritten.", "string"),
        ("frames_per_second", "Playback FPS for the final video — also controls how <code>t</code> is scaled in motion expressions. 12–15 for dreamy, 24–30 for smooth.", "number"),
        ("save_every", "Save a PNG frame every N optimization steps. <strong>0 = auto-match steps_per_frame</strong> (recommended). Set a value manually to override. Keep <code>pre_animation_steps</code> a multiple of <code>steps_per_frame</code> so each frame is saved right before the camera moves, when it's most refined.", "number"),
        ("display_every", "Has no visible effect in this UI: pytti reports losses only at debug level, which the live log leaves out. The Latest Frame preview updates whenever a frame is saved (see <code>save_every</code>).", "number"),
        ("backups", "Number of rolling <code>.bak</code> backup files each run keeps in its <code>backup</code> folder, holding the image model's state at the latest saved frames. Resume Render continues a stopped or failed render from the newest one, so renders keep at least 2: a lower value is raised when the render starts, without changing the preset. Each takes about <code>(palettes + 1) × width × height × 4</code> bytes with Limited Palette, about 20 MB at 512x512, and much less with the other image models. Video Source mode also reloads earlier frames from these for optical flow and needs at least <code>2^flow_long_term_samples + 1</code>; lower values are raised automatically.", "number"),
        ("breath_mode", "When enabled, saved frames linearly crossfade from the <code>init_image</code> to the CLIP-optimized output. Frame 1 is nearly 100% the init image; the final frame is 100% optimized. Requires <code>init_image</code> to be set. Works with all animation modes, but looks best with little or no camera motion: the init image stays still while the camera moves.", "bool"),
    ]),
]

def _format_default(value) -> str | None:
    """Render a default.yaml value for the help tab; None for resolver strings like ${now:%f}."""
    if isinstance(value, str) and value.startswith("${"):
        return None
    if value is None or value == "":
        return "blank"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build_help_html(defaults: dict):
    """Generate the full HTML for the help/wiki tab, with defaults taken from default.yaml."""
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
            shown_default = None
            if name in defaults and ftype not in ("string", "path"):
                shown_default = _format_default(defaults[name])
            if shown_default is not None:
                desc = f"{desc} Default: <code>{html.escape(shown_default)}</code>."
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
EMBEDDED_PYTHON = PORTABLE_ROOT / "python" / "python.exe"
# Models and Video Source conversions (cache/models, cache/video); install.bat keeps pip's
# downloads here too
CACHE_DIR = PORTABLE_ROOT / "cache"
# Fallback: system Python (for dev use)
PYTHON_EXE = EMBEDDED_PYTHON if EMBEDDED_PYTHON.exists() else Path(sys.executable)

# Must match pytti's VQGAN_MODEL_NAMES (pytti/image_models/vqgan.py); any other name crashes the render
VQGAN_MODELS = ["imagenet", "coco", "wikiart", "sflckr", "openimages"]
# Presets saved by older versions of this UI may use these names
_LEGACY_VQGAN_NAMES = {"sflickr": "sflckr"}
IMAGE_MODELS = ["Limited Palette", "Unlimited Palette", "VQGAN"]
ANIMATION_MODES = ["off", "Video Source", "2D", "3D"]
BORDER_MODES = ["clamp", "mirror", "wrap", "black", "smear"]
SAMPLING_MODES = ["nearest", "bilinear", "bicubic"]
INFILL_MODES = ["mirror", "wrap", "black", "smear"]
# Settings pytti accepts only from a fixed list; a typo in a hand-written preset fails the render
CHOICES = {
    "image_model": IMAGE_MODELS,
    "vqgan_model": VQGAN_MODELS,
    "animation_mode": ANIMATION_MODES,
    "border_mode": BORDER_MODES,
    "sampling_mode": SAMPLING_MODES,
    "infill_mode": INFILL_MODES,
}
CLIP_MODELS = ("ViTB32", "ViTB16", "ViTL14", "ViTL14_336px", "RN50", "RN101", "RN50x4", "RN50x16", "RN50x64")

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

class PresetError(Exception):
    """A preset that can't be read, worded for the status box."""


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict, header: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        # Keep the caller's key order: the UI's field order reads better than alphabetical
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_conf_files():
    files = sorted(CONF_DIR.glob("*.yaml"))
    return [f.name for f in files if not f.name.startswith("_")]


# Load Config's first entry: default.yaml's settings with a blank Config Name. A page
# reload brings back the last preset, so this is the way back to the defaults.
DEFAULTS_CHOICE = "(defaults)"


def load_choices() -> list[str]:
    """Load Config's entries: the defaults, then the presets."""
    return [DEFAULTS_CHOICE] + get_conf_files()


def load_defaults() -> dict:
    return load_yaml(DEFAULT_YAML)


def _yaml_problem(error: yaml.YAMLError) -> str:
    """A YAML error as one line: what is wrong and where."""
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or (str(error).strip().splitlines() or ["not valid YAML"])[0]
    return f"{problem} (line {mark.line + 1}, column {mark.column + 1})" if mark else problem


def load_conf(name: str) -> dict:
    """conf/<name> as a dict, {} if it doesn't exist; PresetError if it can't be read."""
    path = CONF_DIR / name
    if not path.exists():
        return {}
    try:
        data = load_yaml(path)
    except yaml.YAMLError as e:
        reason = _yaml_problem(e)
    except UnicodeDecodeError:
        reason = "it isn't saved as UTF-8 text"
    except OSError as e:
        reason = e.strerror or str(e)
    else:
        if isinstance(data, dict):
            return data
        reason = "it should hold one setting per line, as name: value"
    raise PresetError(f"Could not read config/conf/{name}: {reason}.")


def _conf_mtime(name: str) -> int | None:
    """mtime_ns of conf/<name>; None if it doesn't exist."""
    try:
        return (CONF_DIR / name).stat().st_mtime_ns
    except OSError:
        return None


def _stamped(name: str, stamp) -> bool:
    """Whether stamp is for conf/<name>; Windows file names ignore case."""
    return bool(stamp) and os.path.normcase(stamp[0]) == os.path.normcase(name)


def _changed_on_disk(name: str, stamp) -> int | None:
    """conf/<name>'s new mtime_ns if it changed since this page loaded or saved it, else None.

    stamp is (file name, mtime_ns as loaded or saved, mtime_ns the user was warned about).
    """
    if not _stamped(name, stamp):
        return None
    mtime = _conf_mtime(name)
    return mtime if mtime not in (None, stamp[1]) else None


def _not_loaded_here(name: str, stamp) -> bool:
    """Whether saving would replace conf/<name>, a preset this page didn't load or save."""
    return _valid_name(_conf_name(name)) and (CONF_DIR / name).exists() and not _stamped(name, stamp)


def _listed_name(name: str) -> str:
    """conf/<name> as Load Config lists it, which may differ in case."""
    return next((listed for listed in get_conf_files() if os.path.normcase(listed) == os.path.normcase(name)), name)


# ---------------------------------------------------------------------------
# Render process management
# ---------------------------------------------------------------------------
_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()     # serializes start/stop with the reader thread's end-of-render bookkeeping
_log_lines: list[str] = []
_log_lock = threading.Lock()
_running = False
_render_its: float = 0.0          # latest observed it/s from tqdm
_render_step: int = 0             # current step within tqdm bar
_render_scene: int = 0            # completed scenes count
_render_dir: Path | None = None   # Hydra run folder of the current (or last) render
_render_namespace: str = ""       # file_namespace of that render
_scene_prompt_count: int = 0     # how many "Running prompt:" lines we've seen
_render_end_step: int | None = None  # Video Source: step where the source video runs out
_render_conf: dict | None = None  # config snapshot for ETA calc
_render_first_step: int = 0       # step the render starts from: 0, or the one Resume Render continues from
_log_prefix: str = ""             # render.log of the run Resume Render continues; this render's log goes after it
_render_start: float = 0.0       # time.time() when render started
_progress_start: tuple[float, int] | None = None  # (time, steps done) at the first progress line
_render_status: str | None = None  # how the last render ended, for the Status box
_stop_requested: bool = False
_summary_appended: bool = False


# DEBUG lines and warnings
_LOG_NOISE = re.compile(r"\| DEBUG\s+\||UserWarning:|warnings\.warn\(")
# What pytti's notebook display() prints outside a notebook, often right after a progress bar
_PIL_REPR = re.compile(r"<PIL\.Image\.Image [^>]*>")
# Any tqdm bar ("  5%|▌    | ..."), including model download bars
_BAR_RE = re.compile(r"\d+%\|")
# The render's progress, e.g. "  5%|▌         | 500/10000 [00:33<10:30, 15.08it/s]"
_TQDM_RE = re.compile(r"(\d+)/(\d+)\s+\[.*?,\s*(\d+(?:\.\d+)?)(s/it|it/s)")
_SCENE_RE = re.compile(r"Running prompt:", re.IGNORECASE)
# Logged by the patched workhorse.py when the source video is shorter than the render
_VIDEO_END_RE = re.compile(r"render will end at step (\d+)")

def _render_progress() -> tuple[int, int]:
    """(total steps, steps done) of the current render, from its config and tqdm progress."""
    conf = _render_conf or {}
    steps_per_scene = max(1, int(_num(conf.get("steps_per_scene"), 1)))
    total = _total_steps(conf)
    if _render_end_step is not None:
        total = min(total, _render_end_step)
    if _render_scene == 0:
        # A resumed render's first progress bar starts partway through a scene
        return total, _render_first_step + _render_step
    return total, (_render_first_step // steps_per_scene + _render_scene) * steps_per_scene + _render_step


def _pngs(folder: Path) -> list[Path]:
    """PNG files in folder; [] if it can't be listed (missing, or a name Windows can't use)."""
    try:
        return list(folder.glob("*.png"))
    except OSError:
        return []


def _render_frames() -> list[Path]:
    """Frames the current (or last) render has saved so far."""
    if _render_dir is None:
        return []
    return _pngs(_render_dir / "images_out" / _render_namespace)


def _append_summary(label: str):
    """Append render summary to log. Only runs once per render."""
    global _summary_appended
    if _summary_appended:
        return
    _summary_appended = True
    now = time.time()
    elapsed = now - _render_start if _render_start else 0
    total_steps, done = _render_progress()
    frames = _render_frames()
    # A resumed render counts only its own frames for the average
    new_frames = sum(1 for frame in frames if _modified(frame) >= _render_start)
    frames = len(frames)
    lines = [
        "=" * 50,
        label,
        "-" * 50,
        f"  Steps:         {done} / {total_steps}",
        f"  Frames saved:  {frames}",
        f"  Total time:    {_format_eta(elapsed)}",
    ]
    if _progress_start:
        # Timed from the first progress line, so model loading and downloads don't count
        start_time, start_done = _progress_start
        render_time = now - start_time
        if render_time > 0 and done > start_done:
            lines.append(f"  Avg speed:     {(done - start_done) / render_time:.2f} step/s")
        if new_frames > 0:
            lines.append(f"  Avg per frame: {_format_eta(render_time / new_frames)}")
    lines.append("=" * 50)
    with _log_lock:
        _log_lines.extend(lines)


def _save_render_log():
    """Keep the log in the render's folder: pytti logs through loguru, so Hydra's workhorse.log stays empty.

    A resumed render's log goes after the log the run already had.
    """
    if _render_dir is None or not _render_dir.is_dir():
        return
    with _log_lock:
        text = _log_prefix + "\n".join(_log_lines) + "\n"
    with contextlib.suppress(OSError):
        (_render_dir / "render.log").write_text(text, encoding="utf-8")


_ES_CONTINUOUS, _ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def _keep_awake(on: bool):
    """Keep Windows from sleeping while a render runs; the display may still turn off.

    A busy GPU doesn't count as activity, so the idle timer would suspend an unattended
    render. The request belongs to the calling thread, so turn it off from the same one.
    """
    if os.name != "nt":
        return
    with contextlib.suppress(Exception):
        set_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_state.argtypes, set_state.restype = [ctypes.c_uint32], ctypes.c_uint32
        set_state(_ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0))


def _kill_tree(proc: subprocess.Popen):
    """Stop a render and every process it started (e.g. pytti's ffmpeg video conversion)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # TerminateProcess alone would leave child processes running
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _stream_output(proc):
    global _running, _render_its, _render_step, _render_scene, _scene_prompt_count, _render_end_step, _progress_start, _render_status
    _keep_awake(True)
    last_idx = -1      # index in _log_lines of the latest progress line, if nothing was logged after it
    redrawn = False    # that line ended in a bare \r, so whatever comes next replaces it
    try:
        # newline="" keeps line ends as they are, so a bare \r (progress redrawn in place by
        # tqdm, ffmpeg and download bars) can be told apart from the end of a line
        stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace", newline="")
        for line in iter(stream.readline, ""):
            if proc is not _proc or _stop_requested:
                continue  # output after Stop, or from a stopped render; keep it out of the log
            # A bare \r, or the cursor-up a bar nested in another (a download during the
            # render) ends with: either way the next output is drawn over this line
            redraw = line.endswith("\r") or "\x1b[A" in line
            clean = _ANSI_ESCAPE.sub("", line).rstrip()
            # display() output glued to a bar ends that line early; the bar is redrawn after it
            clean, displayed = _PIL_REPR.subn("", clean)
            if not clean.strip() or _LOG_NOISE.search(clean):
                continue
            bar = bool(_BAR_RE.search(clean))
            # Extract tqdm progress; bars before the first scene are model downloads
            m = _TQDM_RE.search(clean)
            if m and _scene_prompt_count and float(m.group(3)) > 0:
                _render_step = int(m.group(1))
                rate = float(m.group(3))
                # tqdm may report "s/it" (slow) or "it/s" (fast)
                _render_its = (1.0 / rate) if m.group(4) == "s/it" else rate
                if _progress_start is None:
                    _progress_start = (time.time(), _render_progress()[1])
            # Track scene transitions (pytti logs "Running prompt:" for each scene)
            if _SCENE_RE.search(clean):
                _scene_prompt_count += 1
                # First "Running prompt:" is scene 0 starting; subsequent ones mean prior scene completed
                _render_scene = max(0, _scene_prompt_count - 1)
                _render_step = 0  # the new scene's bar starts at 0; its first line has no rate yet
            end = _VIDEO_END_RE.search(clean)
            if end:
                _render_end_step = int(end.group(1))
            with _log_lock:
                # Keep one line per progress bar instead of one per redraw
                if last_idx == len(_log_lines) - 1 and (redrawn or bar):
                    _log_lines[-1] = clean
                else:
                    _log_lines.append(clean)
                last_idx = len(_log_lines) - 1 if redraw or (bar and displayed) else -1
                redrawn = redraw
    except Exception as e:
        # Nobody would drain the pipe anymore, so the render would stall; stop it instead
        with _log_lock:
            _log_lines.append(f"Log reader failed ({e!r}); stopping render.")
        _kill_tree(proc)
    finally:
        try:
            proc.wait()
            with _proc_lock:
                if proc is _proc:  # a newer render may have started since this one was stopped
                    try:
                        if not _stop_requested:
                            code = proc.returncode
                            if code == 0:
                                _render_status = "Render complete."
                            else:
                                _render_status = f"Render ended (exit code {code}).{_blocked_note()}{_resume_offer(_render_dir)}"
                            _append_summary("RENDER COMPLETE" if code == 0 else f"RENDER ENDED (exit code {code})")
                            _save_render_log()
                    finally:
                        # Even if the summary failed; otherwise Start Render would say "Already running." for good
                        _running = False
                        _render_its = 0.0
        finally:
            _keep_awake(False)


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
    """ETA of the render from the observed it/s and its config; blank until a rate is known."""
    its = _render_its
    if its <= 0:
        return ""
    total_steps, done = _render_progress()
    remaining = max(0, total_steps - done)
    if remaining == 0:
        return "ETA: finishing..."
    eta_sec = remaining / its
    return f"ETA: ~{_format_eta(eta_sec)} remaining ({its:.1f} it/s, {done}/{total_steps} steps)"


# Where a copy named ffmpeg.exe goes when it can't go next to python.exe
_FFMPEG_TEMP_DIR = Path(tempfile.gettempdir()) / "pytti-ffmpeg"


def _copy_file(src: Path, dst: Path):
    """Copy src to dst unless dst already matches it; under a temp name first, so a failed copy never leaves a partial dst."""
    with contextlib.suppress(OSError):
        s, d = src.stat(), dst.stat()
        if s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime):
            return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _ffmpeg_exe() -> str | None:
    """Find ffmpeg: the build bundled with imageio-ffmpeg, else python\\ffmpeg.exe, else one on PATH.

    The bundled build is known to have the encoders the app relies on (libx264,
    prores_ks); one on PATH may not (LGPL builds leave out libx264). In the portable
    install it is copied next to python.exe as ffmpeg.exe, where pytti's own bare
    "ffmpeg" calls (Video Source conversion, audio) find it before anything on PATH.
    The copy is replaced when it no longer matches, e.g. after imageio-ffmpeg is updated.
    """
    local = EMBEDDED_PYTHON.parent / "ffmpeg.exe"
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return str(local) if local.is_file() else shutil.which("ffmpeg")
    if PYTHON_EXE == EMBEDDED_PYTHON:
        with contextlib.suppress(OSError):
            _copy_file(Path(bundled), local)
            return str(local)
    return bundled


def _ffmpeg_folder(ffmpeg: str) -> str | None:
    """A folder holding this ffmpeg under the name ffmpeg.exe, for the render's PATH.

    pytti runs a bare "ffmpeg"; the bundled binary is named like ffmpeg-win-x86_64-v7.1.exe,
    so if it couldn't be copied next to python.exe, a copy goes in a temp folder.
    """
    path = Path(ffmpeg)
    if path.stem.lower() == "ffmpeg":
        return str(path.parent)
    try:
        _copy_file(path, _FFMPEG_TEMP_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    except OSError:
        return None
    return str(_FFMPEG_TEMP_DIR)


def _new_run_dir() -> Path:
    """A fresh outputs/<date>/<time> folder name, the layout Hydra uses by default."""
    base = OUTPUTS_DIR / time.strftime("%Y-%m-%d") / time.strftime("%H-%M-%S")
    run_dir, n = base, 1
    while run_dir.exists():  # two renders started within the same second
        n += 1
        run_dir = base.with_name(f"{base.name}-{n}")
    return run_dir


# Backups every render keeps at least; a preset's lower Backups is raised when the render
# starts, without changing the preset. Resume Render continues from the newest backup, and
# with two, one cut off by Stop Render still leaves the one before it.
MIN_BACKUPS = 2
# config/conf/_resume.yaml: the settings of the run Resume Render continues
RESUME_CONF = "_resume"


def _app_path(path: Path) -> str:
    """path relative to the app folder when it is inside it, with forward slashes, e.g.
    outputs/2026-10-04/11-22-47; for Hydra overrides and the status box."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _launch(run_dir: Path, conf: dict, overrides: list[str], log: list[str], first_step: int = 0,
            log_prefix: str = "") -> str | None:
    """Start pytti on a render into run_dir; a message if it couldn't start. Call with _proc_lock held.

    conf holds the render's settings, for its progress and preview, and log the lines its
    log starts with. A resumed render starts at first_step, and its render.log adds its
    log to log_prefix.
    """
    global _proc, _running, _render_its, _render_step, _render_scene, _scene_prompt_count, _render_conf, _render_start, _stop_requested, _summary_appended, _render_dir, _render_namespace, _render_end_step, _progress_start, _render_status, _render_first_step, _log_prefix
    with _log_lock:
        _log_lines[:] = log
    _stop_requested = False
    _summary_appended = False
    _render_its = 0.0
    _render_step = 0
    _render_scene = 0
    _scene_prompt_count = 0
    _render_end_step = None
    _progress_start = None
    _render_status = None
    _render_start = time.time()
    _render_conf = conf
    _render_first_step = first_step
    _log_prefix = log_prefix
    _render_dir = run_dir
    # The preset's own value, even if blank: that is the folder pytti saves into
    _render_namespace = str(conf.get("file_namespace", load_defaults().get("file_namespace", "")))
    # UTF-8 output so the pipe decodes the same way whatever the Windows code page;
    # INFO level drops pytti's per-step DEBUG output. torch >= 2.6 refuses to load
    # checkpoints holding pickled objects (VQGAN imagenet's Lightning callbacks) unless
    # told to; earlier torch versions ignore the variable.
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "LOGURU_LEVEL": "INFO",
           "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"}
    # Where model_mirror.py and the rotoscoper.py patch put models and Video Source conversions
    env["PYTTI_CACHE"] = str(CACHE_DIR)
    # pytti runs a bare "ffmpeg" (Video Source conversion, audio); make it the one the UI uses
    ffmpeg = _ffmpeg_exe()
    ffmpeg_dir = _ffmpeg_folder(ffmpeg) if ffmpeg else None
    if ffmpeg_dir:
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
    try:
        # Binary stdout: _stream_output decodes it itself to see progress redraws.
        # No stdin, so a key pressed in the console can't stop ffmpeg ('q') mid-conversion.
        _proc = subprocess.Popen(
            [str(PYTHON_EXE), "-W", "ignore", "-m", "pytti.workhorse", *overrides],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",  # lets _kill_tree signal the whole group
        )
    except OSError as e:
        return f"Could not start render: {e}"
    _running = True
    threading.Thread(target=_stream_output, args=(_proc,), daemon=True).start()
    return None


def start_render(conf_name: str):
    with _proc_lock:
        if _running:
            return "Already running."
        name = conf_name if conf_name.endswith(".yaml") else conf_name + ".yaml"
        try:
            render_conf = load_conf(name)
        except PresetError as e:
            return str(e)
        conf_name = conf_name.removesuffix(".yaml")
        # Choose the run folder ourselves so the preview and summary know where frames go
        run_dir = _new_run_dir()
        overrides = [f"conf='{conf_name}'", f"hydra.run.dir='{_app_path(run_dir)}'"]
        seed = render_conf.get("seed")
        if re.fullmatch(r"-?\d+", str(seed)):
            seed_note = f"Seed: {seed}"
        else:
            # Pick the random seed here so it can be shown and reused
            seed = random.randint(0, 2**32 - 1)
            overrides.append(f"seed={seed}")
            seed_note = f"Seed: {seed} (random; enter it as the Seed to repeat this render)"
        # Snapshot config for ETA calculations
        conf = {**load_defaults(), **render_conf}
        if _num(conf.get("backups"), 0) < MIN_BACKUPS:
            overrides.append(f"backups={MIN_BACKUPS}")
            conf["backups"] = MIN_BACKUPS
        warnings, summary = preflight(conf)
        # The preset's name goes in render.log: resuming the run makes Hydra record _resume instead
        error = _launch(run_dir, conf, overrides, [f"Preset: {conf_name}", seed_note, *summary, *warnings])
        if error:
            return error
    return " ".join(["Render started.", *warnings])


def _run_settings(run_dir: Path) -> dict | None:
    """The settings a run was rendered with, as Hydra saved them in its folder; None if they can't be read."""
    try:
        data = load_yaml(run_dir / ".hydra" / "config.yaml")
    except (OSError, ValueError, yaml.YAMLError):  # ValueError: not UTF-8
        return None
    return data if isinstance(data, dict) else None


def _backups(run_dir: Path, namespace: str) -> list[tuple[int, Path]]:
    """(frame, file) of each backup pytti kept in a run, newest first."""
    pattern = re.compile(rf"{re.escape(namespace)}_(\d+)\.bak")
    try:
        files = list((run_dir / "backup" / namespace).iterdir())
    except OSError:
        return []
    found = [(int(m.group(1)), path) for path in files if (m := pattern.fullmatch(path.name))]
    return sorted(found, key=lambda backup: backup[0], reverse=True)


def _bak_damaged(path: Path) -> bool:
    """True if a backup was cut off, e.g. by Stop Render while pytti was writing it.

    torch.save writes a zip file, and a cut-off one has lost the directory at its end.
    """
    try:
        zipfile.ZipFile(path).close()
    except OSError:
        return False  # can't tell, e.g. locked by another program
    except Exception:
        # Besides BadZipFile, a damaged directory can raise e.g. UnicodeDecodeError
        return True
    return False


def _save_every(conf: dict) -> int:
    """Steps between saved frames: save_every, or steps_per_frame when it is 0, as patched pytti does."""
    save_every = int(_num(conf.get("save_every"), 0))
    return save_every if save_every > 0 else max(1, int(_num(conf.get("steps_per_frame"), 1)))


def _scene_count(conf: dict) -> int:
    """How many scenes || separates; at least 1."""
    return max(1, len([scene for scene in str(conf.get("scenes") or "").split("||") if scene.strip()]))


def _total_steps(conf: dict) -> int:
    """Steps of all scenes together."""
    return _scene_count(conf) * max(1, int(_num(conf.get("steps_per_scene"), 1)))


def _resume_point(run_dir: Path, settings: dict, delete_damaged: bool = False) -> tuple[int, int, int] | str:
    """(frame, step, frames in all) a stopped render continues from, or why it can't be resumed.

    The step is the one the patched pytti continues with. delete_damaged deletes newer
    backups that were cut off, which pytti would otherwise try to load.
    """
    where = _app_path(run_dir)
    try:
        log = (run_dir / "render.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        log = ""
    ends = re.findall(r"^RENDER (COMPLETE|STOPPED|ENDED)", log, re.MULTILINE)
    if ends and ends[-1] == "COMPLETE":
        return f"The render in {where} is complete, so there is nothing to resume."
    for frame, path in _backups(run_dir, str(settings.get("file_namespace") or "")):
        if not _bak_damaged(path):
            break
        if delete_damaged:
            try:
                path.unlink()
            except OSError as e:
                return f"Could not delete {path.name}, a damaged backup in {where}: {e.strerror or e}. Delete it, then press Resume Render again."
    else:
        return f"The render in {where} can't be resumed: it has no backup to continue from. Renders keep backups from their first saved frame on."
    save_every = _save_every(settings)
    # A Video Source render ends with its clip, at the step its log gave
    total = min([_total_steps(settings)] + [int(step) for step in _VIDEO_END_RE.findall(log)])
    if frame * save_every >= total:
        return f"The render in {where} is complete, so there is nothing to resume."
    return frame, max(0, frame * save_every - 1), total // save_every


def _resume_offer(run_dir: Path | None) -> str:
    """' Resume Render continues it from frame N.' for a render that can be resumed, else ''."""
    settings = _run_settings(run_dir) if run_dir else None
    point = _resume_point(run_dir, settings) if settings else None
    return f" Resume Render continues it from frame {point[0]}." if isinstance(point, tuple) else ""


def resume_render(run_dir: Path, labels: dict) -> str:
    """Continue a stopped render in its own run folder, from its newest backup and with the
    settings it was started with. labels name the settings in messages."""
    with _proc_lock:
        if _running:
            return "Already running."
        where = _app_path(run_dir)
        settings = _run_settings(run_dir)
        if settings is None:
            return f"The render in {where} can't be resumed: its settings, .hydra/config.yaml in its folder, are missing or can't be read."
        point = _resume_point(run_dir, settings, delete_damaged=True)
        if isinstance(point, str):
            return point
        frame, step, frames = point
        # The checks Start Render makes, on the settings the run was started with
        values = {key: settings.get(key) for key in CONF_FIELDS}
        extras = {key: value for key, value in settings.items() if key not in CONF_KEYS}
        problems = missing_files(values, labels, extras) + preset_risks(values, extras, labels)[0]
        if problems:
            return " ".join([f"The render in {where} can't be resumed."] + problems)
        conf = {key: value for key, value in settings.items() if key != "restore"}
        conf["backups"] = max(MIN_BACKUPS, int(_num(conf.get("backups"), 0)))
        try:
            save_yaml(CONF_DIR / f"{RESUME_CONF}.yaml", conf, header="# @package _global_\n")
        except OSError as e:
            return f"Could not write config/conf/{RESUME_CONF}.yaml: {e.strerror or e}."
        # ++ adds restore, or sets it if the composed settings already have it (+ would fail then)
        overrides = [f"conf='{RESUME_CONF}'", f"hydra.run.dir='{_app_path(run_dir)}'", "++restore=true"]
        warnings, summary = preflight(conf)
        try:
            log_prefix = (run_dir / "render.log").read_text(encoding="utf-8", errors="replace").rstrip("\n") + "\n\n"
        except OSError:
            log_prefix = ""
        resuming = f"Resuming the render in {where} from frame {frame} of {frames}"
        error = _launch(run_dir, conf, overrides, [f"{resuming} (step {step}).", *summary, *warnings], step, log_prefix)
        if error:
            return error
    return " ".join([f"{resuming}.", *warnings])


# ---------------------------------------------------------------------------
# Preflight: what a render will produce and need, shown as it starts
# ---------------------------------------------------------------------------

# Bytes per pixel of a saved PNG frame: 0.58 to 0.66 of the 3 bytes of RGB in past renders
_PNG_BYTES_PER_PIXEL = 3 * 0.65
_mirror = None  # app/model_mirror.py once loaded; False if it can't be


def _model_mirror():
    """app/model_mirror.py, for its lists of model files and sizes and the folders it picks;
    None if it can't be loaded.

    Loaded by path, as this folder isn't on sys.path, and without pytti: importing pytti
    imports torch.
    """
    global _mirror
    if _mirror is None:
        try:
            spec = importlib.util.spec_from_file_location("pytti_portable_model_mirror", ROOT / "model_mirror.py")
            _mirror = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mirror)
            # The folders renders use, which _launch passes them as PYTTI_CACHE
            _mirror.CACHE, _mirror.MODELS = CACHE_DIR, CACHE_DIR / "models"
        except Exception:
            _mirror = False
    return _mirror or None


def _downloads(conf: dict) -> list[tuple[str, int, Path]]:
    """(file, size, folder) of each model the render downloads before it starts.

    The models model_mirror.prefetch_models fetches, unless they are already in the
    folder model_mirror.py picks for them.
    """
    mirror = _model_mirror()
    if mirror is None:
        return []
    needed = []

    def need(file, target: Path, exact=True):
        # As model_mirror._fetch decides: a file of another size is a cut-off download
        size = file[2]
        try:
            missing = not target.exists() or (exact and target.is_file() and target.stat().st_size != size)
        except OSError:
            missing = True
        if missing:
            needed.append((target.name, size, target.parent))

    for key, file in mirror.CLIP_MODELS.items():
        if conf.get(key):
            name = Path(file[0]).name
            need(file, mirror._clip_folder(name) / name)
    mode = "off" if conf.get("animation_mode") is False else conf.get("animation_mode")
    depth_weight = str(conf.get("depth_stabilization_weight") or "").strip()
    if mode == "3D" or (depth_weight not in ("", "0") and (mode != "off" or conf.get("init_image"))):
        hub = mirror.hub_folder()
        need(mirror.ADABINS, mirror.adabins_folder() / "AdaBins_nyu.pt")
        need(mirror.EFFICIENTNET, hub / "checkpoints" / Path(mirror.EFFICIENTNET[0]).name)
        need(mirror.GEN_EFFICIENTNET, hub / "rwightman_gen-efficientnet-pytorch_master")
    name, parent = conf.get("vqgan_model"), str(conf.get("models_parent_dir") or "${user_cache:}")
    # Hydra fills in any other ${...} when the render starts, so that folder isn't known here
    if conf.get("image_model") == "VQGAN" and name in mirror.VQGAN_MODELS and (parent == "${user_cache:}" or "${" not in parent):
        # Without models_parent_dir, vqgan_folder uses ${user_cache:}'s folder, the .cache folder
        folder = mirror.vqgan_folder({"vqgan_model": name, "models_parent_dir": None if parent == "${user_cache:}" else parent})
        config, checkpoint = mirror.VQGAN_MODELS[name]
        need(config, folder / f"{name}.yaml", exact=False)
        need(checkpoint, folder / f"{name}.ckpt", exact=False)
    return needed


def _probe(path: str) -> dict | None:
    """A media file's duration in seconds and, for a video, its frame size as played back
    (rotation applied); None if ffmpeg can't read it."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not Path(path).is_file():
        return None
    try:
        # With no output file ffmpeg describes the input and exits
        result = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stderr.decode("utf-8", "replace")
    duration = re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", text)
    if not duration:
        return None
    info = {"duration": int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])}
    video = re.search(r"Stream #.*?: Video: .*?, (\d+)x(\d+)[\s,]", text)
    if video:
        width, height = int(video[1]), int(video[2])
        # Phone videos are often stored sideways; ffmpeg turns them upright when pytti converts them
        rotation = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", text)
        if rotation and round(abs(float(rotation[1]))) % 180 == 90:
            width, height = height, width
        info["size"] = (width, height)
    return info


def _video_end(frames: int, pre: int, steps_per_frame: int, stride: int, save_every: int) -> int:
    """The step a Video Source render ends at to show a clip of this many frames, as the
    patched workhorse.py works it out."""
    moves = -(-(frames - 1) // stride)
    if pre == 0:
        moves = max(moves, 1)
    repeat = pre + moves * steps_per_frame
    last_start = repeat - steps_per_frame if moves else 0
    save = (repeat + 1) // save_every * save_every - 1
    if save <= last_start:
        save += save_every
    return save + 1


def _backup_bytes(conf: dict, width: int, height: int) -> int:
    """About how big one backup is: the image model's state."""
    if conf.get("image_model") == "Limited Palette":
        return (int(_num(conf.get("palettes"), 1)) + 1) * width * height * 4
    if conf.get("image_model") == "VQGAN":
        scale = max(1, int(_num(conf.get("pixel_size"), 1)))
        return 3 * (width * scale // 16) * (height * scale // 16) * 256 * 4
    return 3 * width * height * 4


def _size_text(size: float) -> str:
    if size >= 2**30:
        return f"{size / 2**30:.1f} GB"
    return f"{round(size / 2**20)} MB" if size >= 2**20 else f"{max(1, round(size / 2**10))} KB"


def _drive(path: Path) -> tuple[str, int] | None:
    """(drive, free bytes) for a folder that may not exist yet; None if unknown."""
    path = path.resolve()
    for folder in (path, *path.parents):
        if folder.exists():
            try:
                return path.anchor, shutil.disk_usage(folder).free
            except OSError:
                return None
    return None


def preflight(conf: dict) -> tuple[list[str], list[str]]:
    """What a render with these settings (default.yaml's with the preset's over them) will
    produce and need, as (warnings, summary lines) for the status box and the log.

    Warnings are for what may waste the render: a Video Source clip or an audio track it
    doesn't fit, a clip stretched to another shape, too little disk space. All figures are
    estimates, so nothing is reported if working them out fails.
    """
    try:
        return _preflight(conf)
    except Exception:
        return [], []


def _preflight(conf: dict) -> tuple[list[str], list[str]]:
    warnings, summary = [], []
    mode = "off" if conf.get("animation_mode") is False else conf.get("animation_mode")
    steps_per_frame = max(1, int(_num(conf.get("steps_per_frame"), 1)))
    pre = max(0, int(_num(conf.get("pre_animation_steps"), 0)))
    fps = max(1, int(_num(conf.get("frames_per_second"), 1)))
    save_every = _save_every(conf)
    scenes = _scene_count(conf)
    total = steps = _total_steps(conf)  # steps: where the render ends
    width, height = int(_num(conf.get("width"), -1)), int(_num(conf.get("height"), -1))
    estimated = False

    def at_least(steps_needed):
        return f"set Steps per Scene to at least {-(-steps_needed // scenes)}"

    clip = _probe(str(conf["video_path"])) if mode == "Video Source" and conf.get("video_path") else None
    if clip and clip["duration"] > 0:
        stride = max(1, int(_num(conf.get("frame_stride"), 1)))
        # pytti converts the clip to the render's frame rate first; this count is within a frame
        frames_in = max(1, round(clip["duration"] * fps))
        end = _video_end(frames_in, pre, steps_per_frame, stride, save_every)
        estimated = end < total
        if end < total:
            steps = end  # the patched workhorse.py ends the render with the clip
        elif total < end - steps_per_frame:  # more than a frame short
            moves = -(-(total - pre) // steps_per_frame) if total > pre else 0
            covered = min(clip["duration"], moves * stride / fps)
            warnings.append(f"The render shows about {covered:.1f} s of the {clip['duration']:.1f} s Video Source clip. To render all of it, {at_least(end)}.")
        if clip.get("size") and width > 0 and height > 0:
            clip_w, clip_h = clip["size"]
            if abs(math.log(clip_w * height / (clip_h * width))) > 0.02:
                warnings.append(f"The Video Source clip is {clip_w}x{clip_h}, so it is stretched to fit the {width}x{height} render. To keep its shape, set Height to -1.")
        if clip.get("size") and (width == -1) != (height == -1) and not conf.get("init_image"):
            # -1 follows the clip's shape
            clip_w, clip_h = clip["size"]
            width, height = (int(height * clip_w / clip_h), height) if width == -1 else (width, int(width * clip_h / clip_w))

    audio = _probe(str(conf["input_audio"])) if conf.get("input_audio") and conf.get("input_audio_filters") else None
    if audio:
        offset = float(_num(conf.get("input_audio_offset"), 0))
        available = audio["duration"] - offset
        # The audio is read once per animation frame, from pre_animation_steps on
        length = (-(-(steps - pre) // steps_per_frame) if steps > pre else 0) / fps
        if available <= 0:
            warnings.append(f"Audio Offset ({offset:g} s) is past the end of the {audio['duration']:.1f} s of audio, so the render will stop with an error once its models have loaded.")
        elif length > available + 1:
            warnings.append(f"The audio runs out about {length - available:.1f} s before the render ends; from there on, the audio variables keep their last values.")
        elif available > length + 1 and steps == total:
            warnings.append(f"The render uses {length:.1f} s of the {available:.1f} s of audio after the offset. To use all of it, {at_least(pre + int(available * fps) * steps_per_frame)}.")

    frames = steps // save_every
    about = "about " if estimated else ""
    summary.append(f"Output: {about}{frames} frames, {frames / fps:.1f} s of video at {fps} fps ({about}{steps} steps).")
    downloads = _downloads(conf)
    if downloads:
        files = ", ".join(f"{name} ({_size_text(size)})" for name, size, _ in downloads)
        summary.append(f"Downloads before the render starts: {files}.")

    needs = {}  # drive -> [free bytes, bytes needed]
    if width > 0 and height > 0:
        scale = max(1, int(_num(conf.get("pixel_size"), 1)))
        # Frames, and the backups pytti keeps plus the one it is writing
        size = frames * width * height * scale**2 * _PNG_BYTES_PER_PIXEL
        size += (max(MIN_BACKUPS, int(_num(conf.get("backups"), 0))) + 1) * _backup_bytes(conf, width, height)
        if drive := _drive(OUTPUTS_DIR):
            needs.setdefault(drive[0], [drive[1], 0])[1] += size
    for _, size, folder in downloads:
        if drive := _drive(folder):
            needs.setdefault(drive[0], [drive[1], 0])[1] += size
    for drive, (free, size) in needs.items():
        summary.append(f"Disk: about {_size_text(size)} on {drive}, which has {_size_text(free)} free.")
        if size > free:
            warnings.append(f"The render needs about {_size_text(size)} on {drive}, which has only {_size_text(free)} free.")
    return warnings, summary


def _subdirs(folder: Path, reverse: bool = False) -> list[Path]:
    """Sorted subfolders of folder; [] if it can't be listed."""
    try:
        return sorted((path for path in folder.iterdir() if path.is_dir()), reverse=reverse)
    except OSError:
        return []


def _png_count(folder: Path) -> int:
    """Number of PNG files in folder; 0 if it can't be listed."""
    try:
        with os.scandir(folder) as entries:
            return sum(1 for entry in entries if entry.name.endswith(".png"))
    except OSError:
        return 0


def get_encodable_runs():
    """Scan outputs/ for runs that have PNG frames."""
    runs = []
    for day_dir in _subdirs(OUTPUTS_DIR, reverse=True):
        for time_dir in _subdirs(day_dir, reverse=True):
            for ns_dir in _subdirs(time_dir / "images_out"):
                frames = _png_count(ns_dir)
                if frames:
                    label = f"{day_dir.name}/{time_dir.name} ({ns_dir.name}) — {frames} frames"
                    runs.append((label, str(ns_dir)))
    return runs


def run_fps(frames_dir: str):
    """frames_per_second a run was rendered with, from the config Hydra saved in its folder."""
    data = _run_settings(Path(frames_dir).parent.parent)
    return _num(data.get("frames_per_second"), None) if data is not None else None


def _frame_number(path: Path):
    """Sort key: frame number, so unpadded names (frame_10.png after frame_9.png) order correctly too."""
    m = re.search(r"(\d+)\.png$", path.name)
    return (int(m.group(1)) if m else -1, path.name)


def _discard_encode(proc: subprocess.Popen, part: Path):
    """Stop an encode and delete its unfinished output."""
    proc.kill()
    with contextlib.suppress(OSError):
        proc.stdin.close()
    proc.wait()
    with contextlib.suppress(OSError):
        part.unlink(missing_ok=True)


def encode_video(frames_dir: str, fps: int, fmt: str):
    """Encode a PNG frame sequence to video using ffmpeg."""
    if not frames_dir:
        return "Select a run first."
    frames_path = Path(frames_dir)
    if not frames_path.is_dir():
        return f"Directory not found: {frames_dir}"
    pngs = sorted(_pngs(frames_path), key=_frame_number)
    if not pngs:
        return "No PNG frames found."
    if not fps or fps < 1:
        return "Set FPS to at least 1."
    fps = int(fps)

    # Convert to BT.709 and tag it, which players assume for HD-sized video; ffmpeg's
    # default conversion is an untagged BT.601 one, so hues shift on playback
    bt709 = ("scale=out_color_matrix=bt709:out_range=tv,"
             "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709")
    color_tags = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    run_dir = frames_path.parent.parent  # up from images_out/namespace/
    if fmt == "ProRes 4444 (MOV)":
        suffix = "_prores4444.mov"
        codec_args = ["-vf", bt709, "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                      "-movflags", "+write_colr"]
    elif fmt == "ProRes HQ (MOV)":
        suffix = "_proreshq.mov"
        codec_args = ["-vf", bt709, "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
                      "-movflags", "+write_colr"]
    else:  # MP4
        suffix = ".mp4"
        # yuv420p needs even dimensions; pad odd sizes by one pixel
        codec_args = ["-vf", bt709 + ",pad=ceil(iw/2)*2:ceil(ih/2)*2",
                      "-c:v", "libx264", "-crf", "17", "-preset", "slow", "-pix_fmt", "yuv420p",
                      "-movflags", "+faststart"]

    out_file = run_dir / f"{frames_path.name}_{fps}fps{suffix}"
    # ffmpeg empties its output file before encoding, so encode under a temp name: a
    # failed encode then can't cost the previous export with the same settings
    part = out_file.with_name(f"{out_file.stem}.part{out_file.suffix}")

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return "ffmpeg not found. Install ffmpeg and ensure it's on your PATH."
    # Pipe the frames in order rather than using an image-sequence pattern, which stops
    # at the first gap in the numbering and breaks on '%' in the path
    cmd = [ffmpeg, "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-"]
    cmd += codec_args + color_tags + [str(part)]
    deadline = time.time() + max(600, 5 * len(pngs))
    written = skipped = 0
    with tempfile.TemporaryFile() as ffmpeg_log:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=ffmpeg_log)
        except OSError:
            return "ffmpeg not found. Install ffmpeg and ensure it's on your PATH."
        try:
            for png in pngs:
                if time.time() > deadline:
                    raise subprocess.TimeoutExpired(cmd, 0)
                try:
                    data = png.read_bytes()
                except OSError as e:
                    _discard_encode(proc, part)
                    return f"Could not read {png.name}: {e.strerror or e}. Close any program using it and try again."
                if not data.endswith(_PNG_END):
                    # Still being written, or cut short: ffmpeg would drop it and every frame after it
                    skipped += 1
                    continue
                try:
                    proc.stdin.write(data)
                except OSError:
                    break  # ffmpeg quit early and closed the pipe; its log says why
                written += 1
            with contextlib.suppress(OSError):
                proc.stdin.close()
            proc.wait(timeout=max(1.0, deadline - time.time()))
        except subprocess.TimeoutExpired:
            _discard_encode(proc, part)
            return "Encoding timed out."
        ffmpeg_log.seek(0)
        stderr = ffmpeg_log.read().decode("utf-8", "replace")
    if proc.returncode != 0 or not written:
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        if skipped == len(pngs):
            return "No finished PNG frames found."
        return f"ffmpeg error:\n{_ffmpeg_error(stderr)}"
    encoded = _frames_encoded(stderr)
    if encoded is not None and encoded < written:
        # ffmpeg leaves out a frame it can't decode (one damaged but still ending like a PNG),
        # sometimes with the frames after it, and still exits 0
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        return f"ffmpeg could decode only {encoded} of {written} frames, so the video was not saved. A frame may be damaged:\n{_ffmpeg_error(stderr)}"
    try:
        os.replace(part, out_file)
    except OSError:
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        return f"Could not replace {out_file.name}. Close it in your video player and try again."
    msg = f"Encoded {written} frames → {out_file.name}\nSaved to: {out_file}"
    if skipped:
        msg += f"\nSkipped {skipped} unfinished frame{'s' if skipped > 1 else ''}."
    if _running and _render_dir is not None and frames_path.is_relative_to(_render_dir):
        msg += "\nThis render is still running, so the video has only the frames saved so far."
    return msg


def _ffmpeg_error(stderr: str) -> str:
    """Pick the lines that explain an ffmpeg failure; the tail alone is often just its banner."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines
              if re.search(r"error|invalid|not divisible|no such file|could not|unable|failed", line, re.I)]
    return "\n".join((errors or lines)[-8:])


def _frames_encoded(stderr: str) -> int | None:
    """Distinct frames in ffmpeg's output, from its last progress line; None if it printed none."""
    stats = re.findall(r"^frame=\s*(\d+)(.*)$", stderr.replace("\r", "\n"), re.MULTILINE)
    if not stats:
        return None
    frames, rest = stats[-1]
    # dup= counts copies of a frame that ffmpeg added to fill a gap left by one it couldn't decode
    dup = re.search(r"\bdup=\s*(\d+)", rest)
    return int(frames) - (int(dup.group(1)) if dup else 0)


def stop_render():
    global _running, _stop_requested, _render_status
    with _proc_lock:
        proc = _proc
        if not (proc and _running):
            return "No render running."
        # The reader drops output from here on, so the log ends with this summary
        _stop_requested = True
        _render_status = "Render stopped."
        try:
            _append_summary("RENDER STOPPED")
            _save_render_log()
        finally:
            _running = False
            _kill_tree(proc)
    # After the kill, so a backup pytti was still writing counts as cut off
    return "Render stopped." + _resume_offer(_render_dir)


# What a render prints when Windows blocks one of its files. Smart App Control blocks files
# that aren't signed, as most of PyTorch's aren't; App Control policies on PCs that a company
# or school manages give the same error.
_APP_CONTROL_RE = re.compile(r"WinError 4551|Application Control policy has blocked", re.IGNORECASE)


def _blocked_note() -> str:
    """Why the render failed if Windows blocked one of its files, for the Status box; else ''."""
    with _log_lock:
        blocked = any(_APP_CONTROL_RE.search(line) for line in _log_lines)
    if not blocked:
        return ""
    return (" Windows blocked one of PyTorch's files (WinError 4551). Smart App Control blocks files"
            " that aren't signed, as most of PyTorch's aren't. To render, turn it off: Windows Security >"
            " App & browser control > Smart App Control settings > Off. On many Windows versions it can't"
            " be turned back on without reinstalling Windows. On a PC that a company or school manages,"
            " an App Control policy gives the same error: ask its IT department.")


@atexit.register
def _stop_render_on_exit():
    # Once the UI exits nothing drains the render's output, so it would stall; end it too
    if _proc and _proc.poll() is None:
        _kill_tree(_proc)


def get_log():
    with _log_lock:
        return "\n".join(_log_lines[-200:])


def _latest_run_frames(namespace: str) -> list[Path]:
    """Frames of the newest run under outputs/ that used this namespace."""
    namespace = (namespace or "").strip()  # saved stripped
    if not _valid_name(namespace):
        return []
    for day_dir in _subdirs(OUTPUTS_DIR, reverse=True):
        for run_dir in _subdirs(day_dir, reverse=True):
            frames = _pngs(run_dir / "images_out" / namespace)
            if frames:
                return frames
    return []


def _newest_run() -> Path | None:
    """The newest run folder under outputs/; None if there is none."""
    for day_dir in _subdirs(OUTPUTS_DIR, reverse=True):
        for run_dir in _subdirs(day_dir, reverse=True):
            return run_dir
    return None


_PNG_END = b"IEND\xaeB`\x82"  # the closing chunk of every PNG


def _png_complete(path: Path) -> bool:
    """True once the PNG's closing IEND chunk is on disk."""
    try:
        with open(path, "rb") as f:
            f.seek(-len(_PNG_END), os.SEEK_END)
            return f.read() == _PNG_END
    except OSError:
        return False


def _modified(path: Path) -> float:
    """mtime for sorting; 0 for a file deleted since it was listed."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def get_latest_frame(namespace: str):
    """Newest finished frame of the current (or last) render; before any render, of the newest run using namespace."""
    frames = _render_frames() if _render_dir is not None else _latest_run_frames(namespace)
    # outputs/ is served as static files, read from disk as they are, so skip a frame pytti is still writing
    for frame in sorted(frames, key=_modified, reverse=True):
        if _png_complete(frame):
            return str(frame)
    return None



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


def _clean_path(text: str) -> str:
    """Strip "Copy as path" quotes and make relative paths absolute.

    pytti opens these files after Hydra has changed into outputs/<date>/<time>/,
    so a relative path would never be found there.
    """
    path = text.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
        path = path[1:-1].strip()
    if not path or "://" in path or Path(path).is_absolute():
        return path
    for base in (PORTABLE_ROOT, ROOT):
        if (base / path).exists():
            return str((base / path).resolve())
    return path


def _missing_file(text) -> str | None:
    """The cleaned path of a field if it names a local file that doesn't exist; None if blank, a URL or found."""
    path = _clean_path(text or "")
    if not path or "://" in path:
        return None
    # A relative path _clean_path couldn't resolve isn't found from the render's folder either
    return None if Path(path).is_absolute() and Path(path).is_file() else path


def _split_image_prompts(text: str) -> list[list[str]]:
    """[image, :weight_mask suffix if any] of each | separated direct image prompt."""
    # Same split pytti uses: a colon followed by a slash or backslash is part of the path
    parts = [re.split(r":(?![\\/])", prompt.strip(), maxsplit=1) for prompt in text.split("|")]
    return [part for part in parts if part[0]]


def _clean_image_prompts(text: str) -> str:
    """Apply _clean_path to the image of each | separated prompt, keeping its :weight_mask suffix."""
    return " | ".join(":".join([_clean_path(image)] + weight) for image, *weight in _split_image_prompts(text))


def _clean_scenes(text: str) -> str:
    """Collapse whitespace and drop empty scenes, which pytti would still run as scenes."""
    return " || ".join(" ".join(scene.split()) for scene in text.split("||") if scene.strip())


# What a blank Seed saves. Hydra would resolve it, but start_render replaces it with a
# random seed=N override, so the seed can be shown in the log and reused
RANDOM_SEED = "${now:%f}"


def _seed_value(text) -> int | str:
    """A whole-number seed, or RANDOM_SEED when the field is blank."""
    text = str(text).strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else RANDOM_SEED


def _learning_rate_value(text) -> float | None:
    """Learning Rate as saved: None (auto) when blank."""
    text = "" if text is None else str(text).strip()
    return float(text) if text else None


def _weight_value(text) -> str:
    """A loss weight field as saved: blank when it is zero.

    pytti skips a loss only for '' or '0', and still computes one weighted '0.0' every
    step. Expressions and mask syntax are kept as typed.
    """
    text = str(text or "").strip()
    try:
        return "" if float(text) == 0 else text
    except ValueError:
        return text


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
    frames_per_second, save_every, display_every, file_namespace, backups,
    field_of_view, near_plane, far_plane,
    gradient_accumulation_steps, smoothing_weight,
    direct_stabilization_weight, semantic_stabilization_weight,
    depth_stabilization_weight, edge_stabilization_weight, flow_stabilization_weight,
    reencode_each_frame,
    input_audio, input_audio_offset, flow_long_term_samples,
    breath_mode,
):
    return {
        "scenes": _clean_scenes(scenes),
        "scene_prefix": _clean_prompt_field(scene_prefix, trailing_pipe=True),
        "scene_suffix": _clean_prompt_field(scene_suffix, leading_pipe=True),
        "direct_image_prompts": _clean_image_prompts(direct_image_prompts),
        "init_image": _clean_path(init_image),
        "direct_init_weight": _weight_value(direct_init_weight),
        "semantic_init_weight": _weight_value(semantic_init_weight),
        "image_model": image_model,
        "vqgan_model": vqgan_model,
        "animation_mode": animation_mode,
        "video_path": _clean_path(video_path),
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
        "learning_rate": _learning_rate_value(learning_rate),
        "seed": _seed_value(seed),
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
        "target_palette": _clean_path(target_palette),
        "frames_per_second": int(frames_per_second),
        "save_every": int(save_every),
        "display_every": int(display_every),
        "file_namespace": str(file_namespace or "").strip(),
        "backups": int(backups),
        "field_of_view": int(field_of_view),
        "near_plane": int(near_plane),
        "far_plane": int(far_plane),
        "gradient_accumulation_steps": int(gradient_accumulation_steps),
        "smoothing_weight": float(smoothing_weight),
        "direct_stabilization_weight": _weight_value(direct_stabilization_weight),
        "semantic_stabilization_weight": _weight_value(semantic_stabilization_weight),
        "depth_stabilization_weight": _weight_value(depth_stabilization_weight),
        "edge_stabilization_weight": _weight_value(edge_stabilization_weight),
        "flow_stabilization_weight": _weight_value(flow_stabilization_weight),
        "reencode_each_frame": reencode_each_frame,
        "input_audio": _clean_path(input_audio),
        "input_audio_offset": float(input_audio_offset),
        "flow_long_term_samples": int(flow_long_term_samples),
        "breath_mode": breath_mode,
    }


# Preset keys the UI has widgets for, in build_conf_dict's order; any other key in a
# preset is kept as-is on save
CONF_FIELDS = tuple(inspect.signature(build_conf_dict).parameters)
CONF_KEYS = frozenset(CONF_FIELDS)

# Letters, digits, space, - _ . (no quotes or path separators, which would break the
# conf='<name>' override or write outside config/conf); a leading _ hides it from the list.
# No trailing space or dot, which Windows drops from file and folder names.
_CONF_NAME_RE = re.compile(r"[^\W_](?:[\w .-]*[\w-])?")
# Device names Windows reserves, alone or with an extension
_RESERVED_NAME_RE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\..*)?", re.IGNORECASE)
# Motion settings each animation mode evaluates; a blank one stops the render
_MOTION_KEYS = {
    "2D": ("translate_x", "translate_y", "rotate_2d", "zoom_x_2d", "zoom_y_2d"),
    "3D": ("translate_x", "translate_y", "translate_z_3d", "rotate_3d"),
}
# Preset keys pytti or Hydra read that default.yaml doesn't list
_OPTIONAL_KEYS = {"defaults", "hydra", "restore", "mmc_models"}
# Loss weights pytti splits as weight_mask:stop, and the two it splits like a scene
# prompt's weight_mask_cutoff:stop
_LOSS_WEIGHT_KEYS = ("direct_init_weight", "direct_stabilization_weight", "depth_stabilization_weight",
                     "edge_stabilization_weight", "flow_stabilization_weight")
_PROMPT_WEIGHT_KEYS = ("semantic_init_weight", "semantic_stabilization_weight")
# Text pytti turns into prompts, weights and camera moves. OmegaConf fills in a ${...}
# in it when the render starts, after the checks here.
_PARSED_TEXT_KEYS = ("scenes", "scene_prefix", "scene_suffix", "direct_image_prompts", "init_image",
                     *_LOSS_WEIGHT_KEYS, *_PROMPT_WEIGHT_KEYS, "translate_x", "translate_y",
                     "translate_z_3d", "rotate_2d", "rotate_3d", "zoom_x_2d", "zoom_y_2d")
# pytti runs expressions with eval() among math's functions and constants (no "math."
# prefix), abs, max, min, pow, round and the time t (pytti/eval_tools.py). numpy is
# there too, as np, but is left out here: its attributes reach the rest of Python,
# os included.
_EXPRESSION_NAMES = frozenset({name for name in dir(math) if "_" not in name} | {"abs", "max", "min", "pow", "round", "t"})
# 3D camera moves can also use the depth of the frame: nearest point, farthest point, typical depth
_DEPTH_NAMES = frozenset({"r", "R", "mu"})
# Python syntax an expression may use: numbers, arithmetic, comparisons, and/or/not,
# x if c else y, calls, lists and tuples, and the lambdas and comprehensions some
# presets build a rotation with. Attributes (np.lib...), indexing and quoted text are
# left out: they are how an expression gets past the names above.
_EXPRESSION_SYNTAX = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Store, ast.UnaryOp, ast.unaryop,
    ast.BinOp, ast.operator, ast.BoolOp, ast.boolop, ast.Compare, ast.cmpop, ast.IfExp,
    ast.Call, ast.keyword, ast.List, ast.Tuple, ast.Lambda, ast.arguments, ast.arg,
    ast.ListComp, ast.GeneratorExp, ast.comprehension,
)
# Characters an expression may have. Python 3.10's ast.parse crashes the whole UI on
# input nested some 20000 levels deep, such as "1+1+1..."; the longest expression in
# the presets seen so far has about 170.
_MAX_EXPRESSION = 2000


def _conf_name(name) -> str:
    """A config name as typed, stripped and without .yaml."""
    name = str(name or "").strip()
    return name[:-len(".yaml")] if name.lower().endswith(".yaml") else name


def _valid_name(name: str) -> bool:
    """Whether name works as a config name and as File Namespace, which pytti uses as a folder name."""
    return bool(_CONF_NAME_RE.fullmatch(name)) and not _RESERVED_NAME_RE.fullmatch(name)


def _name_problem(name: str, subject: str) -> str | None:
    """Why name can't be used, worded for the status box; None if it can."""
    if _RESERVED_NAME_RE.fullmatch(name):
        return f"{subject} can't be {name}: Windows reserves that name."
    if not _CONF_NAME_RE.fullmatch(name):
        return f"{subject} can use letters, numbers, spaces, - _ and ., must start with a letter or number, and can't end with a space or dot."
    return None


def conf_problems(name: str, values: dict, labels: dict) -> list[str]:
    """Settings that can't be saved or would crash pytti, worded for the status box.

    name is the config name as _conf_name returns it.
    """
    problems = []
    if not name:
        problems.append("Enter a config name first.")
    elif name.lower().endswith((".yml", ".yaml")):
        # Hydra would take it for a file name with an extension and not find the preset
        problems.append("Config names can't end in .yml or .yaml.")
    elif problem := _name_problem(name, "Config names"):
        problems.append(problem)
    empty = [labels[key] for key, value in values.items() if value is None]
    if empty:
        problems.append("Fill in: " + ", ".join(empty) + ".")
    if values["file_namespace"] is not None:
        namespace = str(values["file_namespace"]).strip()
        if not namespace:
            problems.append(f"{labels['file_namespace']} can't be blank.")
        elif problem := _name_problem(namespace, labels["file_namespace"]):
            problems.append(problem)
    for key, choices in CHOICES.items():
        if values[key] is not None and values[key] not in choices:
            problems.append(f"{labels[key]} '{values[key]}' isn't a valid choice.")
    mode, image_model = values["animation_mode"], values["image_model"]
    if values["scenes"] is not None and not _clean_scenes(values["scenes"]):
        problems.append("Scenes can't be empty (any short text prompt works with an init image).")
    if mode == "Video Source" and not _clean_path(values["video_path"] or ""):
        problems.append("Set a Video Path for Video Source mode.")
    if not any(values[key] for key in CLIP_MODELS):
        problems.append("Tick at least one CLIP model.")
    blank_motion = [labels[key] for key in _MOTION_KEYS.get(mode, ()) if values[key] is not None and not str(values[key]).strip()]
    if blank_motion:
        problems.append(f"{', '.join(blank_motion)} can't be blank in {mode} mode.")
    seed = "" if values["seed"] is None else str(values["seed"]).strip()
    if seed and not re.fullmatch(r"-?\d+", seed):
        problems.append("Seed must be a whole number, or blank for random.")
    elif seed and not -2**63 <= int(seed) < 2**64:  # what torch.manual_seed accepts
        problems.append("Seed must be between -9223372036854775808 and 18446744073709551615, or blank for random.")
    rate = "" if values["learning_rate"] is None else str(values["learning_rate"]).strip()
    if rate:
        try:
            rate_ok = math.isfinite(float(rate)) and float(rate) > 0
        except ValueError:
            rate_ok = False
        if not rate_ok:
            problems.append("Learning Rate must be a number above 0, or blank for auto.")
    at_least_1 = ["steps_per_scene", "steps_per_frame", "frames_per_second", "gradient_accumulation_steps", "cutouts", "pixel_size"]
    if image_model == "Limited Palette":
        at_least_1 += ["palette_size", "palettes"]
    if mode == "Video Source":
        at_least_1.append("frame_stride")
    for key in at_least_1:
        if values[key] is not None and values[key] < 1:
            problems.append(f"{labels[key]} must be at least 1.")
    cutouts, accumulation = values["cutouts"], values["gradient_accumulation_steps"]
    if cutouts is not None and accumulation and accumulation > 0 and int(cutouts) % int(accumulation):
        problems.append(f"{labels['cutouts']} ({int(cutouts)}) must be divisible by {labels['gradient_accumulation_steps']} ({int(accumulation)}).")
    has_init = bool(_clean_path(values["init_image"] or ""))
    width, height, pixel_size = values["width"], values["height"], values["pixel_size"]
    if width == -1 and height == -1:
        problems.append(f"{labels['width']} and {labels['height']} can't both be -1.")
    else:
        for key in ("width", "height"):
            size = values[key]
            if size == -1 and not (has_init or mode == "Video Source"):
                problems.append(f"{labels[key]} can be -1 only with an Init Image or in Video Source mode.")
            elif size is not None and size != -1 and size < 1:
                problems.append(f"{labels[key]} must be at least 1, or -1 to follow the init image's shape.")
    # The depth model (3D camera moves, depth stabilization) fails on frames with fewer than
    # 129 32-pixel blocks; in "off" mode depth stabilization only runs against an init image
    uses_depth = mode == "3D" or (_weight_value(values["depth_stabilization_weight"]) and (mode != "off" or has_init))
    if uses_depth and None not in (width, height, pixel_size) and min(width, height, pixel_size) >= 1:
        frame_w, frame_h = int(width) * int(pixel_size), int(height) * int(pixel_size)
        if (frame_w // 32) * (frame_h // 32) < 129:
            problems.append(f"3D mode and depth stabilization need a frame of at least about 384x384, and Width x Pixel Size by Height x Pixel Size is {frame_w}x{frame_h}. For example, 512x288 works but 512x256 does not.")
    fov = values["field_of_view"]
    if mode == "3D" and fov is not None and not 0 < fov < 180:
        problems.append(f"{labels['field_of_view']} must be more than 0 and less than 180.")
    return problems


def missing_files(values: dict, labels: dict, extras: dict | None = None) -> list[str]:
    """Input files the render would open that don't exist, worded for the status box.

    A render would fail on them only after its models have loaded. A preset can still be
    saved without them, e.g. while its media is on a drive that isn't connected. extras
    holds the preset's keys that have no widget; its input_audio_filters decide whether
    Input Audio is read.
    """
    files = [("init_image", values["init_image"])]
    files += [("direct_image_prompts", image) for image, *_ in _split_image_prompts(values["direct_image_prompts"] or "")]
    if values["animation_mode"] == "Video Source":
        files.append(("video_path", values["video_path"]))
    if values["image_model"] == "Limited Palette":
        files.append(("target_palette", values["target_palette"]))
    if (extras or {}).get("input_audio_filters", load_defaults().get("input_audio_filters")):
        files.append(("input_audio", values["input_audio"]))
    return [f"File not found: {missing} ({labels[key]})." for key, text in files if (missing := _missing_file(text))]


def _shorten(text: str, length: int = 60) -> str:
    """text cut to length characters for the status box, ending in ... if it was longer."""
    return text if len(text) <= length else text[:length - 3] + "..."


def _prompt_parts(prompt: str) -> list[tuple[str, str]]:
    """(part, text) of each expression in a scene prompt, split the way pytti splits
    text:weight_mask_cutoff:stop: colons and underscores inside [ ] don't count."""
    _, *rest = re.split(r":(?![^\[]*\])", prompt, maxsplit=2)
    if not rest:
        return []
    weight, *mask = re.split(r"_(?![^\[]*\])", rest[0], maxsplit=2)
    parts = [("weight", weight)]
    if len(mask) == 2:
        parts.append(("mask cutoff", mask[1]))
    if len(rest) == 2:
        parts.append(("stop", rest[1]))
    return parts


def _loss_parts(spec: str) -> list[tuple[str, str]]:
    """(part, text) of each expression in a loss weight or in what follows an image prompt's
    path, split the way pytti splits weight_mask:stop: a colon before \\ or / is a path's."""
    weight, *stop = re.split(r":(?![\\/])", spec, maxsplit=1)
    return [("weight", weight.split("_", 1)[0])] + [("stop", text) for text in stop]


def _expression_problem(text: str, names) -> tuple[bool, str] | None:
    """What keeps text from being an expression pytti can evaluate with these names: (True,
    the part that could run code) or (False, the mistake, worded to follow the field's
    name); None if there is nothing."""
    text = text.strip()  # pytti's eval() skips leading spaces, ast.parse doesn't
    if not text:
        return False, "is empty"
    if len(text) > _MAX_EXPRESSION:
        return False, f"is too long to check ({len(text)} characters; {_MAX_EXPRESSION} at most)"
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        return False, f"isn't a valid expression: {_shorten(text)} ({e.msg})"
    except (ValueError, MemoryError, RecursionError):  # a null character, or nested too deep to parse
        return False, f"isn't a valid expression: {_shorten(text)}"

    def quoted(node):
        return _shorten(ast.get_source_segment(text, node) or type(node).__name__)
    for node in ast.walk(tree):
        # Text in quotes can't reach anything by itself; an f-string's {...} parts are checked here
        if not isinstance(node, (*_EXPRESSION_SYNTAX, ast.JoinedStr, ast.FormattedValue)):
            return True, quoted(node)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, complex))):
            # Usually a preset's unquoted [a, b, c, d], which YAML reads as a list of text
            return False, f"uses {quoted(node)}, which isn't a number. In a preset file, put single quotes around the whole expression"
    # Names a lambda or comprehension in the expression defines
    names = names | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in names:
            return False, f"uses {node.id}, which isn't t, a math function or one of the preset's audio variables"
    return None


def preset_risks(values: dict, extras: dict, labels: dict) -> tuple[list[str], list[str]]:
    """What in a preset could run code on this PC, and expressions pytti can't evaluate.

    values holds the UI fields; of extras, only the preset's keys without a widget are
    read. Returns (problems, which stop a render, notes), worded for the status box.
    Expressions may use what PROMPTING.md lists: numbers, arithmetic, t and math's
    functions. pytti runs them with eval(), so anything beyond that could run code.
    """
    code, mistakes, notes = [], [], []
    if extras.get("hydra"):
        code.append("The preset has a hydra: section, which can run programs on this PC. PyTTI doesn't need one: delete it from the preset's file in config/conf.")
    if extras.get("defaults") not in (None, [], ["_self_"]):
        code.append("The preset has a defaults: list, which can pull other files into the render, such as one with a hydra: section. PyTTI doesn't need one: delete it from the preset's file in config/conf.")
    for key in _PARSED_TEXT_KEYS:
        if "${" in str(values.get(key) or ""):
            code.append(f"{labels[key]} uses ${{...}}, which pulls in other text when the render starts, where it could run code on this PC. Write the value out instead.")
    filters = extras.get("input_audio_filters", load_defaults().get("input_audio_filters"))
    audio = {str(f["variable_name"]) for f in filters if isinstance(f, dict) and f.get("variable_name")} if isinstance(filters, list) else set()
    names = _EXPRESSION_NAMES | audio | {f"{name}_prev" for name in audio}  # pytti adds the previous frame's as <name>_prev

    checks = []  # (where, expression, the names it may use)
    mode = values.get("animation_mode")
    motion_names = (names | _DEPTH_NAMES) if mode == "3D" else names
    for key in _MOTION_KEYS.get(mode, ()):
        if str(values.get(key) or "").strip():  # conf_problems reports a blank one
            checks.append((labels[key], str(values[key]), motion_names))
    # Prefix, scene and suffix give the same prompts checked apart: saving makes the prefix
    # end and the suffix start with a pipe, and turns line breaks and runs of spaces into one
    for key in ("scene_prefix", "scenes", "scene_suffix"):
        for prompt in str(values.get(key) or "").split("|"):
            prompt = " ".join(prompt.split())
            checks += [(f"The {part} of '{_shorten(prompt)}' in {labels[key]}", text, names)
                       for part, text in _prompt_parts(prompt)]
    for image, *spec in _split_image_prompts(str(values.get("direct_image_prompts") or "")):
        if spec:
            prompt = f"{image}:{spec[0]}"
            checks += [(f"The {part} of '{_shorten(prompt)}' in {labels['direct_image_prompts']}", text, names)
                       for part, text in _loss_parts(spec[0])]
    for key in _LOSS_WEIGHT_KEYS + _PROMPT_WEIGHT_KEYS:
        weight = _weight_value(values.get(key))  # pytti skips a blank one
        if weight:
            parts = _prompt_parts(f"weight:{weight}") if key in _PROMPT_WEIGHT_KEYS else _loss_parts(weight)
            checks += [(labels[key] if part == "weight" else f"The {part} of {labels[key]}", text, names) for part, text in parts]
    expression_code = []
    for where, text, allowed in checks:
        found = _expression_problem(text, allowed)
        if found and found[0]:
            expression_code.append(f"{where} uses {found[1]}, which could run code on this PC.")
        elif found:
            mistakes.append(f"{where} {found[1]}.")
    if expression_code:
        code += expression_code + ["Expressions can use numbers, t, math functions such as sin() and the preset's audio variables."]
    if code:
        code.append("Only render presets from people you trust.")

    models_dir = extras.get("models_parent_dir")
    if models_dir not in (None, "${user_cache:}"):
        notes.append(f"The preset loads VQGAN models from {models_dir} (models_parent_dir), and model files can run code on this PC: keep it only for models you trust.")
    # A prompt used in several scenes would be reported once per scene
    return list(dict.fromkeys(code + mistakes)), notes


# Tokens CLIP reads per prompt, its start and end markers included
_CLIP_CONTEXT = 77
_tokenizer = None  # CLIP's tokenizer once loaded; False if it can't be


def _clip_tokenizer():
    """CLIP's own tokenizer, from the installed clip package; None if it can't be loaded.

    simple_tokenizer.py is loaded by path: importing the clip package would import torch.
    """
    global _tokenizer
    if _tokenizer is None:
        try:
            folder = Path(importlib.util.find_spec("clip").origin).parent  # finds it without importing it
            spec = importlib.util.spec_from_file_location("pytti_portable_clip_tokenizer", folder / "simple_tokenizer.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _tokenizer = module.SimpleTokenizer()
        except Exception:
            _tokenizer = False
    return _tokenizer or None


def long_prompts(values: dict, labels: dict) -> list[str]:
    """Scene prompts longer than CLIP can read, worded for the status box.

    pytti finds them only once its models have loaded, and stops the render. It glues
    Scene Prefix, each scene and Scene Suffix together and splits them on pipes; saving
    makes the prefix end and the suffix start with a pipe, so each field splits the same
    way on its own. Only a prompt's text is tokenized, not its weight, stop or mask.
    """
    tokenizer = _clip_tokenizer()
    if tokenizer is None:
        return []
    problems = []
    for key in ("scene_prefix", "scenes", "scene_suffix"):
        for prompt in str(values.get(key) or "").split("|"):
            # pytti's split: colons inside [ ] don't count
            text = re.split(r":(?![^\[]*\])", prompt, maxsplit=1)[0].strip()
            if not text or (text[0] == "[" and text[-1] == "]"):
                continue  # nothing to tokenize, or an image prompt
            tokens = len(tokenizer.encode(text)) + 2
            if tokens > _CLIP_CONTEXT:
                problems.append(f"The prompt '{_shorten(' '.join(text.split()))}' in {labels[key]} is {tokens} tokens long, "
                                f"and CLIP reads at most {_CLIP_CONTEXT}. Shorten it, or split it into several prompts with |.")
    return list(dict.fromkeys(problems))


def _unknown_key_notes(data: dict) -> list[str]:
    """A note naming preset keys pytti doesn't read, which are often typos, with the closest real key."""
    known = set(load_defaults()) | _OPTIONAL_KEYS
    unknown = []
    for key in sorted(str(key) for key in data if key not in known):
        match = difflib.get_close_matches(key, known, n=1)
        unknown.append(f"{key} (did you mean {match[0]}?)" if match else key)
    return [f"Unknown settings, ignored by pytti: {', '.join(unknown)}."] if unknown else []


def _conf_notes(data: dict) -> list[str]:
    """Fix settings pytti can't run with and explain anything that won't behave as expected."""
    notes = []
    flow_samples = int(data.get("flow_long_term_samples") or 0)
    if data.get("animation_mode") == "Video Source" and flow_samples > 0:
        # Long-term optical flow reloads the frame 2^N back from the rolling .bak files
        needed = 2 ** flow_samples + 1
        if int(data.get("backups") or 0) < needed:
            data["backups"] = needed
            notes.append(f"Backups raised to {needed} for long-term optical flow.")
    spf, pre = int(data["steps_per_frame"]), int(data["pre_animation_steps"])
    if data.get("animation_mode") != "off" and int(data.get("save_every") or 0) <= 0 and spf > 0 and pre % spf:
        # Frames are saved every steps_per_frame steps from step 0, camera moves start at pre_animation_steps
        notes.append(f"Tip: make Pre-animation Steps a multiple of Steps per Frame ({spf}) so each frame is saved fully refined.")
    scenes = [scene for scene in str(data.get("scenes") or "").split("||") if scene.strip()]
    interpolation, per_scene = int(data.get("interpolation_steps") or 0), int(data["steps_per_scene"])
    if len(scenes) > 1 and interpolation > per_scene:
        # The previous scene fades out over the first interpolation_steps of each scene
        notes.append(f"Tip: Interpolation Steps ({interpolation}) is more than Steps per Scene ({per_scene}), so crossfades between scenes never finish.")
    if data.get("breath_mode") and not str(data.get("init_image") or "").strip():
        notes.append("Breath Mode does nothing without an Init Image.")
    if data.get("input_audio") and not (data.get("input_audio_filters") or load_defaults().get("input_audio_filters")):
        notes.append("Input audio is ignored until input_audio_filters are added to the preset YAML.")
    return notes + _unknown_key_notes(data)


def preset_base(name: str, extras: dict | None) -> dict:
    """The keys a save keeps besides the UI fields: those of the existing conf/<name>.yaml,
    or for a new file those carried over from the preset that was last loaded (e.g.
    input_audio_filters). PresetError if the existing file can't be read.
    """
    if _valid_name(name) and (CONF_DIR / f"{name}.yaml").exists():
        return load_conf(f"{name}.yaml")
    return dict(extras or {})


def write_conf(filename: str, base: dict, values: dict) -> list[str]:
    """Save the UI fields over base to conf/<filename>; returns notes for the status box."""
    conf = build_conf_dict(**values)
    # The UI's settings in its order, then the keys it has no widget for
    data = {key: conf[key] for key in CONF_FIELDS}
    data.update((key, value) for key, value in base.items() if key not in CONF_KEYS)
    notes = _conf_notes(data)
    save_yaml(CONF_DIR / filename, data, header="# @package _global_\n")
    return notes


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


_REFERENCE = re.compile(r"\$\{(\w+)\}")


def _resolve_references(data: dict) -> dict:
    """Replace plain ${key} references (e.g. save_every: ${steps_per_frame}) with the referenced value."""
    def resolve(value, seen):
        match = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
        if match and match.group(1) in data and match.group(1) not in seen:
            return resolve(data[match.group(1)], seen | {match.group(1)})
        return value
    return {key: resolve(value, {key}) for key, value in data.items()}


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
    gr.set_static_paths([str(OUTPUTS_DIR)])

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
            return _live_view(namespace, _running)

        def tick(namespace, encode_pick):
            running = _running
            view = _live_view(namespace, running)
            if running:
                return *view, gr.skip(), gr.skip()
            # The render has ended: say how, and offer its frames for encoding
            return *view, _render_status or gr.skip(), refresh_encode_list(encode_pick)

        def load_existing(name):
            global _last_preset
            if not name:
                return [gr.update()] * (len(all_inputs) + 5)
            if name == DEFAULTS_CHOICE:
                # No config name and no stamp, so a save asks before replacing a preset
                preset, stamp = {}, None
            elif not (CONF_DIR / name).exists():
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
            if _running:
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
            return gr.Dropdown(choices=load_choices()), " ".join([msg] + status), gr.Timer(active=_running), stamp

        def stop_and_deactivate_timer(namespace, encode_pick):
            msg = stop_render()
            log, frame, progress, _ = _live_view(namespace, False)
            return msg, gr.Timer(active=False), log, frame, progress, refresh_encode_list(encode_pick)

        def resume_last():
            """Resume Render on the Run tab: the last render, or after a restart the newest run."""
            run_dir = _render_dir or _newest_run()
            if run_dir is None:
                return "There is no render to resume yet.", gr.Timer(active=False)
            msg = resume_render(run_dir, labels)
            if not _running:
                msg += " To resume another render, pick it in the Run list on the Output tab and press Resume Render there."
            return msg, gr.Timer(active=_running)

        def resume_picked(frames_dir):
            """Resume Render on the Output tab: the run picked in its list."""
            if not frames_dir:
                return "Select a run first.", gr.skip(), gr.skip()
            msg = resume_render(Path(frames_dir).parent.parent, labels)
            # The Run tab shows the resumed render
            return msg, msg if _running else gr.skip(), gr.Timer(active=_running)

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
        demo.load(fn=lambda: gr.Timer(active=_running), outputs=[timer])
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
    print(f"Using Python: {PYTHON_EXE}")
    demo = make_ui()
    # This PC only: the UI starts renders, and their motion expressions run as Python code
    demo.launch(inbrowser=True, show_api=False, server_name="127.0.0.1", share=False)
