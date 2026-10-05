"""
Running pytti: starting, stopping and resuming a render, its live log and progress,
and what it will make and need, shown as it starts.
"""
import atexit
import contextlib
import ctypes
import importlib.util
import io
import math
import os
import random
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import yaml

import paths
from presets import (
    CONF_FIELDS, CONF_KEYS, PresetError, _num, load_conf, load_defaults, load_yaml,
    missing_files, preset_risks, save_yaml,
)


# ---------------------------------------------------------------------------
# Render process management
# ---------------------------------------------------------------------------
_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()     # serializes start/stop with the reader thread's end-of-render bookkeeping
_log_lines: list[str] = []
_log_lock = threading.Lock()
_running = False
_render_its: float = 0.0          # latest observed it/s from tqdm
_render_step: int = 0             # current step within tqdm bar
_render_scene: int = 0            # completed scenes count
_render_dir: Path | None = None   # Hydra run folder of the current (or last) render
_render_namespace: str = ""       # file_namespace of that render
_scene_prompt_count: int = 0     # how many "Running prompt:" lines we've seen
_render_end_step: int | None = None  # Video Source: step where the source video runs out
_render_conf: dict | None = None  # config snapshot for ETA calc
_render_first_step: int = 0       # step the render starts from: 0, or the one Resume Render continues from
_log_prefix: str = ""             # render.log of the run Resume Render continues; this render's log goes after it
_render_start: float = 0.0       # time.time() when render started
_progress_start: tuple[float, int] | None = None  # (time, steps done) at the first progress line
_render_status: str | None = None  # how the last render ended, for the Status box
_stop_requested: bool = False
_summary_appended: bool = False


# Colors and cursor moves (tqdm moves up and down between nested bars)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# DEBUG lines and warnings
_LOG_NOISE = re.compile(r"\| DEBUG\s+\||UserWarning:|warnings\.warn\(")
# What pytti's notebook display() prints outside a notebook, often right after a progress bar
_PIL_REPR = re.compile(r"<PIL\.Image\.Image [^>]*>")
# Any tqdm bar ("  5%|▌    | ..."), including model download bars
_BAR_RE = re.compile(r"\d+%\|")
# The render's progress, e.g. "  5%|▌         | 500/10000 [00:33<10:30, 15.08it/s]"
_TQDM_RE = re.compile(r"(\d+)/(\d+)\s+\[.*?,\s*(\d+(?:\.\d+)?)(s/it|it/s)")
_SCENE_RE = re.compile(r"Running prompt:", re.IGNORECASE)
# Logged by the patched workhorse.py when the source video is shorter than the render
_VIDEO_END_RE = re.compile(r"render will end at step (\d+)")

def _render_progress() -> tuple[int, int]:
    """(total steps, steps done) of the current render, from its config and tqdm progress."""
    conf = _render_conf or {}
    steps_per_scene = max(1, int(_num(conf.get("steps_per_scene"), 1)))
    total = _total_steps(conf)
    if _render_end_step is not None:
        total = min(total, _render_end_step)
    if _render_scene == 0:
        # A resumed render's first progress bar starts partway through a scene
        return total, _render_first_step + _render_step
    return total, (_render_first_step // steps_per_scene + _render_scene) * steps_per_scene + _render_step


def _pngs(folder: Path) -> list[Path]:
    """PNG files in folder; [] if it can't be listed (missing, or a name Windows can't use)."""
    try:
        return list(folder.glob("*.png"))
    except OSError:
        return []


def _render_frames() -> list[Path]:
    """Frames the current (or last) render has saved so far."""
    if _render_dir is None:
        return []
    return _pngs(_render_dir / "images_out" / _render_namespace)


def _append_summary(label: str):
    """Append render summary to log. Only runs once per render."""
    global _summary_appended
    if _summary_appended:
        return
    _summary_appended = True
    now = time.time()
    elapsed = now - _render_start if _render_start else 0
    total_steps, done = _render_progress()
    frames = _render_frames()
    # A resumed render counts only its own frames for the average
    new_frames = sum(1 for frame in frames if _modified(frame) >= _render_start)
    frames = len(frames)
    lines = [
        "=" * 50,
        label,
        "-" * 50,
        f"  Steps:         {done} / {total_steps}",
        f"  Frames saved:  {frames}",
        f"  Total time:    {_format_eta(elapsed)}",
    ]
    if _progress_start:
        # Timed from the first progress line, so model loading and downloads don't count
        start_time, start_done = _progress_start
        render_time = now - start_time
        if render_time > 0 and done > start_done:
            lines.append(f"  Avg speed:     {(done - start_done) / render_time:.2f} step/s")
        if new_frames > 0:
            lines.append(f"  Avg per frame: {_format_eta(render_time / new_frames)}")
    lines.append("=" * 50)
    with _log_lock:
        _log_lines.extend(lines)


def _save_render_log():
    """Keep the log in the render's folder: pytti logs through loguru, so Hydra's workhorse.log stays empty.

    A resumed render's log goes after the log the run already had.
    """
    if _render_dir is None or not _render_dir.is_dir():
        return
    with _log_lock:
        text = _log_prefix + "\n".join(_log_lines) + "\n"
    with contextlib.suppress(OSError):
        (_render_dir / "render.log").write_text(text, encoding="utf-8")


_ES_CONTINUOUS, _ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def _keep_awake(on: bool):
    """Keep Windows from sleeping while a render runs; the display may still turn off.

    A busy GPU doesn't count as activity, so the idle timer would suspend an unattended
    render. The request belongs to the calling thread, so turn it off from the same one.
    """
    if os.name != "nt":
        return
    with contextlib.suppress(Exception):
        set_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_state.argtypes, set_state.restype = [ctypes.c_uint32], ctypes.c_uint32
        set_state(_ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0))


def _kill_tree(proc: subprocess.Popen):
    """Stop a render and every process it started (e.g. pytti's ffmpeg video conversion)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # TerminateProcess alone would leave child processes running
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _stream_output(proc):
    global _running, _render_its, _render_step, _render_scene, _scene_prompt_count, _render_end_step, _progress_start, _render_status
    _keep_awake(True)
    last_idx = -1      # index in _log_lines of the latest progress line, if nothing was logged after it
    redrawn = False    # that line ended in a bare \r, so whatever comes next replaces it
    try:
        # newline="" keeps line ends as they are, so a bare \r (progress redrawn in place by
        # tqdm, ffmpeg and download bars) can be told apart from the end of a line
        stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace", newline="")
        for line in iter(stream.readline, ""):
            if proc is not _proc or _stop_requested:
                continue  # output after Stop, or from a stopped render; keep it out of the log
            # A bare \r, or the cursor-up a bar nested in another (a download during the
            # render) ends with: either way the next output is drawn over this line
            redraw = line.endswith("\r") or "\x1b[A" in line
            clean = _ANSI_ESCAPE.sub("", line).rstrip()
            # display() output glued to a bar ends that line early; the bar is redrawn after it
            clean, displayed = _PIL_REPR.subn("", clean)
            if not clean.strip() or _LOG_NOISE.search(clean):
                continue
            bar = bool(_BAR_RE.search(clean))
            # Extract tqdm progress; bars before the first scene are model downloads
            m = _TQDM_RE.search(clean)
            if m and _scene_prompt_count and float(m.group(3)) > 0:
                _render_step = int(m.group(1))
                rate = float(m.group(3))
                # tqdm may report "s/it" (slow) or "it/s" (fast)
                _render_its = (1.0 / rate) if m.group(4) == "s/it" else rate
                if _progress_start is None:
                    _progress_start = (time.time(), _render_progress()[1])
            # Track scene transitions (pytti logs "Running prompt:" for each scene)
            if _SCENE_RE.search(clean):
                _scene_prompt_count += 1
                # First "Running prompt:" is scene 0 starting; subsequent ones mean prior scene completed
                _render_scene = max(0, _scene_prompt_count - 1)
                _render_step = 0  # the new scene's bar starts at 0; its first line has no rate yet
            end = _VIDEO_END_RE.search(clean)
            if end:
                _render_end_step = int(end.group(1))
            with _log_lock:
                # Keep one line per progress bar instead of one per redraw
                if last_idx == len(_log_lines) - 1 and (redrawn or bar):
                    _log_lines[-1] = clean
                else:
                    _log_lines.append(clean)
                last_idx = len(_log_lines) - 1 if redraw or (bar and displayed) else -1
                redrawn = redraw
    except Exception as e:
        # Nobody would drain the pipe anymore, so the render would stall; stop it instead
        with _log_lock:
            _log_lines.append(f"Log reader failed ({e!r}); stopping render.")
        _kill_tree(proc)
    finally:
        try:
            proc.wait()
            with _proc_lock:
                if proc is _proc:  # a newer render may have started since this one was stopped
                    try:
                        if not _stop_requested:
                            code = proc.returncode
                            if code == 0:
                                _render_status = "Render complete."
                            else:
                                _render_status = f"Render ended (exit code {code}).{_blocked_note()}{_resume_offer(_render_dir)}"
                            _append_summary("RENDER COMPLETE" if code == 0 else f"RENDER ENDED (exit code {code})")
                            _save_render_log()
                    finally:
                        # Even if the summary failed; otherwise Start Render would say "Already running." for good
                        _running = False
                        _render_its = 0.0
        finally:
            _keep_awake(False)


def _format_eta(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


def _get_eta() -> str:
    """ETA of the render from the observed it/s and its config; blank until a rate is known."""
    its = _render_its
    if its <= 0:
        return ""
    total_steps, done = _render_progress()
    remaining = max(0, total_steps - done)
    if remaining == 0:
        return "ETA: finishing..."
    eta_sec = remaining / its
    return f"ETA: ~{_format_eta(eta_sec)} remaining ({its:.1f} it/s, {done}/{total_steps} steps)"


# Where a copy named ffmpeg.exe goes when it can't go next to python.exe
_FFMPEG_TEMP_DIR = Path(tempfile.gettempdir()) / "pytti-ffmpeg"


def _copy_file(src: Path, dst: Path):
    """Copy src to dst unless dst already matches it; under a temp name first, so a failed copy never leaves a partial dst."""
    with contextlib.suppress(OSError):
        s, d = src.stat(), dst.stat()
        if s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime):
            return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _ffmpeg_exe() -> str | None:
    """Find ffmpeg: the build bundled with imageio-ffmpeg, else python\\ffmpeg.exe, else one on PATH.

    The bundled build is known to have the encoders the app relies on (libx264,
    prores_ks); one on PATH may not (LGPL builds leave out libx264). In the portable
    install it is copied next to python.exe as ffmpeg.exe, where pytti's own bare
    "ffmpeg" calls (Video Source conversion, audio) find it before anything on PATH.
    The copy is replaced when it no longer matches, e.g. after imageio-ffmpeg is updated.
    """
    local = paths.EMBEDDED_PYTHON.parent / "ffmpeg.exe"
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return str(local) if local.is_file() else shutil.which("ffmpeg")
    if paths.PYTHON_EXE == paths.EMBEDDED_PYTHON:
        with contextlib.suppress(OSError):
            _copy_file(Path(bundled), local)
            return str(local)
    return bundled


def _ffmpeg_folder(ffmpeg: str) -> str | None:
    """A folder holding this ffmpeg under the name ffmpeg.exe, for the render's PATH.

    pytti runs a bare "ffmpeg"; the bundled binary is named like ffmpeg-win-x86_64-v7.1.exe,
    so if it couldn't be copied next to python.exe, a copy goes in a temp folder.
    """
    path = Path(ffmpeg)
    if path.stem.lower() == "ffmpeg":
        return str(path.parent)
    try:
        _copy_file(path, _FFMPEG_TEMP_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    except OSError:
        return None
    return str(_FFMPEG_TEMP_DIR)


def _new_run_dir() -> Path:
    """A fresh outputs/<date>/<time> folder name, the layout Hydra uses by default."""
    base = paths.OUTPUTS_DIR / time.strftime("%Y-%m-%d") / time.strftime("%H-%M-%S")
    run_dir, n = base, 1
    while run_dir.exists():  # two renders started within the same second
        n += 1
        run_dir = base.with_name(f"{base.name}-{n}")
    return run_dir


# Backups every render keeps at least; a preset's lower Backups is raised when the render
# starts, without changing the preset. Resume Render continues from the newest backup, and
# with two, one cut off by Stop Render still leaves the one before it.
MIN_BACKUPS = 2
# config/conf/_resume.yaml: the settings of the run Resume Render continues
RESUME_CONF = "_resume"


def _app_path(path: Path) -> str:
    """path relative to the app folder when it is inside it, with forward slashes, e.g.
    outputs/2026-10-04/11-22-47; for Hydra overrides and the status box."""
    try:
        return path.relative_to(paths.ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _launch(run_dir: Path, conf: dict, overrides: list[str], log: list[str], first_step: int = 0,
            log_prefix: str = "") -> str | None:
    """Start pytti on a render into run_dir; a message if it couldn't start. Call with _proc_lock held.

    conf holds the render's settings, for its progress and preview, and log the lines its
    log starts with. A resumed render starts at first_step, and its render.log adds its
    log to log_prefix.
    """
    global _proc, _running, _render_its, _render_step, _render_scene, _scene_prompt_count, _render_conf, _render_start, _stop_requested, _summary_appended, _render_dir, _render_namespace, _render_end_step, _progress_start, _render_status, _render_first_step, _log_prefix
    with _log_lock:
        _log_lines[:] = log
    _stop_requested = False
    _summary_appended = False
    _render_its = 0.0
    _render_step = 0
    _render_scene = 0
    _scene_prompt_count = 0
    _render_end_step = None
    _progress_start = None
    _render_status = None
    _render_start = time.time()
    _render_conf = conf
    _render_first_step = first_step
    _log_prefix = log_prefix
    _render_dir = run_dir
    # The preset's own value, even if blank: that is the folder pytti saves into
    _render_namespace = str(conf.get("file_namespace", load_defaults().get("file_namespace", "")))
    # UTF-8 output so the pipe decodes the same way whatever the Windows code page;
    # INFO level drops pytti's per-step DEBUG output. torch >= 2.6 refuses to load
    # checkpoints holding pickled objects (VQGAN imagenet's Lightning callbacks) unless
    # told to; earlier torch versions ignore the variable.
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "LOGURU_LEVEL": "INFO",
           "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"}
    # Where model_mirror.py and the rotoscoper.py patch put models and Video Source conversions
    env["PYTTI_CACHE"] = str(paths.CACHE_DIR)
    # pytti runs a bare "ffmpeg" (Video Source conversion, audio); make it the one the UI uses
    ffmpeg = _ffmpeg_exe()
    ffmpeg_dir = _ffmpeg_folder(ffmpeg) if ffmpeg else None
    if ffmpeg_dir:
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
    try:
        # Binary stdout: _stream_output decodes it itself to see progress redraws.
        # No stdin, so a key pressed in the console can't stop ffmpeg ('q') mid-conversion.
        _proc = subprocess.Popen(
            [str(paths.PYTHON_EXE), "-W", "ignore", "-m", "pytti.workhorse", *overrides],
            cwd=str(paths.ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",  # lets _kill_tree signal the whole group
        )
    except OSError as e:
        return f"Could not start render: {e}"
    _running = True
    threading.Thread(target=_stream_output, args=(_proc,), daemon=True).start()
    return None


def start_render(conf_name: str):
    with _proc_lock:
        if _running:
            return "Already running."
        name = conf_name if conf_name.endswith(".yaml") else conf_name + ".yaml"
        try:
            render_conf = load_conf(name)
        except PresetError as e:
            return str(e)
        conf_name = conf_name.removesuffix(".yaml")
        # Choose the run folder ourselves so the preview and summary know where frames go
        run_dir = _new_run_dir()
        overrides = [f"conf='{conf_name}'", f"hydra.run.dir='{_app_path(run_dir)}'"]
        seed = render_conf.get("seed")
        if re.fullmatch(r"-?\d+", str(seed)):
            seed_note = f"Seed: {seed}"
        else:
            # Pick the random seed here so it can be shown and reused
            seed = random.randint(0, 2**32 - 1)
            overrides.append(f"seed={seed}")
            seed_note = f"Seed: {seed} (random; enter it as the Seed to repeat this render)"
        # Snapshot config for ETA calculations
        conf = {**load_defaults(), **render_conf}
        if _num(conf.get("backups"), 0) < MIN_BACKUPS:
            overrides.append(f"backups={MIN_BACKUPS}")
            conf["backups"] = MIN_BACKUPS
        warnings, summary = preflight(conf)
        # The preset's name goes in render.log: resuming the run makes Hydra record _resume instead
        error = _launch(run_dir, conf, overrides, [f"Preset: {conf_name}", seed_note, *summary, *warnings])
        if error:
            return error
    return " ".join(["Render started.", *warnings])


def _run_settings(run_dir: Path) -> dict | None:
    """The settings a run was rendered with, as Hydra saved them in its folder; None if they can't be read."""
    try:
        data = load_yaml(run_dir / ".hydra" / "config.yaml")
    except (OSError, ValueError, yaml.YAMLError):  # ValueError: not UTF-8
        return None
    return data if isinstance(data, dict) else None


def _backups(run_dir: Path, namespace: str) -> list[tuple[int, Path]]:
    """(frame, file) of each backup pytti kept in a run, newest first."""
    pattern = re.compile(rf"{re.escape(namespace)}_(\d+)\.bak")
    try:
        files = list((run_dir / "backup" / namespace).iterdir())
    except OSError:
        return []
    found = [(int(m.group(1)), path) for path in files if (m := pattern.fullmatch(path.name))]
    return sorted(found, key=lambda backup: backup[0], reverse=True)


def _bak_damaged(path: Path) -> bool:
    """True if a backup was cut off, e.g. by Stop Render while pytti was writing it.

    torch.save writes a zip file, and a cut-off one has lost the directory at its end.
    """
    try:
        zipfile.ZipFile(path).close()
    except OSError:
        return False  # can't tell, e.g. locked by another program
    except Exception:
        # Besides BadZipFile, a damaged directory can raise e.g. UnicodeDecodeError
        return True
    return False


def _save_every(conf: dict) -> int:
    """Steps between saved frames: save_every, or steps_per_frame when it is 0, as patched pytti does."""
    save_every = int(_num(conf.get("save_every"), 0))
    return save_every if save_every > 0 else max(1, int(_num(conf.get("steps_per_frame"), 1)))


def _scene_count(conf: dict) -> int:
    """How many scenes || separates; at least 1."""
    return max(1, len([scene for scene in str(conf.get("scenes") or "").split("||") if scene.strip()]))


def _total_steps(conf: dict) -> int:
    """Steps of all scenes together."""
    return _scene_count(conf) * max(1, int(_num(conf.get("steps_per_scene"), 1)))


def _resume_point(run_dir: Path, settings: dict, delete_damaged: bool = False) -> tuple[int, int, int] | str:
    """(frame, step, frames in all) a stopped render continues from, or why it can't be resumed.

    The step is the one the patched pytti continues with. delete_damaged deletes newer
    backups that were cut off, which pytti would otherwise try to load.
    """
    where = _app_path(run_dir)
    try:
        log = (run_dir / "render.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        log = ""
    ends = re.findall(r"^RENDER (COMPLETE|STOPPED|ENDED)", log, re.MULTILINE)
    if ends and ends[-1] == "COMPLETE":
        return f"The render in {where} is complete, so there is nothing to resume."
    for frame, path in _backups(run_dir, str(settings.get("file_namespace") or "")):
        if not _bak_damaged(path):
            break
        if delete_damaged:
            try:
                path.unlink()
            except OSError as e:
                return f"Could not delete {path.name}, a damaged backup in {where}: {e.strerror or e}. Delete it, then press Resume Render again."
    else:
        return f"The render in {where} can't be resumed: it has no backup to continue from. Renders keep backups from their first saved frame on."
    save_every = _save_every(settings)
    # A Video Source render ends with its clip, at the step its log gave
    total = min([_total_steps(settings)] + [int(step) for step in _VIDEO_END_RE.findall(log)])
    if frame * save_every >= total:
        return f"The render in {where} is complete, so there is nothing to resume."
    return frame, max(0, frame * save_every - 1), total // save_every


def _resume_offer(run_dir: Path | None) -> str:
    """' Resume Render continues it from frame N.' for a render that can be resumed, else ''."""
    settings = _run_settings(run_dir) if run_dir else None
    point = _resume_point(run_dir, settings) if settings else None
    return f" Resume Render continues it from frame {point[0]}." if isinstance(point, tuple) else ""


def resume_render(run_dir: Path, labels: dict) -> str:
    """Continue a stopped render in its own run folder, from its newest backup and with the
    settings it was started with. labels name the settings in messages."""
    with _proc_lock:
        if _running:
            return "Already running."
        where = _app_path(run_dir)
        settings = _run_settings(run_dir)
        if settings is None:
            return f"The render in {where} can't be resumed: its settings, .hydra/config.yaml in its folder, are missing or can't be read."
        point = _resume_point(run_dir, settings, delete_damaged=True)
        if isinstance(point, str):
            return point
        frame, step, frames = point
        # The checks Start Render makes, on the settings the run was started with
        values = {key: settings.get(key) for key in CONF_FIELDS}
        extras = {key: value for key, value in settings.items() if key not in CONF_KEYS}
        problems = missing_files(values, labels, extras) + preset_risks(values, extras, labels)[0]
        if problems:
            return " ".join([f"The render in {where} can't be resumed."] + problems)
        conf = {key: value for key, value in settings.items() if key != "restore"}
        conf["backups"] = max(MIN_BACKUPS, int(_num(conf.get("backups"), 0)))
        try:
            save_yaml(paths.CONF_DIR / f"{RESUME_CONF}.yaml", conf, header="# @package _global_\n")
        except OSError as e:
            return f"Could not write config/conf/{RESUME_CONF}.yaml: {e.strerror or e}."
        # ++ adds restore, or sets it if the composed settings already have it (+ would fail then)
        overrides = [f"conf='{RESUME_CONF}'", f"hydra.run.dir='{_app_path(run_dir)}'", "++restore=true"]
        warnings, summary = preflight(conf)
        try:
            log_prefix = (run_dir / "render.log").read_text(encoding="utf-8", errors="replace").rstrip("\n") + "\n\n"
        except OSError:
            log_prefix = ""
        resuming = f"Resuming the render in {where} from frame {frame} of {frames}"
        error = _launch(run_dir, conf, overrides, [f"{resuming} (step {step}).", *summary, *warnings], step, log_prefix)
        if error:
            return error
    return " ".join([f"{resuming}.", *warnings])


# ---------------------------------------------------------------------------
# Preflight: what a render will produce and need, shown as it starts
# ---------------------------------------------------------------------------

# Bytes per pixel of a saved PNG frame: 0.58 to 0.66 of the 3 bytes of RGB in past renders
_PNG_BYTES_PER_PIXEL = 3 * 0.65
_mirror = None  # app/model_mirror.py once loaded; False if it can't be
# GPU memory in GB a render with the default settings needs at Gradient Accumulation Steps
# 1 and at 2, and the GPU size below which 1 may not fit (24 GB cards report a bit less)
_GAS_1_GB, _GAS_2_GB = 17, 9
_GAS_1_MIN_GPU_GB = 23
_gpu_gb = None  # memory of the largest GPU in GB once read; False if it can't be


def _model_mirror():
    """app/model_mirror.py, for its lists of model files and sizes and the folders it picks;
    None if it can't be loaded.

    Loaded by path, as this folder isn't on sys.path, and without pytti: importing pytti
    imports torch.
    """
    global _mirror
    if _mirror is None:
        try:
            spec = importlib.util.spec_from_file_location("pytti_portable_model_mirror", paths.ROOT / "model_mirror.py")
            _mirror = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mirror)
            # The folders renders use, which _launch passes them as PYTTI_CACHE
            _mirror.CACHE, _mirror.MODELS = paths.CACHE_DIR, paths.CACHE_DIR / "models"
        except Exception:
            _mirror = False
    return _mirror or None


def _downloads(conf: dict) -> list[tuple[str, int, Path]]:
    """(file, size, folder) of each model the render downloads before it starts.

    The models model_mirror.prefetch_models fetches, unless they are already in the
    folder model_mirror.py picks for them.
    """
    mirror = _model_mirror()
    if mirror is None:
        return []
    needed = []

    def need(file, target: Path, exact=True):
        # As model_mirror._fetch decides: a file of another size is a cut-off download
        size = file[2]
        try:
            missing = not target.exists() or (exact and target.is_file() and target.stat().st_size != size)
        except OSError:
            missing = True
        if missing:
            needed.append((target.name, size, target.parent))

    for key, file in mirror.CLIP_MODELS.items():
        if conf.get(key):
            name = Path(file[0]).name
            need(file, mirror._clip_folder(name) / name)
    mode = "off" if conf.get("animation_mode") is False else conf.get("animation_mode")
    depth_weight = str(conf.get("depth_stabilization_weight") or "").strip()
    if mode == "3D" or (depth_weight not in ("", "0") and (mode != "off" or conf.get("init_image"))):
        hub = mirror.hub_folder()
        need(mirror.ADABINS, mirror.adabins_folder() / "AdaBins_nyu.pt")
        need(mirror.EFFICIENTNET, hub / "checkpoints" / Path(mirror.EFFICIENTNET[0]).name)
        need(mirror.GEN_EFFICIENTNET, hub / "rwightman_gen-efficientnet-pytorch_master")
    name, parent = conf.get("vqgan_model"), str(conf.get("models_parent_dir") or "${user_cache:}")
    # Hydra fills in any other ${...} when the render starts, so that folder isn't known here
    if conf.get("image_model") == "VQGAN" and name in mirror.VQGAN_MODELS and (parent == "${user_cache:}" or "${" not in parent):
        # Without models_parent_dir, vqgan_folder uses ${user_cache:}'s folder, the .cache folder
        folder = mirror.vqgan_folder({"vqgan_model": name, "models_parent_dir": None if parent == "${user_cache:}" else parent})
        config, checkpoint = mirror.VQGAN_MODELS[name]
        need(config, folder / f"{name}.yaml", exact=False)
        need(checkpoint, folder / f"{name}.ckpt", exact=False)
    return needed


def _probe(path: str) -> dict | None:
    """A media file's duration in seconds and, for a video, its frame size as played back
    (rotation applied); None if ffmpeg can't read it."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not Path(path).is_file():
        return None
    try:
        # With no output file ffmpeg describes the input and exits
        result = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stderr.decode("utf-8", "replace")
    duration = re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", text)
    if not duration:
        return None
    info = {"duration": int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])}
    video = re.search(r"Stream #.*?: Video: .*?, (\d+)x(\d+)[\s,]", text)
    if video:
        width, height = int(video[1]), int(video[2])
        # Phone videos are often stored sideways; ffmpeg turns them upright when pytti converts them
        rotation = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", text)
        if rotation and round(abs(float(rotation[1]))) % 180 == 90:
            width, height = height, width
        info["size"] = (width, height)
    return info


def _video_end(frames: int, pre: int, steps_per_frame: int, stride: int, save_every: int) -> int:
    """The step a Video Source render ends at to show a clip of this many frames, as the
    patched workhorse.py works it out."""
    moves = -(-(frames - 1) // stride)
    if pre == 0:
        moves = max(moves, 1)
    repeat = pre + moves * steps_per_frame
    last_start = repeat - steps_per_frame if moves else 0
    save = (repeat + 1) // save_every * save_every - 1
    if save <= last_start:
        save += save_every
    return save + 1


def _backup_bytes(conf: dict, width: int, height: int) -> int:
    """About how big one backup is: the image model's state."""
    if conf.get("image_model") == "Limited Palette":
        return (int(_num(conf.get("palettes"), 1)) + 1) * width * height * 4
    if conf.get("image_model") == "VQGAN":
        scale = max(1, int(_num(conf.get("pixel_size"), 1)))
        return 3 * (width * scale // 16) * (height * scale // 16) * 256 * 4
    return 3 * width * height * 4


def _size_text(size: float) -> str:
    if size >= 2**30:
        return f"{size / 2**30:.1f} GB"
    return f"{round(size / 2**20)} MB" if size >= 2**20 else f"{max(1, round(size / 2**10))} KB"


def _drive(path: Path) -> tuple[str, int] | None:
    """(drive, free bytes) for a folder that may not exist yet; None if unknown."""
    path = path.resolve()
    for folder in (path, *path.parents):
        if folder.exists():
            try:
                return path.anchor, shutil.disk_usage(folder).free
            except OSError:
                return None
    return None


def _largest_gpu_gb() -> float | None:
    """Memory of this PC's largest NVIDIA GPU in GB, from nvidia-smi; None if it can't be read.

    Read once. The UI doesn't import torch, which would load CUDA into this process.
    """
    global _gpu_gb
    if _gpu_gb is None:
        _gpu_gb = False
        # Where drivers from before 2019 put nvidia-smi, as in system_check.ps1
        smi = shutil.which("nvidia-smi") or os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")
        try:
            result = subprocess.run([smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            result = None
        if result and result.returncode == 0:
            sizes = [float(mib) for mib in re.findall(r"^\s*(\d+(?:\.\d+)?)\s*$", result.stdout, re.MULTILINE)]
            if sizes:
                _gpu_gb = max(sizes) / 1024
    return _gpu_gb or None


def preflight(conf: dict) -> tuple[list[str], list[str]]:
    """What a render with these settings (default.yaml's with the preset's over them) will
    produce and need, as (warnings, summary lines) for the status box and the log.

    Warnings are for what may waste the render: a Video Source clip or an audio track it
    doesn't fit, a clip stretched to another shape, too little disk space or GPU memory.
    All figures are estimates, so nothing is reported if working them out fails.
    """
    try:
        return _preflight(conf)
    except Exception:
        return [], []


def _preflight(conf: dict) -> tuple[list[str], list[str]]:
    warnings, summary = [], []
    mode = "off" if conf.get("animation_mode") is False else conf.get("animation_mode")
    steps_per_frame = max(1, int(_num(conf.get("steps_per_frame"), 1)))
    pre = max(0, int(_num(conf.get("pre_animation_steps"), 0)))
    fps = max(1, int(_num(conf.get("frames_per_second"), 1)))
    save_every = _save_every(conf)
    scenes = _scene_count(conf)
    total = steps = _total_steps(conf)  # steps: where the render ends
    width, height = int(_num(conf.get("width"), -1)), int(_num(conf.get("height"), -1))
    estimated = False

    def at_least(steps_needed):
        return f"set Steps per Scene to at least {-(-steps_needed // scenes)}"

    clip = _probe(str(conf["video_path"])) if mode == "Video Source" and conf.get("video_path") else None
    if clip and clip["duration"] > 0:
        stride = max(1, int(_num(conf.get("frame_stride"), 1)))
        # pytti converts the clip to the render's frame rate first; this count is within a frame
        frames_in = max(1, round(clip["duration"] * fps))
        end = _video_end(frames_in, pre, steps_per_frame, stride, save_every)
        estimated = end < total
        if end < total:
            steps = end  # the patched workhorse.py ends the render with the clip
        elif total < end - steps_per_frame:  # more than a frame short
            moves = -(-(total - pre) // steps_per_frame) if total > pre else 0
            covered = min(clip["duration"], moves * stride / fps)
            warnings.append(f"The render shows about {covered:.1f} s of the {clip['duration']:.1f} s Video Source clip. To render all of it, {at_least(end)}.")
        if clip.get("size") and width > 0 and height > 0:
            clip_w, clip_h = clip["size"]
            if abs(math.log(clip_w * height / (clip_h * width))) > 0.02:
                warnings.append(f"The Video Source clip is {clip_w}x{clip_h}, so it is stretched to fit the {width}x{height} render. To keep its shape, set Height to -1.")
        if clip.get("size") and (width == -1) != (height == -1) and not conf.get("init_image"):
            # -1 follows the clip's shape
            clip_w, clip_h = clip["size"]
            width, height = (int(height * clip_w / clip_h), height) if width == -1 else (width, int(width * clip_h / clip_w))

    audio = _probe(str(conf["input_audio"])) if conf.get("input_audio") and conf.get("input_audio_filters") else None
    if audio:
        offset = float(_num(conf.get("input_audio_offset"), 0))
        available = audio["duration"] - offset
        # The audio is read once per animation frame, from pre_animation_steps on
        length = (-(-(steps - pre) // steps_per_frame) if steps > pre else 0) / fps
        if available <= 0:
            warnings.append(f"Audio Offset ({offset:g} s) is past the end of the {audio['duration']:.1f} s of audio, so the render will stop with an error once its models have loaded.")
        elif length > available + 1:
            warnings.append(f"The audio runs out about {length - available:.1f} s before the render ends; from there on, the audio variables keep their last values.")
        elif available > length + 1 and steps == total:
            warnings.append(f"The render uses {length:.1f} s of the {available:.1f} s of audio after the offset. To use all of it, {at_least(pre + int(available * fps) * steps_per_frame)}.")

    frames = steps // save_every
    about = "about " if estimated else ""
    summary.append(f"Output: {about}{frames} frames, {frames / fps:.1f} s of video at {fps} fps ({about}{steps} steps).")
    downloads = _downloads(conf)
    if downloads:
        files = ", ".join(f"{name} ({_size_text(size)})" for name, size, _ in downloads)
        summary.append(f"Downloads before the render starts: {files}.")

    needs = {}  # drive -> [free bytes, bytes needed]
    if width > 0 and height > 0:
        scale = max(1, int(_num(conf.get("pixel_size"), 1)))
        # Frames, and the backups pytti keeps plus the one it is writing
        size = frames * width * height * scale**2 * _PNG_BYTES_PER_PIXEL
        size += (max(MIN_BACKUPS, int(_num(conf.get("backups"), 0))) + 1) * _backup_bytes(conf, width, height)
        if drive := _drive(paths.OUTPUTS_DIR):
            needs.setdefault(drive[0], [drive[1], 0])[1] += size
    for _, size, folder in downloads:
        if drive := _drive(folder):
            needs.setdefault(drive[0], [drive[1], 0])[1] += size
    for drive, (free, size) in needs.items():
        summary.append(f"Disk: about {_size_text(size)} on {drive}, which has {_size_text(free)} free.")
        if size > free:
            warnings.append(f"The render needs about {_size_text(size)} on {drive}, which has only {_size_text(free)} free.")

    # 1 needs about twice the GPU memory of 2, for the same result
    if int(_num(conf.get("gradient_accumulation_steps"), 1)) == 1 and (gpu := _largest_gpu_gb()) and gpu < _GAS_1_MIN_GPU_GB:
        warnings.append(f"Gradient Accumulation Steps is 1, which needs about {_GAS_1_GB} GB of GPU memory with the default "
                        f"settings, and this PC's GPU has {gpu:.0f} GB. If the render runs out of memory or slows down, "
                        f"set it to 2, which gives the same result with about {_GAS_2_GB} GB.")
    return warnings, summary


def stop_render():
    global _running, _stop_requested, _render_status
    with _proc_lock:
        proc = _proc
        if not (proc and _running):
            return "No render running."
        # The reader drops output from here on, so the log ends with this summary
        _stop_requested = True
        _render_status = "Render stopped."
        try:
            _append_summary("RENDER STOPPED")
            _save_render_log()
        finally:
            _running = False
            _kill_tree(proc)
    # After the kill, so a backup pytti was still writing counts as cut off
    return "Render stopped." + _resume_offer(_render_dir)


# What a render prints when Windows blocks one of its files. Smart App Control blocks files
# that aren't signed, as most of PyTorch's aren't; App Control policies on PCs that a company
# or school manages give the same error.
_APP_CONTROL_RE = re.compile(r"WinError 4551|Application Control policy has blocked", re.IGNORECASE)


def _blocked_note() -> str:
    """Why the render failed if Windows blocked one of its files, for the Status box; else ''."""
    with _log_lock:
        blocked = any(_APP_CONTROL_RE.search(line) for line in _log_lines)
    if not blocked:
        return ""
    return (" Windows blocked one of PyTorch's files (WinError 4551). Smart App Control blocks files"
            " that aren't signed, as most of PyTorch's aren't. To render, turn it off: Windows Security >"
            " App & browser control > Smart App Control settings > Off. On many Windows versions it can't"
            " be turned back on without reinstalling Windows. On a PC that a company or school manages,"
            " an App Control policy gives the same error: ask its IT department.")


@atexit.register
def _stop_render_on_exit():
    # Once the UI exits nothing drains the render's output, so it would stall; end it too
    if _proc and _proc.poll() is None:
        _kill_tree(_proc)


def get_log():
    with _log_lock:
        return "\n".join(_log_lines[-200:])


def _modified(path: Path) -> float:
    """mtime for sorting; 0 for a file deleted since it was listed."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
