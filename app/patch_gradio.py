"""
patch_gradio.py
---------------
Patches to pytti-core that this UI relies on (breath mode, save_every=0,
zero-padded frame names, Windows paths, safe video conversion, Video Source
end of video).

Run by install.bat and on every launch.bat, so an install picks up new patches
after `git pull`. Re-running is safe: patches already applied are skipped. If any
patch can't be applied, nothing is written and the script exits with status 1.

The gradio_client schema fix is applied at runtime by ui.py instead.

    python patch_gradio.py [--quiet]
"""
import pathlib
import sys

SITE_PACKAGES = pathlib.Path(__file__).parent.parent / "python" / "Lib" / "site-packages"

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
    # Video Source: end the render when the source video runs out. Past its last
    # frame pytti only re-stylizes that frame, which can take hours.
    (
        '        last_scene = prompts[0] if skip_prompts == 0 else prompts[skip_prompts - 1]\n'
        '        for scene in prompts[skip_prompts:]:\n'
        '            logger.info("Running prompt:", " | ".join(map(str, scene)))\n'
        '            i += model.run_steps(\n'
        '                params.steps_per_scene - skip_steps,\n',
        '        last_scene = prompts[0] if skip_prompts == 0 else prompts[skip_prompts - 1]\n'
        '\n'
        '        # Video Source: stop at the first step whose target frame (frame_stride past\n'
        '        # (i - pre_animation_steps) * frame_stride // steps_per_frame) is past the video\n'
        '        end_step = len(prompts) * params.steps_per_scene\n'
        '        if video_frames is not None and params.frame_stride > 0:\n'
        '            n_frames = len(video_frames)\n'
        '            video_end = params.pre_animation_steps + (\n'
        '                (n_frames - params.frame_stride) * params.steps_per_frame + params.frame_stride - 1\n'
        '            ) // params.frame_stride\n'
        '            if video_end < end_step:\n'
        '                end_step = video_end\n'
        '                logger.info(\n'
        '                    f"Video source has {n_frames} frames, so the render will end at step {end_step} "\n'
        '                    f"of {len(prompts) * params.steps_per_scene}"\n'
        '                )\n'
        '        for scene in prompts[skip_prompts:]:\n'
        '            if i >= end_step:\n'
        '                break\n'
        '            logger.info("Running prompt:", " | ".join(map(str, scene)))\n'
        '            i += model.run_steps(\n'
        '                min(params.steps_per_scene - skip_steps, end_step - i),\n',
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

# The breath mode block as the previous version of this script inserted it; installs
# patched with it are upgraded in place
_BREATH_MODE_V1 = (
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
    '        im.save(filename)'
)

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
    # Zero-pad frame filenames + breath mode blend. Only blends when the user set an
    # init image (Video Source mode fills init_image_pil with the clip's first frame),
    # and resizes it once rather than for every saved frame.
    (
        (
            '        filename = f"{OUTPATH}/{file_namespace}/{base_name}_{n}.png"\n'
            '        im.save(filename)',
            _BREATH_MODE_V1,
        ),
        '        filename = f"{OUTPATH}/{file_namespace}/{base_name}_{n:04d}.png"\n'
        '\n'
        '        # Breath mode: blend init image with optimized output\n'
        '        breath_mode = getattr(params, "breath_mode", False) if params else False\n'
        '        if breath_mode and init_image_pil is not None and params.init_image:\n'
        '            num_scenes = max(1, len([s for s in params.scenes.split("||") if s.strip()]))\n'
        '            total_frames = max(1, (num_scenes * params.steps_per_scene) // save_every)\n'
        '            progress = min(n / total_frames, 1.0)\n'
        '            size_key = (id(init_image_pil), im.size)\n'
        '            if getattr(update, "breath_init", (None, None))[0] != size_key:\n'
        '                update.breath_init = (size_key, init_image_pil.resize(im.size, Image.LANCZOS))\n'
        '            im = Image.blend(update.breath_init[1], im, alpha=progress)\n'
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

# ── pytti-core patches: MSELossClass.py / LatentLossClass.py ─────────────────

PYTTI_MSELOSS = SITE_PACKAGES / "pytti" / "LossAug" / "MSELossClass.py"
PYTTI_LATENTLOSS = SITE_PACKAGES / "pytti" / "LossAug" / "LatentLossClass.py"

PYTTI_IMAGE_PROMPT_PATCHES = [
    # Fix Windows paths in direct image prompts and weight masks: the old split
    # cut "C:\img.png" at the drive letter. A colon followed by a slash or
    # backslash (C:\, C:/, https://) is part of the path, not a weight separator.
    (
        r'prompt_string, r"(?<!^http)(?<!s):|:(?!/)", ["", "1", "-inf"]',
        r'prompt_string, r":(?![\\/])", ["", "1", "-inf"]',
    ),
]

# ── pytti-core patches: rotoscoper.py ─────────────────────────────────────────

PYTTI_ROTOSCOPER = SITE_PACKAGES / "pytti" / "rotoscoper.py"

PYTTI_ROTOSCOPER_PATCHES = [
    (
        'import imageio, subprocess\n',
        'import imageio, os, subprocess\n',
    ),
    # Convert Video Source clips to a temp file and publish it only if ffmpeg
    # succeeds, so an interrupted conversion is never reused as <video>_converted.mp4
    (
        '            "copy",  # copy audio codec cause why not\n'
        '            out_fname,\n'
        '        ]\n'
        '        logger.debug(cmd)\n'
        '\n'
        '        subprocess.run(cmd)\n',
        '            "copy",  # copy audio codec cause why not\n'
        '            "-y",\n'
        '            out_fname + ".part.mp4",\n'
        '        ]\n'
        '        logger.debug(cmd)\n'
        '\n'
        '        subprocess.run(cmd, check=True)\n'
        '        os.replace(out_fname + ".part.mp4", out_fname)\n',
    ),
    # imageio reports a video's frame count as inf, which makes len() huge, so
    # pytti's end-of-video clamps never trigger and it reads past the last frame
    # (IndexError). Count the frames: a stream copy, no decoding, about a second.
    (
        '    vid = imageio.get_reader(out_fname, "ffmpeg")\n'
        '    n_frames = vid._meta["nframes"]\n',
        '    vid = imageio.get_reader(out_fname, "ffmpeg")\n'
        '    vid._nframes = vid._meta["nframes"] = vid.count_frames()\n'
        '    n_frames = vid._meta["nframes"]\n',
    ),
    # Video masks shorter than the render hold their last frame
    (
        '            return\n'
        '        mask_pil = Image.fromarray(self.frames.get_data(frame_n)).convert("L")\n',
        '            return\n'
        '        frame_n = min(frame_n, len(self.frames) - 1)\n'
        '        mask_pil = Image.fromarray(self.frames.get_data(frame_n)).convert("L")\n',
    ),
]

TARGETS = [
    (PYTTI_WORKHORSE, PYTTI_WORKHORSE_PATCHES, "workhorse.py"),
    (PYTTI_IMAGEGUIDE, PYTTI_IMAGEGUIDE_PATCHES, "ImageGuide.py"),
    (PYTTI_UPDATEFUNC, PYTTI_UPDATEFUNC_PATCHES, "update_func.py"),
    (PYTTI_LOSSORCH, PYTTI_LOSSORCH_PATCHES, "LossOrchestratorClass.py"),
    (PYTTI_MSELOSS, PYTTI_IMAGE_PROMPT_PATCHES, "MSELossClass.py"),
    (PYTTI_LATENTLOSS, PYTTI_IMAGE_PROMPT_PATCHES, "LatentLossClass.py"),
    (PYTTI_ROTOSCOPER, PYTTI_ROTOSCOPER_PATCHES, "rotoscoper.py"),
]

# ── Apply patches ───────────────────────────────────────────────────────────

def plan_patches(target, patches, label):
    """Return (patched text or None if already up to date, problems) without writing anything.

    A patch's old text can be a tuple of alternatives, e.g. the upstream code and the
    code an earlier version of a patch produced.
    """
    if not target.exists():
        return None, [f"{label}: {target} not found. Is pytti-core installed?"]
    text = target.read_text(encoding="utf-8")
    changed = False
    problems = []
    for olds, new in patches:
        olds = (olds,) if isinstance(olds, str) else olds
        found = [(old, text.count(old)) for old in olds if old in text]
        if len(found) == 1 and found[0][1] == 1:
            text = text.replace(found[0][0], new)
            changed = True
        elif not found and new in text:
            continue  # already applied
        else:
            where = "not found" if not found else "found more than once"
            problems.append(f"{label}: {where}: {olds[0][:60].strip()!r}...")
    return (text if changed else None), problems


def main():
    quiet = "--quiet" in sys.argv
    planned, problems = [], []
    for target, patches, label in TARGETS:
        text, file_problems = plan_patches(target, patches, label)
        problems += file_problems
        if text is not None:
            planned.append((target, text, label))

    # Several patches depend on each other across files, so apply all or nothing
    if problems:
        print("  ERROR: pytti-core doesn't match the expected version. No files were changed.")
        for problem in problems:
            print(f"    {problem}")
        return 1

    for target, text, label in planned:
        target.write_text(text, encoding="utf-8")
        print(f"  Patched {label}")
    if not planned and not quiet:
        print("  All patches already applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
