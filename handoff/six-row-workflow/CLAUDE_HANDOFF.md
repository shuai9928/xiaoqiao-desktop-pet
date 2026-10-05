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

## 质感：透明度与形状灯

- **逐像素透明，不做毛玻璃**：面板填充 alpha 常态 `PANEL_REST=232`（约 91%），展开、悬停、有 waiting／error 时 `PANEL_ACTIVE=248`；描边、字形、灯都保持不透明。`render()` 输出仍是普通非预乘 RGBA，由 `pet.py` 的 `premult_bgra` 预乘。仓库里没有 DWM／亚克力代码，亚克力会糊整个窗口矩形、不跟她的形状走，所以不做。
- **悬停档位需要宿主接线**：`push()` 读取 `owner._flat_hover`，本包没有悬停检测。不接线的话，只有展开和「有等确认／出错」时才会变实。
- **形状＋颜色双编码**（`glyph()`、`SHAPES`）：星芒＝在跑，空心环＝等你，三角＝出错，实心点＝完成／空闲。绿色盲下「出错红」与「完成绿」色差只有约 12.6，纯靠颜色分不清；测试要求四种形状两两轮廓重合度 < 0.8。
- **同一套状态语汇**：live 行、展开列表、Agent 灯条现在都用 `COLORS` + `SHAPES`（此前灯条里「运行＝绿」，live 里「运行＝紫」）。
- **配色**：向靛蓝微调（`BG #1d1e2e`、`DIM #b4b7cc`、错误红 `#f39292`），面板描边换成淡紫 `RIM #666b96`。纯白背景最坏情形下，232 的文字对比度约为 INK 11、DIM 6.3；`test_rest_alpha_keeps_text_readable_over_white` 把这个下限锁住（低于约 216 次要文字会不达 AA）。
- **已知代价**：白文档上的大号深色字会隐约透到面板标题后面；常态值是一个常量，觉得透就调高。
- **未验证**：真实 `apple_ui` 字体更细时有效对比度会低于上面的数字；`push_layered` 在本机私有版是否把第 5 个参数 `255` 当整体透明度（若是，面板变淡时她也会跟着淡）；点击穿透只对 alpha=0 的像素成立，面板最低 232，不受影响。

## 文件

- flat_workspace.py：当前工作台完整参考实现，包含 Agent 选择和工作流过滤。
- test_flat_workspace.py：行数、交互、来源映射、真实灯态与 live 视图测试。
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
