import hashlib
import json
import pathlib
import subprocess
import sys

from mario_eval.simulation import MarioSimulator

if len(sys.argv) != 3:
    raise SystemExit("Usage: render_replay.py EPISODE_JSONL OUTPUT_DIRECTORY")
source = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
es = [json.loads(l) for l in source.read_text().splitlines()]
start = es[0]
assert start["env"] == "SuperMarioBros-1-1-v0", "Renderer expects stage 1-1"
assert all(e["metadata"]["model"] == "zoom-decisions" for e in es if e["event"] == "ranking"), (
    "Renderer expects standard Decisions log"
)
executions = [e for e in es if e["event"] == "execution"]


def stamp(frames):
    ms = round(frames * 1000 / 60)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


sub = []
frames = 0
for i, e in enumerate(executions, 1):
    end = frames + len(e["actions"])
    label = e["candidate"].replace("_", " + ")
    sub.append(
        f"{i}\n{stamp(frames)} --> {stamp(end)}\nZoom Decisions | stage 1-1\nDecision {i}/{len(executions)}: {label}\nRecorded replay: API/simulation waits omitted\n"
    )
    frames = end
sub.append(
    f"{len(executions) + 1}\n{stamp(frames)} --> {stamp(frames + 120)}\nZoom Decisions | stage 1-1 CLEARED\nRecorded replay: API/simulation waits omitted\n"
)
srt = out / "decisions-stage-1-1-replay.srt"
srt.write_text("\n".join(sub))
ass = out / "decisions-stage-1-1-replay.ass"
header = """[Script Info]
ScriptType: v4.00+
PlayResX: 768
PlayResY: 840
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,22,&H00FFFFFF,&H00FFFFFF,&H00111827,&H00111827,0,0,0,0,100,100,0,0,1,1,0,8,12,12,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(frame):
    cs = round(frame * 100 / 60)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


lines = []
cursor = 0
for i, e in enumerate(executions, 1):
    end = cursor + len(e["actions"])
    caption = f"Zoom Decisions | stage 1-1\\NDecision {i}/{len(executions)}: {e['candidate']}\\NRecorded replay: API/simulation waits omitted"
    lines.append(
        f"Dialogue: 0,{ass_time(cursor)},{ass_time(end)},Default,,0,0,0,,{{\\an8\\pos(384,10)}}{caption}"
    )
    cursor = end
lines.append(
    f"Dialogue: 0,{ass_time(cursor)},{ass_time(cursor + 120)},Default,,0,0,0,,{{\\an8\\pos(384,10)}}Zoom Decisions | stage 1-1 CLEARED\\NRecorded replay: API/simulation waits omitted"
)
ass.write_text(header + "\n".join(lines) + "\n")
video = out / "decisions-stage-1-1-replay.mp4"
sim = MarioSimulator(start["env"], start["seed"])
proc = None
try:
    assert sim.digest() == start["initial_digest"]
    h, w = sim.frame.shape[:2]
    vf = f"scale=768:720:flags=neighbor,pad=768:840:0:120:color=0x111827,ass={ass},fps=30"
    proc = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{w}x{h}",
            "-framerate",
            "60",
            "-i",
            "pipe:0",
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(video),
        ],
        stdin=subprocess.PIPE,
    )
    for e in executions:
        assert sim.digest() == e["before_digest"]
        for action in e["actions"]:
            sim.step(action)
            proc.stdin.write(sim.frame.tobytes())
        assert sim.digest() == e["after_digest"]
    assert sim.clear and sim.digest() == es[-1]["final_digest"]
    for _ in range(120):
        proc.stdin.write(sim.frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    (out / "replay-manifest.json").write_text(
        json.dumps(
            {
                "source_run": source.parent.name,
                "source_log": source.name,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "model": next(e["metadata"]["model"] for e in es if e["event"] == "ranking"),
                "depth": start["simulation"]["continuation_depth"],
                "seed": start["seed"],
                "verified_gameplay_frames": frames,
                "hold_frames": 120,
                "clear": sim.clear,
                "decision_count": len(executions),
                "note": "Frame-by-frame recorded-control replay, rendered at 30 fps from 60 emulator fps. API and simulation waits omitted; final frame held two seconds. No fresh API calls.",
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "Verified frames",
        frames,
        "decisions",
        len(executions),
        "clear",
        sim.clear,
        "bytes",
        video.stat().st_size,
    )
finally:
    sim.close()
    if proc and proc.poll() is None:
        proc.kill()
        proc.wait()
