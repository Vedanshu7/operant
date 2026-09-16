#!/usr/bin/env python
"""
Build the README GIFs from real evidence and eval results.

- ``discovery.gif``: a recorded discovery run, one frame per turn, with a
  caption of what the agent did on that screen (from the run log).
- ``replay.gif``: a recorded replay of the saved capability, its steps
  appearing over the final screen - no model in the loop.
- ``evals.gif``: the eval summary table from a results JSONL, typed out
  like a terminal.
- ``demo.gif`` and ``demo.mp4``: the desktop app's own window, recorded
  frame by frame (``OPERANT_DESKTOP_RECORD``) while a goal is typed in
  and the run plays out.

Only window screenshots of the public ParaBank demo are used, and the run
logs are already redacted.

Run: ``uv run python scripts/make_readme_media.py --discovery <dir>
--replay <dir> --evals state/evals/<session>.jsonl --demo <frames dir>``
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Tuple

import PIL.Image as pimage
import PIL.ImageChops as pchops
import PIL.ImageDraw as pdraw
import PIL.ImageFont as pfont

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_OUT = _ROOT / "docs" / "media"
_WIDTH = 800
_CAPTION_H = 64
_BG = (17, 24, 39)
_FG = (229, 231, 235)
_ACCENT = (52, 211, 153)
_MUTED = (156, 163, 175)


def _font(size: int) -> pfont.FreeTypeFont | pfont.ImageFont:
    """
    Load a monospace font, falling back to Pillow's bundled one.
    """
    for candidate in (
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if pathlib.Path(candidate).exists():
            return pfont.truetype(candidate, size)
    return pfont.load_default(size=size)


def _events(run_dir: pathlib.Path) -> List[Dict[str, Any]]:
    """
    Read a run's evidence log.
    """
    lines = (run_dir / "run-log.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _describe(event: Dict[str, Any]) -> str:
    """
    Turn one discovery event into a short caption, or "" to skip it.
    """
    kind = event["type"]
    summary = str(event.get("summary") or "")
    text = ""
    if kind == "sensitive_value_classified" and "provided by human" in summary:
        # The model asked for a credential by name; it never sees the value.
        name = summary.split()[1]
        text = f"request_secret({name}) - the model never sees the value"
    elif kind == "agent_action":
        # A UI action, already policy-checked.
        text = summary
    elif kind == "input_declared":
        # A typed input of the future capability.
        text = f"declare_input {event.get('name')} (sensitive: redacted)"
    elif kind == "extraction_recorded":
        # The answer, read from the screen.
        text = f"extract {event.get('name')} (redacted in evidence)"
    elif kind == "goal_complete":
        # The recording becomes a replayable capability.
        text = "goal_complete -> saved as a typed, replayable capability"
    return text


def _captions(events: List[Dict[str, Any]]) -> List[Tuple[str, List[str]]]:
    """
    Pair each screenshot with what happened before the next one.
    """
    frames: List[Tuple[str, List[str]]] = []
    for event in events:
        if event["type"] == "screenshot_saved":
            frames.append((str(event.get("file")), []))
        elif frames:
            text = _describe(event)
            if text:
                frames[-1][1].append(text)
    return frames


def _caption_frame(
    shot: pimage.Image, title: str, lines: List[str]
) -> pimage.Image:
    """
    Scale a screenshot and add a caption strip under it.
    """
    scale = _WIDTH / shot.width
    body = shot.convert("RGB").resize(
        (_WIDTH, int(shot.height * scale)), pimage.Resampling.LANCZOS
    )
    height = _CAPTION_H + 18 * max(0, len(lines) - 1)
    frame = pimage.new("RGB", (_WIDTH, body.height + height), _BG)
    frame.paste(body, (0, 0))
    draw = pdraw.Draw(frame)
    draw.text((14, body.height + 10), title, fill=_ACCENT, font=_font(15))
    for index, line in enumerate(lines or ["observe the screen"]):
        draw.text(
            (14, body.height + 32 + 18 * index),
            line[:96],
            fill=_FG,
            font=_font(14),
        )
    return frame


def _save(frames: List[pimage.Image], durations: List[int], name: str) -> None:
    """
    Write an optimised, looping GIF with frames padded to one size.
    """
    width = max(f.width for f in frames)
    height = max(f.height for f in frames)
    padded = []
    for frame in frames:
        canvas = pimage.new("RGB", (width, height), _BG)
        canvas.paste(frame, (0, 0))
        padded.append(
            canvas.quantize(colors=128, method=pimage.Quantize.MEDIANCUT)
        )
    _OUT.mkdir(parents=True, exist_ok=True)
    padded[0].save(
        _OUT / name,
        save_all=True,
        append_images=padded[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"wrote {_OUT / name} ({len(frames)} frames)")


def discovery_gif(run_dir: pathlib.Path) -> None:
    """
    Build the discovery GIF: one captioned frame per turn.
    """
    events = _events(run_dir)
    goal = next(e for e in events if e["type"] == "discovery_started")["goal"]
    frames: List[pimage.Image] = []
    durations: List[int] = []
    for turn, (file, lines) in enumerate(_captions(events), start=1):
        shot = pimage.open(run_dir / file)
        frames.append(
            _caption_frame(shot, f"discover - turn {turn} - {goal}", lines)
        )
        durations.append(1800)
    durations[-1] = 3500
    _save(frames, durations, "discovery.gif")


def replay_gif(run_dir: pathlib.Path) -> None:
    """
    Build the replay GIF: the steps appear one by one over the result.
    """
    events = _events(run_dir)
    shot_file = next(e for e in events if e["type"] == "screenshot_saved")["file"]
    shot = pimage.open(run_dir / str(shot_file))
    wanted = {
        "replay_started",
        "action_performed",
        "localized",
        "path_planned",
        "approval_resolved",
        "outputs_extracted",
        "replay_finished",
    }
    # The path list makes the first line too long to read; drop it.
    steps = [
        str(e["summary"]).split(", path", maxsplit=1)[0][:96]
        for e in events
        if e["type"] in wanted
    ]
    frames = [
        _caption_frame(shot, "replay - no model in the loop", steps[: i + 1])
        for i in range(len(steps))
    ]
    durations = [1200] * len(frames)
    durations[-1] = 4000
    _save(frames, durations, "replay.gif")


def _table(rows: List[Dict[str, Any]]) -> List[str]:
    """
    Render the per-scenario pass-rate table, single vs multi.
    """
    groups: Dict[Tuple[str, str], Dict[str, List[Dict[str, Any]]]] = (
        collections.defaultdict(lambda: collections.defaultdict(list))
    )
    for row in rows:
        groups[(row["family"], row["scenario"])][row["mode"]].append(row)
    lines = [f"{'family':<10}{'scenario':<24}{'single':>9}{'multi':>9}"]
    for (family, scenario), modes in sorted(groups.items()):
        cells = []
        for mode in ("single", "multi"):
            got = modes.get(mode, [])
            passed = sum(1 for r in got if r["passed"])
            cells.append(f"{passed}/{len(got)}" if got else "-")
        lines.append(f"{family:<10}{scenario:<24}{cells[0]:>9}{cells[1]:>9}")
    return lines


def evals_gif(results: pathlib.Path) -> None:
    """
    Build the evals GIF: the summary table typed out like a terminal.
    """
    rows = [
        json.loads(line)
        for path in str(results).split(",")
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines()
        if line
    ]
    lines = [
        "$ OPERANT_RUN_LLM_EVALS=1 uv run pytest tests/evals",
        f"  {len(rows)} trials - 3 app skins x single/multi agent",
        "",
        *_table(rows),
    ]
    font = _font(15)
    height = 24 * (len(lines) + 2)
    frames: List[pimage.Image] = []
    for shown in range(1, len(lines) + 1):
        frame = pimage.new("RGB", (_WIDTH, height), _BG)
        draw = pdraw.Draw(frame)
        for index, line in enumerate(lines[:shown]):
            colour = _ACCENT if index == 0 else (_MUTED if index == 1 else _FG)
            draw.text((16, 16 + 24 * index), line, fill=colour, font=font)
        frames.append(frame)
    durations = [700 if i < 3 else 180 for i in range(len(frames))]
    durations[-1] = 5000
    _save(frames, durations, "evals.gif")


_FRAME_MS = 700
_HOLD_MAX_MS = 2500


def demo_media(frames_dir: pathlib.Path) -> None:
    """
    Build the demo GIF and MP4 from the app window's recorded frames.

    Unchanged frames merge into one longer hold (capped, so a quiet wait
    does not stall the loop), which keeps the GIF small.
    """
    kept: List[pimage.Image] = []
    durations: List[int] = []
    for path in sorted(frames_dir.glob("frame-*.png")):
        frame = pimage.open(path).convert("RGB")
        frame = frame.resize(
            (_WIDTH, int(frame.height * _WIDTH / frame.width)),
            pimage.Resampling.LANCZOS,
        )
        if kept and not _changed(kept[-1], frame):
            durations[-1] = min(durations[-1] + _FRAME_MS, _HOLD_MAX_MS)
            continue
        kept.append(frame)
        durations.append(_FRAME_MS)
    durations[-1] = 4000
    _save(kept, durations, "demo.gif")
    _mp4(kept, durations, _OUT / "demo.mp4")


def _changed(first: pimage.Image, second: pimage.Image) -> bool:
    """
    Report whether any pixel differs (captures are pixel-exact).
    """
    return pchops.difference(first, second).getbbox() is not None


def _mp4(
    frames: List[pimage.Image], durations: List[int], out: pathlib.Path
) -> None:
    """
    Encode the frames with their hold times as an H.264 MP4 via ffmpeg.
    """
    with tempfile.TemporaryDirectory() as tmp:
        listing = []
        for index, (frame, ms) in enumerate(zip(frames, durations)):
            name = f"{index:05d}.png"
            frame.save(pathlib.Path(tmp) / name)
            listing += [f"file '{name}'", f"duration {ms / 1000:.3f}"]
        # The concat demuxer ignores the last duration without a repeat.
        listing.append(f"file '{len(frames) - 1:05d}.png'")
        (pathlib.Path(tmp) / "frames.txt").write_text("\n".join(listing))
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                "frames.txt",
                "-vf",
                "fps=10,format=yuv420p",
                "-c:v",
                "libx264",
                "-crf",
                "26",
                "-movflags",
                "+faststart",
                str(out),
            ],
            cwd=tmp,
            check=True,
        )
    print(f"wrote {out}")


def main() -> int:
    """
    Build whichever GIFs were asked for.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--discovery", type=pathlib.Path)
    parser.add_argument("--replay", type=pathlib.Path)
    parser.add_argument("--evals", type=pathlib.Path)
    parser.add_argument("--demo", type=pathlib.Path)
    args = parser.parse_args()
    if args.discovery:
        discovery_gif(args.discovery)
    if args.replay:
        replay_gif(args.replay)
    if args.evals:
        evals_gif(args.evals)
    if args.demo:
        demo_media(args.demo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
