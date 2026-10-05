# 六行工作台与 Agent 切换交接给 Claude

本分支保存小乔桌宠工作台的实现参考，供 Claude 云端查看并继续修改。

## 当前交互

- 窗口高度为 (260+14)×u（u=1.5 时 411px）：展开面板高 260，面板上方 14 个单位留给她的帽尖探出（见下文「比例」）；右侧工作流列表行高 18px，可见六条记录。
- 底部可切换 Codex、Claude、ZCode。上方列表随所选 Agent 过滤；进入具体记录后展示该会话步骤。
- Codex 的 Mac 和 WSL 会话归为 Codex；Claude 会话归为 Claude。
- 指示灯表示实际会话状态：运行中为绿、等待为黄、错误为红、空闲为灰。当前所选 Agent 另用边框和文字高亮，避免把空闲状态伪报为运行。
- 没有工作记录的 Agent 仍可切换，但列表显示“暂无步骤记录”，不会伪造任务。
- Agent 灯条和 AI 额度在**右栏**、列表下方（与 live 视图共用 `quota_block`）；左栏整列留给她，下面不再画任何分隔线、灯或文字，也没有点击区，所以点她仍然是摸头／挠痒。

## 紧凑 live 视图（默认视图）

目的：AI 状态一眼可见，同时把版面还给她。上面「当前交互」描述的是点「展开」后的完整视图，仍然完整保留。

- **只列活着的会话**：running／waiting／error 各一行，最多 `LIVE_ROWS=2` 行，**跨所有 Agent**（对应灯条注释里"是否还有任何 Agent 在跑"）；done／idle 与超出部分折叠成「另有 N 个已结束 · 展开」。展开后仍是按所选 Agent 过滤的列表。
- **工作链用圆点串表示**：每步一个点（颜色取自步骤 status），当前步放大带光圈；多于 6 步时前面折成两个小灰点；只写当前步标题和「第 N 步」，不假设总步数。
- **额度并入右栏**压成两行，不再通栏，避免盖住她的区域。标题用她的口吻，按「等确认 > 出错 > 在跑 > 都忙完啦／暂时没有任务」取最该提示的一种。
- **live 只画面板的上 178 高**（`LIVE_H`），位于窗口 y=`PY`..`PY`+178，面板下方保持透明。透明区是否让点击穿透、窗口是否因此悬在任务栏之上，需要在本机确认。
- **不新增点击类型**，只复用 `flat_task`、`flat_agent`、`flat_mode`、`house_chat`、`swallow`。`flat_mode` 的 payload 新增 `live`；展开列表右上角多了「收起」，其标题宽度因此收窄到 185。
- 点「展开」发出 `flat_agent`（取第一条活跃会话的 Agent；该 Agent 不在 `AGENT_ORDER` 时退回 `flat_mode`/`tasks`），所以展开后直接落在你刚看的那个 Agent 上。
- 点 live 里某一行发出 `flat_task`；`action` 现在会按该会话的来源同步 `_flat_agent`，否则点到非当前 Agent 的会话会因按 Agent 过滤而显示别人的步骤。`_swing` 结构异常时不会抛错，只是不同步。
- 默认模式由 `DEFAULT_MODE='live'` 决定。依赖旧默认（列表）的测试已显式加上 `p._flat_mode='tasks'`：`test_scroll_clamps_and_never_rebuilds_scene`、`test_scrollbar_drag_reaches_last_row`、`test_native_composition`、`test_track_click_pages_by_one_full_window`。前三条依赖本机的 `pet`／`export_house_stage`，本包环境里无法运行，请在本机确认。
- **取舍**：Agent 灯条（含 `house_trace` 入口）只在展开视图里保留；live 里每行自带 Agent 名和状态灯。需要在 live 里直接进 trace 的话，要另给入口。
- 圆点配色依赖 `moon_board.workflow` 返回的步骤 status（`COLORS` 的键）；本包里没有该模块，未用真实数据验证。`six-row-workflow.patch` 不包含 live 视图。

## 质感：透明度与形状灯

- **逐像素透明，不做毛玻璃**：面板填充 alpha 常态 `PANEL_REST=232`（约 91%），展开、悬停、有 waiting／error 时 `PANEL_ACTIVE=248`；描边、字形、灯都保持不透明。`render()` 输出仍是普通非预乘 RGBA，由 `pet.py` 的 `premult_bgra` 预乘。仓库里没有 DWM／亚克力代码，亚克力会糊整个窗口矩形、不跟她的形状走，所以不做。
- **悬停档位需要宿主接线**：`push()` 读取 `owner._flat_hover`，本包没有悬停检测。不接线的话，只有展开和「有等确认／出错」时才会变实。
- **形状＋颜色双编码**（`glyph()`、`SHAPES`）：星芒＝在跑，空心环＝等你，三角＝出错，实心点＝完成／空闲。绿色盲下「出错红」与「完成绿」色差只有约 12.6，纯靠颜色分不清；测试要求四种形状两两轮廓重合度 < 0.8。
- **同一套状态语汇**：live 行、展开列表、Agent 灯条现在都用 `COLORS` + `SHAPES`（此前灯条里「运行＝绿」，live 里「运行＝紫」）。
- **配色**：向靛蓝微调（`BG #1d1e2e`、`DIM #b4b7cc`、错误红 `#f39292`），面板描边换成淡紫 `RIM #666b96`。纯白背景最坏情形下，232 的文字对比度约为 INK 11、DIM 6.3；`test_rest_alpha_keeps_text_readable_over_white` 把这个下限锁住（低于约 216 次要文字会不达 AA）。
- **已知代价**：白文档上的大号深色字会隐约透到面板标题后面；常态值是一个常量，觉得透就调高。
- **未验证**：真实 `apple_ui` 字体更细时有效对比度会低于上面的数字；`push_layered` 在本机私有版是否把第 5 个参数 `255` 当整体透明度（若是，面板变淡时她也会跟着淡）；点击穿透只对 alpha=0 的像素成立，面板最低 232，不受影响。

## 比例：无支架的秋千，放大约 40%，帽尖探出面板，灯条和额度挪进右栏

灰色 A 形支架不再绘制（`SHOW_STAND=False`），秋千和她直接挂在面板上沿。展开视图下面的 Agent 灯条和额度整体挪进右栏，左栏整列留给她，所以她不再受展开视图分隔线（y=172）限制，可以再放大一档。她的大小和位置按**秋千图本身的实际内容范围**定，而不是按 studio 包围盒：

- **测量依据**：用你的截图（`images/previews/six-row-live.png`）拟合出旧布局里秋千图的比例和位置——约 0.112 单位／像素，图块左 6、顶 0，重合度 0.74。据此得到 `ART_OLD=(38.7, 9.0, 139.8, 140.0)`（内容的左、帽尖、右、鞋底，旧布局单位）。`swing.png` 的内容范围是 x 292–1195、帽尖约 y=80、鞋底约 y=1250（图块 1254 见方）。
- **数值**：`PET_M=1.4`（比旧布局大 40%）、`PET_CX=80`、`PET_TOP=10`、`PY=14`、`RX=10`、`LIVE_H=178`。`PET_BOX` 现在只是 studio 包围盒的缩放（`142×140` 乘 `PET_M`），用来给 `geometry()` 定比例，不再是她的可见范围；可见范围用 `pet_content()` 算：左 19.4、帽尖 1.6、右 160.9、鞋底 185.0（窗口单位）。
- **窗口**：高 `H=PH+PY=274`。帽尖在窗口顶边下 1.6，比面板上沿（y=14）高出约 12；鞋底在 live 面板（底边 y=192）内 7；右缘 160.9，离步骤列（x=180）约 19。`LIST` 是窗口坐标（含 `PY`），宿主里把事件坐标直接和它比较的地方不用改。
- **展开视图右栏**：分隔线、`Agent` 标签、灯条、额度都从 `x=173+RX` 开始。额度用共用的 `quota_block`（名称列 52，两个周期各 76，进度条 24），`Codex WSL` 这类长名字不会被截断；灯条按数量压缩间距（5 个也放得下，超出的名字会被截断）。`house_trace` 的点击区跟着移到 `Agent` 标签上。
- **`push()`**：`if SHOW_STAND:` 才渲染 `_studio().render(k)`；`geometry()` 仍读 `_studio().bounds()` 来定比例和偏移，所以 studio 对象必须保留。
- **顶部的金色残片**：`swing.png` 顶部（y<60）有几块被矩形裁断的金色挂钩残片，原本被支架横梁遮着。放大后它们落在窗口顶边以外，会被窗口自然裁掉；若你本机的窗口顶边留得更高，它们会露出来，浅色桌面上更明显。
- **回退**：她的大小、位置和支架可以只靠常量回到旧样子：`PET_M=1.0`、`PET_CX=82`、`PET_TOP=15`、`RX=0`、`PY=0`、`LIVE_H=170`、`SHOW_STAND=True`，测试仍然全过。但灯条和额度已经在右栏，这部分是结构改动，不是常量。
- **必须在本机核对**：
  - 窗口多出的 14 个单位对落地位置和窗口锚点的影响：窗口若按底边锚定，整体会上移 `14*u` 像素；按顶边锚定，面板会下移。
  - 她的点击区是否随放大调整，以及头部／身体的命中区；`on_wheel_scene`／`_ui_hit` 若把列表区域写死成了 `y=42` 之类的数字，会偏 14 个单位；若本机把 Agent 灯条或额度区域的点击／滚轮范围写成通栏（`x=16..424`），现在也不对了。
  - 摆动时（±8° 量级）帽尖和右缘是否碰到窗口顶边或步骤列：我只做了绕绳顶旋转的示意，你本机用的是带透视的 `SWING_PERSP`。
  - 真实字体宽度（本包用文泉驿估算）。
  - 此前版本的 `PET_TOP=1`、放大 20% 是按飞行立绘估的，用秋千图会把帽尖切掉约 8 个单位，已作废。
## 互动：AI 陪跑规则（`agent_reactions.py`）

原则：让 AI 状态在她身上「长出来」，而不是「播出来」。事件先变成肢体、贴纸、短句，再经统一的门放行；不紧急的话先攒着，等你摸她或靠近时再说。她永远只说 Agent 的名字，不念任务标题、路径或报错。

这一节的**规则**已实现并有测试（纯逻辑，不依赖 Tk／PIL／时钟）；**接到 `pet.py` 是你本机的工作**，本包里没有那部分代码。结构照搬电量感知（`_battery_event` 是纯函数，`_battery_tick` 做门控，`_battery_react` 执行，`pet.py:4085-4139`）。

**状态→反应**（`SPEC` 里的键名都对应 `pet.py` 里真实存在的东西；`level` 为 `few` 只做标★的行）

| 变化 | 她做什么 | 备注 |
| --- | --- | --- |
| 开始运行 | 偏头看一眼（`_start_micro_motion("notice")`），10 分钟内一次，不说话 | 仅 `normal` |
| 变成「等确认」 | 先偏头；持续 20 秒后「在吗」类贴纸（`curious`）＋ `hop` ＋ 一句话，只说一次；10 分钟后仍未处理再提一次，之后不再提 ★ | 睡眠／专注时丢弃，不补播 |
| 出错 | 面板亮红灯，她不动；持续 10 秒后记成便条，**等你摸她或靠近**才安慰：`care` 贴纸＋一滴 `sweat`＋一句 ★ | 不念报错内容 |
| 完成 | 运行满 90 秒才算；先飘几点星光（`star_burst`）不说话，便条里存一句，靠近时说（`proud`）；20 秒内多个完成合并成一句 | 仅 `normal`；过期（stale）变成的 idle 不算完成 |
| 额度 ≥90% | 只在跨线那一次提一句（`mild`）；有任务在跑时先存成便条；回落到 70% 以下才重新武装 | 仅 `normal`；过期读数不告警 |
| 运行满 20 分钟 | `start_stretch()`，每个会话一次，仅 idle 时 | 仅 `normal` |
| 你问「进度／在忙吗」 | 按名字和数量汇报，不念标题；任何档位都回答（睡着、被拖动时除外） | 加进 `PET_ACTIONS`（`pet.py:3468`） |

**门**（全部在 `Reactor` 里，测试覆盖）：首次采样只记基线，不会启动即播报；专注／睡眠／拖动／唱歌时丢弃而不是攒着；用户正看着 Agent 的窗口时不提醒；气泡占用时存成便条而不是覆盖；全局两句话至少间隔 120 秒、每天最多 10 句（按本地日期重置）；便条 30 分钟过期，问题解决了就取消；摸头只有 25% 概率触发、2 分钟冷却；靠近 1 分钟冷却，专注中靠近不触发，但摸头仍可（那是你主动的）。以上数字全是猜的，请在本机调；它们都是模块顶部的常量。

**本机接线**（建议顺序）
1. 设置项 `agent_companion`：`off`／`few`（默认）／`normal`，读写方式照 `battery_watch`（`pet.py:1005,1375,4064`）。
2. `_agent_tick`：每 1–2 秒调用 `Reactor.update(now, rows, quota_rows(ui), ctx)`。`rows` 直接用 `flat_workspace.rows_for(ui,'live')`（已有 `id/agent/state`，stale 已折成 idle；`test_live_rows_feed_the_reaction_rules_without_adapting` 保证这个契约）。`ctx` 取：`focus=self.focus_mode()`、`sleeping=self.state in ('sleep','yawn')`、`dragging`、`singing`、`bubble_busy=bool(self.bubble)`、`cursor_near`、`watching_agent`（用 `_fg_bucket` 判断前台是否是 Agent 的终端；Windows Terminal 的标题未必含「terminal」，需实测）。
3. `_agent_react(r)`：`say` 用 `self.say(r.say, 2.6)`——**不要用 `_reply`**，它会写聊天记录、走 TTS，还绕开专注期缩短；`emotion` 用 `if not self.play_emotion(r.emotion, 2.4) and r.fallback: self.play_emotion(r.fallback, 2.4)`（`play_emotion` 对不存在的类别返回 False）；`motion` → `_start_micro_motion`；`effects`：`hop`→`self.hop(0.4)`，`star_burst`→`self.star_burst(0.22, -0.2, 3)`，`sweat`→`self.add_part("sweat", …)`（用法见 `pet.py:2120`），`stretch`→`self.start_stretch()`；`sfx` 仅 `normal` 档保留，值是 `assets/audio` 的前缀。
4. 拉取：`pet_head`（`pet.py:1602`）里调 `pull(now,'head',rows,ctx)`；`just_approached` 那一段（`pet.py:5822` 附近，现在是「在叫我吗?」）先试 `pull(now,'approach',…)`，没有便条再走原来的好奇反应。
5. 新增情绪类别 `care`：在 `assets/emotions.json` 加 `"care": ["comfort"]`。现有的 `tired`／`lazy` 里虽有「辛苦啦」，但同一类别还会抽到「晚安」「摸鱼中」，用来安慰出错不合适。注意 `random_emotion`（`pet.py:3171`）会把新类别也抽进去，README 里的「20 类」也要同步成 21。不加的话，`error` 会回退到 `mild`。**本次没有改公开的 `emotions.json` 和 README。**
6. 与 `zcode_notify.py` 共存：hook 里 `permission` 的播报是有意不限频的（「漏一次就可能干等」），而 `waiting` 来自会话快照，带去抖和间隔。两条同时开会对同一件事说两次。建议：桌宠在运行且快照能看到该会话时，让 `waiting` 负责；hook 保留作为桌宠没开时的拉起路径。另外 `_exec_cmd` 的 `announce`（`pet.py:5329`）现在直接走 `_reply`，**不遵守专注／睡眠**，迁移后也应补上这道门。`pet_cmd.json` 是单槽文件，多个 Agent 几乎同时写入会互相覆盖，未验证实际是否会丢消息。

**刻意不做**：Stop 钩子每轮回答结束都会触发，不当「完成」播；逐步播报；红点／未读数／等级／成就；用任务数或额度去挂钩星光或好感；重复催促或递增语气；念任务标题或报错、用 TTS 读 AI 文本；叫醒睡着的她；事后补播。「陪跑时每几分钟无声闪一次星光、不自动入睡」也暂不做：收益模糊，且会让 20fps 档持续耗电（`EXPERIMENTS.md` E12）。

**未验证**：时间阈值都是估计；会话数据在面板隐藏或睡眠低帧率时是否照常刷新、`waiting`↔`running` 会不会抖动、会话 `id` 是否稳定，都要在本机看；`care` 的贴纸效果、气泡与她出框后的帽尖是否冲突（气泡在窗口里的位置我没看到）。

## 文件

- flat_workspace.py：当前工作台完整参考实现，包含 Agent 选择和工作流过滤。
- test_flat_workspace.py：行数、交互、来源映射、真实灯态、live 视图、透明度与布局测试。
- agent_reactions.py：AI 陪跑规则（纯逻辑）；test_agent_reactions.py：其测试，可直接 `python -m unittest test_agent_reactions` 运行，不需要任何依赖。
- six-row-workflow.patch：较早的六行间距差异，只覆盖压缩列表，不包含这里新增的 Agent 切换实现。需要 Agent 切换时以当前完整 flat_workspace.py 和测试为准。

## 验证状态

- 工作台定向测试通过。
- 本机全量测试运行 448 项：445 项通过、2 项跳过、1 项失败。
- 未解决失败：`test_core_runtime.CoreRuntimeTests.test_shipped_profile_renders_and_keeps_retired_data_dormant`。测试期望 `exported['ai_panel']['codex_quota_connected']` 为 `False`，实际为 `True`。
- 该失败检查的是额度连接状态，与工作流 Agent 切换和图像素材交接无关；本次没有修改额度连接代码，因此保留为待排查项。
## 图像素材

索引和预览见 assets/INDEX.md；包含本机项目已有的 48 张图像、6 张工作台截图/模拟预览，以及文件相对路径清单。

## 仓库背景

目标仓库是 https://github.com/shuai9928/xiaoqiao-desktop-pet。公开 main 目前不含这套半高工作台基线；本机工作区与公开 main 没有共同 Git 历史。这个分支是交接参考，不是可直接运行的完整仓库，也不应合并到 main 来代替本机项目基线。

在 Claude 云端中打开本分支的文件即可检查和继续修改。应用到其它代码时，先确认其 pet.py、moon_board.py 等接口与本机基线一致，再运行对应测试。
