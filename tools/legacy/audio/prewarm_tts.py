# -*- coding: utf-8 -*-
"""把小乔的固定台词先合成好塞进 _tts_cache,聊天时这些句子就不用等网络。

pet.py 的 _speak() 是按「文本 -> md5 -> mp3」缓存的,所以这里只要用完全
相同的 voice/pitch/rate 和同一套 key 生成文件,运行时自然就命中了。
顺带:预热过的句子在断网时也能正常发声(未预热的会退回系统 SAPI 机器音)。

用法(在项目根目录):
    _sfx_dl\\ttsvenv\\Scripts\\python.exe _sfx_dl\\prewarm_tts.py
"""
import ast
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
PET = os.path.join(ROOT, "pet.py")
PY = os.path.join(HERE, "ttsvenv", "Scripts", "python.exe")

# 从 pet.py 里直接读常量,不 import —— import 会连带执行 DPI 设置等副作用。
WANT_STR = ("TTS_VOICE", "TTS_PITCH", "TTS_RATE", "HELP")
WANT_LIST = ("GREET", "IDLE_SAY", "TICKLE_SAY", "HUNGRY_SAY",
             "WAKE_LINES", "STROKE_LINES", "CAST_LINES")


def read_consts():
    tree = ast.parse(open(PET, encoding="utf-8").read())
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in WANT_STR + WANT_LIST:
                try:
                    out[t.id] = ast.literal_eval(node.value)
                except Exception:
                    pass
    missing = [k for k in WANT_STR if k not in out]
    if missing:
        sys.exit(f"pet.py 里没找到:{missing}")
    return out


def main():
    c = read_consts()
    voice, pitch, rate = c["TTS_VOICE"], c["TTS_PITCH"], c["TTS_RATE"]
    cache = os.path.join(ROOT, "_tts_cache")
    os.makedirs(cache, exist_ok=True)

    lines = [c["HELP"]]
    for k in WANT_LIST:
        lines += list(c.get(k, []))
    # 和 _speak() 的清洗规则保持一致,否则算出来的 md5 对不上
    lines = [" ".join(str(x).split())[:120] for x in lines]
    lines = sorted({x for x in lines if x})

    ok = hit = fail = 0
    for text in lines:
        key = hashlib.md5(
            f"{voice}|{pitch}|{rate}|{text}".encode("utf-8")).hexdigest()
        dst = os.path.join(cache, key + ".mp3")
        if os.path.exists(dst) and os.path.getsize(dst) > 1000:
            hit += 1
            print(f"  已有  「{text}」")
            continue
        tmp = dst + ".part"
        r = subprocess.run(
            [PY, "-m", "edge_tts", f"--voice={voice}", f"--pitch={pitch}",
             f"--rate={rate}", f"--text={text}", f"--write-media={tmp}"],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
            os.replace(tmp, dst)
            ok += 1
            print(f"  合成  「{text}」")
        else:
            fail += 1
            if os.path.exists(tmp):
                os.remove(tmp)
            print(f"  失败  「{text}」 {r.stderr[-120:]}", file=sys.stderr)
    print(f"\n共 {len(lines)} 句:新合成 {ok},已有 {hit},失败 {fail}")
    print("缓存目录:", cache)


if __name__ == "__main__":
    main()
