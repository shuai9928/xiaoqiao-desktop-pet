"""Export the actual room renderer's depth views and a short motion preview."""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import argparse
import json
import math
from pathlib import Path
import shutil
import statistics
import time

from PIL import Image, ImageDraw, ImageFont

from room_preview import RoomSceneRenderer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    renderer = RoomSceneRenderer(Path(__file__).resolve().parents[2] / "assets")
    frames, times, manifest = [], [], {}
    for i in range(48):
        phase = i / 48 * math.tau
        view = (math.sin(phase), .4 * math.sin(phase+.5))
        lag = (math.sin(phase-.15), .4 * math.sin(phase+.35))
        start = time.perf_counter()
        image, rects = renderer.render(1.0, view, lag, .85*math.sin(phase))
        times.append((time.perf_counter()-start)*1000)
        canvas = Image.new("RGB", image.size, "#1b1629")
        canvas.paste(image, mask=image.getchannel("A"))
        frames.append(canvas)
        if i in (0, 12, 24, 36):
            name = f"depth-key-{i}.png"
            image.save(out/name)
            manifest[name] = {"view": view, "entrances": rects}
    frames[0].save(out/"room-depth-demo.gif", save_all=True, append_images=frames[1:],
                   duration=100, loop=0, optimize=False)
    neutral, rects = renderer.render()
    neutral.save(out/"room-normal.png")
    small, _ = renderer.render(.76)
    small.save(out/"room-0.76.png")
    old = out.parent/"codex-room"/"room-normal.png"
    if old.exists():
        shutil.copy2(old, out/"before.png")
        compare = Image.new("RGB", (840, 550), "#1b1629")
        with Image.open(old) as original:
            compare.paste(original, (10, 40), original)
        compare.paste(neutral, (430, 40), neutral)
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
        d = ImageDraw.Draw(compare)
        d.text((24, 10), "上一版", font=font, fill="#bbaec7")
        d.text((444, 10), "空间感增强 · 相同400×500尺寸", font=font, fill="#f3e5d1")
        compare.save(out/"before-after.png")
    warm = []
    for i in range(12):
        start=time.perf_counter();renderer.render(1.0,(0,0),(0,0),i/12)
        warm.append((time.perf_counter()-start)*1000)
    report = {"frames":48,"duration_seconds":4.8,"manifest":manifest,
              "moving_render_median_ms":round(statistics.median(times),1),
              "stationary_render_median_ms":round(statistics.median(warm),1),
              "scope":"Actual renderer output; GUI rendering uses a latest-frame background worker."}
    (out/"depth-verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "manifest"},ensure_ascii=False))


if __name__ == "__main__":
    main()
