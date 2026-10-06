# 小乔 AI 显示：数据层已经接好，桌宠这边还差几件（Claude → 正在改小乔的 AI）

项目：C:\Users\user\.zcode\workspace\default\xiaoqiao-2.5d（WSL：/mnt/c/Users/user/.zcode/workspace/default/xiaoqiao-2.5d）
写于 2026-10-01 11:15 CST。**pet.py 我一行没动**，下面「要你做的」都在 pet.py 里。

## 先说结论：数据都到位了

| 灯的来源 | 写入方 | 现在的样子 |
|---|---|---|
| 本机 ZCode | zcode_notify.py（hook） | 状态 + 最近 3 步，步骤写成人话（「读 pet.py」「跑测试 pytest」「命令 git status」） |
| WSL 的 Codex | ~/.local/bin/xiaoqiao-lights-hook.py（= wsl_lights_hook.py 的拷贝，旁边放 ai_lights_core.py） | 同上 |
| Mac（Claude / Codex / ZCode） | mac_session_sync.py --loop（pythonw 在跑） | 状态 + 最近 3 步 + 这一轮的整条路线（steps） |
| 额度 | Windows 的 AIQuota.exe 每 20 秒写 %LOCALAPPDATA%\AIQuota\usage.json | Claude、Codex、Codex WSL 每个窗口的百分比和重置时间 |

**更正之前那份《AI显示指导-对齐Mac触控栏.md》**：它说 Mac 状态文件里的 actions 由 hook 写、「你只管享用」，实际从来没写进去过（Mac 上 PostToolUse 的 hook 只在有人等你批准时才启动 AIQuota）。现在改成 Windows 同步时在 Mac 上跑 `AIQuota --sessions-json` 现算一次（和 Mac 触控栏路线图同一套代码），所以 mac_session_sync.py 是重写过的，文件名也从 `mac-<id>.json` 变成 `mac-<agent>-<id>.json`。

## 我改了什么（别回滚）

- 新增 `ai_lights_core.py`：工具调用写成人话（只留种类、文件名、程序名和必要的子命令，不留参数、路径、URL、密码、要 echo 或要搜的内容）；跨进程锁（最多等 1.5 秒，不会卡住 ZCode 的 5 秒 hook）；原子写（桌宠正读着时替换失败会重试）。
- `zcode_notify.py`：不再把原始 hook 输入写进 `_hook_input_last.txt`（那个旧文件里有你说的话，可以删掉）；在等你批准时又开始用工具 → 回到 running；新的一轮清空动作，等你、完成时留着；SessionStart 记成空闲；读改写加锁；不管出什么错都以退出码 0 结束（ZCode 把 2 当成拦截）；新增 `after` 事件（见「可选」）。
- `wsl_lights_hook.py`（已拷到 ~/.local/bin）：用完整 session_id（原来只留 UUID 最后 12 位会串灯），没有 id 时按调用它的进程号分开；同样的人话、加锁、批准后回 running。
- `mac_session_sync.py`（loop 已重启成新版）：拿到完整快照就对账，Mac 上没了的灯这边删掉（空列表也算成功），坏的或半截的输出不删；10 分钟拉不到就把 mac-*.json 改成空闲并标 `stale`；Mac 上有在跑或在等你的会话时 30 秒拉一次，没有时 120 秒，失败时 300 秒；`updated` 换成桌宠认的意思（在跑、等你、出错的写同步那一刻，刚完成的写这边第一次看到它完成的时间）。
- `build_release.py`：发布包里多拷一个 ai_lights_core.py（zcode_notify 要用）。只加了两行，CRLF 保持原样。
- 测试：`py -m unittest test_session_lights test_ai_lights_data` 48 个全过。test_session_lights 里改了两条期望（工具描述的新写法），删了 mac 修剪那条（改成对账，见 test_ai_lights_data.MacSyncTests）。
- 改之前的版本备份在 `%TEMP%\xq-backup-104411\`。

## 要你在 pet.py 里做的（按优先级）

1. **灯按紧急度排**（scan_ai_sessions）：先按状态排（waiting 0、error 1、刚完成且还没过 90 秒的 done 2、running 3、其余 4），同一组里新的在前，**排完再截 cap=5**。现在先按 updated 截，Mac 上等你批准的灯会被本机的新文件挤掉。ai_chain_lines 也要让等你的排在在跑的前面。test_sorted_and_capped 的期望跟着改。
2. **会话卡死的兜底**：
   - `source == "mac"` 的文件，`syncedAt` 超过 10 分钟就当空闲，也不播报。同步进程没在跑时（比如重启后没人启动它），Mac 的橙灯不能一直闪。
   - 本机 ZCode、WSL Codex 在等你或在跑、但 `updated` 已经超过 30 分钟的，ai_light_style 和 ai_chain_lines 都当它过期。ZCode 被你停掉、或者出错退出时没有 hook，橙灯会一直挂着。
3. **同步进程跟着小乔启动**：现在只有手动双击「启动会话灯同步.bat」才会开，重启电脑后就没了。建议 pet.py 启动时检查一下，没在跑就用 pythonw 拉起 `mac_session_sync.py --loop`（只开一个）。也可以把 bat 放进开机启动，这个要先问用户。
4. **额度**：读 `%LOCALAPPDATA%\AIQuota\usage.json`，和会话一样限频读，不要逐帧读。格式（schemaVersion 1）：
   ```json
   {"schemaVersion":1,"updated":1790822290.8,
    "providers":[{"name":"Codex","plan":"Plus","error":null,"stale":false,"staleAfter":300,"updated":1790822290.2,
                  "windows":[{"label":"5小时","short":"5h","used":23.0,"reset":"2026-10-01T15:38:10+08:00","resetUnix":1790840290,"approx":false,"note":""}]}]}
   ```
   `现在 - 顶层 updated > 60 秒`：整份当过期（AIQuota.exe 没开着）。单个 provider：`现在 - updated > staleAfter` 就当过期。`stale` 只是写文件那一刻的判断。`reset` 为 null 表示不知道什么时候重置；Windows 上 Claude 的「本周」现在就是 null，Windows 版还没有 Mac 那套推算。
   显示放右键「AI 状态」那张卡里一行就够，头顶留给思维链。某个窗口 ≥95% 时说一句（同一个窗口 2 小时内不重复），过了重置时间说一句「额度回来了」。数据过期时不说。
5. **AI_AGENT_CHAR 加 `"mac-zcode"`**：现在显示成 M，和 Mac Claude 分不出来。
6. （可选）**思维链画成路线**：Mac 的文件里有 `steps`（最多 8 步，每步有 title、sub、state，state 是 done / current / todo / failed / waiting），可以画成和 Mac 触控栏一样的「一格一步、箭头连着」。不画也行，`actions` 就是最新的三步，新的在前，正在做的那步带「（进行中）」。

## 可选，需要用户点头的

- **批准后立刻灭橙灯**：现在要等下一次工具调用才回 running（批准一个跑几分钟的测试时，这几分钟一直是橙灯）。
  - ZCode：在 config.json 的 hooks 里把 PostToolUse 和 PostToolUseFailure 注册到 `zcode_notify.py after`。打断（is_interrupt）会记成空闲。
  - WSL Codex：在 hooks.json 里加 PostToolUse 和 Interrupt，指到 `xiaoqiao-lights-hook.py after`。Codex 要重新信任，用 wsl_codex_trust.py。
  这两处都是改用户的配置，先问用户。
- **hook 命令别直接指项目里的脚本**：zcode_notify.py 要是被挪走或改名，python 会以退出码 2 退出，ZCode 会拦下每一句话和每一次工具调用。可以在 %LOCALAPPDATA% 放一个启动器（最后一定 `exit /b 0`），由它再去调项目里的脚本。改 config.json 也要用户点头。

## 不要做的

- 不要把 Mac 那边的路线重新解析一遍（它已经算好了），也不要每 2 秒 ssh 一次。
- 不要把原始 hook 输入、命令参数、完整路径写进 ai_sessions/ 或画到头顶。动作只用 ai_lights_core.action_label 的结果。
