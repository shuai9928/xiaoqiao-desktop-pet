# -*- coding: utf-8 -*-
"""把下载的 CC0 音效预处理成桌宠用的 WAV(44.1kHz/16bit/单声道,按类别做峰值归一化)。

MCI 的 waveaudio 设备不支持运行时调音量,所以目标响度在这里烘焙进文件:
  voice  -> peak 0.40 (约 -8 dBFS)  小乔自己的声音,最突出但不炸
  magic  -> peak 0.28 (约 -11 dBFS) 施法闪烁,做背景层
  blip   -> peak 0.18 (约 -15 dBFS) UI 提示音,点到为止
"""
import math
import re
import subprocess
import sys
import os

DL = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DL, "..", "assets", "audio")
VOICE = os.path.join(DL, "voice", "RPG Voice Starter Pack", "Type 1")
KEN = os.path.join(DL, "kenney", "Audio")

# 行内注释别写在字典字面量中间 —— 它会把后面的 } 一起吃掉,整个文件都编译不了。
TARGET_DB = {
    "voice": -8.0,   # 历史遗留:人声已改由 gen_voice.py 生成,这里不再用
    "magic": -11.0,
    "blip": -15.0,
}

# (源文件, 类别, 输出名)
JOBS = [
    # ---- 魔法闪烁(CC0, Magic Spell SFX by JaggedStone)----
    (f"{DL}/magical_1.ogg", "magic", "magic_1"),
    (f"{DL}/magical_2.ogg", "magic", "magic_2"),
    (f"{DL}/magical_3.ogg", "magic", "magic_3"),
    (f"{DL}/magical_5.ogg", "magic", "magic_4"),
    (f"{DL}/magical_6.ogg", "magic", "magic_5"),
    (f"{DL}/magical_7.ogg", "magic", "magic_6"),
    # ---- 柔和 UI 音(CC0, Kenney Interface Sounds)----
    (f"{KEN}/bong_001.ogg",         "blip", "boing_1"),
    (f"{KEN}/glass_001.ogg",        "blip", "sparkle_1"),
    (f"{KEN}/glass_003.ogg",        "blip", "sparkle_2"),
    (f"{KEN}/glass_005.ogg",        "blip", "sparkle_3"),
    (f"{KEN}/minimize_001.ogg",     "blip", "sleep_1"),
    (f"{KEN}/minimize_002.ogg",     "blip", "sleep_2"),
    (f"{KEN}/maximize_001.ogg",     "blip", "wake_1"),
    (f"{KEN}/maximize_002.ogg",     "blip", "wake_2"),
    (f"{KEN}/confirmation_001.ogg", "blip", "levelup_1"),
    (f"{KEN}/confirmation_003.ogg", "blip", "levelup_2"),
    (f"{KEN}/pluck_001.ogg",        "blip", "pop_1"),
    (f"{KEN}/pluck_002.ogg",        "blip", "pop_2"),
    (f"{KEN}/question_001.ogg",     "blip", "greet_1"),
    (f"{KEN}/question_003.ogg",     "blip", "greet_2"),
    (f"{KEN}/close_001.ogg",        "blip", "bye_1"),
    (f"{KEN}/close_003.ogg",        "blip", "bye_2"),
    (f"{KEN}/tick_001.ogg",         "blip", "tick_1"),
    (f"{KEN}/tick_002.ogg",         "blip", "tick_2"),
]


def peak_db(src):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", src,
         "-map", "a", "-af", "astats=metadata=1:reset=0", "-f", "null", "-"],
        capture_output=True, text=True)
    vals = [float(m) for m in
            re.findall(r"Peak level dB:\s*(-?[\d.]+)", r.stderr)]
    return max(vals) if vals else None


def main():
    os.makedirs(OUT, exist_ok=True)
    fail = 0
    for src, cat, name in JOBS:
        tgt = TARGET_DB[cat]
        try:
            pdb = peak_db(src)
            gain = 0.0 if pdb is None else round(tgt - pdb, 2)
            dst = os.path.join(OUT, name + ".wav")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", src,
                 "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
                 "-af", f"volume={gain}dB", dst],
                check=True)
            print(f"{name}.wav  [{cat}] {os.path.basename(src)}  "
                  f"peak {pdb} dB -> gain {gain} dB")
        except Exception as e:
            fail += 1
            print(f"FAIL {name}: {e}", file=sys.stderr)
    print("done, failures:", fail)


if __name__ == "__main__":
    main()
