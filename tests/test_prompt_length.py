"""
The check behind Load, Save and Start Render that each prompt fits in the 77 tokens CLIP
reads (app/presets.py), with CLIP's own tokenizer from the pinned clip wheel.
"""
import ast
import importlib.util

import pytest

import presets

LABELS = {"scenes": "Scenes", "scene_prefix": "Scene Prefix", "scene_suffix": "Scene Suffix"}
WORDS_75 = " ".join(["a"] * 75)  # 75 tokens, 77 with CLIP's start and end markers
WORDS_76 = " ".join(["a"] * 76)
PROSE = ("an extremely detailed and intricate oil painting of a vast ancient forest at dawn, with "
         "golden light streaming through towering moss covered trees, mist rising from a winding "
         "river, deer grazing in a clearing, wildflowers everywhere, and distant snow capped "
         "mountains under a soft pastel sky full of drifting clouds, painted in the style of the "
         "old masters with rich glazes, deep shadows, luminous highlights and a warm golden varnish")  # 82 tokens


@pytest.fixture(scope="module")
def tokenizer(pristine):
    """CLIP's SimpleTokenizer, which clip.tokenize uses; loaded by path, as the UI does."""
    spec = importlib.util.spec_from_file_location("clip_simple_tokenizer", pristine / "clip" / "simple_tokenizer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SimpleTokenizer()


@pytest.fixture(autouse=True)
def clip(tokenizer, monkeypatch):
    monkeypatch.setattr(presets, "_tokenizer", tokenizer)


def long_prompts(scenes="", scene_prefix="", scene_suffix=""):
    values = {"scenes": scenes, "scene_prefix": scene_prefix, "scene_suffix": scene_suffix}
    return presets.long_prompts(values, LABELS)


def test_clip_reads_77_tokens(pristine):
    """clip.tokenize's context_length, which pytti leaves at its default."""
    tree = ast.parse((pristine / "clip" / "clip.py").read_text(encoding="utf-8"))
    tokenize = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "tokenize")
    names = [arg.arg for arg in tokenize.args.args]
    defaults = dict(zip(names[len(names) - len(tokenize.args.defaults):], tokenize.args.defaults))
    assert ast.literal_eval(defaults["context_length"]) == presets._CLIP_CONTEXT == 77


@pytest.mark.parametrize("fields", [
    pytest.param({"scenes": WORDS_75}, id="77 tokens"),
    pytest.param({"scenes": f"{WORDS_75}:{'+'.join(['1'] * 100)}:0.5"}, id="77 tokens and a long weight"),
    pytest.param({"scenes": f"[C:/{'x' * 300}.png]:2"}, id="image prompt"),
    pytest.param({"scenes": "a forest:2_[C:/masks/a:b.png]:0.5"}, id="colon inside a mask"),
    pytest.param({key: presets.load_defaults()[key] for key in LABELS}, id="default.yaml"),
])
def test_prompts_that_fit(fields):
    assert long_prompts(**fields) == []


@pytest.mark.parametrize("fields, tokens, label", [
    pytest.param({"scenes": WORDS_76}, 78, "Scenes", id="78 tokens"),
    pytest.param({"scenes": f"{WORDS_76}:2:0.5"}, 78, "Scenes", id="78 tokens with a weight and stop"),
    pytest.param({"scenes": f"a forest || {PROSE}"}, 82, "Scenes", id="second scene"),
    pytest.param({"scene_prefix": f"{PROSE} |"}, 82, "Scene Prefix", id="Scene Prefix"),
    pytest.param({"scene_suffix": f"| {PROSE}"}, 82, "Scene Suffix", id="Scene Suffix"),
])
def test_prompts_that_dont(fields, tokens, label):
    problems = long_prompts(**fields)
    assert len(problems) == 1, problems
    assert f"in {label} is {tokens} tokens long, and CLIP reads at most 77" in problems[0]


def test_a_prompt_in_several_scenes_is_reported_once():
    assert len(long_prompts(f"{PROSE} || a forest || {PROSE}")) == 1
