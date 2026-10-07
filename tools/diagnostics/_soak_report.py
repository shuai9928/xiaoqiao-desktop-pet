# -*- coding: utf-8 -*-
"""浸泡监控报告:读 soak_monitor.log 出一份内存趋势分析。

    py _soak_report.py

判定:最大最小差 > 150MB 且末段明显高于前段 -> 可疑(再查);
缓存预热带来的前期上涨属正常(warp 缓存按需填充)。
"""

from pathlib import Path
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))

import statistics
import sys

LOG = os.path.join(str(Path(__file__).resolve().parents[2]),
                   "soak_monitor.log") if (os := __import__("os")) else "soak_monitor.log"


def main():
    try:
        # utf-8-sig:PowerShell 的 Add-Content UTF8 会在首行写 BOM
        with open(LOG, encoding="utf-8-sig") as f:
            rows = [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        print("还没有采样数据(soak_monitor.log 不存在)。")
        return 1
    samples = []
    for ln in rows:
        parts = ln.split(",")
        if len(parts) >= 5 and parts[2].isdigit():
            samples.append((parts[0], parts[1], int(parts[2]),
                            int(parts[3] or 0), float(parts[4] or 0)))
    running = [s for s in samples if s[1] != "not-running"]
    down = len(samples) - len(running)
    print(f"采样 {len(samples)} 条(其中 {down} 条桌宠未运行)")
    if not running:
        print("没有有效样本。")
        return 1
    rss = [s[2] for s in running]
    print(f"内存: 首采 {rss[0]}MB | 最低 {min(rss)}MB | 最高 {max(rss)}MB | "
          f"中位 {statistics.median(rss):.0f}MB | 末采 {rss[-1]}MB")
    handles = [s[3] for s in running]
    print(f"句柄: 最低 {min(handles)} | 最高 {max(handles)}")
    # 观察窗口用墙钟差:运行时长在中途重启后会回退,直接相减会出负数
    from datetime import datetime
    t0 = datetime.strptime(running[0][0], "%Y-%m-%d %H:%M:%S")
    t1 = datetime.strptime(running[-1][0], "%Y-%m-%d %H:%M:%S")
    span_h = (t1 - t0).total_seconds() / 3600
    print(f"观察窗口: {span_h:.1f} 小时")
    growth = max(rss) - min(rss)
    tail = statistics.mean(rss[-max(1, len(rss) // 4):])
    head = statistics.mean(rss[:max(1, len(rss) // 4)])
    verdict = "健康(波动在缓存预热范围内)" if growth <= 150 else \
        f"可疑:波动 {growth}MB 且尾段均值 {tail:.0f}MB > 头段 {head:.0f}MB —— 建议继续观察或抓泄漏"
    print(f"波动: {growth}MB | 头段均值 {head:.0f}MB vs 尾段均值 {tail:.0f}MB")
    print(f"结论: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
