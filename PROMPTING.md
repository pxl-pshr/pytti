# Prompt format for PyTTI Portable

This is the reference for writing prompts and presets for this app. Point an AI assistant at this file, or read it yourself, when you want a prompt built.

It describes what the installed engine does. Every rule was checked against the pytti-core commit that `install.bat` pins (`b5070aa`), with the patches from `app/patch_gradio.py` applied, and against `app/ui.py`. PyTTI steers an image with CLIP instead of running a diffusion model, so habits from Stable Diffusion or Midjourney do not carry over: there are no comma lists, no `(word:1.2)` emphasis and no separate negative prompt box.

## If you are an AI assistant

Return one of two things:

- **Three prompt fields** (the default): Scenes, Scene Prefix and Scene Suffix, each in its own code block on a single line, with no quotes around them. The person pastes them into the Prompts section of the UI.
- **A preset file** when the request involves anything beyond the prompt text, such as camera motion, resolution, timing or audio. See [Preset files](#preset-files).

Follow the [grammar](#grammar) and the [hard rules](#hard-rules) exactly. They describe how the parser behaves, so a prompt that breaks them either stops the render or quietly does something other than what it says. Go through the [checklist](#checklist) before you answer.

## Grammar

```
scenes  =  scene || scene || scene
scene   =  prompt | prompt | prompt
prompt  =  text
           text:weight
           text:weight:stop
           text:weight_mask
           text:weight_mask:stop
```

| Part | What it is | If left out |
|------|------------|-------------|
| `text` | A short phrase for CLIP to match | required |
| `weight` | How hard to push. Negative pushes away. A number or an expression | `1` |
| `stop` | Where the prompt stops pushing | never stops |
| `mask` | Limits the prompt to part of the image | whole image |

A single pipe separates prompts that are active together. A double pipe starts the next scene. Spaces around pipes and colons are ignored.

For every scene, the engine glues Scene Prefix, the scene and Scene Suffix into one string with nothing in between, then splits that string on pipes. Each piece becomes its own CLIP target. This is why the prefix has to end with a pipe and the suffix has to start with one.

Scenes run one after another. Each lasts `steps_per_scene` steps, which is `steps_per_scene / (steps_per_frame * frames_per_second)` seconds of video. With the defaults in `app/config/default.yaml` that is 10000 / (80 * 15), about 8.3 seconds. `interpolation_steps` is the length of the crossfade between two scenes.

## Hard rules

1. **No colon inside prompt text.** The first colon always starts the weight. `image credit: nasa` treats "nasa" as the weight and the render stops with an error. Write `image credit nasa`. Ratios like 16:9 and times like 12:30 are worse because they don't stop the render: the number after the colon quietly becomes the weight.
2. **No pipe inside prompt text.** A pipe always separates prompts. There is no grouping or alternation: `(red|blue) car` becomes the two prompts `(red` and `blue) car`.
3. **No square brackets around text.** A prompt that starts with `[` and ends with `]` is opened as an image file or URL.
4. **A negative weight always gets a stop.** Write `text:-1:-.95`, never `text:-1`. Without a stop the engine keeps pushing away forever and draws "anti-text" artifacts.
5. **No underscore inside a weight.** The first underscore after the weight starts a mask, so a weight like `2*my_var` is cut in half. Underscores in the text part are fine.
6. **One short phrase per prompt.** CLIP reads at most 77 tokens per prompt, roughly 50 words, and the render stops with an error above that. Aim for 3 to 12 words and split longer ideas into several prompts.
7. **Scene Prefix ends with a pipe and Scene Suffix starts with one.** Otherwise the last prefix prompt and the first scene prompt fuse into one phrase. The UI adds a missing pipe when it saves, but write them anyway.
8. **No empty parts.** A trailing colon such as `fog:` stops the render.

## Weights and stops

Typical weights:

| Role | Weight |
|------|--------|
| Main subject | 2 to 3 |
| Supporting detail | 1 to 1.5 |
| Style and quality keywords | 1 to 2 |
| Things to remove | -1 with stop -.95 |

A stop tells a prompt when it has done enough. For a positive weight the stop is between 0 and 1, and a lower stop pushes further: `birds:1:0.87` adds only a light touch of birds. For a negative weight the stop is between -1 and 0, and `-.95` is the standard value.

A scene works best with 3 to 6 prompts of its own. Put shared style in the prefix and cleanup in the suffix.

## Masks

A mask limits a prompt to part of the image. It comes after the weight, joined by an underscore.

| Kind | Example | What it does |
|------|---------|--------------|
| Semantic | `dragon:3_baby` | Applies the prompt only where CLIP sees the mask text |
| Direction | `sky:3_u_0.3` | Applies the prompt to one side of a cutoff line |
| Image file | `magical:3_[C:\masks\m.png]` | Applies the prompt to the white areas of the image |
| Video file | `sunlight:3_[C:\masks\sky.mp4]` | The same, with a mask that changes from frame to frame. The file must end in lowercase `.mp4` |

File masks always need the square brackets. Without them the path is read as semantic mask text. Put a minus before the path, `[-C:\masks\m.png]`, to apply the prompt to the black areas instead. A mask video that ends before the render does holds its last frame.

A direction mask is a letter and a cutoff between 0 and 1, measured from the top or the left of the frame:

| Mask | Covers |
|------|--------|
| `_u_0.3` | The top 30% |
| `_d_0.7` | Everything below the 70% line, so the bottom 30% |
| `_l_0.4` | The left 40% |
| `_r_0.6` | Everything right of the 60% line, so the right 40% |

CLIP looks at the image through square crops of varying size, and a mask goes by the center of each crop. Edges are therefore soft, and a cutoff close to 0 or 1 catches few crops or none, more so with a low `cut_pow`. Cutoffs between 0.3 and 0.7 are safe.

A semantic mask takes an optional cutoff from 0 to 1 as a third part, `dragon:3_baby_0.5`. Lower is stricter. Leave it off unless the mask is catching too much.

Direction and image masks rely on a fix that `launch.bat` applies to pytti-core. On an unpatched pytti-core they cover the wrong regions.

## Images

**An image as a prompt inside Scenes.** Wrap a path or URL in square brackets. CLIP reads what the image shows and uses it like a text prompt. Colons inside the brackets are fine.

```text
[C:\refs\coral.png]:2 | fractal clouds | hole in the sky
```

**The Direct Image Prompts field** (`direct_image_prompts`) is a separate field with pixel-level targets. It takes `path:weight`, or `path:weight_maskpath` with a mask, and several entries separated by pipes. No square brackets here. A minus before the mask path inverts it, and a video mask must end in lowercase `.mp4`.

**Init image.** `init_image` is a path. `direct_init_weight` keeps the pixels close to it and `semantic_init_weight` keeps the meaning close to it.

Paths can be absolute (`C:\images\ref.png`) or URLs. A path relative to the pytti folder works only in the fields that hold a path (Init Image, the image part of Direct Image Prompts, Video Path, Target Palette and Input Audio), because the UI turns those into absolute paths. Image prompts and file masks inside Scenes, and mask paths in Direct Image Prompts, need an absolute path or a URL: the engine runs from the render's output folder, where a relative path is not found.

## Weights that change over time

A weight or stop can be any Python expression. `t` is the time in seconds since the animation started, `(step - pre_animation_steps) / (steps_per_frame * frames_per_second)`, so it is negative during the pre-animation steps. The functions of Python's `math` module are available without a prefix (`sin`, `cos`, `pi`, `sqrt`, `radians` and so on), along with `abs`, `min`, `max`, `pow` and `round`.

```text
dawn light over the hills:2 if t < 4 else 0 | harsh midday sun:2 if 4 <= t < 8 else 0 | purple dusk:2 if t >= 8 else 0
```

```text
rolling fog:min(2, max(0, t/5)) | pine forest:2
```

## Audio-reactive weights

Audio variables come from bandpass filters. The filters are not editable in the UI, so they go in the preset file as `input_audio_filters` (see the last example). Each filter's `variable_name` becomes a value from 0 to 1 that follows the loudness of that band.

- Name the variables without underscores (`fLo`, `fHi`), because of hard rule 5.
- Set `pre_animation_steps: 0` when a prompt weight uses an audio variable. The variables do not exist until the first animation frame, and a weight that refers to one before then stops the render.
- Motion expressions can use the same variables and do not need that setting.

## Preset files

A preset is a YAML file in `app/config/conf/`. It holds only the settings you want to change. Everything else comes from `app/config/default.yaml`, which lists every setting, and the FAQ tab in the UI explains each one.

To use a preset, save it as `app/config/conf/<name>.yaml`, press the refresh button next to Load Config in the Run tab, load it and press Start Render. The file name can use letters, numbers, spaces, `-`, `_` and `.`, and must start with a letter or number.

The first line must be `# @package _global_`.

### Quote every string

Put single quotes around every prompt field, every expression and every choice value. Unquoted values break in ways that are easy to miss:

| Unquoted value | What YAML does with it |
|----------------|------------------------|
| A prompt containing ` #pixelart` | Drops everything from the `#` on, as a comment |
| A suffix that starts with a pipe | Parse error |
| A weight with a space after the colon, `flowers: 2` | Parse error |
| `rotate_3d: [cos(radians(1)), 0, 0, 0]` | Turns it into a list, and the motion fails |
| `animation_mode: off` | Turns it into `false` |

Single quotes keep Windows backslashes as they are. To put an apostrophe inside a single-quoted value, double it: `'the artist''s studio'`.

### Settings with fixed choices

| Setting | Allowed values |
|---------|----------------|
| `image_model` | `Limited Palette`, `Unlimited Palette`, `VQGAN` |
| `vqgan_model` | `imagenet`, `coco`, `wikiart`, `sflckr`, `openimages` |
| `animation_mode` | `off`, `2D`, `3D`, `Video Source` |
| `border_mode` | `clamp`, `mirror`, `wrap`, `black`, `smear` |
| `sampling_mode` | `nearest`, `bilinear`, `bicubic` |
| `infill_mode` | `mirror`, `wrap`, `black`, `smear` |

Constraints the engine or the UI enforces:

- `cutouts` must be divisible by `gradient_accumulation_steps`.
- `steps_per_scene` must be at least `interpolation_steps`.
- Keep `pre_animation_steps` a multiple of `steps_per_frame`.
- 3D mode needs an image of at least about 384x384.
- Use `pixel_size: 1` with VQGAN.
- `seed` is a whole number. Leave it out for a random seed.

### Motion expressions

The motion settings are strings holding Python expressions, evaluated once per frame with the same `t` and functions as prompt weights.

| Setting | Meaning |
|---------|---------|
| `translate_x`, `translate_y` | Camera shift per frame, in pixels |
| `translate_z_3d` | Forward movement per frame (3D). Positive moves into the scene |
| `rotate_3d` | Rotation per frame (3D) as a quaternion `[w, x, y, z]`. `[1, 0, 0, 0]` is no rotation |
| `rotate_2d` | Rotation per frame in degrees (2D) |
| `zoom_x_2d`, `zoom_y_2d` | Zoom per frame (2D). `0` is no zoom |

To turn `a` degrees per frame around an axis `x, y, z`, use `[cos(radians(a/2)), x*sin(radians(a/2)), y*sin(radians(a/2)), z*sin(radians(a/2))]`. Axis `1, 0, 0` looks up or down, `0, 1, 0` looks left or right and `0, 0, 1` rolls.

In 3D, `lock_camera` (on by default) subtracts the average movement from every frame so the view doesn't drift. That cancels `translate_x`, `translate_y` and looking up, down, left or right, leaving only the parallax between near and far objects. Set `lock_camera: false` to pan or turn. Rolls and `translate_z_3d` are not affected.

3D moves shrink with depth, so the same numbers do much less to distant scenery. At the default planes (`near_plane: 2000`, `far_plane: 12500`), a 1 degree roll per frame turns the nearest objects about 0.2 degrees and the farthest about 0.035 degrees, and `translate_z_3d: 27` zooms the nearest objects about 0.3% per frame and the farthest almost not at all. Raise the values, or lower `near_plane` and `far_plane`, to get more movement.

## What to put in the text

CLIP learned from captioned images on the web, so write the way images are captioned.

- **Name the medium.** "a photograph of", "oil on canvas", "watercolor", "isometric pixelart", "concept art".
- **Say it several ways, as separate prompts.** A queen, a princess and an elegant woman wearing a tiara all pull the same direction and reinforce each other.
- **Keep the prompts in a scene related.** Prompts that share visual elements stack cleanly. Unrelated prompts fight over the same pixels.
- **Quality keywords:** `trending on artstation`, `artstation contest winner`, `Behance HD`, `CGSociety`, `Unreal Engine`, `ZBrush central contest winner`, `National Geographic photo`.
- **Camera and film:** `macro photography`, `tilt shift`, `depth of field`, `bokeh`, `infrared`, `Velvia`, `Provia`, `Kodak Portra`.
- **Light and color:** `volumetric lighting`, `iridescent`, `holographic`, `glowing neon`.
- **Materials:** "made of crystals", "made of glass", "made of liquid metal", "made of vines", "made of mist". These reshape the subject while keeping its form.
- **Hashtags** such as `#pixelart` and `#macro` work as style keywords.
- **Artist and studio names** are strong style keywords. They often bring a signature with them, so pair them with `signature:-1:-.95`.
- **Colors:** name things that have the color instead of the bare color word, and stack synonyms, as in "crimson vermillion sunset fire".
- **Scale:** "seen from a distance", "seen from above", "closeup", "macro".
- **Expect leakage.** Deserts bring cactus, cities bring people, and a single-word prompt often brings the word itself as text. Counter it with a negative prompt.
- **Avoid** `stock photo` (adds watermarks), `low poly` and `pixel perfect`.

Suffixes to copy:

```text
| text:-1:-.95 | watermark:-1:-.95 | signature:-1:-.95
```

```text
| text:-1:-.95 | watermark:-1:-.95 | signature:-1:-.95 | collage:-1:-.95 | comic book:-1:-.95
```

The second one also removes the patchwork look the engine sometimes produces. Add `| faces:-1:-.95 | eyes:-1:-.95` to keep faces out of landscapes.

## Examples

### A still image, as three fields

Scenes:

```text
ancient lighthouse on a basalt cliff:3 | storm waves breaking against black rock:2 | sea spray and mist | beam of light cutting through fog:1.5
```

Scene Prefix:

```text
oil on canvas | dramatic seascape painting |
```

Scene Suffix:

```text
| volumetric lighting | trending on artstation:1.5 | text:-1:-.95 | watermark:-1:-.95 | signature:-1:-.95
```

### A semantic mask

The fireflies prompt only applies where CLIP already sees dark trees.

```text
moonlit forest clearing:3 | dark twisted trees:2 | fireflies glowing:3_dark twisted trees | low mist
```

### Direction masks

The sky prompt covers the top of the frame and the ocean prompt the bottom. The sailboat has no mask and can land anywhere.

```text
sunset sky with orange clouds:3_u_0.45 | calm ocean reflecting the sun:3_d_0.55 | sailboat on the horizon:2
```

### A three-scene 3D animation, as a preset

Each scene lasts 6000 / (80 * 15) = 5 seconds, with a crossfade between scenes. The camera pushes forward while turning slowly, so `lock_camera` is off; with it on, the turn would be cancelled.

```yaml
# @package _global_
scenes: 'bioluminescent jungle temple:3 | glowing vines and roots:2 | fireflies || crystal cavern:3 | giant quartz pillars:2 | underground river reflecting light || alien ocean at golden hour:3 | floating islands:2 | waves made of liquid glass'
scene_prefix: 'cinematic concept art | volumetric lighting | '
scene_suffix: '| Unreal Engine:1.5 | text:-1:-.95 | watermark:-1:-.95 | collage:-1:-.95'
image_model: 'Limited Palette'
animation_mode: '3D'
width: 640
height: 384
steps_per_scene: 6000
steps_per_frame: 80
interpolation_steps: 800
pre_animation_steps: 160
frames_per_second: 15
translate_x: '0'
translate_y: '0'
translate_z_3d: '30 + 10*sin(t)'
rotate_3d: '[cos(radians(0.5)), 0, sin(radians(0.5)), 0]'
lock_camera: false
```

### Audio-reactive, as a preset

Set `steps_per_scene` to cover the length of the audio. Here 48000 / (80 * 30) = 20 seconds.

```yaml
# @package _global_
scenes: 'storm clouds over the sea:2 | lightning:4*fHi | deep rumbling darkness:3*fLo'
scene_prefix: 'dramatic landscape photograph | '
scene_suffix: '| text:-1:-.95 | watermark:-1:-.95'
animation_mode: '3D'
pre_animation_steps: 0
steps_per_scene: 48000
steps_per_frame: 80
frames_per_second: 30
input_audio: 'C:\music\track.wav'
input_audio_offset: 0
input_audio_filters:
  - variable_name: fLo
    f_center: 105
    f_width: 65
    order: 5
  - variable_name: fHi
    f_center: 900
    f_width: 600
    order: 5
translate_z_3d: '20 + 60*fLo'
```

## Checklist

- No colon, pipe or surrounding square brackets inside any prompt text.
- Every negative weight has a stop.
- No underscore inside a weight, apart from the one that starts a mask.
- Every prompt is a short phrase.
- Scene Prefix ends with a pipe and Scene Suffix starts with one.
- File masks and image prompts are in square brackets.
- Direction masks use `u`, `d`, `l` or `r` and a cutoff between 0.3 and 0.7.
- In a preset: first line is `# @package _global_`, every string is in single quotes, and choice values come from the table above.
- Audio variables are defined in `input_audio_filters`, have no underscores, and `pre_animation_steps` is 0 if a prompt weight uses them.

## Where this comes from

The syntax follows the [pytti-book scene syntax](https://pytti-tools.github.io/pytti-book/SceneDSL.html), checked against the pytti-core source. The keyword notes are condensed from the [pytti-book Grimoire](https://pytti-tools.github.io/pytti-book/Grimoire.html), kingdomakrillic's CLIP + VQGAN keyword study and tips shared in the VQLIPSE Discord.
