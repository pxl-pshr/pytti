# Changelog

What changed in each version of PyTTI Portable, newest first.

## [Unreleased]

### Changed

- Faster renders: speed patches for pytti-core and kornia. Palette lookups and cutout sampling do less work and wait less on the GPU, and on GPUs with 20 GB or more the CLIP image encoders run as CUDA graphs.
- The Gradient Accumulation Steps help text gives the memory used at 1 and 2, and the README has a troubleshooting entry for slow renders.

## [1.1.0-beta] - 2026-10-04

### Added

- RTX 50xx support: PyTorch 2.7.1 with CUDA 12.8, which also rendered 20–30% faster than PyTorch 2.0 in tests on an RTX 4090.
- A system check before installing. `install.bat` checks the GPU, driver, disk space, Git and the Visual C++ runtime before it downloads anything, and says what to fix.
- Models download first from PyTTI Portable's mirror on Hugging Face, [pxlpshr/pytti-models](https://huggingface.co/pxlpshr/pytti-models), each checked against its SHA-256, with the original sources as fallback. The mirror includes the imagenet, wikiart, sflckr and openimages VQGAN models.
- [PROMPTING.md](PROMPTING.md), a reference for the prompt syntax and preset YAML.
- A Progress box with the ETA, and each render's random seed in the log so the render can be repeated.
- Settings are checked before a preset is saved or a render starts: empty number fields, the seed, the learning rate, config names, cutouts against gradient accumulation steps, and frame sizes the 3D depth model can't handle.

### Changed

- `launch.bat` re-applies the pytti-core patches on every start, so updates pulled with git take effect, and says when the installed packages are out of date.
- `install.bat` pins its dependencies, can resume an interrupted install or update an existing one in place, and keeps pip away from the user's own Python packages. pytti-core is pinned to the commit the patches are written for.
- The default 3D camera motion uses the PyTTI 5 notebook values. Pre-animation Steps now defaults to 80, so each frame is saved fully refined, and Backups to 0; Video Source mode raises it as needed.
- Encode Video defaults its FPS to the frame rate the run was rendered for.
- Saving a preset keeps the settings the UI has no field for, such as `input_audio_filters`.
- Removed the Allow Overwrite option, which had no effect: every render already gets its own folder.

### Fixed

- Video Source renders end when the source video runs out, an interrupted conversion no longer leaves a broken cached video behind, and Stop also stops pytti's ffmpeg.
- Windows paths such as `C:\images\ref.png` in direct image prompts and masks, and direction and image masks.
- A render could hang when pytti printed characters outside the Windows code page.
- Starting a render right after stopping one could mix their logs and leave the new render impossible to stop.
- Video encoding with gaps in the frame numbering, `%` in the path, or odd frame sizes (MP4). ProRes 4444 and ProRes HQ no longer overwrite each other.
- The VQGAN Model list offered names pytti rejects.
- The live log no longer jumps back to the bottom while you read it, and the UI stops polling when a render ends.
- The latest-frame preview follows the running render and skips frames that are still being written.
- Tooltips and FAQ text that contradicted pytti, such as `|` versus `||` for scenes and `t` being in seconds.

## 1.0.0-beta - 2026-03-13

First public version: a Gradio web UI for pytti-core, set up by `install.bat` in an embedded Python.

- Text-to-image and animation with the Limited Palette, Unlimited Palette and VQGAN image models, guided by an ensemble of CLIP models.
- 2D and 3D camera motion with AdaBins depth estimation, and Video Source mode.
- Presets saved and loaded as Hydra YAML files, a live log with an ETA, and a preview of the latest frame.

Updates released under the same version through April 2026 added:

- Video encoding to MP4 (H.264), ProRes 4444 and ProRes HQ.
- Breath mode, zero-padded frame names, and a Save Every setting of 0 that matches Steps per Frame.
- A fix for Windows paths in the init image settings.

[Unreleased]: https://github.com/pxl-pshr/pytti/compare/v1.1.0-beta...HEAD
[1.1.0-beta]: https://github.com/pxl-pshr/pytti/releases/tag/v1.1.0-beta
