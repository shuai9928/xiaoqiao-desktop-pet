# -*- coding: utf-8 -*-
"""ZCode hook -> 小乔播报。

ZCode 在 ~/.zcode/cli/config.json 的 hooks 里配置(process 类型):
    Stop             -> ZCode 每轮回答结束时:python zcode_notify.py stop
    PermissionRequest-> ZCode 弹确认框等你点头:python zcode_notify.py permission

stdin 会收到 hook 的 JSON 输入,这里不解析、直接忽略。播报通过写
pet_cmd.json 的 {"op":"announce"} 实现,桌宠渲染循环每帧检测 mtime,
她在桌面右下角冒个气泡就把话带到了——桌宠没开时写文件也无害。
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CMD = os.path.join(HERE, "pet_cmd.json")
STATE = os.path.join(HERE, ".zcode_hook_state.json")

STOP_LINES = [
    "主人忙完一段啦,歇会儿眼睛~",
    "搞定一段!剩下的我来陪你~",
    "呼——干完一段了,伸个懒腰吧",
    "任务告一段落,记得喝水哦",
]
PERM_LINES = [
    "主人!ZCode 有确认框等你点头!",
    "喂喂,快去点一下确认,人家等着呢~",
    "有个弹窗在等你批准,快去看看!",
]


def announce(text, emotion="happy"):
    try:
        # 原子替换:桌宠按 mtime 轮询本文件,直接 open("w") 会让它读到
        # 写了一半的 JSON,这条播报就丢了
        tmp = CMD + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"op": "announce", "text": text, "emotion": emotion},
                      f, ensure_ascii=False)
        os.replace(tmp, CMD)
    except Exception:
        pass  # 桌宠不在/盘不可写都无所谓,hook 不能因此报错


def main():
    event = (sys.argv[1] if len(sys.argv) > 1 else "stop").lower()
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    if event == "permission":
        # 要人点头的事不限频,漏一次就可能干等
        announce(random.choice(PERM_LINES), "surprised")
        return 0

    # stop:3 分钟最多播一次,不然每轮回答结束都吵一句
    now = time.time()
    try:
        last = json.load(open(STATE, encoding="utf-8")).get("last_stop", 0)
    except Exception:
        last = 0.0
    if now - last < 180:
        return 0
    try:
        json.dump({"last_stop": now}, open(STATE, "w", encoding="utf-8"))
    except Exception:
        pass
    announce(random.choice(STOP_LINES), "happy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
