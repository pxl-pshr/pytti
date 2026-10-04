"""
patch_pytti.py
--------------
Patches to pytti-core that this UI relies on (breath mode, save_every=0,
zero-padded frame names, Windows paths, Video Source and video mask conversion,
Video Source end of video, prompt mask positions, output and backup folders,
resuming from backups, VQGAN downloads, audio input, audio variables in 2D camera
moves, the folders models load from), plus model_mirror.py, which fetches models
from PyTTI Portable's mirror on Hugging Face and picks those folders, and AdaBins'
torch.hub branch.

Speed patches to pytti-core and kornia leave what a render computes unchanged and cut
the time the CPU and GPU spend waiting for each other.

Run by install.bat and on every launch.bat, so an install picks up new patches
after `git pull`. Re-running is safe: patches already applied are skipped.

Exit status:
    0  patched, or nothing to do
    1  pytti-core doesn't match the expected version; nothing was written
    2  a file could not be read or written (e.g. locked by another program);
       running this again finishes the job

The gradio_client schema fix is applied at runtime by ui.py instead.

    python patch_pytti.py [--quiet]
"""
import errno
import os
import pathlib
import sys

SITE_PACKAGES = pathlib.Path(__file__).parent.parent / "python" / "Lib" / "site-packages"

# ── pytti-core patches: workhorse.py ───────────────────────────────────────

PYTTI_WORKHORSE = SITE_PACKAGES / "pytti" / "workhorse.py"

# The Video Source end as earlier versions of this script inserted it (it could stop
# before the last frame was saved, e.g. with a frame_stride above 1); installs patched
# with it are upgraded in place
_VIDEO_END_V1 = (
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
    '                min(params.steps_per_scene - skip_steps, end_step - i),\n'
)

PYTTI_WORKHORSE_PATCHES = [
    # OUTPATH was fixed when workhorse.py was imported, before Hydra changes into the
    # render's folder, so every render left an empty app/images_out/<namespace>. As a
    # relative path it resolves against the render's folder, where the frames are saved.
    (
        'OUTPATH = f"{os.getcwd()}/images_out/"',
        'OUTPATH = "images_out/"',
    ),
    # Only make backup/<namespace> when backups are on, the only time pytti writes there
    # (Video Source reads it, and the UI turns backups on for that); otherwise every
    # render left it empty.
    (
        '        Path(f"{OUTPATH}/{params.file_namespace}").mkdir(parents=True, exist_ok=True)\n'
        '        Path(f"backup/{params.file_namespace}").mkdir(parents=True, exist_ok=True)',
        '        Path(f"{OUTPATH}/{params.file_namespace}").mkdir(parents=True, exist_ok=True)\n'
        '        if params.backups > 0:\n'
        '            Path(f"backup/{params.file_namespace}").mkdir(parents=True, exist_ok=True)',
    ),
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
        (
            '        last_scene = prompts[0] if skip_prompts == 0 else prompts[skip_prompts - 1]\n'
            '        for scene in prompts[skip_prompts:]:\n'
            '            logger.info("Running prompt:", " | ".join(map(str, scene)))\n'
            '            i += model.run_steps(\n'
            '                params.steps_per_scene - skip_steps,\n',
            _VIDEO_END_V1,
        ),
        '        last_scene = prompts[0] if skip_prompts == 0 else prompts[skip_prompts - 1]\n'
        '\n'
        '        # Video Source: end the render with the last save that shows the last source\n'
        '        # frame. The target frame moves only at steps pre_animation_steps + m *\n'
        '        # steps_per_frame, to frame (m + 1) * frame_stride (at most the last frame), and\n'
        '        # the frame saved at step s is the image after steps 0 to s - 1.\n'
        '        end_step = len(prompts) * params.steps_per_scene\n'
        '        n_frames = len(video_frames) if video_frames is not None else 0\n'
        '        if n_frames and params.frame_stride > 0 and params.save_every > 0:\n'
        '            # Moves until the target is the last frame. Without pre-animation steps\n'
        '            # frame 0 is never a target, so even a one-frame video needs one.\n'
        '            moves = -(-(n_frames - 1) // params.frame_stride)\n'
        '            if params.pre_animation_steps == 0:\n'
        '                moves = max(moves, 1)\n'
        '            # Steps last_start to repeat - 1 render the last frame; later ones re-stylize it\n'
        '            repeat = params.pre_animation_steps + moves * params.steps_per_frame\n'
        '            last_start = repeat - params.steps_per_frame if moves else 0\n'
        '            # Stop after the last save up to step repeat or, when save_every skips the\n'
        '            # steps that render the last frame, after the next save, which shows it\n'
        '            save = (repeat + 1) // params.save_every * params.save_every - 1\n'
        '            if save <= last_start:\n'
        '                save += params.save_every\n'
        '            if save + 1 < end_step:\n'
        '                end_step = save + 1\n'
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
    # Fetch the models the render needs from PyTTI Portable's Hugging Face mirror before
    # they're loaded (pytti/model_mirror.py, added below). Whatever it can't fetch is
    # downloaded from the original source as before.
    (
        '        # Phase 2 - load and parse\n'
        '        ###########################\n'
        '\n'
        '        # load CLIP\n',
        '        # Phase 2 - load and parse\n'
        '        ###########################\n'
        '\n'
        '        try:\n'
        '            from pytti.model_mirror import prefetch_models\n'
        '\n'
        '            prefetch_models(params)\n'
        '        except Exception as e:\n'
        '            logger.warning(f"Skipped the PyTTI model mirror: {e}")\n'
        '\n'
        '        # load CLIP\n',
    ),
    # VQGAN models load from the folder model_mirror.py picks: a preset's own
    # models_parent_dir, or by default the pytti folder's cache/models, unless earlier
    # versions downloaded the model to the .cache folder
    (
        '            model_artifacts_path = Path(params.models_parent_dir) / "vqgan"\n',
        '            from pytti.model_mirror import vqgan_folder\n'
        '\n'
        '            model_artifacts_path = vqgan_folder(params)\n',
    ),
    # Resume (restore=true, which the UI's Resume Render sets): without a backup to continue
    # from, the render stopped with FileNotFoundError, or tried to load a file named "None".
    # It now starts from the beginning with a warning.
    (
        '    # NB: `backup/` dir probably not working at present\n'
        '    if restore and restore_run == latest:\n'
        '        _, restore_run = get_last_file(\n'
        '            f"backup/{params.file_namespace}",\n'
        r'            f"^(?P<pre>{re.escape(params.file_namespace)}\\(?)(?P<index>\\d*)(?P<post>\\)?_\\d+\\.bak)$",' '\n'
        '        )\n',
        '    if restore and restore_run == latest:\n'
        '        restore_run = None\n'
        '        if os.path.isdir(f"backup/{params.file_namespace}"):\n'
        '            _, restore_run = get_last_file(\n'
        '                f"backup/{params.file_namespace}",\n'
        r'                f"^(?P<pre>{re.escape(params.file_namespace)}\\(?)(?P<index>\\d*)(?P<post>\\)?_\\d+\\.bak)$",' '\n'
        '            )\n'
        '        if restore_run is None:\n'
        '            logger.warning(\n'
        '                f"There is no backup in backup/{params.file_namespace} to resume from, "\n'
        '                "so the render starts from the beginning."\n'
        '            )\n'
        '            restore = False\n',
    ),
    # A backup holds only tensors, so load it as tensors only: then a backup file can't run code
    (
        '                logger.info("restoring from", filename)\n'
        '                img.load_state_dict(\n'
        '                    torch.load(f"backup/{params.file_namespace}/{filename}")\n'
        '                )\n',
        '                img.load_state_dict(\n'
        '                    torch.load(f"backup/{params.file_namespace}/{filename}", weights_only=True)\n'
        '                )\n',
    ),
    # Frame n and its backup are saved before step n * save_every - 1 runs. Resuming at step
    # n * save_every skipped that step, and the camera move with it when one was due; resume
    # with it instead, which saves frame n again, unchanged.
    (
        '            i = restore_frame * params.save_every\n'
        '        else:\n'
        '            i = 0\n',
        '            i = max(0, restore_frame * params.save_every - 1)\n'
        '            logger.info(f"Resuming from {filename}: frame {restore_frame}, step {i}")\n'
        '        else:\n'
        '            i = 0\n',
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
    # Speed and memory with gradient_accumulation_steps above 1: each batch's CLIP losses are
    # backpropagated into a detached copy of the decoded image, which frees that batch's
    # graph; the decoded image and the stabilization, palette and smoothing losses are then
    # backpropagated once per step instead of once per batch. The gradient is the same sum.
    (
        '        for mb_i in range(gradient_accumulation_steps):\n'
        '            # logger.debug(mb_i)\n'
        '            # logger.debug(self.image_rep.shape)\n'
        '            t = 1\n'
        '            interp_losses = [0]\n'
        '            prompt_losses = {}\n'
        '            if self.embedder is not None:\n'
        '                image_embeds, offsets, sizes = self.embedder(self.image_rep, input=z)\n',
        '        z_clip = z.detach().requires_grad_() if self.embedder is not None else None\n'
        '        for mb_i in range(gradient_accumulation_steps):\n'
        '            t = 1\n'
        '            interp_losses = [0]\n'
        '            prompt_losses = {}\n'
        '            if self.embedder is not None:\n'
        '                image_embeds, offsets, sizes = self.embedder(self.image_rep, input=z_clip)\n',
    ),
    (
        '            total_loss_mb = sum(map(lambda x: sum(x.values()), losses)) + sum(\n'
        '                interp_losses\n'
        '            )\n'
        '\n'
        '            total_loss_mb /= gradient_accumulation_steps\n'
        '\n'
        '            # total_loss_mb.backward()\n'
        '            total_loss_mb.backward(retain_graph=True)\n'
        '            # total_loss += total_loss_mb # this is causing it to break\n'
        '            # total_loss = total_loss_mb\n'
        '\n'
        '        # losses = [{k:v} for k,v in losses_accumulator.items()]\n'
        '        # losses_raw = [{k:v} for k,v in losses_raw_accumulator.items()]\n'
        '        losses_raw.append({"TOTAL": total_loss})  # this needs to be fixed\n',
        '            clip_loss_mb = (sum(losses[0].values()) + sum(interp_losses)) / gradient_accumulation_steps\n'
        '            if torch.is_tensor(clip_loss_mb) and clip_loss_mb.requires_grad:\n'
        '                clip_loss_mb.backward()\n'
        '\n'
        '        image_loss = sum(losses[1].values()) + sum(losses[2].values())\n'
        '        tensors, grads = [], []\n'
        '        if z_clip is not None and z_clip.grad is not None:\n'
        '            tensors.append(z)\n'
        '            grads.append(z_clip.grad)\n'
        '        if torch.is_tensor(image_loss) and image_loss.requires_grad:\n'
        '            tensors.append(image_loss)\n'
        '            grads.append(torch.ones_like(image_loss))\n'
        '        if tensors:\n'
        '            torch.autograd.backward(tensors, grads)\n'
        '\n'
        '        losses_raw.append({"TOTAL": total_loss})  # this needs to be fixed\n',
    ),
    # Speed: only show_graphs and tensorboard read the per-step loss table, and filling it
    # reads every loss back from the GPU, so the CPU waited for each step to finish
    (
        '        if save_loss:\n'
        '            if not self.dataframe:\n',
        '        if save_loss and (\n'
        '            self.params is None\n'
        '            or getattr(self.params, "show_graphs", False)\n'
        '            or getattr(self.params, "use_tensorboard", False)\n'
        '        ):\n'
        '            if not self.dataframe:\n',
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

# ── pytti-core patches: OpticalFlowLossClass.py ──────────────────────────────

PYTTI_OPTICALFLOW = SITE_PACKAGES / "pytti" / "LossAug" / "OpticalFlowLossClass.py"

PYTTI_OPTICALFLOW_PATCHES = [
    # Video Source's long-term optical flow reloads earlier frames from the run's backups,
    # which after Resume Render include ones from before it. They hold only tensors, so
    # load them as tensors only: then a backup file can't run code.
    (
        '            state_dict = torch.load(path, map_location=device)\n',
        '            state_dict = torch.load(path, map_location=device, weights_only=True)\n',
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

# get_frames' video conversion as upstream wrote it, and as earlier versions of this
# script patched it (to a temp file published only if ffmpeg succeeded); installs
# patched with either are upgraded in place
_GET_FRAMES_UPSTREAM = (
    '    in_fname = path\n'
    '    out_fname = f"{path}_converted.mp4"\n'
    '    if not path_exists(path + "_converted.mp4"):\n'
    '        logger.debug(f"Converting {path}...")\n'
    '        cmd = ["ffmpeg", "-i", in_fname]\n'
    '        # if params is None:\n'
    '        # subprocess.run(["ffmpeg", "-i", in_fname, out_fname])\n'
    '        if params is not None:\n'
    '            # https://trac.ffmpeg.org/wiki/ChangingFrameRate\n'
    '            cmd += ["-filter:v", f"fps={params.frames_per_second}"]\n'
    '\n'
    '        # https://trac.ffmpeg.org/wiki/Encode/H.264\n'
    '        cmd += [\n'
    '            "-c:v",\n'
    '            "libx264",\n'
    '            "-crf",\n'
    '            "17",  # = effectively lossless\n'
    '            "-preset",\n'
    '            "veryslow",  # = effectively lossless\n'
    '            "-tune",\n'
    '            "fastdecode",  # not sure this is what I want, zerolatency and stillimage might make sense? can experiment I guess?\n'
    '            "-pix_fmt",\n'
    '            "yuv420p",  # may be necessary for "dumb players"\n'
    '            "-acodec",\n'
    '            "copy",  # copy audio codec cause why not\n'
    '            out_fname,\n'
    '        ]\n'
    '        logger.debug(cmd)\n'
    '\n'
    '        subprocess.run(cmd)\n'
    '\n'
    '        logger.debug(f"Converted {in_fname} to {out_fname}.")\n'
    '\n'
    '        # yeah I don\'t think this is actually true, but it probably should be.\n'
    '        logger.warning(\n'
    '            f"WARNING: future runs will automatically use {out_fname}, unless you delete it."\n'
    '        )\n'
)
_GET_FRAMES_V1 = _GET_FRAMES_UPSTREAM.replace(
    '            out_fname,\n'
    '        ]\n'
    '        logger.debug(cmd)\n'
    '\n'
    '        subprocess.run(cmd)\n',
    '            "-y",\n'
    '            out_fname + ".part.mp4",\n'
    '        ]\n'
    '        logger.debug(cmd)\n'
    '\n'
    '        subprocess.run(cmd, check=True)\n'
    '        os.replace(out_fname + ".part.mp4", out_fname)\n',
)
# The conversion as the previous version of this script patched it, with the copies in the
# temp folder and never deleted; installs patched with it are upgraded in place
_GET_FRAMES_V2 = (
    '    in_fname = path\n'
    '    # libx264 can\'t encode odd sizes as yuv420p: crop the odd last column/row\n'
    '    vf = "crop=trunc(iw/2)*2:trunc(ih/2)*2"\n'
    '    if params is not None:\n'
    '        # https://trac.ffmpeg.org/wiki/ChangingFrameRate\n'
    '        vf = f"fps={params.frames_per_second},{vf}"\n'
    '    # https://trac.ffmpeg.org/wiki/Encode/H.264\n'
    '    args = [\n'
    '        "-filter:v", vf,\n'
    '        "-c:v", "libx264",\n'
    '        "-crf", "17",  # = effectively lossless\n'
    '        "-preset", "veryfast",  # much faster than veryslow; the crf sets the quality\n'
    '        "-tune", "fastdecode",\n'
    '        "-pix_fmt", "yuv420p",  # may be necessary for "dumb players"\n'
    '        "-an",  # pytti reads only the frames\n'
    '    ]\n'
    '    # The copy is named after the clip\'s path, size and modification time and the\n'
    '    # settings above, so an edited clip or another fps is converted again\n'
    '    stat = os.stat(in_fname)\n'
    '    key = f"{os.path.normcase(os.path.abspath(in_fname))}|{stat.st_size}|{stat.st_mtime_ns}|{args}"\n'
    '    cache = Path(tempfile.gettempdir()) / "pytti-video-cache"\n'
    '    name = f"{Path(in_fname).stem[:40]}_{hashlib.sha256(key.encode()).hexdigest()[:16]}.mp4"\n'
    '    out_fname = str(cache / name)\n'
    '    if not path_exists(out_fname):\n'
    '        logger.info(f"Converting {in_fname}...")\n'
    '        cache.mkdir(parents=True, exist_ok=True)\n'
    '        part_fname = out_fname + ".part.mp4"\n'
    '        # ffmpeg on PATH (the UI puts the one it uses first), else imageio-ffmpeg\'s\n'
    '        ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()\n'
    '        cmd = [ffmpeg, "-nostats", "-loglevel", "error", "-y", "-i", in_fname, *args, part_fname]\n'
    '        logger.debug(cmd)\n'
    '        # No stdin, so a key pressed in the console can\'t end the conversion early\n'
    '        try:\n'
    '            subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)\n'
    '            os.replace(part_fname, out_fname)\n'
    '        finally:\n'
    '            if path_exists(part_fname):\n'
    '                os.remove(part_fname)\n'
    '        logger.debug(f"Converted {in_fname} to {out_fname}.")\n'
)

PYTTI_ROTOSCOPER_PATCHES = [
    (
        (
            'import imageio, subprocess\n',
            'import imageio, os, subprocess\n',
            'import hashlib, imageio, imageio_ffmpeg, os, shutil, subprocess, tempfile\n'
            'from pathlib import Path\n',
        ),
        'import contextlib, hashlib, imageio, imageio_ffmpeg, os, shutil, subprocess, tempfile, time\n'
        'from pathlib import Path\n',
    ),
    # Video Source clips and video masks are converted before pytti reads them. Upstream
    # wrote the copy next to the clip (failing in a read-only folder) and reused it even
    # after the fps changed, copied the audio (which fails for Opus or PCM), failed on odd
    # sizes and used x264's slowest preset. Convert without audio, cropped to even sizes,
    # faster, into a cache in the pytti folder named after the clip and the settings, and
    # publish the copy only if ffmpeg succeeds, so a failed or interrupted conversion is
    # never reused. Copies not used for 30 days are deleted.
    (
        (_GET_FRAMES_UPSTREAM, _GET_FRAMES_V1, _GET_FRAMES_V2),
        '    in_fname = path\n'
        '    # libx264 can\'t encode odd sizes as yuv420p: crop the odd last column/row\n'
        '    vf = "crop=trunc(iw/2)*2:trunc(ih/2)*2"\n'
        '    if params is not None:\n'
        '        # https://trac.ffmpeg.org/wiki/ChangingFrameRate\n'
        '        vf = f"fps={params.frames_per_second},{vf}"\n'
        '    # https://trac.ffmpeg.org/wiki/Encode/H.264\n'
        '    args = [\n'
        '        "-filter:v", vf,\n'
        '        "-c:v", "libx264",\n'
        '        "-crf", "17",  # = effectively lossless\n'
        '        "-preset", "veryfast",  # much faster than veryslow; the crf sets the quality\n'
        '        "-tune", "fastdecode",\n'
        '        "-pix_fmt", "yuv420p",  # may be necessary for "dumb players"\n'
        '        "-an",  # pytti reads only the frames\n'
        '    ]\n'
        '    # The copy is named after the clip\'s path, size and modification time and the\n'
        '    # settings above, so an edited clip or another fps is converted again\n'
        '    stat = os.stat(in_fname)\n'
        '    key = f"{os.path.normcase(os.path.abspath(in_fname))}|{stat.st_size}|{stat.st_mtime_ns}|{args}"\n'
        '    # In the pytti folder\'s cache/video (the UI passes renders cache/ as PYTTI_CACHE),\n'
        '    # else in the temp folder\n'
        '    if os.environ.get("PYTTI_CACHE"):\n'
        '        cache = Path(os.environ["PYTTI_CACHE"]) / "video"\n'
        '    else:\n'
        '        cache = Path(tempfile.gettempdir()) / "pytti-video-cache"\n'
        '    name = f"{Path(in_fname).stem[:40]}_{hashlib.sha256(key.encode()).hexdigest()[:16]}.mp4"\n'
        '    out_fname = str(cache / name)\n'
        '    # A copy\'s modification time is when it was last used. Copies unused for 30 days are\n'
        '    # deleted, and so are files an interrupted conversion left behind.\n'
        '    with contextlib.suppress(OSError):\n'
        '        os.utime(out_fname)\n'
        '    for old in cache.glob("*"):\n'
        '        with contextlib.suppress(OSError):  # in use, or deleted meanwhile\n'
        '            if time.time() - old.stat().st_mtime > 30 * 24 * 3600:\n'
        '                old.unlink()\n'
        '    if not path_exists(out_fname):\n'
        '        logger.info(f"Converting {in_fname}...")\n'
        '        cache.mkdir(parents=True, exist_ok=True)\n'
        '        part_fname = out_fname + ".part.mp4"\n'
        '        # ffmpeg on PATH (the UI puts the one it uses first), else imageio-ffmpeg\'s\n'
        '        ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()\n'
        '        cmd = [ffmpeg, "-nostats", "-loglevel", "error", "-y", "-i", in_fname, *args, part_fname]\n'
        '        logger.debug(cmd)\n'
        '        # No stdin, so a key pressed in the console can\'t end the conversion early\n'
        '        try:\n'
        '            subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)\n'
        '            os.replace(part_fname, out_fname)\n'
        '        finally:\n'
        '            if path_exists(part_fname):\n'
        '                os.remove(part_fname)\n'
        '        logger.debug(f"Converted {in_fname} to {out_fname}.")\n',
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

# ── pytti-core patches: Perceptor/Prompt.py ───────────────────────────────────

PYTTI_PROMPT = SITE_PACKAGES / "pytti" / "Perceptor" / "Prompt.py"

PYTTI_PROMPT_PATCHES = [
    # Direction masks (sky:3_u_0.3) and still image masks (fog:2_[mask.png]) were
    # handed each cutout's size as its position and its position as its size, so they
    # covered the wrong part of the frame, and an image mask gave NaN losses unless
    # border_mode was clamp. Video masks already got the two in the right order.
    (
        '    return lambda pos, size, emb: mask_fun(size, pos, emb, parametric_eval(thresh))',
        '    return lambda pos, size, emb: mask_fun(pos, size, emb, parametric_eval(thresh))',
    ),
    # Speed: the prompt weights and stops go to the GPU with non-blocking copies. A blocking
    # copy makes the CPU wait for all queued GPU work, several times per prompt per step.
    (
        '        if not self.enabled or self.weight in ["0", 0]:\n'
        '            return torch.as_tensor(offset, device=device), offset\n'
        '        dists_raw = spherical_dist_loss(embed, self.embeds) + offset\n'
        '        weight = torch.as_tensor(parametric_eval(self.weight), device=device)\n'
        '        stop = torch.as_tensor(parametric_eval(self.stop), device=device)\n'
        '\n'
        '        mask_stops, mask_weights = self.mask(position, size, embed.detach())\n'
        '        weight = torch.as_tensor(mask_weights, device=device) * weight\n',
        '        if not self.enabled or self.weight in ["0", 0]:\n'
        '            return torch.as_tensor(offset).to(device, non_blocking=True), offset\n'
        '        dists_raw = spherical_dist_loss(embed, self.embeds) + offset\n'
        '        weight = torch.as_tensor(parametric_eval(self.weight)).to(device, non_blocking=True)\n'
        '        stop = torch.as_tensor(parametric_eval(self.stop)).to(device, non_blocking=True)\n'
        '\n'
        '        mask_stops, mask_weights = self.mask(position, size, embed.detach())\n'
        '        weight = torch.as_tensor(mask_weights).to(device, non_blocking=True) * weight\n',
    ),
]

# ── pytti-core patches: AudioParse.py ─────────────────────────────────────────

PYTTI_AUDIOPARSE = SITE_PACKAGES / "pytti" / "AudioParse.py"

PYTTI_AUDIOPARSE_PATCHES = [
    (
        'import typing\n'
        'import subprocess\n',
        'import typing\n'
        'import shutil\n'
        'import subprocess\n'
        'import imageio_ffmpeg\n',
    ),
    # Run the ffmpeg on PATH (the UI puts the one it uses first), else imageio-ffmpeg's,
    # instead of failing with a bare FileNotFoundError when no "ffmpeg" is found. Keep its
    # banner out of the log, and give it no stdin, so a key pressed in the console can't
    # cut the audio short.
    (
        "        pipe = subprocess.Popen(['ffmpeg', '-i', input_audio,\n"
        "                                 '-f', 's16le',\n"
        "                                 '-acodec', 'pcm_s16le',\n"
        "                                 '-ar', str(SAMPLERATE),\n"
        "                                 '-ac', '1',\n"
        "                                 '-'], stdout=subprocess.PIPE, bufsize=10 ** 8)\n",
        "        ffmpeg = shutil.which('ffmpeg') or imageio_ffmpeg.get_ffmpeg_exe()\n"
        "        pipe = subprocess.Popen([ffmpeg, '-nostats', '-loglevel', 'error', '-i', input_audio,\n"
        "                                 '-f', 's16le',\n"
        "                                 '-acodec', 'pcm_s16le',\n"
        "                                 '-ar', str(SAMPLERATE),\n"
        "                                 '-ac', '1',\n"
        "                                 '-'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, bufsize=10 ** 8)\n",
    ),
    # An unreadable audio file gives no samples, which the old check (< 0) never caught
    (
        '        if len(self.audio_samples) < 0:\n'
        '            raise RuntimeError("Audio samples are empty, assuming load failed")\n',
        '        if len(self.audio_samples) < 1:\n'
        '            raise RuntimeError(f"Could not read any audio from {input_audio}")\n',
    ),
    # An offset past the end of the audio raised NameError (duration) instead of this message
    (
        '            raise RuntimeError(f"Audio offset set at {offset}s but input audio is only {duration}s long")\n',
        '            raise RuntimeError(f"Audio offset set at {offset}s but input audio is only {self.duration:.1f}s long")\n',
    ),
    # With offset 0, the band-maxima scan's last time step is the very end of a track whose
    # length is a whole number of frames (e.g. 8 s at 12 fps), and filtering the empty
    # window there crashed with "cannot reshape array of size 0"
    (
        '            sample_offset = int(t * SAMPLERATE)\n'
        '            cur_maxima = bp_filtered(self.audio_samples[sample_offset:sample_offset + self.window_size], filters)\n',
        '            sample_offset = int(t * SAMPLERATE)\n'
        '            if sample_offset >= len(self.audio_samples):\n'
        '                break  # the end of the track: no samples left\n'
        '            cur_maxima = bp_filtered(self.audio_samples[sample_offset:sample_offset + self.window_size], filters)\n',
    ),
]

# ── pytti-core patches: Transforms.py ─────────────────────────────────────────

PYTTI_TRANSFORMS = SITE_PACKAGES / "pytti" / "Transforms.py"

PYTTI_TRANSFORMS_PATCHES = [
    # An audio variable used bare in a 2D camera move (zoom_x_2d: 'fLo*20') is a numpy
    # float64, which made the 2D move's matrix float64 and the render stop with "expected
    # scalar type Float but found Double". The matrix now has the image's type.
    (
        '                [zx * math.sin(theta), zy * math.cos(theta), ty],\n'
        '            ]\n'
        '        )\n'
        '        .unsqueeze(0)\n'
        '        .to(device)\n'
        '    )\n',
        '                [zx * math.sin(theta), zy * math.cos(theta), ty],\n'
        '            ]\n'
        '        )\n'
        '        .unsqueeze(0)\n'
        '        .to(device, tensor.dtype)\n'
        '    )\n',
    ),
]

# ── pytti-core patches: image_models/vqgan.py ─────────────────────────────────

PYTTI_VQGAN = SITE_PACKAGES / "pytti" / "image_models" / "vqgan.py"

# The download as the previous version of this script patched it, checking only the
# size; installs patched with it are upgraded in place
_VQGAN_DOWNLOAD_V1 = (
    '        part = f"{dest}.part"\n'
    '        try:\n'
    '            with open(part, "wb") as output, tqdm(total=file_size) as loop:\n'
    '                while True:\n'
    '                    buffer = source.read(8192)\n'
    '                    if not buffer:\n'
    '                        break\n'
    '\n'
    '                    output.write(buffer)\n'
    '                    loop.update(len(buffer))\n'
    '\n'
    '            complete = os.path.getsize(part) == file_size\n'
    '            if complete:\n'
    '                os.replace(part, dest)\n'
    '        finally:\n'
    '            if os.path.exists(part):\n'
    '                os.remove(part)\n'
    '        return complete\n'
    '\n'
    '\n'
    'def _checkpoint_damaged(path):\n'
    '    """True if a checkpoint is cut off, corrupted or isn\'t a checkpoint at all (e.g. an\n'
    '    error page), rather than a whole file that failed to load for another reason"""\n'
    '    try:\n'
    '        with open(path, "rb") as f:\n'
    '            head = f.read(4)\n'
    '        if head == b"PK\\x03\\x04":\n'
    '            # zip format: a cut-off file has lost the central directory at its end\n'
    '            zipfile.ZipFile(path).close()\n'
    '            return False\n'
    '    except OSError:\n'
    '        return False  # can\'t tell\n'
    '    except Exception:\n'
    '        # zipfile can\'t read the central directory. Besides BadZipFile, a corrupted one\n'
    '        # can raise e.g. UnicodeDecodeError or NotImplementedError.\n'
    '        return True\n'
    '    # the legacy format starts with a pickle header\n'
    '    return not head.startswith(b"\\x80")\n'
)

PYTTI_VQGAN_PATCHES = [
    # hashlib and urllib.parse for the download check below, zipfile for _checkpoint_damaged.
    # The second old text is the imports as the previous version of this script patched them.
    (
        (
            'from omegaconf import OmegaConf\n'
            'import urllib.request\n'
            'from tqdm import tqdm\n',
            'from omegaconf import OmegaConf\n'
            'import urllib.request\n'
            'import zipfile\n'
            'from tqdm import tqdm\n',
        ),
        'from omegaconf import OmegaConf\n'
        'import hashlib\n'
        'import urllib.parse\n'
        'import urllib.request\n'
        'import zipfile\n'
        'from tqdm import tqdm\n',
    ),
    # Models were downloaded straight to their final path, and only a missing file is
    # downloaded again, so an interrupted download left a cut-off model that every later
    # VQGAN render failed on. Download to a temp file and move it into place only when it
    # has the full size and, for the files model_mirror.py lists, the mirror's SHA-256 (the
    # original sources serve the same files). Loading a checkpoint unpickles it, which can
    # run code, so a file that was changed on the way is deleted with an error instead.
    (
        (
            '        with open(dest, "wb") as output, tqdm(total=file_size) as loop:\n'
            '            while True:\n'
            '                buffer = source.read(8192)\n'
            '                if not buffer:\n'
            '                    break\n'
            '\n'
            '                output.write(buffer)\n'
            '                loop.update(len(buffer))\n'
            '\n'
            '        return os.path.getsize(dest) == file_size\n',
            _VQGAN_DOWNLOAD_V1,
        ),
        '        part = f"{dest}.part"\n'
        '        digest = hashlib.sha256()\n'
        '        try:\n'
        '            with open(part, "wb") as output, tqdm(total=file_size) as loop:\n'
        '                while True:\n'
        '                    buffer = source.read(8192)\n'
        '                    if not buffer:\n'
        '                        break\n'
        '\n'
        '                    output.write(buffer)\n'
        '                    digest.update(buffer)\n'
        '                    loop.update(len(buffer))\n'
        '\n'
        '            complete = os.path.getsize(part) == file_size\n'
        '            expected = _mirror_sha256(dest)\n'
        '            if complete and expected and digest.hexdigest() != expected:\n'
        '                host = urllib.parse.urlsplit(url).hostname\n'
        '                raise RuntimeError(\n'
        '                    f"The download of {os.path.basename(dest)} from {host} doesn\'t match its "\n'
        '                    "checksum. It was deleted, so the next render downloads it again. If this "\n'
        '                    "keeps happening, try another network, or try later, when the model "\n'
        '                    "mirror on huggingface.co can be reached."\n'
        '                )\n'
        '            if complete:\n'
        '                os.replace(part, dest)\n'
        '        finally:\n'
        '            if os.path.exists(part):\n'
        '                os.remove(part)\n'
        '        return complete\n'
        '\n'
        '\n'
        'def _mirror_sha256(dest):\n'
        '    """The SHA-256 that PyTTI Portable\'s model mirror lists for a VQGAN file, which pytti\n'
        '    saves as <model>.yaml or <model>.ckpt, or None if it lists none"""\n'
        '    try:\n'
        '        from pytti.model_mirror import VQGAN_MODELS\n'
        '    except ImportError:\n'
        '        return None\n'
        '    model, ext = os.path.splitext(os.path.basename(dest))\n'
        '    if model not in VQGAN_MODELS or ext not in (".yaml", ".ckpt"):\n'
        '        return None\n'
        '    config, checkpoint = VQGAN_MODELS[model]\n'
        '    return (config if ext == ".yaml" else checkpoint)[1]\n'
        '\n'
        '\n'
        'def _checkpoint_damaged(path):\n'
        '    """True if a checkpoint is cut off, corrupted or isn\'t a checkpoint at all (e.g. an\n'
        '    error page), rather than a whole file that failed to load for another reason"""\n'
        '    try:\n'
        '        with open(path, "rb") as f:\n'
        '            head = f.read(4)\n'
        '        if head == b"PK\\x03\\x04":\n'
        '            # zip format: a cut-off file has lost the central directory at its end\n'
        '            zipfile.ZipFile(path).close()\n'
        '            return False\n'
        '    except OSError:\n'
        '        return False  # can\'t tell\n'
        '    except Exception:\n'
        '        # zipfile can\'t read the central directory. Besides BadZipFile, a corrupted one\n'
        '        # can raise e.g. UnicodeDecodeError or NotImplementedError.\n'
        '        return True\n'
        '    # the legacy format starts with a pickle header\n'
        '    return not head.startswith(b"\\x80")\n',
    ),
    # A model cut off before the patch above (or damaged on disk) fails to load on every
    # VQGAN render, with a torch error that doesn't name the file. Delete it so the next
    # render downloads it again; other load errors (e.g. torch refusing a whole file) are
    # left as they are.
    (
        '        VQGAN_MODEL, VQGAN_IS_GUMBEL = load_vqgan_model(vqgan_config, vqgan_checkpoint)\n'
        '        with vram_usage_mode("VQGAN"):\n',
        '        try:\n'
        '            VQGAN_MODEL, VQGAN_IS_GUMBEL = load_vqgan_model(vqgan_config, vqgan_checkpoint)\n'
        '        except Exception as e:\n'
        '            if not _checkpoint_damaged(vqgan_checkpoint):\n'
        '                raise\n'
        '            try:\n'
        '                os.remove(vqgan_checkpoint)\n'
        '                fix = "It was deleted, so the next render downloads it again."\n'
        '            except OSError:\n'
        '                fix = "Delete it, and the next render downloads it again."\n'
        '            raise RuntimeError(\n'
        '                f"The VQGAN model file {vqgan_checkpoint} is incomplete or damaged. {fix}"\n'
        '            ) from e\n'
        '        with vram_usage_mode("VQGAN"):\n',
    ),
    # pytti deletes the training loss right after loading. Building it from the imagenet and
    # wikiart configs (VQLPIPSWithDiscriminator) downloaded VGG16 and LPIPS weights just for
    # that; DummyLoss builds nothing, and init_from_ckpt skips the unused loss.* weights.
    (
        '    config = OmegaConf.load(config_path)\n'
        '    if config.model.target == "taming.models.vqgan.VQModel":\n',
        '    config = OmegaConf.load(config_path)\n'
        '    if "lossconfig" in config.model.params:\n'
        '        config.model.params.lossconfig = {"target": "taming.modules.losses.DummyLoss"}\n'
        '    if config.model.target == "taming.models.vqgan.VQModel":\n',
    ),
    # wikiart's host (eaidata.bmk.sh) is gone; pixray's GitHub release has the same files
    (
        '        "http://eaidata.bmk.sh/data/Wikiart_16384/wikiart_f16_16384_8145600.yaml"\n',
        '        "https://github.com/pixray/pixray/releases/download/v1.7.1/vqgan_wikiart_16384.yaml"\n',
    ),
    (
        '        "http://eaidata.bmk.sh/data/Wikiart_16384/wikiart_f16_16384_8145600.ckpt"\n',
        '        "https://github.com/pixray/pixray/releases/download/v1.7.1/vqgan_wikiart_16384.ckpt"\n',
    ),
    # coco's files over HTTPS. batbot.ai redirected the plain HTTP request there, but only
    # after that first request had gone out unencrypted.
    (
        '    "coco": ["http://batbot.ai/models/VQGAN/coco_first_stage.yaml"],\n',
        '    "coco": ["https://batbot.ai/models/VQGAN/coco_first_stage.yaml"],\n',
    ),
    (
        '    "coco": ["http://batbot.ai/models/VQGAN/coco_first_stage.ckpt"],\n',
        '    "coco": ["https://batbot.ai/models/VQGAN/coco_first_stage.ckpt"],\n',
    ),
]

# ── AdaBins patches: models/unet_adaptive_bins.py ───────────────────────────

ADABINS_UNET = SITE_PACKAGES / "adabins" / "models" / "unet_adaptive_bins.py"

ADABINS_UNET_PATCHES = [
    # With no branch named, torch.hub asked GitHub for the repo's default branch on every
    # 3D render and failed on any answer but a 404 or no network, even with the code in its
    # cache (model_mirror.py puts it there). Naming the branch uses the cached copy.
    (
        "        basemodel = torch.hub.load('rwightman/gen-efficientnet-pytorch', basemodel_name, pretrained=True)",
        "        basemodel = torch.hub.load('rwightman/gen-efficientnet-pytorch:master', basemodel_name, pretrained=True)",
    ),
]

# ── pytti-core patches: model folders ──────────────────────────────────────
# Models load from the folders model_mirror.py picks: the pytti folder's cache/models, which
# the UI passes to renders, or the user's .cache folder for a model earlier versions
# downloaded there. VQGAN's folder is patched in workhorse.py.

PYTTI_PERCEPTOR = SITE_PACKAGES / "pytti" / "Perceptor" / "__init__.py"

PYTTI_PERCEPTOR_PATCHES = [
    (
        '        CLIP_PERCEPTORS = [\n'
        '            clip.load(model, jit=False)[0]\n',
        '        from pytti.model_mirror import clip_folder\n'
        '\n'
        '        CLIP_PERCEPTORS = [\n'
        '            clip.load(model, jit=False, download_root=clip_folder(model))[0]\n',
    ),
]

# DepthLossClass.py's speed patch is further down
PYTTI_DEPTHLOSS_FOLDER_PATCHES = [
    # AdaBins builds on an EfficientNet that it loads through torch.hub
    (
        '            infer_helper = InferenceHelper(dataset="nyu", device=device)\n',
        '            from pytti.model_mirror import adabins_folder, hub_folder\n'
        '\n'
        '            torch.hub.set_dir(hub_folder())\n'
        '            infer_helper = InferenceHelper(\n'
        '                pretrained_path_base=str(adabins_folder()), dataset="nyu", device=device\n'
        '            )\n',
    ),
]

# ── Speed patches: pytti-core ───────────────────────────────────────────────
# None of these change what a render computes: the same values (or, for the palette
# gradient, the same sums in a different order), with fewer waits between CPU and GPU.

PYTTI_PIXEL = SITE_PACKAGES / "pytti" / "image_models" / "pixel.py"

PYTTI_PIXEL_PATCHES = [
    # Limited Palette looks up each pixel's colors with pallet[index]. That indexing's
    # backward (index_put with accumulate) adds the ~10^5 pixels sharing each palette row one
    # after another, and took most of a render step's GPU time. PalletGather keeps the
    # forward and sums the gradient per row with a one-hot matmul.
    (
        '    return floors, ceils, rounds, fracs\n'
        '\n'
        '\n'
        'class PalletLoss(nn.Module):\n',
        '    return floors, ceils, rounds, fracs\n'
        '\n'
        '\n'
        'class PalletGather(torch.autograd.Function):\n'
        '    """pallet[index], with the gradient summed per palette row by a one-hot matmul."""\n'
        '\n'
        '    @staticmethod\n'
        '    def forward(ctx, pallet, index):\n'
        '        ctx.save_for_backward(index)\n'
        '        ctx.pallet_shape = pallet.shape\n'
        '        return pallet[index]\n'
        '\n'
        '    @staticmethod\n'
        '    def backward(ctx, grad):\n'
        '        (index,) = ctx.saved_tensors\n'
        '        onehot = F.one_hot(index.reshape(-1), ctx.pallet_shape[0]).to(grad.dtype)\n'
        '        grad_pallet = onehot.t() @ grad.reshape(onehot.shape[0], -1)\n'
        '        return grad_pallet.view(ctx.pallet_shape), None\n'
        '\n'
        '\n'
        'class PalletLoss(nn.Module):\n',
    ),
    (
        '        colors_disc = pallet[value_rounds]\n',
        '        colors_disc = PalletGather.apply(pallet, value_rounds)\n',
    ),
    (
        '            mode="nearest",\n'
        '        )\n'
        '\n'
        '        colors_cont = (\n'
        '            pallet[value_floors] * (1 - value_fracs) + pallet[value_ceils] * value_fracs\n'
        '        )\n',
        '            mode="nearest",\n'
        '        )\n'
        '\n'
        '        colors_cont = (\n'
        '            PalletGather.apply(pallet, value_floors) * (1 - value_fracs)\n'
        '            + PalletGather.apply(pallet, value_ceils) * value_fracs\n'
        '        )\n',
    ),
    # Sorting each palette by brightness: one gather instead of an indexing op per palette
    (
        '        pallet_indices = color_norms.argsort(dim=0).T\n'
        '        pallet = torch.stack(\n'
        '            [pallet[i][:, j] for j, i in enumerate(pallet_indices)], dim=1\n'
        '        )\n'
        '        return pallet\n',
        '        order = color_norms.argsort(dim=0)\n'
        '        return torch.gather(pallet, 0, order.unsqueeze(-1).expand(-1, -1, pallet.shape[-1]))\n',
    ),
]

PYTTI_SAMPLERS = SITE_PACKAGES / "pytti" / "Perceptor" / "cutouts" / "samplers.py"

PYTTI_SAMPLERS_PATCHES = [
    # Each cutout's offset and size went to the GPU as two blocking copies, each making the
    # CPU wait for all queued GPU work; now one non-blocking copy each per call. The random
    # draws and the values are unchanged.
    (
        '        offsets.append(\n'
        '            torch.as_tensor([[offsetx / side_x, offsety / side_y]]).to(device)\n'
        '        )\n'
        '        sizes.append(torch.as_tensor([[size / side_x, size / side_y]]).to(device))\n'
        '    cutouts = augs(torch.cat(cutouts))\n'
        '    offsets = torch.cat(offsets)\n'
        '    sizes = torch.cat(sizes)\n',
        '        offsets.append([offsetx / side_x, offsety / side_y])\n'
        '        sizes.append([size / side_x, size / side_y])\n'
        '    cutouts = augs(torch.cat(cutouts))\n'
        '    offsets = torch.as_tensor(offsets).to(device, non_blocking=True)\n'
        '    sizes = torch.as_tensor(sizes).to(device, non_blocking=True)\n',
    ),
]

PYTTI_EMBEDDER = SITE_PACKAGES / "pytti" / "Perceptor" / "Embedder.py"

PYTTI_EMBEDDER_PATCHES = [
    # CUDA graphs of the CLIP image encoders: each replays an encoder's forward and backward
    # kernels with one launch instead of thousands. Only on GPUs that report 20 GiB or more
    # (24 GB cards and up; cards sold as 20 GB report a little less), since a graph keeps its
    # own memory; a shape whose capture fails runs as before.
    (
        '}\n'
        '\n'
        '\n'
        'class HDMultiClipEmbedder(nn.Module):\n',
        '}\n'
        '\n'
        '# (perceptor, input shape, strides, dtype) -> graphed CLIP image encoder, or None\n'
        '_CLIP_GRAPHS = {}\n'
        '\n'
        '\n'
        'def _encode_image(perceptor, clip_in):\n'
        '    from clip.model import CLIP\n'
        '\n'
        '    if (\n'
        '        not isinstance(perceptor, CLIP)\n'
        '        or not clip_in.is_cuda\n'
        '        or not clip_in.requires_grad\n'
        '        or not torch.is_grad_enabled()\n'
        '        or torch.cuda.get_device_properties(clip_in.device).total_memory < 20 * 2**30\n'
        '    ):\n'
        '        return perceptor.encode_image(clip_in)\n'
        '    x = clip_in.type(perceptor.dtype)\n'
        '    key = (id(perceptor), tuple(x.shape), x.stride(), x.dtype)\n'
        '    if key not in _CLIP_GRAPHS:\n'
        '        visual = perceptor.visual\n'
        '        try:\n'
        '            # the random sample used for capture leaves the render\'s random draws as they were\n'
        '            with torch.random.fork_rng(devices=[x.device]):\n'
        '                sample = torch.empty_like(x).normal_().requires_grad_(True)\n'
        '                _CLIP_GRAPHS[key] = torch.cuda.make_graphed_callables(lambda t: visual(t), (sample,))\n'
        '        except Exception as e:\n'
        '            from loguru import logger\n'
        '\n'
        '            logger.warning(f"CLIP runs without CUDA graphs: {e}")\n'
        '            _CLIP_GRAPHS[key] = None\n'
        '    graphed = _CLIP_GRAPHS[key]\n'
        '    return graphed(x) if graphed is not None else perceptor.encode_image(clip_in)\n'
        '\n'
        '\n'
        'class HDMultiClipEmbedder(nn.Module):\n',
    ),
    (
        '            image_embeds.append(perceptor.encode_image(clip_in).float().unsqueeze(0))\n',
        '            image_embeds.append(_encode_image(perceptor, clip_in).float().unsqueeze(0))\n',
    ),
]

PYTTI_BASELOSS = SITE_PACKAGES / "pytti" / "LossAug" / "BaseLossClass.py"

PYTTI_BASELOSS_PATCHES = [
    # The stabilization losses' weights and stops go to the GPU with non-blocking copies
    (
        '        weight = torch.as_tensor(parametric_eval(self.weight), device=device)\n'
        '        stop = torch.as_tensor(parametric_eval(self.stop), device=device)\n',
        '        weight = torch.as_tensor(parametric_eval(self.weight)).to(device, non_blocking=True)\n'
        '        stop = torch.as_tensor(parametric_eval(self.stop)).to(device, non_blocking=True)\n',
    ),
]

PYTTI_DEPTHLOSS = SITE_PACKAGES / "pytti" / "LossAug" / "DepthLossClass.py"

PYTTI_DEPTHLOSS_PATCHES = [
    # Emptying PyTorch's GPU memory cache around the depth model made the following steps
    # allocate that memory again; it is only kept on GPUs under 12 GB
    (
        '        gc.collect()\n'
        '        torch.cuda.empty_cache()\n'
        '        _, depth_map = infer_helper.predict_pil(depth_input)\n'
        '        gc.collect()\n'
        '        torch.cuda.empty_cache()\n',
        '        low_vram = torch.cuda.is_available() and (\n'
        '            torch.cuda.get_device_properties(torch.cuda.current_device()).total_memory < 12 * 2**30\n'
        '        )\n'
        '        if low_vram:\n'
        '            gc.collect()\n'
        '            torch.cuda.empty_cache()\n'
        '        _, depth_map = infer_helper.predict_pil(depth_input)\n'
        '        if low_vram:\n'
        '            gc.collect()\n'
        '            torch.cuda.empty_cache()\n',
    ),
]

# ── Speed patches: kornia ───────────────────────────────────────────────────
# kornia picks the cutouts an augmentation applies to with a bool mask on the CPU and
# indexes the GPU batch with it: a blocking copy in the forward pass and a sync in the
# backward pass, each making the CPU wait for all queued GPU work. The same positions as a
# GPU index tensor (one non-blocking copy) select the same items in the same order.

KORNIA_AUG_BASE = SITE_PACKAGES / "kornia" / "augmentation" / "base.py"

KORNIA_AUG_BASE_PATCHES = [
    (
        '        else:  # If any tensor needs to be transformed.\n'
        '            output = self.apply_non_transform(in_tensor, params, flags, transform=transform)\n'
        '            applied = self.apply_transform(\n'
        '                in_tensor[to_apply], params, flags, transform=transform if transform is None else transform[to_apply]\n'
        '            )\n'
        '\n'
        '            if is_autocast_enabled():\n'
        '                output = output.type(input.dtype)\n'
        '                applied = applied.type(input.dtype)\n'
        '            output = output.index_put((to_apply,), applied)\n',
        '        else:  # If any tensor needs to be transformed.\n'
        '            # PyTTI Portable: a GPU index tensor instead of the CPU bool mask\n'
        '            if not to_apply.is_cuda:\n'
        '                to_apply = to_apply.nonzero(as_tuple=True)[0].to(in_tensor.device, non_blocking=True)\n'
        '            output = self.apply_non_transform(in_tensor, params, flags, transform=transform)\n'
        '            applied = self.apply_transform(\n'
        '                in_tensor[to_apply], params, flags, transform=transform if transform is None else transform[to_apply]\n'
        '            )\n'
        '\n'
        '            if is_autocast_enabled():\n'
        '                output = output.type(input.dtype)\n'
        '                applied = applied.type(input.dtype)\n'
        '            output = output.index_put((to_apply,), applied)\n',
    ),
]

KORNIA_ERASING = SITE_PACKAGES / "kornia" / "augmentation" / "_2d" / "intensity" / "erasing.py"

KORNIA_ERASING_PATCHES = [
    # RandomErasing drew each cutout's box into a CPU mask in a Python loop and uploaded it,
    # plus a full-size tensor of fill values. The same boxes (bbox_to_mask's (boxes + 1).long()
    # on its 1-pixel padded grid) are drawn on the GPU with comparisons.
    (
        '        _, c, h, w = input.size()\n'
        '        values = params["values"].unsqueeze(-1).unsqueeze(-1).unsqueeze(-1).repeat(1, *input.shape[1:]).to(input)\n'
        '\n'
        '        bboxes = bbox_generator(params["xs"], params["ys"], params["widths"], params["heights"])\n'
        '        mask = bbox_to_mask(bboxes, w, h)  # Returns B, H, W\n'
        '        mask = mask.unsqueeze(1).repeat(1, c, 1, 1).to(input)  # Transform to B, c, H, W\n'
        '        transformed = where(mask == 1.0, values, input)\n'
        '        return transformed\n',
        '        # PyTTI Portable: the boxes bbox_to_mask would draw, drawn on the GPU\n'
        '        import torch\n'
        '        from kornia.geometry.bbox import validate_bbox\n'
        '\n'
        '        _, c, h, w = input.size()\n'
        '        values = params["values"].to(input.device, input.dtype, non_blocking=True)\n'
        '        bboxes = bbox_generator(params["xs"], params["ys"], params["widths"], params["heights"])\n'
        '        validate_bbox(bboxes)\n'
        '        box_i = (bboxes + 1).long()\n'
        '        bounds = torch.stack([box_i[:, 0, 1], box_i[:, 2, 1], box_i[:, 0, 0], box_i[:, 1, 0]], dim=1)\n'
        '        bounds = bounds.to(input.device, non_blocking=True)\n'
        '        rows = torch.arange(1, h + 1, device=input.device)\n'
        '        cols = torch.arange(1, w + 1, device=input.device)\n'
        '        in_rows = (rows >= bounds[:, 0:1]) & (rows <= bounds[:, 1:2])\n'
        '        in_cols = (cols >= bounds[:, 2:3]) & (cols <= bounds[:, 3:4])\n'
        '        mask = in_rows[:, None, :, None] & in_cols[:, None, None, :]\n'
        '        return where(mask, values[:, None, None, None], input)\n',
    ),
]

KORNIA_AUG_2D_BASE = SITE_PACKAGES / "kornia" / "augmentation" / "_2d" / "base.py"

KORNIA_AUG_2D_BASE_PATCHES = [
    (
        '        else:\n'
        '            trans_matrix_A = self.identity_matrix(in_tensor)\n'
        '            trans_matrix_B = self.compute_transformation(in_tensor[to_apply], params=params, flags=flags)\n',
        '        else:\n'
        '            # PyTTI Portable: a GPU index tensor instead of the CPU bool mask\n'
        '            if not to_apply.is_cuda:\n'
        '                to_apply = to_apply.nonzero(as_tuple=True)[0].to(in_tensor.device, non_blocking=True)\n'
        '            trans_matrix_A = self.identity_matrix(in_tensor)\n'
        '            trans_matrix_B = self.compute_transformation(in_tensor[to_apply], params=params, flags=flags)\n',
    ),
]

# ── Files added to pytti-core ───────────────────────────────────────────────

# (source next to this script, destination in pytti-core, label); copied whenever the
# destination is missing or differs, so `git pull` updates them too. The model folder
# patches import model_mirror.py, so a missing source is an error.
ADDED_FILES = [
    (
        pathlib.Path(__file__).parent / "model_mirror.py",
        SITE_PACKAGES / "pytti" / "model_mirror.py",
        "model_mirror.py",
    ),
]

TARGETS = [
    (PYTTI_WORKHORSE, PYTTI_WORKHORSE_PATCHES, "workhorse.py"),
    (PYTTI_IMAGEGUIDE, PYTTI_IMAGEGUIDE_PATCHES, "ImageGuide.py"),
    (PYTTI_UPDATEFUNC, PYTTI_UPDATEFUNC_PATCHES, "update_func.py"),
    (PYTTI_LOSSORCH, PYTTI_LOSSORCH_PATCHES, "LossOrchestratorClass.py"),
    (PYTTI_OPTICALFLOW, PYTTI_OPTICALFLOW_PATCHES, "OpticalFlowLossClass.py"),
    (PYTTI_MSELOSS, PYTTI_IMAGE_PROMPT_PATCHES, "MSELossClass.py"),
    (PYTTI_LATENTLOSS, PYTTI_IMAGE_PROMPT_PATCHES, "LatentLossClass.py"),
    (PYTTI_ROTOSCOPER, PYTTI_ROTOSCOPER_PATCHES, "rotoscoper.py"),
    (PYTTI_PROMPT, PYTTI_PROMPT_PATCHES, "Prompt.py"),
    (PYTTI_AUDIOPARSE, PYTTI_AUDIOPARSE_PATCHES, "AudioParse.py"),
    (PYTTI_TRANSFORMS, PYTTI_TRANSFORMS_PATCHES, "Transforms.py"),
    (PYTTI_VQGAN, PYTTI_VQGAN_PATCHES, "vqgan.py"),
    (ADABINS_UNET, ADABINS_UNET_PATCHES, "unet_adaptive_bins.py"),
    (PYTTI_PERCEPTOR, PYTTI_PERCEPTOR_PATCHES, "Perceptor/__init__.py"),
    (PYTTI_PIXEL, PYTTI_PIXEL_PATCHES, "pixel.py"),
    (PYTTI_SAMPLERS, PYTTI_SAMPLERS_PATCHES, "samplers.py"),
    (PYTTI_EMBEDDER, PYTTI_EMBEDDER_PATCHES, "Embedder.py"),
    (PYTTI_BASELOSS, PYTTI_BASELOSS_PATCHES, "BaseLossClass.py"),
    (PYTTI_DEPTHLOSS, PYTTI_DEPTHLOSS_FOLDER_PATCHES + PYTTI_DEPTHLOSS_PATCHES, "DepthLossClass.py"),
]

# Speed-only patches outside pytti-core: a file that doesn't match is left as it is,
# without holding up the other patches
OPTIONAL_TARGETS = [
    (KORNIA_AUG_BASE, KORNIA_AUG_BASE_PATCHES, "kornia augmentation/base.py"),
    (KORNIA_AUG_2D_BASE, KORNIA_AUG_2D_BASE_PATCHES, "kornia augmentation/_2d/base.py"),
    (KORNIA_ERASING, KORNIA_ERASING_PATCHES, "kornia augmentation/_2d/intensity/erasing.py"),
]

# ── Apply patches ───────────────────────────────────────────────────────────

def plan_patches(target, patches, label):
    """Return (patched text or None if already up to date, problems) without writing anything.

    A patch's old text can be a tuple of alternatives, e.g. the upstream code and the
    code an earlier version of a patch produced. When a patch's new text changes, keep
    the text it replaces as an alternative, or installs patched with it can't be
    upgraded. An old text must not occur in its own new text, or it is applied again on
    every run.
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
    try:
        for target, patches, label in TARGETS:
            text, file_problems = plan_patches(target, patches, label)
            problems += file_problems
            if text is not None:
                planned.append((target, text, label))
        for target, patches, label in OPTIONAL_TARGETS:
            text, file_problems = plan_patches(target, patches, label)
            if file_problems:
                if not quiet:
                    print(f"  Skipped the speed patch for {label}: it doesn't match the expected version.")
            elif text is not None:
                planned.append((target, text, label))
        for source, target, label in ADDED_FILES:
            text = source.read_text(encoding="utf-8")
            try:
                current = target.read_text(encoding="utf-8")
            except (FileNotFoundError, UnicodeDecodeError):
                current = None  # missing, or damaged: write it again
            if current != text:
                planned.append((target, text, label))
    except OSError as e:
        print(f"  ERROR: Could not read {e.filename or target}: {e.strerror or e}")
        return 2

    # Several patches depend on each other across files, so apply all or nothing
    if problems:
        print("  ERROR: pytti-core doesn't match the expected version. No files were changed.")
        for problem in problems:
            print(f"    {problem}")
        return 1

    # Write every file under a temp name first, then swap them all in: a file that can't
    # be written (read-only, or locked by another program) then usually leaves nothing
    # changed, and an interrupted write never leaves a half-written file. Files already
    # swapped in count as patched the next time this runs.
    temps = [target.with_name(target.name + ".tmp") for target, _, _ in planned]
    swapped = 0
    try:
        for (target, text, _), temp in zip(planned, temps):
            if target.exists() and not os.access(target, os.W_OK):
                raise PermissionError(errno.EACCES, "The file is read-only")
            temp.write_text(text, encoding="utf-8")
        for (target, _, label), temp in zip(planned, temps):
            os.replace(temp, target)
            swapped += 1
            print(f"  Patched {label}")
    except OSError as e:
        print(f"  ERROR: Could not write {target}: {e.strerror or e}")
        if not swapped:
            print("  No files were changed.")
        return 2
    finally:
        for temp in temps:
            try:
                temp.unlink()
            except OSError:
                pass  # swapped in, or never written
    if not planned and not quiet:
        print("  All patches already applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
