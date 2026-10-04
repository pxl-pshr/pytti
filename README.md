# PyTTI Portable

> Neural image synthesizer — text-to-image and animation powered by CLIP + VQGAN/Limited Palette

PyTTI Portable is a self-contained distributable of [pytti-core](https://github.com/pytti-tools/pytti-core) with a Gradio web UI. Everything is bootstrapped from a single `install.bat` — no system-wide Python required.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![CUDA](https://img.shields.io/badge/CUDA-12.8-green)
![Python](https://img.shields.io/badge/python-3.10-yellow)
[![License: MIT](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)

<p align="center">
  <img src="examples/example-01.png" width="24%" />
  <img src="examples/example-07.png" width="24%" />
  <img src="examples/example-11.png" width="24%" />
  <img src="examples/example-09.png" width="24%" />
</p>

<p align="center">
  <img src="examples/ui.png" width="80%" />
</p>

## Features

- **Gradio web UI** with live preview, config save/load, and render controls
- **[3D animation](https://www.youtube.com/watch?v=W3oDPhUV0Pc)** with camera transforms (translate, rotate, zoom) and depth estimation
- **Multiple image models**: Limited Palette, Unlimited Palette, and VQGAN (imagenet, coco, wikiart, sflckr, openimages)
- **CLIP-guided rendering** with multi-model ensemble (ViT-B/32, ViT-B/16, RN50x4, etc.)
- **Video Source mode** for style transfer onto existing video, with optical flow keeping frames consistent
- **Breath mode** — linear crossfade from init image to CLIP-optimized output over the full render. Frame 1 is your original image; the final frame is fully transformed by CLIP. Creates smooth "emergence" animations showing the AI interpretation gradually taking over (best with little or no camera motion)
- **Video encoding** — built-in ffmpeg encoding (MP4 H.264, ProRes 4444, ProRes HQ) directly from the Output tab
- **Audioreactive** animation support (audio filters are set in the preset YAML)
- **Config system** powered by Hydra — save, load, and share render presets as YAML files

## Requirements

- Windows 10 or 11 (64-bit)
- NVIDIA GPU from the GTX 10xx series through RTX 50xx, with 6 GB or more of video memory recommended
- NVIDIA driver 528.33 or newer (570.65 or newer recommended)
- [Git](https://git-scm.com) installed and on PATH
- [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) (x64)
- About 17 GB of free disk space to install. Afterwards the `python` folder takes about 6.5 GB, and pip's download cache and the models take more (see [Disk space](#disk-space))
- 8 GB or more of RAM recommended

`install.bat` checks all of these before downloading anything and tells you what to fix.

## Quick Start

```
git clone https://github.com/pxl-pshr/pytti.git
cd pytti
```

Or download the ZIP from GitHub and extract all of it. Either way, keep the folder outside OneDrive (for example `C:\pytti`), since OneDrive would try to sync the whole install.

1. Double-click **`install.bat`** (one-time, ~20-60 min depending on your connection)
2. Double-click **`launch.bat`**
3. A browser window opens — start rendering

To update: `git pull` from the pytti folder. `launch.bat` applies any new pytti-core patches automatically. When an update also changes the packages PyTTI needs, `launch.bat` says the installed packages are out of date: run `install.bat` and answer Y to update them in place. pip skips the packages that are already up to date.

Installs made before RTX 50xx support was added run PyTorch 2.0 and keep working. To move one to PyTorch 2.7, which RTX 50xx cards need and which rendered 20-30% faster in tests on an RTX 4090, update it with `install.bat` the same way. That downloads PyTorch again (3.3 GB) and needs NVIDIA driver 528.33 or newer, which `install.bat` checks before it changes anything.

The first render downloads the CLIP and depth models, about 2 GB with the default settings, and keeps them for later renders (see [Disk space](#disk-space)). They come from PyTTI Portable's mirror on Hugging Face, [pxlpshr/pytti-models](https://huggingface.co/pxlpshr/pytti-models), with each file checked against its SHA-256. A model the mirror doesn't have, or can't deliver, is downloaded from its original source instead.

## Disk space

- **The `python` folder** takes about 6.5 GB.
- **pip's download cache** is in `%LOCALAPPDATA%\pip\cache`, with about 3.3 GB for the PyTorch wheel. Updates and reinstalls reuse it. To clear it, run `python\python.exe -m pip cache purge` from the pytti folder. That empties the cache every Python on the PC shares, not only PyTTI's part.
- **Models** are downloaded on first use to `%USERPROFILE%\.cache`:
  - `clip`: CLIP models, about 1.1 GB for the three that are on by default
  - `adabins`: the depth model for 3D mode, about 0.9 GB
  - `torch\hub`: a 120 MB model the depth model builds on
  - `vqgan`: VQGAN models, from 0.3 GB (coco) to 4.3 GB (sflckr) each

Deleting the pytti folder leaves the cache and the models in place. To remove them too, delete those folders. Other programs that use CLIP or PyTorch may keep files in `clip` and `torch\hub` as well.

## Project Structure

```
pytti/
├── install.bat          # One-time installer (downloads Python, PyTorch, deps)
├── launch.bat           # Starts the Gradio UI
├── PROMPTING.md         # Prompt and preset format reference
├── python/              # Embedded Python and all packages (created by install.bat)
├── app/
│   ├── ui.py            # Gradio web UI
│   ├── patch_gradio.py  # pytti-core patches (applied on install and every launch)
│   ├── model_mirror.py  # Fetches models from the Hugging Face mirror (copied into pytti-core)
│   ├── system_check.ps1 # Pre-install check: GPU, driver, disk space, etc.
│   ├── deps_rev.txt     # Revision of install.bat's package list
│   ├── outputs/         # Renders, one folder per run (created on first render)
│   └── config/
│       ├── default.yaml # Default render settings
│       └── conf/        # User-saved presets
└── examples/            # Sample renders
```

## How It Works

PyTTI uses CLIP to guide an image generator (Limited Palette, Unlimited Palette or VQGAN) toward text prompts. In animation mode, each frame is warped via 2D/3D transforms with AdaBins depth estimation, then re-optimized toward the prompt — producing dreamlike, evolving visuals. Video Source mode follows an existing video instead, using GMA optical flow to keep frames consistent.

## Writing Prompts

[PROMPTING.md](PROMPTING.md) is the format reference for prompts and presets: the scene syntax, weights and stops, masks, time-based and audio-reactive weights, preset YAML and worked examples. It is written so you can hand it to an AI assistant and ask for a prompt or a preset that loads on the first try.

## Troubleshooting

- **Out of GPU memory**: lower the width and height, use fewer cutouts or CLIP models, or raise `gradient_accumulation_steps`.
- **3D mode fails with `... to have 128 channels, but got N channels instead`**: the AdaBins depth model, which 3D mode and `depth_stabilization_weight` use, needs `(width * pixel_size) // 32` times `(height * pixel_size) // 32` to be at least 129. With `pixel_size` 1, 512×288 works and 512×256 doesn't. The UI checks this before it starts a render.
- **The install stopped partway**: run `install.bat` again. It offers to resume, or to delete the `python` folder and start over.
- **Starting over**: delete the `python` folder and run `install.bat` again. Your presets and renders in `app` are kept, and so are pip's download cache and the models, which are stored outside the pytti folder (see [Disk space](#disk-space)).

## Resources

- [Demo video](https://www.youtube.com/watch?v=W3oDPhUV0Pc) — pytti in action
- [pytti-book](https://pytti-tools.github.io/pytti-book/intro.html) — documentation, tutorials, and parameter guide
- [pytti-motion-preview](https://github.com/pxl-pshr/pytti-motion-preview) — camera motion preview tool
- [pytti-notebook](https://github.com/pytti-tools/pytti-notebook) — the original Colab notebook this project is based on

## Credits

- [David Marx](https://github.com/dmarx) & [sportsracer48](https://github.com/sportsracer48) — original pytti creators and maintainers
- [Katherine Crowson](https://github.com/crowsonkb) — CLIP-guided generation techniques pytti-core builds on
- [pytti-core](https://github.com/pytti-tools/pytti-core) — the rendering engine
- [CLIP](https://github.com/openai/CLIP) — OpenAI's vision-language model
- [taming-transformers](https://github.com/CompVis/taming-transformers) — VQGAN
- [AdaBins](https://github.com/shariqfarooq123/AdaBins) — monocular depth estimation (3D mode)
- [GMA](https://github.com/zacjiang/GMA) — optical flow for video mode
- [Gradio](https://gradio.app) — web UI framework

## License

MIT — see [LICENSE](LICENSE) for details.
