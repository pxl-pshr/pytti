"""
The settings help: the tip under each field, and the FAQ tab's settings reference.
"""
import html


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
    "gradient_accumulation_steps": "Split each step's cutouts into N smaller batches. 1 is fastest; 2 or more uses less VRAM (default settings: about 17 GB at 1, 9 GB at 2). Same result either way. Must divide Cutouts evenly.",
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
        ("gradient_accumulation_steps", "Splits each step's cutouts into N smaller batches that are summed into one update; it does not change the result. Must divide <code>cutouts</code> evenly. 1 is fastest, and 2 or more uses less GPU memory. With the default settings a render uses about 17 GB at 1 and about 9 GB at 2: on GPUs with less than 24 GB, set it to 2 or more.", "number"),
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
