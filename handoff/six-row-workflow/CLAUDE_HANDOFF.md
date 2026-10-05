# 六行工作台与 Agent 切换交接给 Claude

本分支保存小乔桌宠工作台的实现参考，供 Claude 云端查看并继续修改。

## 当前交互

- 工作区高度为 390px；右侧工作流列表行高 18px，可见六条记录。
- 底部可切换 Codex、Claude、ZCode。上方列表随所选 Agent 过滤；进入具体记录后展示该会话步骤。
- Codex 的 Mac 和 WSL 会话归为 Codex；Claude 会话归为 Claude。
- 指示灯表示实际会话状态：运行中为绿、等待为黄、错误为红、空闲为灰。当前所选 Agent 另用边框和文字高亮，避免把空闲状态伪报为运行。
- 没有工作记录的 Agent 仍可切换，但列表显示“暂无步骤记录”，不会伪造任务。
- AI 额度区域保留在工作流和 Agent 区域下方。

## 文件

- `flat_workspace.py)：当前工作台完整参考实现，包含 Agent 选择和工作流过滤。
- `test_flat_workspace.py)：行数、交互、来源映射与真实灯态测试。
- `six-row-workflow.patch)：较早的六行间距差异，只覆盖压缩列表，不包含这里新增的 Agent 切换实现。需要 Agent 切换时以当前完整 `flat_workspace.py` 和测试为准。

## 仓库背景

目标仓库是 https://github.com/shuai9928/xiaoqiao-desktop-pet 。公开 `main` 目前不含这套半高工作台基线；本机工作区与公开 `main` 没有共同 Git 历史。这个分支是交接参考，不是可直接运行的完整仓库，也不应合并到 `main` 来代替本机项目基线。

在 Claude 云端中打开本分支的文件即可检查和继续修改。应用到其它代码时，先确认其 `pet.py`、`moon_board.py` 等接口与本机基线一致，再运行对应测试。
