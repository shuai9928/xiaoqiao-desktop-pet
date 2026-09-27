# -*- coding: utf-8 -*-
"""agent.py 回归:意图解析口语覆盖 + 提醒解析 + 索引节流。

全部确定性(不碰网络/不耗 AI 配额/不弹窗),随时可跑:

    py test_agent.py
"""
import os
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

import agent

RESULTS = []


def check(name, cond):
    RESULTS.append(("PASS " if cond else "FAIL ") + name)
    return cond


def main():
    # ---- 1. 意图解析口语覆盖 ----
    # 使用说明里写明的招牌用法 + 语序变体 + 不该误伤的抬杠句。
    # 「来个番茄钟」曾被 open 的「来一个」抢先误判成"打开番茄钟";
    # 「5分钟后提醒我喝水」曾漏给 AI 兜底(多一次调用一秒延迟)。
    cases = [
        ("帮我打开微信", "open"), ("微信打开一下", "open"), ("启动钉钉", "open"),
        ("把学习通卸载掉", "uninstall"), ("关闭QQ", "close"), ("QQ关掉", "close"),
        ("搜索一下天气", "search"), ("帮我找个报告.pdf", "find_file"),
        ("打开下载文件夹", "folder"), ("打开一个网页", "open"),
        ("来一个拥抱", "open"),
        ("5分钟后提醒我喝水", "remind"), ("半小时后提醒我开会", "remind"),
        ("提醒我10分钟后站起来", "remind"), ("2小时后提醒我关空调", "remind"),
        ("30秒后提醒我切茶", "remind"),
        ("来个番茄钟", "pomo"), ("番茄钟", "pomo"),
        ("翻译剪贴板", "translate"), ("总结一下剪贴板", "clipboard"),
        # 抬杠保护:这些必须原样交给 AI,不能被本地规则误吞
        ("别跳舞", None), ("今天心情不好", None), ("你是谁", None),
        ("提醒我喝水", None),      # 没有时长:不是合法的本地提醒
        ("番茄钟有什么用", None),   # 问句不是指令
    ]
    hit = 0
    misses = []
    for text, want in cases:
        got = agent.parse(text)
        kind = got["kind"] if got else None
        ok = (kind is None) if want is None else (kind == want)
        if ok:
            hit += 1
        else:
            misses.append(f"{text!r} -> {kind} (期望 {want})")
    check(f"意图: 口语覆盖 {hit}/{len(cases)} {misses or ''}",
          hit == len(cases))

    # ---- 1b. 勿扰指令 ----
    # 「关闭勿扰」「打开勿扰」曾会被通用 open/close 规则当成开关一个叫「勿扰」
    # 的程序;「别吵」带否定词,不在本地接住就会整句交给 AI。
    dnd = [
        ("勿扰", "on", None), ("打开勿扰", "on", None), ("开启勿扰模式", "on", None),
        ("安静一会儿", "on", None), ("别吵我", "on", None), ("小乔,别说话了", "on", None),
        ("勿扰一小时", "on", 60.0), ("安静半小时", "on", 30.0), ("勿扰 2 小时", "on", 120.0),
        ("安静30分钟", "on", 30.0),
        ("关闭勿扰", "off", None), ("结束勿扰", "off", None), ("取消勿扰模式", "off", None),
        ("可以说话了", "off", None),
    ]
    got = [(t, agent.parse(t)) for t, _, _ in dnd]
    bad = [f"{t!r} -> {r and (r['kind'], r.get('target'), r.get('minutes'))}"
           for (t, want, mins), (_, r) in zip(dnd, got)
           if not (r and r["kind"] == "dnd" and r["target"] == want
                   and r.get("minutes") == mins)]
    check(f"勿扰: 开关与时长 {len(dnd) - len(bad)}/{len(dnd)} {bad or ''}", not bad)
    keep = ["安静地陪我写作业", "勿扰是什么意思", "别吵架", "安静的音乐"]
    stolen = [t for t in keep if agent.parse(t)]
    check(f"勿扰: 不误吞普通句子 {stolen or ''}", not stolen)

    # ---- 2. 提醒解析的分钟数换算 ----
    probes = [
        ("5分钟后提醒我喝水", 5.0, "喝水"),
        ("半小时后提醒我开会", 30.0, "开会"),
        ("提醒我10分钟后站起来", 10.0, "站起来"),
        ("2小时后提醒我关空调", 120.0, "关空调"),
        ("30秒后提醒我切茶", 0.5, "切茶"),
    ]
    for text, want_min, want_target in probes:
        r = agent._remind_parse(text)
        check(f"提醒: {text!r} -> {want_min}分钟/{want_target!r}",
              r == (want_min, want_target))

    # ---- 3. 应用索引的 notfound 节流重扫 ----
    # 用临时快捷方式测试真实索引逻辑，不依赖电脑是否安装微信。
    with tempfile.TemporaryDirectory(prefix="xiaoqiao-index-") as folder:
        shortcut = Path(folder) / "WeChat.lnk"
        shortcut.touch()  # 只索引名称，不读取或启动快捷方式。
        index = agent.AppIndex()
        with (patch.object(agent, "_INDEX", index),
              patch.object(agent, "_START_MENU", [folder]),
              patch.object(agent.os, "listdir", return_value=[]),
              patch.object(agent.time, "time", return_value=1000.0) as clock,
              patch.object(index, "build", wraps=index.build) as build):
            index.build()
            st, _ = agent.resolve_app("绝对不存在的软件xyzzy")
            rescans = lambda: sum(c.kwargs.get("force", False)
                                  for c in build.call_args_list)
            check("索引: notfound 时索引未超龄则不重扫",
                  st == "notfound" and index.built_at == 1000.0
                  and rescans() == 0)
            clock.return_value = 2000.0
            st, _ = agent.resolve_app("绝对不存在的软件xyzzy")
            check("索引: 超龄后 notfound 触发一次重扫",
                  index.built_at == 2000.0 and st == "notfound"
                  and rescans() == 1)
            clock.return_value = 3000.0  # 即使索引超龄，命中也不应重扫。
            st, data = agent.resolve_app("微信")
            check("索引: 常规命中不受节流影响",
                  st == "ok" and data == ("WeChat", str(shortcut))
                  and index.built_at == 2000.0 and rescans() == 1)

    # ---- 汇总 ----
    bad = [r for r in RESULTS if r.startswith("FAIL") or r.startswith("ERROR")]
    for r in RESULTS:
        print(r)
    print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
