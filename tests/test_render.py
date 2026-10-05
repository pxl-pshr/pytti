"""
Resume Render's bookkeeping and the summary a render starts with (app/render.py), on run
folders and settings made here. Nothing starts a render.
"""
import io
import textwrap
import zipfile
from types import SimpleNamespace

import pytest

import patch_pytti
import presets
import render

NAMESPACE = "my run.v2"


def make_run(folder, settings=None, backups=(), cut_off=(), log=None):
    """A run folder as pytti leaves it: the settings Hydra saved, backups and render.log.
    Its render has 2 scenes of 100 steps and saves a frame every 10, so 20 frames."""
    run = folder / "run"
    (run / "backup" / NAMESPACE).mkdir(parents=True)
    if settings is not None:
        presets.save_yaml(run / ".hydra" / "config.yaml", {
            "file_namespace": NAMESPACE, "scenes": "a || b", "steps_per_scene": 100,
            "steps_per_frame": 10, "save_every": 0, **settings})
    for frame in backups:
        # torch.save writes a zip file; Stop Render can cut one off
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("archive/data.pkl", b"x" * 100)
        data = buffer.getvalue()
        data = data[:len(data) // 2] if frame in cut_off else data
        (run / "backup" / NAMESPACE / f"{NAMESPACE}_{frame}.bak").write_bytes(data)
    if log is not None:
        (run / "render.log").write_text(log, encoding="utf-8")
    return run


VIDEO_END = "Video source has 9 frames, so the render will end at step 90 of 200\n"


# ── Resume Render ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("backups, cut_off, log, point", [
    pytest.param((4, 5), (), None, (5, 49, 20), id="newest backup"),
    pytest.param((4, 5), (5,), None, (4, 39, 20), id="newest backup cut off"),
    pytest.param((7,), (), "RENDER COMPLETE\nRENDER STOPPED\n", (7, 69, 20), id="resumed after it completed, then stopped"),
    pytest.param((5, 6), (), VIDEO_END + "RENDER STOPPED\n", (6, 59, 9), id="Video Source clip ends early"),
])
def test_where_a_render_resumes(tmp_path, backups, cut_off, log, point):
    """(frame, step, frames in all): frame n is saved before step n * 10 - 1, which the
    render runs again, so it doesn't skip that step."""
    run = make_run(tmp_path, {}, backups, cut_off, log)
    assert render._resume_point(run, render._run_settings(run)) == point
    assert render._resume_offer(run) == f" Resume Render continues it from frame {point[0]}."


@pytest.mark.parametrize("backups, cut_off, log, reason", [
    pytest.param((), (), None, "has no backup to continue from", id="no backups"),
    pytest.param((4, 5), (4, 5), None, "has no backup to continue from", id="every backup cut off"),
    pytest.param((19, 20), (), "RENDER STOPPED\nRENDER COMPLETE\n", "is complete", id="log ends complete"),
    pytest.param((19, 20), (), None, "is complete", id="backup of the last frame"),
    pytest.param((8, 9), (), VIDEO_END + "RENDER STOPPED\n", "is complete", id="last frame of a short Video Source clip"),
])
def test_runs_that_cant_be_resumed(tmp_path, backups, cut_off, log, reason):
    run = make_run(tmp_path, {}, backups, cut_off, log)
    point = render._resume_point(run, render._run_settings(run))
    assert isinstance(point, str) and reason in point
    assert render._resume_offer(run) == ""


def test_resume_deletes_a_cut_off_backup(tmp_path):
    """pytti loads the newest backup, so one that Stop Render cut off is deleted first."""
    run = make_run(tmp_path, {}, (4, 5), cut_off=(5,))
    assert render._resume_point(run, render._run_settings(run), delete_damaged=True) == (4, 39, 20)
    assert [path.name for path in (run / "backup" / NAMESPACE).iterdir()] == [f"{NAMESPACE}_4.bak"]


@pytest.mark.parametrize("settings, log, reason", [
    pytest.param(None, None, "are missing or can't be read", id="no saved settings"),
    pytest.param({}, "RENDER COMPLETE\n", "is complete", id="complete"),
])
def test_resume_render_refuses(tmp_path, settings, log, reason):
    run = make_run(tmp_path, settings, (19, 20), log=log)
    assert reason in render.resume_render(run, {})
    assert not render._running


@pytest.mark.parametrize("first_step, scene, bar, done", [
    (0, 0, 10, 10),
    (0, 1, 10, 310),
    (149, 0, 0, 149),
    (149, 0, 150, 299),
    (149, 1, 0, 300),
    (149, 1, 299, 599),
    (349, 0, 10, 359),
])
def test_progress_of_a_resumed_render(monkeypatch, first_step, scene, bar, done):
    """A resumed render's first progress bar starts partway through a scene; the Progress box
    counts the steps of the whole run (here 2 scenes of 300)."""
    for name, value in {"_render_conf": {"scenes": "a || b", "steps_per_scene": 300}, "_render_end_step": None,
                        "_render_first_step": first_step, "_render_scene": scene, "_render_step": bar}.items():
        monkeypatch.setattr(render, name, value)
    assert render._render_progress() == (600, done)


# ── Where a Video Source render ends ────────────────────────────────────────


def end_from_the_patch(frames, scenes, steps_per_scene, pre, steps_per_frame, stride, save_every):
    """Where the patched workhorse.py ends a Video Source render, run from the patch's own text."""
    new = next(new for _, patches, _ in patch_pytti.TARGETS for _, new in patches if "render will end at step" in new)
    start = new.rindex("\n", 0, new.index("end_step = len(prompts)")) + 1
    end = new.rindex("\n", 0, new.index("for scene in prompts[skip_prompts:]")) + 1
    names = {
        "prompts": [None] * scenes,
        "video_frames": [None] * frames,
        "params": SimpleNamespace(steps_per_scene=steps_per_scene, pre_animation_steps=pre,
                                  steps_per_frame=steps_per_frame, frame_stride=stride, save_every=save_every),
        "logger": SimpleNamespace(info=lambda *args: None),
    }
    exec(textwrap.dedent(new[start:end]), names)
    return names["end_step"]


@pytest.mark.parametrize("pre", [0, 10, 15])
@pytest.mark.parametrize("steps_per_frame, save_every", [(10, 10), (10, 3), (10, 7), (5, 20)])
@pytest.mark.parametrize("stride", [1, 2, 3])
def test_the_summary_ends_a_video_source_render_where_pytti_does(pre, steps_per_frame, save_every, stride):
    for frames in range(1, 14):
        for scenes, steps_per_scene in ((1, 60), (2, 200)):
            expected = end_from_the_patch(frames, scenes, steps_per_scene, pre, steps_per_frame, stride, save_every)
            estimate = min(scenes * steps_per_scene, render._video_end(frames, pre, steps_per_frame, stride, save_every))
            assert estimate == expected, (frames, scenes, steps_per_scene)


# ── The summary a render starts with ────────────────────────────────────────

MEDIA = {
    "clip.mp4": {"duration": 4.5, "size": (640, 360)},
    "beat.wav": {"duration": 8.0},
}
AUDIO = {"animation_mode": "2D", "input_audio": "beat.wav", "input_audio_filters": [{"variable_name": "fLo"}],
         "frames_per_second": 12, "steps_per_frame": 10, "pre_animation_steps": 0, "scenes": "a"}
VIDEO = {"animation_mode": "Video Source", "video_path": "clip.mp4", "frames_per_second": 12,
         "steps_per_frame": 10, "pre_animation_steps": 10, "width": 256, "scenes": "a"}


@pytest.fixture
def preflight(monkeypatch):
    """render.preflight on default.yaml's settings with others over them: (warnings, summary).
    The media are made up, nothing needs downloading, and the disk and the GPU have room."""
    monkeypatch.setattr(render, "_probe", lambda path: MEDIA.get(path))
    monkeypatch.setattr(render, "_downloads", lambda conf: [])
    monkeypatch.setattr(render, "_drive", lambda path: ("C:\\", 10**15))
    monkeypatch.setattr(render, "_largest_gpu_gb", lambda: 31.8)
    return lambda **settings: render.preflight({**presets.load_defaults(), **settings})


def test_frames_and_seconds(preflight):
    warnings, summary = preflight(animation_mode="3D", steps_per_scene=10000, steps_per_frame=80,
                                  save_every=0, frames_per_second=15, scenes="a")
    assert warnings == []
    assert summary[0] == "Output: 125 frames, 8.3 s of video at 15 fps (10000 steps)."


@pytest.mark.parametrize("settings, expected", [
    pytest.param({**VIDEO, "steps_per_scene": 200, "height": 256},
                 ["The render shows about 1.6 s of the 4.5 s Video Source clip. To render all of it, set Steps per Scene to at least 540.",
                  "The Video Source clip is 640x360, so it is stretched to fit the 256x256 render. To keep its shape, set Height to -1."],
                 id="clip longer than the render, and stretched"),
    pytest.param({**AUDIO, "steps_per_scene": 60},
                 ["The render uses 0.5 s of the 8.0 s of audio after the offset. To use all of it, set Steps per Scene to at least 960."],
                 id="audio longer than the render"),
    pytest.param({**AUDIO, "steps_per_scene": 1440},
                 ["The audio runs out about 4.0 s before the render ends; from there on, the audio variables keep their last values."],
                 id="audio shorter than the render"),
    pytest.param({**AUDIO, "steps_per_scene": 60, "input_audio_offset": 9},
                 ["Audio Offset (9 s) is past the end of the 8.0 s of audio, so the render will stop with an error once its models have loaded."],
                 id="offset past the end of the audio"),
    pytest.param({**AUDIO, "steps_per_scene": 960}, [], id="audio as long as the render"),
    pytest.param({**AUDIO, "steps_per_scene": 60, "input_audio_filters": []}, [], id="audio without filters is ignored"),
])
def test_warnings(preflight, settings, expected):
    assert preflight(**settings)[0] == expected


def test_a_clip_shorter_than_the_render_ends_it(preflight):
    """Height -1 follows the clip's shape, and the render ends with the clip."""
    warnings, summary = preflight(**VIDEO, steps_per_scene=10000, height=-1)
    assert warnings == []
    assert summary[0] == "Output: about 54 frames, 4.5 s of video at 12 fps (about 540 steps)."


def test_a_full_disk(preflight, monkeypatch):
    monkeypatch.setattr(render, "_drive", lambda path: ("C:\\", 1000))
    warnings, summary = preflight(animation_mode="2D", steps_per_scene=1000, scenes="a")
    assert any(line.startswith("The render needs about ") and "which has only 1 KB free" in line for line in warnings)


@pytest.mark.parametrize("gpu_gb, accumulation, warned", [
    pytest.param(15.99, 1, True, id="1 on a 16 GB GPU"),
    pytest.param(19.99, 1, True, id="1 on a 20 GB GPU"),
    pytest.param(23.99, 1, False, id="1 on a 24 GB GPU"),
    pytest.param(15.99, 2, False, id="2 on a 16 GB GPU"),
    pytest.param(None, 1, False, id="GPU memory unknown"),
])
def test_gradient_accumulation_on_a_small_gpu(preflight, monkeypatch, gpu_gb, accumulation, warned):
    """1 needs about 17 GB with the default settings, 2 about 9 GB, with the same result."""
    monkeypatch.setattr(render, "_largest_gpu_gb", lambda: gpu_gb)
    warnings, _ = preflight(gradient_accumulation_steps=accumulation, animation_mode="2D", steps_per_scene=100, scenes="a")
    found = [line for line in warnings if line.startswith("Gradient Accumulation Steps is 1")]
    assert bool(found) == warned
    if warned:
        assert f"this PC's GPU has {gpu_gb:.0f} GB" in found[0] and "set it to 2" in found[0]


@pytest.mark.parametrize("stdout, returncode, gb", [
    pytest.param("16376\n", 0, 15.99, id="one GPU"),
    pytest.param("8192\n24564\n", 0, 23.99, id="the larger of two"),
    pytest.param("[N/A]\n", 0, None, id="no size"),
    pytest.param("", 9, None, id="nvidia-smi fails"),
])
def test_gpu_memory_from_nvidia_smi(monkeypatch, stdout, returncode, gb):
    monkeypatch.setattr(render, "_gpu_gb", None)
    monkeypatch.setattr(render.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=stdout, returncode=returncode))
    found = render._largest_gpu_gb()
    assert found is None if gb is None else found == pytest.approx(gb, abs=0.01)


def test_no_nvidia_smi(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr(render, "_gpu_gb", None)
    monkeypatch.setattr(render.subprocess, "run", missing)
    assert render._largest_gpu_gb() is None
