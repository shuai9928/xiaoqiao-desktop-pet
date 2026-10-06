"""Offline source-scene preview of optional portrait depth, no user files/Tk."""
import argparse
import json
import math
from pathlib import Path

from PIL import Image

from scene_art import SceneArt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=Path(__file__).parent / "assets")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    scene = SceneArt(args.assets / "scene")
    k, scale = .32, .76
    scaled = scene.scaled(k)
    size = tuple(round(v * k) + 12 for v in scene.size)

    def render(theta, view):
        canvas = Image.new("RGBA", size)
        for key in ("static", "swing", "book", "crystal"):
            image, offset = scaled[key]
            if key == "swing":
                image, offset = scene.keystone(image, offset, k, theta, .12,
                                                portrait_view=view)
            canvas.alpha_composite(image, (round(offset[0]) + 6, round(offset[1]) + 6))
        return canvas

    frames = []
    for i in range(56):
        phase = i / 56 * math.tau
        # Use the main pet's bounded, quantized phase coupling.
        theta = round(.28 * math.sin(phase) / .008) * .008
        view = (max(-1.0, min(1.0, theta / .12)),
                max(-1.0, min(1.0, math.sin(theta) * 2.0)))
        im = render(theta, view)
        small = im.convert("RGBa").resize(tuple(round(v * scale) for v in size),
                                          Image.Resampling.LANCZOS).convert("RGBA")
        matte = Image.new("RGBA", small.size, (35, 31, 46, 255))
        matte.alpha_composite(small)
        frames.append(matte.convert("RGB"))
        if i in (0, 14, 28, 42):
            small.save(args.out / f"swing-depth-key-{i}.png")
    frames[0].save(args.out / "swing-depth-0.76.gif", save_all=True, append_images=frames[1:],
                   duration=100, loop=0, optimize=False, disposal=2)
    neutral = render(0, (0.0, 0.0))
    neutral.save(args.out / "swing-depth-normal.png")
    metadata = {"scope": "素材场景离线渲染；GIF用深色桌面底，PNG透明；无在线UI/用户数据",
                "normal_size": size, "small_size": frames[0].size, "scale": scale,
                "max_hat_hair_shift_pixels": 1.216, "face_shift_pixels": (.192, .096),
                "fixed": "挂点/握绳手/绳索/身体/臀/坐垫；不切层、不补侧脸",
                "optional": "keystone(...,portrait_view=(vx,vy)); 默认None完全保留原行为"}
    (args.out / "swing-depth-verification.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=True))


if __name__ == "__main__":
    main()
