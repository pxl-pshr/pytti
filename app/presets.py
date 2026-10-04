"""
Presets: reading and writing them in config/conf, the defaults in config/default.yaml,
and the checks behind Load, Save and Start Render.
"""
import ast
import difflib
import importlib.util
import inspect
import math
import os
import re
from pathlib import Path

import yaml

import paths


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
    files = sorted(paths.CONF_DIR.glob("*.yaml"))
    return [f.name for f in files if not f.name.startswith("_")]


# Load Config's first entry: default.yaml's settings with a blank Config Name. A page
# reload brings back the last preset, so this is the way back to the defaults.
DEFAULTS_CHOICE = "(defaults)"


def load_choices() -> list[str]:
    """Load Config's entries: the defaults, then the presets."""
    return [DEFAULTS_CHOICE] + get_conf_files()


def load_defaults() -> dict:
    return load_yaml(paths.DEFAULT_YAML)


def _yaml_problem(error: yaml.YAMLError) -> str:
    """A YAML error as one line: what is wrong and where."""
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or (str(error).strip().splitlines() or ["not valid YAML"])[0]
    return f"{problem} (line {mark.line + 1}, column {mark.column + 1})" if mark else problem


def load_conf(name: str) -> dict:
    """conf/<name> as a dict, {} if it doesn't exist; PresetError if it can't be read."""
    path = paths.CONF_DIR / name
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
        return (paths.CONF_DIR / name).stat().st_mtime_ns
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
    return _valid_name(_conf_name(name)) and (paths.CONF_DIR / name).exists() and not _stamped(name, stamp)


def _listed_name(name: str) -> str:
    """conf/<name> as Load Config lists it, which may differ in case."""
    return next((listed for listed in get_conf_files() if os.path.normcase(listed) == os.path.normcase(name)), name)


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
    for base in (paths.PORTABLE_ROOT, paths.ROOT):
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
    if _valid_name(name) and (paths.CONF_DIR / f"{name}.yaml").exists():
        return load_conf(f"{name}.yaml")
    return dict(extras or {})


def write_conf(filename: str, base: dict, values: dict) -> list[str]:
    """Save the UI fields over base to conf/<filename>; returns notes for the status box."""
    conf = build_conf_dict(**values)
    # The UI's settings in its order, then the keys it has no widget for
    data = {key: conf[key] for key in CONF_FIELDS}
    data.update((key, value) for key, value in base.items() if key not in CONF_KEYS)
    notes = _conf_notes(data)
    save_yaml(paths.CONF_DIR / filename, data, header="# @package _global_\n")
    return notes


_REFERENCE = re.compile(r"\$\{(\w+)\}")


def _resolve_references(data: dict) -> dict:
    """Replace plain ${key} references (e.g. save_every: ${steps_per_frame}) with the referenced value."""
    def resolve(value, seen):
        match = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
        if match and match.group(1) in data and match.group(1) not in seen:
            return resolve(data[match.group(1)], seen | {match.group(1)})
        return value
    return {key: resolve(value, {key}) for key, value in data.items()}
