# Changelog

What changed in each version of PyTTI Portable, newest first.

## [Unreleased]

### Changed

- Faster renders that need less GPU memory: speed patches for pytti-core and kornia. Palette lookups and cutout sampling do less work and wait less on the GPU, and on GPUs with more than 20 GB the CLIP image encoders run as CUDA graphs. With Gradient Accumulation Steps at 2, the default, a render with the default settings needs about 9 GB of GPU memory instead of about 14 GB.
- The Gradient Accumulation Steps help text gives the memory used at 1 and 2, and the README has a troubleshooting entry for slow renders.
- Installing no longer needs Git. pytti-core, AdaBins, GMA, taming-transformers and CLIP install from wheels on PyTTI Portable's Hugging Face mirror, each checked against its SHA-256, instead of from their GitHub repositories. Git is only needed to install with `git clone` and update with `git pull`.

## [1.1.0-beta] - 2026-10-04

### Added

- RTX 50xx support: PyTorch 2.7.1 with CUDA 12.8, which also rendered 20–30% faster than PyTorch 2.0 in tests on an RTX 4090. It needs NVIDIA driver 528.33 or newer (570.65 or newer recommended), which `install.bat` checks before it changes anything.
- A system check before installing or updating. `install.bat` checks Windows, the GPU and its driver, RAM, disk space, the install folder, Git and the Visual C++ runtime before it downloads anything, and says what to fix.
- Models download first from PyTTI Portable's mirror on Hugging Face, [pxlpshr/pytti-models](https://huggingface.co/pxlpshr/pytti-models), each checked against its SHA-256, with the original sources as fallback. The mirror has all nine CLIP models, the depth model and all five VQGAN models.
- [PROMPTING.md](PROMPTING.md), a reference for the prompt syntax and preset YAML.
- Each render's seed is shown at the top of its log, so the render can be run again with the same seed. The result is similar, not identical.
- Settings are checked before a preset is saved or a render starts, among them empty fields, the seed, the learning rate, config and File Namespace names, that a CLIP model is ticked, cutouts against gradient accumulation steps, and frame sizes the 3D depth model can't handle. Start Render also reports input files that don't exist before any model loads.
- Loading a preset reports YAML mistakes by line and column, and settings pytti doesn't read along with the closest real setting.
- While a render runs, Windows doesn't go to sleep (the display can still turn off), and each render's log is saved as `render.log` in its run folder.

### Changed

- `launch.bat` re-applies the pytti-core patches on every start, so updates pulled with git take effect, and says when the installed packages are out of date.
- `install.bat` pins the packages it installs directly to tested versions and commits, can resume an interrupted install or update an existing one in place, and keeps pip away from the user's own Python packages. pytti-core is pinned to the commit the patches are written for.
- The default 3D camera motion uses the PyTTI 5 notebook values. Pre-animation Steps now defaults to 80, so each frame is saved fully refined, and Backups to 0; Video Source mode raises it as needed.
- The ETA moved from the top of the live log into its own Progress box.
- Encode Video, Video Source mode and audio input use the ffmpeg that comes with the install, so ffmpeg no longer has to be installed separately.
- Encode Video defaults its FPS to the frame rate the run was rendered for, and converts the video to BT.709 and tags it, so players show the colors as rendered.
- Saving a preset keeps the settings the UI has no field for, such as `input_audio_filters`.
- Start Render stops with a message if the preset was edited outside PyTTI since it was loaded, and Save warns once before overwriting such edits.
- Opening `launch.bat` while PyTTI is already running points to the open window instead of starting a second UI.

### Removed

- The Allow Overwrite option, which had no effect: every render already gets its own folder.

### Fixed

- Video Source renders end when the source video runs out, an interrupted conversion no longer leaves a broken cached video behind, and Stop also stops pytti's ffmpeg.
- Video Source clips and video masks are converted again when the clip or the FPS setting changes, instead of reusing a copy made at the old frame rate. Conversion now works for clips with odd frame sizes, clips in read-only folders and clips with audio such as Opus or PCM, and the converted copy goes to `%TEMP%\pytti-video-cache` instead of next to the clip. A video mask shorter than the render holds its last frame.
- Windows paths such as `C:\images\ref.png` in direct image prompts and their masks.
- Direction masks such as `sky:3_u_0.3` and image masks such as `fog:2_[mask.png]` in Scenes applied the prompt to the wrong part of the frame.
- A render could hang when its output contained certain non-ASCII characters, for example a video or audio file whose name or tags use accented or non-Latin letters.
- Starting a render right after stopping one could mix their logs and leave the new render impossible to stop.
- Video encoding with gaps in the frame numbering, `%` in the path, or odd frame sizes (MP4). ProRes 4444 and ProRes HQ no longer overwrite each other. A failed encode keeps the previous video with the same settings, and the time an encode may take grows with the number of frames instead of stopping at 10 minutes.
- The wikiart VQGAN model downloads again: its original server is gone, so it comes from the mirror or pixray's GitHub release. imagenet and wikiart no longer download VGG16 and LPIPS weights, over 500 MB, that rendering doesn't use.
- An interrupted VQGAN model download no longer breaks every later VQGAN render: a damaged model file is deleted with an error that names it, and the next render downloads it again.
- 3D renders and depth stabilization no longer ask GitHub for the depth model's code on every render, which made them fail whenever GitHub answered with an error.
- Audio input: with no Audio Offset, a track whose length is a whole number of frames no longer stops the render as it starts, and an unreadable file or an offset past the end of the track gives a clear error.
- The VQGAN Model list offered names pytti rejects.
- The live log no longer jumps back to the bottom while you read it, and the UI stops polling when a render ends.
- The latest-frame preview follows the running render and skips frames that are still being written.
- Tooltips and FAQ text that contradicted pytti, such as `|` versus `||` for scenes and `t` being in seconds.

### Security

- Gradio's usage analytics are turned off. Earlier versions sent Gradio usage data, including the PC's public IP address, to Gradio's servers each time the UI started. The UI also listens only on this PC (127.0.0.1).

## 1.0.0-beta - 2026-03-13

First public version: a Gradio web UI for pytti-core, set up by `install.bat` in an embedded Python.

- Text-to-image and animation with the Limited Palette, Unlimited Palette and VQGAN image models, guided by an ensemble of CLIP models.
- 2D and 3D camera motion with AdaBins depth estimation, and Video Source mode.
- Presets saved and loaded as Hydra YAML files, a live log with an ETA, and a preview of the latest frame.

Updates released under the same version through April 2026 added:

- Video encoding to MP4 (H.264), ProRes 4444 and ProRes HQ.
- Breath mode, zero-padded frame names, and a Save Every setting of 0 that matches Steps per Frame.
- A fix for Windows paths in the init image settings.
- Fields for Smoothing Weight, Cutout Border, Reset LR Each Frame, Pixel Size, Backups, Re-encode Each Frame, Audio Offset and the RN50x64 CLIP model.

On an install updated with `git pull`, breath mode, zero-padded frame names, Save Every 0 and the init image fix needed a reinstall to take effect, because `launch.bat` only started applying new pytti-core patches in 1.1.0-beta.

[Unreleased]: https://github.com/pxl-pshr/pytti/compare/v1.1.0-beta...HEAD
[1.1.0-beta]: https://github.com/pxl-pshr/pytti/releases/tag/v1.1.0-beta
