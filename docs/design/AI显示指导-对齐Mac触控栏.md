# 小乔的 AI 显示·对齐 Mac 触控栏（指导文档）

写给在这台机器上干活、负责小乔的 AI：Mac 那边的触控栏已经把「显示各种 AI」做成了一套完整设计，
你（小乔这边）已经做了大半，本文档是差距盘点 + 剩余工作的具体做法。**已经做对的别推翻**，
下面每一条都先说「现状」再说「要做什么」。

## 你已经有的（都保留，别重写）

- `ai_sessions/*.json` 会话灯：zcode / wslcodex / mac-claude / mac-codex 四路都有，状态机、
  颜色（橙=等你、红=出错、紫=在跑、绿=刚完成、空心=空闲）和呼吸/闪烁节奏都对。
- `mac_session_sync.py` 走 WSL `ssh mac` 拉会话状态——**Mac 侧刚加了新字段，你不用改这个脚本**（见下）。
- `zcode_notify.py`：本机 ZCode 的 hook → 灯 + 播报，permission 时才把她拉起来，分寸是对的。
- 头顶思维链（`ai_chain_lines`）：标题 + 最多 3 条动作，播报限频（同类 120 秒、全局 40 秒、睡着不吵）——规则保持。

## Mac 侧刚做完的（你只管享用）

Mac 的 AIQuota 会话状态文件（`~/Library/Application Support/AIQuota/sessions/`，`mac_session_sync.py`
拉的就是它们）从 2026-09-30 起多了两个字段：

```json
{
  "id": "…", "agent": "claude", "state": "running", "title": "…", "updated": 1790818761.87,
  "actions": ["读 Pet.swift", "命令 git status", "跑测试 test.sh"]
}
```

`actions` 是主代理这一轮最近做成的动作，新的在前、最多 3 条、新一轮自动清空、子代理的不记。
分类口径和 Mac 触控栏路线图一致：读/改/写/跑测试/构建/命令/搜索/查网页/子代理。
你的 `scan_ai_sessions` 已经在读 `actions` 了——**同步一开，小乔头顶的思维链就是真动作，不再是状态词**。
唯一要做的：确认 `mac_session_sync.py` 拉回的文件没把 actions 丢掉（它是整份 JSON 拷贝，理论上有就行），
然后跑一次验证（见文末验收）。

## 差距清单（按优先级，逐条给做法）

### 1. 灯的排序：按紧急度，不按时间

现状 `scan_ai_sessions` 按 `updated` 降序取最新 5 个。Mac 的规则是**等你的 > 出错的 > 刚完成的 > 在跑的 > 空闲**，
同组里才按先后排。理由：等你批准的灯被别的会话的新动作挤掉，是会耽误事的。
改法：`out.sort` 前先按 `AI_SESSION_STATES` 的反向紧急度分桶（waiting=0, error=1, done=2, running=3, idle=4），
桶内按 updated 降序。

### 2. 额度：把 AIQuota.exe 的百分比接进小乔

现状：Windows 的 AIQuota.exe（`%LOCALAPPDATA%\AIQuota`）自己显示 Claude/Codex 的 5 小时和每周百分比，
但小乔不知道。做法分两半：

- **AIQuota.cs 侧**（源码在 Mac 上 `ai-quota/win/AIQuota.cs`，改完在 Mac 上跑 `win/deploy.sh` 部署）：
  每次刷新成功后把数据落盘到 `%LOCALAPPDATA%\AIQuota\usage.json`：
  ```json
  {"updated": 1790818761.0,
   "providers": [{"name": "Codex", "plan": "Plus",
                  "windows": [{"label": "5小时", "used": 23.0, "reset": "2026-10-01T05:48:00+08:00"},
                              {"label": "本周", "used": 82.0, "reset": null}]}]}
  ```
  就多一个 `File.WriteAllText`，别加锁别加线程。
- **小乔侧**：读 `usage.json`（和 ai_sessions 一样限频扫描）。
  气泡台词加两条：某个窗口 ≥95% 且知道重置时间 → 「Codex 本周已用 82%，照这速度今晚就用完啦」
  （只提一句，同类 2 小时内不重复）；到重置时间 → 「Codex 的 5 小时额度回来了，可以继续了」。
  卡片/菜单里可以列一行额度，别做成常驻——她身上已有灯和思维链，再挂满数字就吵了。

### 3. ZCode 的 token 记账

Mac 侧刚给触控栏加了「今日 / 近 7 天 token 用量」，数据源是 ZCode 会话库的 `turn_usage` 表。
这台机器的 ZCode 库在 `C:\Users\user\.zcode\cli\db\db.sqlite`，SQL 现成：

```sql
SELECT total(input_tokens + output_tokens) FROM turn_usage WHERE started_at >= :since_ms;
```

今日 = 本地零点起的毫秒时间戳；近 7 天 = now - 7*86400*1000。**只读连接**（`file:...?mode=ro`），
库被 ZCode 占着时读失败就静默跳过。展示放右键菜单的「AI 状态」卡里一行即可
（「今天 2.4亿 tokens · 7天 8.1亿」），不要上她头顶——头顶留给思维链。

### 4. 播报的两条补充（可选，先做 1 和 2）

- 「做完叫我」的等价物：等你批准时她已经会拉起自己说话 ✓；再加一种——**同一会话从 running 变 done 且
  之前说过「工作中」**，说一句就够（已有 done 台词 ✓，确认它对 mac-claude 也生效，不只本机 zcode）。
- 灯的语义对齐：Mac 的 running 是暗实心（余光知道在跑就行），你用了紫色呼吸——**保留你的版本**，
  这属于小乔的性格，不必像素级照抄。紧急度排序（第 1 条）才是要对齐的。

## 不要做的

- 不要把小乔做成第二个悬浮额度窗（AIQuota.exe 已经干了这件事，她只负责「说人话」）。
- 不要替用户点任何确认框——Mac 侧的共识是「只报告，不代按」，hooks 里 PermissionRequest 的
  脚本不输出任何东西，弹窗照常弹。
- 不要为扫描加轮询线程——沿用「2 秒限频 + 主循环里扫」的现有节奏。

## 验收清单

1. Mac 上让一个 AI 跑起来 → 30 秒内小乔头顶出现思维链（标题 + 真实动作，如「读 xxx.swift」），不是状态词。
2. 同一会话跑完 → 绿灯 90 秒后转空心，气泡说「Mac 的任务干完啦」一类。
3. 人为在 Mac 上停在一个权限确认框 → 小乔橙灯急闪 + 播报，且排在其他灯前面。
4. 改 AIQuota.cs 部署后 → `%LOCALAPPDATA%\AIQuota\usage.json` 存在且随刷新更新，≥95% 时小乔说一次额度。
5. 右键「AI 状态」能看到今日/7天 token 数，ZCode 正在跑时数字会涨。
6. 以上全部进行时，她睡着时不被吵醒（灯照常更新、不播报）。

—— Mac 侧对接人：ZCode（Mac 上的触控栏项目在 `~/Documents/Codex/2026-09-26/ni/work/ai-quota`，
有 git，口径问题以 README.md 为准）。
