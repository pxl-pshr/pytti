"""
The settings checks in app/presets.py that decide what Save and Start Render accept, on the
presets in the repo and on presets written here. Presets are loaded through the UI's own
Load Config callback, so each check sees the values the UI's fields would show.
"""
import os
from types import SimpleNamespace

import pytest

import paths
import presets
import ui


@pytest.fixture(scope="module")
def form():
    """The UI's Load Config callback, and the labels of the fields it fills."""
    demo = ui.make_ui()
    load = next(fn for fn in demo.fns.values() if fn.name == "load_existing")
    fields = load.outputs[:len(presets.CONF_FIELDS)]  # the settings come first, in CONF_FIELDS order
    return SimpleNamespace(load_existing=load.fn, labels={key: field.label for key, field in zip(presets.CONF_FIELDS, fields)})


@pytest.fixture
def conf_dir(tmp_path, monkeypatch):
    """An empty config/conf for the presets a test writes."""
    folder = tmp_path / "conf"
    folder.mkdir()
    monkeypatch.setattr(paths, "CONF_DIR", folder)
    return folder


@pytest.fixture
def load(form, monkeypatch):
    """Load a preset as Load Config does: (the values its fields show, its keys that have no field)."""
    monkeypatch.setattr(ui, "_last_preset", None)  # load_existing remembers the preset for page reloads

    def load(name=presets.DEFAULTS_CHOICE):
        preset = {} if name == presets.DEFAULTS_CHOICE else presets.load_conf(name)
        values = dict(zip(presets.CONF_FIELDS, form.load_existing(name)))
        return values, {key: value for key, value in preset.items() if key not in presets.CONF_KEYS}
    return load


@pytest.fixture
def load_preset(conf_dir, load):
    """Save a preset's YAML in config/conf and load it."""
    def load_preset(text):
        (conf_dir / "preset.yaml").write_text(text, encoding="utf-8")
        return load("preset.yaml")
    return load_preset


def render_problems(form, values, extras):
    """What stops Start Render before it renders, gathered as _save_preset gathers it."""
    return (
        presets.conf_problems("preset", values, form.labels)
        + presets.missing_files(values, form.labels, extras)
        + presets.preset_risks(values, extras, form.labels)[0]
    )


AUDIO = """\
input_audio_filters:
  - variable_name: bass
    f_center: 84
    f_width: 50
    order: 5
"""


# ── The presets in the repo ─────────────────────────────────────────────────


@pytest.mark.parametrize("name", [presets.DEFAULTS_CHOICE, "_empty.yaml"])
def test_the_presets_in_the_repo_render(form, load, name):
    """default.yaml, alone and with conf/_empty.yaml, as a render combines them."""
    values, extras = load(name)
    assert render_problems(form, values, extras) == []
    assert presets.preset_risks(values, extras, form.labels) == ([], [])
    assert presets._conf_notes({**presets.build_conf_dict(**values), **extras}) == []


def test_saving_and_loading_keeps_every_setting(load, load_preset):
    values, extras = load_preset(AUDIO)
    assert extras  # input_audio_filters has no field, and is kept
    presets.write_conf("saved.yaml", presets.preset_base("saved", extras), values)
    assert load("saved.yaml") == (values, extras)


def test_every_field_has_a_default():
    assert set(presets.CONF_FIELDS) - set(presets.load_defaults()) == set()


# ── Presets that could run code, and expressions pytti can't evaluate ───────


@pytest.mark.parametrize("preset", [
    pytest.param("", id="default.yaml's 3D camera motion"),
    pytest.param("scenes: 'a forest:sin(t*pi/2) | sky:3_u_0.3 | fog:2_[mask.png]:0.5'\n", id="prompt weights, masks and stops"),
    pytest.param("direct_stabilization_weight: 'sin(t*pi/2)'\nsemantic_stabilization_weight: '0.5*sin(t*pi/2)'\n", id="sin(t*pi/2) weights"),
    pytest.param("rotate_3d: '(lambda a: [cos(a), 0, sin(a), 0])(radians(t))'\n", id="lambda in rotate_3d"),
    pytest.param("rotate_3d: '[cos(radians(x)) for x in [1, 2, 3, 4]]'\n", id="comprehension in rotate_3d"),
    pytest.param("translate_z_3d: 'mu / 10 + R - r'\n", id="depth in a 3D camera move"),
    pytest.param(AUDIO + "translate_z_3d: '10 * bass + bass_prev'\n", id="audio variables"),
    pytest.param("animation_mode: 2D\nrotate_2d: 'max(0, t - 5) if t > 5 else 0'\n", id="2D camera move"),
    pytest.param("animation_mode: off\n", id="YAML's bare off"),
    pytest.param("direct_image_prompts: 'https://example.com/a.png:2_https://example.com/m.png'\n", id="image prompt with a mask"),
])
def test_presets_that_render(form, load_preset, preset):
    values, extras = load_preset(preset)
    assert render_problems(form, values, extras) == []


@pytest.mark.parametrize("preset, problem", [
    pytest.param("hydra:\n  run:\n    dir: C:/Windows\n", "hydra: section", id="hydra section"),
    pytest.param("defaults:\n  - _self_\n  - override hydra/launcher: basic\n", "defaults: list", id="defaults list"),
    pytest.param("scenes: 'a forest ${oc.env:USERNAME}'\n", "uses ${...}", id="${...} in a prompt"),
    pytest.param("translate_x: '${oc.env:PATH}'\n", "uses ${...}", id="${...} in a camera move"),
    pytest.param("translate_x: 'np.sin(t)'\n", "could run code", id="np call"),
    pytest.param("rotate_3d: '__import__(\"os\").system(\"calc\")'\n", "could run code", id="__import__ call"),
    pytest.param("translate_x: '__import__(1)'\n", "uses __import__", id="__import__ name"),
    pytest.param("scenes: 'a forest:1:(lambda: 0).__globals__'\n", "could run code", id="attribute in a stop"),
    pytest.param("semantic_init_weight: '[c for c in ().__class__.__mro__]'\n", "could run code", id="attribute in a comprehension"),
    pytest.param("direct_image_prompts: 'https://example.com/a.png:np.cos(t)'\n", "could run code", id="np call in an image prompt"),
    pytest.param("translate_z_3d: '10 * bass'\n", "uses bass", id="audio variable without its filter"),
    pytest.param("animation_mode: 2D\ntranslate_x: 'mu'\n", "uses mu", id="depth in a 2D camera move"),
    pytest.param("rotate_3d: [cos(radians(1.5)), 0, 0, 0]\n", "put single quotes around the whole expression", id="unquoted list"),
    pytest.param("translate_x: 'sin(t'\n", "isn't a valid expression", id="unclosed bracket"),
])
def test_presets_that_dont_render(form, load_preset, preset, problem):
    values, extras = load_preset(preset)
    problems = render_problems(form, values, extras)
    assert any(problem in p for p in problems), problems


def test_another_models_folder_gets_a_note(form, load_preset):
    values, extras = load_preset("models_parent_dir: D:/models\n")
    problems, notes = presets.preset_risks(values, extras, form.labels)
    assert problems == []
    assert any("models_parent_dir" in note for note in notes)


@pytest.mark.parametrize("text, verdict", [
    ("sin(t*pi/2)", None),
    ("-1700*sin(radians(1.5))", None),
    ("[cos(radians(1.5)), 0, -sin(radians(1.5))/sqrt(2), sin(radians(1.5))/sqrt(2)]", None),
    ("max(0, t - 5) if t > 5 and t < 9 else 0", None),
    ("(lambda a: a * 2)(t)", None),
    ("[x / 2 for x in (1, 2)]", None),
    ("np.sin(t)", "code"),
    ("t.real", "code"),
    ("[1, 2][0]", "code"),
    ("{1: 2}", "code"),
    ("__import__('os').system('calc')", "code"),
    ("__import__('os')", "mistake"),
    ("open(1)", "mistake"),
    ("'1'", "mistake"),
    ("f'{t}'", "mistake"),
    ("sin(", "mistake"),
    ("", "mistake"),
    ("(" * 300 + "1" + ")" * 300, "mistake"),  # nested deeper than Python's parser takes
    ("1+" * 10000 + "1", "mistake"),  # nested deep enough to crash Python 3.10's parser
])
def test_expression_check(text, verdict):
    found = presets._expression_problem(text, presets._EXPRESSION_NAMES)
    assert (found and ("code" if found[0] else "mistake")) == verdict


# ── conf_problems ───────────────────────────────────────────────────────────

# (config name, changes to default.yaml's settings, the problem; {key} stands for the label of
# that setting's field)
CONF_PROBLEMS = [
    ("", {}, "Enter a config name first."),
    ("render.yml", {}, "can't end in .yml or .yaml"),
    ("CON", {}, "Windows reserves that name"),
    ("lpt1.txt", {}, "Windows reserves that name"),
    ("_hidden", {}, "must start with a letter or number"),
    ("a/b", {}, "can use letters, numbers"),
    ("trailing.", {}, "can't end with a space or dot"),
    ("ok", {"file_namespace": "  "}, "{file_namespace} can't be blank."),
    ("ok", {"file_namespace": "nul"}, "Windows reserves that name"),
    ("ok", {"image_model": "Stable Diffusion"}, "{image_model} 'Stable Diffusion' isn't a valid choice."),
    ("ok", {"scenes": " || "}, "Scenes can't be empty"),
    ("ok", {"animation_mode": "Video Source"}, "Set a Video Path for Video Source mode."),
    ("ok", {"animation_mode": "Video Source", "video_path": "clip.mp4", "frame_stride": 0}, "{frame_stride} must be at least 1."),
    ("ok", dict.fromkeys(presets.CLIP_MODELS, False), "Tick at least one CLIP model."),
    ("ok", {"translate_x": " "}, "{translate_x} can't be blank in 3D mode."),
    ("ok", {"seed": "1.5"}, "Seed must be a whole number"),
    ("ok", {"seed": str(2**64)}, "Seed must be between"),
    ("ok", {"learning_rate": "0"}, "Learning Rate must be a number above 0"),
    ("ok", {"learning_rate": "nan"}, "Learning Rate must be a number above 0"),
    ("ok", {"steps_per_frame": 0}, "{steps_per_frame} must be at least 1."),
    ("ok", {"gradient_accumulation_steps": 3}, "must be divisible by {gradient_accumulation_steps} (3)"),
    ("ok", {"width": -1, "height": -1}, "{width} and {height} can't both be -1."),
    ("ok", {"width": -1}, "{width} can be -1 only with an Init Image"),
    ("ok", {"height": 256}, "is 512x256"),  # too small for the depth model in 3D mode
    ("ok", {"animation_mode": "2D", "depth_stabilization_weight": "1", "pixel_size": 1, "height": 256}, "is 512x256"),
    ("ok", {"field_of_view": 180}, "{field_of_view} must be more than 0 and less than 180."),
    ("ok", {"width": None}, "Fill in: {width}."),
]


@pytest.mark.parametrize("name, changes, problem", CONF_PROBLEMS)
def test_conf_problems(form, load, name, changes, problem):
    values, _ = load()
    problems = presets.conf_problems(name, {**values, **changes}, form.labels)
    assert any(problem.format(**form.labels) in p for p in problems), problems


@pytest.mark.parametrize("name, changes", [
    ("My render 2.1", {}),
    ("ok", {"seed": "-42", "learning_rate": "0.02"}),
    ("ok", {"height": 288}),  # 512x288: the smallest 16:9 frame the depth model takes
    ("ok", {"width": -1, "init_image": "https://example.com/init.png"}),
    ("ok", {"animation_mode": "Video Source", "video_path": "clip.mp4", "translate_x": ""}),
    ("ok", {"animation_mode": "off", "depth_stabilization_weight": "1", "height": 256}),  # no depth without a camera move or init image
])
def test_conf_problems_accepts(form, load, name, changes):
    values, _ = load()
    assert presets.conf_problems(name, {**values, **changes}, form.labels) == []


# ── missing_files ───────────────────────────────────────────────────────────


def test_missing_files(form, load, tmp_path):
    values, _ = load()
    labels = form.labels
    found = tmp_path / "found.png"
    found.write_bytes(b"")
    gone = tmp_path / "gone.png"

    def missing(extras=None, **changes):
        return presets.missing_files({**values, **changes}, labels, extras)

    def not_found(path, key):
        return [f"File not found: {path} ({labels[key]})."]

    assert missing() == []
    assert missing(init_image=str(found)) == []
    assert missing(init_image=f'"{found}"') == []  # with the quotes Explorer's Copy as path adds
    assert missing(init_image="https://example.com/init.png") == []
    assert missing(init_image=str(gone)) == not_found(gone, "init_image")
    assert missing(init_image="gone.png") == not_found("gone.png", "init_image")  # relative to the pytti folder
    assert missing(direct_image_prompts=f"{found}:2 | {gone}:1_{found}") == not_found(gone, "direct_image_prompts")
    # Video Path is read only in Video Source mode, Target Palette only with Limited Palette,
    # and Input Audio only with input_audio_filters
    assert missing(video_path=str(gone)) == []
    assert missing(video_path=str(gone), animation_mode="Video Source") == not_found(gone, "video_path")
    assert missing(target_palette=str(gone)) == not_found(gone, "target_palette")
    assert missing(target_palette=str(gone), image_model="VQGAN") == []
    assert missing(input_audio=str(gone)) == []
    assert missing({"input_audio_filters": [{"variable_name": "bass"}]}, input_audio=str(gone)) == not_found(gone, "input_audio")


# ── Presets changed or replaced outside this page ───────────────────────────


def test_not_loaded_here(conf_dir):
    (conf_dir / "mine.yaml").write_text("scenes: a forest\n", encoding="utf-8")
    (conf_dir / "_hidden.yaml").write_text("", encoding="utf-8")
    loaded = ("mine.yaml", presets._conf_mtime("mine.yaml"), None)
    assert presets._not_loaded_here("mine.yaml", None)  # e.g. its name typed in over other settings
    assert presets._not_loaded_here("mine.yaml", ("other.yaml", 1, None))
    assert not presets._not_loaded_here("mine.yaml", loaded)
    assert not presets._not_loaded_here("MINE.yaml", loaded)  # Windows file names ignore case
    assert not presets._not_loaded_here("new.yaml", None)  # nothing to replace
    assert not presets._not_loaded_here("_hidden.yaml", None)  # conf_problems refuses the name instead


def test_changed_on_disk(conf_dir):
    path = conf_dir / "mine.yaml"
    path.write_text("scenes: a forest\n", encoding="utf-8")
    stamp = ("mine.yaml", presets._conf_mtime("mine.yaml"), None)
    assert presets._changed_on_disk("mine.yaml", stamp) is None
    edited = stamp[1] + 10**9
    os.utime(path, ns=(edited, edited))
    assert presets._changed_on_disk("mine.yaml", stamp) == edited
    assert presets._changed_on_disk("other.yaml", stamp) is None


@pytest.mark.parametrize("content, problem", [
    (b"scenes: 'a forest\n", "(line 2, column 1)"),
    (b"- a forest\n", "one setting per line"),
    ("scenes: caf\u00e9\n".encode("cp1252"), "isn't saved as UTF-8"),
])
def test_unreadable_presets(conf_dir, content, problem):
    (conf_dir / "bad.yaml").write_bytes(content)
    with pytest.raises(presets.PresetError) as error:
        presets.load_conf("bad.yaml")
    assert problem in str(error.value)


# ── What Save fixes or explains ─────────────────────────────────────────────


def test_conf_notes(load):
    values, _ = load()
    data = presets.build_conf_dict(**{**values, "animation_mode": "Video Source", "flow_long_term_samples": 2, "backups": 0})
    assert any("Backups raised to 5" in note for note in presets._conf_notes(data))
    assert data["backups"] == 5  # long-term flow reads the frame 2^2 back from the backups

    data = presets.build_conf_dict(**{**values, "pre_animation_steps": 100, "breath_mode": True})
    notes = " ".join(presets._conf_notes(data))
    assert "multiple of Steps per Frame" in notes
    assert "Breath Mode does nothing without an Init Image" in notes

    notes = presets._conf_notes({**presets.build_conf_dict(**values), "scnes": "a forest"})
    assert any("scnes (did you mean scenes?)" in note for note in notes)


def test_references_are_resolved():
    data = {"steps_per_frame": 50, "save_every": "${steps_per_frame}", "seed": "${now:%f}", "a": "${b}", "b": "${a}"}
    resolved = presets._resolve_references(data)
    assert resolved["save_every"] == 50
    assert resolved["seed"] == "${now:%f}"  # a resolver, left for Hydra
    assert resolved["a"] in ("${a}", "${b}")  # a loop ends


# ── Field cleanup ───────────────────────────────────────────────────────────


def test_clean_path(tmp_path):
    image = tmp_path / "an image.png"
    image.write_bytes(b"")
    assert presets._clean_path(f' "{image}" ') == str(image)
    assert presets._clean_path("https://example.com/a.png") == "https://example.com/a.png"
    # pytti opens files from the render's folder, so a relative path is made absolute if found
    assert presets._clean_path("docs/images/ui.png") == str((paths.PORTABLE_ROOT / "docs" / "images" / "ui.png").resolve())
    assert presets._clean_path("nowhere/a.png") == "nowhere/a.png"


def test_split_image_prompts():
    # A colon followed by a slash or backslash is part of a path, not a weight
    assert presets._split_image_prompts(r"C:\img\a.png:2 | https://example.com/b.png | | c.png:1_C:\m.png") == [
        [r"C:\img\a.png", "2"], ["https://example.com/b.png"], ["c.png", r"1_C:\m.png"],
    ]


def test_clean_scenes():
    assert presets._clean_scenes(" a  forest |  fog || \n || night\n sky ") == "a forest | fog || night sky"


@pytest.mark.parametrize("text, saved", [("0", ""), ("0.0", ""), ("", ""), (None, ""), (" 1 ", "1"), ("sin(t)", "sin(t)")])
def test_weight_value(text, saved):
    assert presets._weight_value(text) == saved  # pytti skips a loss only when its weight is blank


@pytest.mark.parametrize("text, saved", [("", presets.RANDOM_SEED), (" 42 ", 42), ("-7", -7)])
def test_seed_value(text, saved):
    assert presets._seed_value(text) == saved
