"""
Renders on disk: the runs under outputs/, the latest frame, and Encode Video.
"""
import contextlib
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import paths
from presets import _num, _valid_name
import render
from render import _ffmpeg_exe, _modified, _pngs, _render_frames, _run_settings


def _subdirs(folder: Path, reverse: bool = False) -> list[Path]:
    """Sorted subfolders of folder; [] if it can't be listed."""
    try:
        return sorted((path for path in folder.iterdir() if path.is_dir()), reverse=reverse)
    except OSError:
        return []


def _png_count(folder: Path) -> int:
    """Number of PNG files in folder; 0 if it can't be listed."""
    try:
        with os.scandir(folder) as entries:
            return sum(1 for entry in entries if entry.name.endswith(".png"))
    except OSError:
        return 0


def get_encodable_runs():
    """Scan outputs/ for runs that have PNG frames."""
    runs = []
    for day_dir in _subdirs(paths.OUTPUTS_DIR, reverse=True):
        for time_dir in _subdirs(day_dir, reverse=True):
            for ns_dir in _subdirs(time_dir / "images_out"):
                frames = _png_count(ns_dir)
                if frames:
                    label = f"{day_dir.name}/{time_dir.name} ({ns_dir.name}) — {frames} frames"
                    runs.append((label, str(ns_dir)))
    return runs


def run_fps(frames_dir: str):
    """frames_per_second a run was rendered with, from the config Hydra saved in its folder."""
    data = _run_settings(Path(frames_dir).parent.parent)
    return _num(data.get("frames_per_second"), None) if data is not None else None


def _frame_number(path: Path):
    """Sort key: frame number, so unpadded names (frame_10.png after frame_9.png) order correctly too."""
    m = re.search(r"(\d+)\.png$", path.name)
    return (int(m.group(1)) if m else -1, path.name)


def _discard_encode(proc: subprocess.Popen, part: Path):
    """Stop an encode and delete its unfinished output."""
    proc.kill()
    with contextlib.suppress(OSError):
        proc.stdin.close()
    proc.wait()
    with contextlib.suppress(OSError):
        part.unlink(missing_ok=True)


def encode_video(frames_dir: str, fps: int, fmt: str):
    """Encode a PNG frame sequence to video using ffmpeg."""
    if not frames_dir:
        return "Select a run first."
    frames_path = Path(frames_dir)
    if not frames_path.is_dir():
        return f"Directory not found: {frames_dir}"
    pngs = sorted(_pngs(frames_path), key=_frame_number)
    if not pngs:
        return "No PNG frames found."
    if not fps or fps < 1:
        return "Set FPS to at least 1."
    fps = int(fps)

    # Convert to BT.709 and tag it, which players assume for HD-sized video; ffmpeg's
    # default conversion is an untagged BT.601 one, so hues shift on playback
    bt709 = ("scale=out_color_matrix=bt709:out_range=tv,"
             "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709")
    color_tags = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    run_dir = frames_path.parent.parent  # up from images_out/namespace/
    if fmt == "ProRes 4444 (MOV)":
        suffix = "_prores4444.mov"
        codec_args = ["-vf", bt709, "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                      "-movflags", "+write_colr"]
    elif fmt == "ProRes HQ (MOV)":
        suffix = "_proreshq.mov"
        codec_args = ["-vf", bt709, "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
                      "-movflags", "+write_colr"]
    else:  # MP4
        suffix = ".mp4"
        # yuv420p needs even dimensions; pad odd sizes by one pixel
        codec_args = ["-vf", bt709 + ",pad=ceil(iw/2)*2:ceil(ih/2)*2",
                      "-c:v", "libx264", "-crf", "17", "-preset", "slow", "-pix_fmt", "yuv420p",
                      "-movflags", "+faststart"]

    out_file = run_dir / f"{frames_path.name}_{fps}fps{suffix}"
    # ffmpeg empties its output file before encoding, so encode under a temp name: a
    # failed encode then can't cost the previous export with the same settings
    part = out_file.with_name(f"{out_file.stem}.part{out_file.suffix}")

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return "ffmpeg not found. Install ffmpeg and ensure it's on your PATH."
    # Pipe the frames in order rather than using an image-sequence pattern, which stops
    # at the first gap in the numbering and breaks on '%' in the path
    cmd = [ffmpeg, "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-"]
    cmd += codec_args + color_tags + [str(part)]
    deadline = time.time() + max(600, 5 * len(pngs))
    written = skipped = 0
    with tempfile.TemporaryFile() as ffmpeg_log:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=ffmpeg_log)
        except OSError:
            return "ffmpeg not found. Install ffmpeg and ensure it's on your PATH."
        try:
            for png in pngs:
                if time.time() > deadline:
                    raise subprocess.TimeoutExpired(cmd, 0)
                try:
                    data = png.read_bytes()
                except OSError as e:
                    _discard_encode(proc, part)
                    return f"Could not read {png.name}: {e.strerror or e}. Close any program using it and try again."
                if not data.endswith(_PNG_END):
                    # Still being written, or cut short: ffmpeg would drop it and every frame after it
                    skipped += 1
                    continue
                try:
                    proc.stdin.write(data)
                except OSError:
                    break  # ffmpeg quit early and closed the pipe; its log says why
                written += 1
            with contextlib.suppress(OSError):
                proc.stdin.close()
            proc.wait(timeout=max(1.0, deadline - time.time()))
        except subprocess.TimeoutExpired:
            _discard_encode(proc, part)
            return "Encoding timed out."
        ffmpeg_log.seek(0)
        stderr = ffmpeg_log.read().decode("utf-8", "replace")
    if proc.returncode != 0 or not written:
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        if skipped == len(pngs):
            return "No finished PNG frames found."
        return f"ffmpeg error:\n{_ffmpeg_error(stderr)}"
    encoded = _frames_encoded(stderr)
    if encoded is not None and encoded < written:
        # ffmpeg leaves out a frame it can't decode (one damaged but still ending like a PNG),
        # sometimes with the frames after it, and still exits 0
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        return f"ffmpeg could decode only {encoded} of {written} frames, so the video was not saved. A frame may be damaged:\n{_ffmpeg_error(stderr)}"
    try:
        os.replace(part, out_file)
    except OSError:
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        return f"Could not replace {out_file.name}. Close it in your video player and try again."
    msg = f"Encoded {written} frames → {out_file.name}\nSaved to: {out_file}"
    if skipped:
        msg += f"\nSkipped {skipped} unfinished frame{'s' if skipped > 1 else ''}."
    if render._running and render._render_dir is not None and frames_path.is_relative_to(render._render_dir):
        msg += "\nThis render is still running, so the video has only the frames saved so far."
    return msg


def _ffmpeg_error(stderr: str) -> str:
    """Pick the lines that explain an ffmpeg failure; the tail alone is often just its banner."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines
              if re.search(r"error|invalid|not divisible|no such file|could not|unable|failed", line, re.I)]
    return "\n".join((errors or lines)[-8:])


def _frames_encoded(stderr: str) -> int | None:
    """Distinct frames in ffmpeg's output, from its last progress line; None if it printed none."""
    stats = re.findall(r"^frame=\s*(\d+)(.*)$", stderr.replace("\r", "\n"), re.MULTILINE)
    if not stats:
        return None
    frames, rest = stats[-1]
    # dup= counts copies of a frame that ffmpeg added to fill a gap left by one it couldn't decode
    dup = re.search(r"\bdup=\s*(\d+)", rest)
    return int(frames) - (int(dup.group(1)) if dup else 0)


def _latest_run_frames(namespace: str) -> list[Path]:
    """Frames of the newest run under outputs/ that used this namespace."""
    namespace = (namespace or "").strip()  # saved stripped
    if not _valid_name(namespace):
        return []
    for day_dir in _subdirs(paths.OUTPUTS_DIR, reverse=True):
        for run_dir in _subdirs(day_dir, reverse=True):
            frames = _pngs(run_dir / "images_out" / namespace)
            if frames:
                return frames
    return []


def _newest_run() -> Path | None:
    """The newest run folder under outputs/; None if there is none."""
    for day_dir in _subdirs(paths.OUTPUTS_DIR, reverse=True):
        for run_dir in _subdirs(day_dir, reverse=True):
            return run_dir
    return None


_PNG_END = b"IEND\xaeB`\x82"  # the closing chunk of every PNG


def _png_complete(path: Path) -> bool:
    """True once the PNG's closing IEND chunk is on disk."""
    try:
        with open(path, "rb") as f:
            f.seek(-len(_PNG_END), os.SEEK_END)
            return f.read() == _PNG_END
    except OSError:
        return False


def get_latest_frame(namespace: str):
    """Newest finished frame of the current (or last) render; before any render, of the newest run using namespace."""
    frames = _render_frames() if render._render_dir is not None else _latest_run_frames(namespace)
    # outputs/ is served as static files, read from disk as they are, so skip a frame pytti is still writing
    for frame in sorted(frames, key=_modified, reverse=True):
        if _png_complete(frame):
            return str(frame)
    return None
