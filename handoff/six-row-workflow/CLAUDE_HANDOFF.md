# 六行工作台与 Agent 切换交接给 Claude

本分支保存小乔桌宠工作台的实现参考，供 Claude 云端查看并继续修改。

## 当前交互

- 工作区高度为 390px；右侧工作流列表行高 18px，可见六条记录。
- 底部可切换 Codex、Claude、ZCode。上方列表随所选 Agent 过滤；进入具体记录后展示该会话步骤。
- Codex 的 Mac 和 WSL 会话归为 Codex；Claude 会话归为 Claude。
- 指示灯表示实际会话状态：运行中为绿、等待为黄、错误为红、空闲为灰。当前所选 Agent 另用边框和文字高亮，避免把空闲状态伪报为运行。
- 没有工作记录的 Agent 仍可切换，但列表显示“暂无步骤记录”，不会伪造任务。
- AI 额度区域保留在工作流和 Agent 区域下方。

## 紧凑 live 视图（默认视图）

目的：AI 状态一眼可见，同时把版面还给她。上面「当前交互」描述的是点「展开」后的完整视图，仍然完整保留。

- **只列活着的会话**：running／waiting／error 各一行，最多 `LIVE_ROWS=2` 行，**跨所有 Agent**（对应灯条注释里"是否还有任何 Agent 在跑"）；done／idle 与超出部分折叠成「另有 N 个已结束 · 展开」。展开后仍是按所选 Agent 过滤的列表。
- **工作链用圆点串表示**：每步一个点（颜色取自步骤 status），当前步放大带光圈；多于 6 步时前面折成两个小灰点；只写当前步标题和「第 N 步」，不假设总步数。
- **额度并入右栏**压成两行，不再通栏，避免盖住她的区域。标题用她的口吻，按「等确认 > 出错 > 在跑 > 都忙完啦／暂时没有任务」取最该提示的一种。
- **窗口尺寸不变（仍是 440×260×u）**：live 只画上面 `LIVE_H=170`，其余保持透明，不需要改本机 `_art_geo`。透明区是否让点击穿透、窗口是否因此悬在任务栏之上，需要在本机确认。
- **不新增点击类型**，只复用 `flat_task`、`flat_agent`、`flat_mode`、`house_chat`、`swallow`。`flat_mode` 的 payload 新增 `live`；展开列表右上角多了「收起」，其标题宽度因此收窄到 185。
- 点「展开」发出 `flat_agent`（取第一条活跃会话的 Agent；该 Agent 不在 `AGENT_ORDER` 时退回 `flat_mode`/`tasks`），所以展开后直接落在你刚看的那个 Agent 上。
- 点 live 里某一行发出 `flat_task`；`action` 现在会按该会话的来源同步 `_flat_agent`，否则点到非当前 Agent 的会话会因按 Agent 过滤而显示别人的步骤。`_swing` 结构异常时不会抛错，只是不同步。
- 默认模式由 `DEFAULT_MODE='live'` 决定。依赖旧默认（列表）的测试已显式加上 `p._flat_mode='tasks'`：`test_scroll_clamps_and_never_rebuilds_scene`、`test_scrollbar_drag_reaches_last_row`、`test_native_composition`、`test_track_click_pages_by_one_full_window`。前三条依赖本机的 `pet`／`export_house_stage`，本包环境里无法运行，请在本机确认。
- **取舍**：Agent 灯条（含 `house_trace` 入口）只在展开视图里保留；live 里每行自带 Agent 名和状态灯。需要在 live 里直接进 trace 的话，要另给入口。
- 圆点配色依赖 `moon_board.workflow` 返回的步骤 status（`COLORS` 的键）；本包里没有该模块，未用真实数据验证。`six-row-workflow.patch` 不包含 live 视图。

## 文件

- flat_workspace.py：当前工作台完整参考实现，包含 Agent 选择和工作流过滤。
- test_flat_workspace.py：行数、交互、来源映射、真实灯态与 live 视图测试。
- six-row-workflow.patch：较早的六行间距差异，只覆盖压缩列表，不包含这里新增的 Agent 切换实现。需要 Agent 切换时以当前完整 flat_workspace.py 和测试为准。

## 图像素材

索引和预览见 assets/INDEX.md；包含本机项目已有的 48 张图像、6 张工作台截图/模拟预览，以及文件相对路径清单。

## 仓库背景

目标仓库是 https://github.com/shuai9928/xiaoqiao-desktop-pet。公开 main 目前不含这套半高工作台基线；本机工作区与公开 main 没有共同 Git 历史。这个分支是交接参考，不是可直接运行的完整仓库，也不应合并到 main 来代替本机项目基线。

在 Claude 云端中打开本分支的文件即可检查和继续修改。应用到其它代码时，先确认其 pet.py、moon_board.py 等接口与本机基线一致，再运行对应测试。
