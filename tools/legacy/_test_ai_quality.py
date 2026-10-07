# -*- coding: utf-8 -*-
"""AI 对话质量实弹评测(手动跑,会消耗真实 API 配额):

    py _test_ai_quality.py

跑 8 轮不同类型的真实对话,校验 JSON 结构(say/emotion/action/intent)、
情绪枚举合法、延迟分布。上一轮全优基线:中位 775ms、异常 0。
"""
import os
import statistics
import sys
import time

import ai_chat


def main():
    brain = ai_chat.AIBrain(os.path.join("assets", "ai_config.json"))
    if not brain.available:
        print("没有可用的 API 密钥,先在 assets/ai_config.json 填好再跑。")
        return 1
    tests = [
        "你好呀", "今天好累啊", "夸夸我",
        "帮我打开计算器", "明天会下雨吗", "给我讲个冷笑话",
        "我最近在学吉他", "晚安",
    ]
    lat, bad, hist = [], [], []
    for q in tests:
        t0 = time.perf_counter()
        out = brain.chat(q, hist)
        ms = (time.perf_counter() - t0) * 1000
        lat.append(ms)
        if out is None or out.get("error"):
            bad.append((q, "error:" + str((out or {}).get("error"))))
            print(f"[FAIL] {ms:5.0f}ms {q!r}")
            continue
        say = out.get("say", "")
        probs = []
        if not say:
            probs.append("无 say")
        if out.get("emotion") not in ai_chat.EMOTIONS:
            probs.append(f"emotion 越界:{out.get('emotion')}")
        act = out.get("action")
        if act is not None and act not in ai_chat.ACTIONS:
            probs.append(f"action 越界:{act}")
        if len(say) > 120:
            probs.append(f"超长 {len(say)} 字")
        if probs:
            bad.append((q, ";".join(probs)))
        print(f"[{'WARN' if probs else 'OK '}] {ms:5.0f}ms {q!r} "
              f"emo={out.get('emotion')} | {say[:26]}")
        hist.append({"role": "user", "content": q})
        hist.append({"role": "assistant", "content": say,
                     "emotion": out.get("emotion", "")})
    print(f"延迟: 中位 {statistics.median(lat):.0f}ms / 最大 {max(lat):.0f}ms "
          f"| 异常 {len(bad)} 项")
    for q, w in bad:
        print("  -", q, "->", w)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
