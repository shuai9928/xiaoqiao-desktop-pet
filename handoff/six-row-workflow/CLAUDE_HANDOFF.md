# 六行工作流交接给 Claude

本包记录本机桌宠工作台的六行压缩改动，供 Claude 云端对照和接手。

## 本次改动

- 工作流列表行高从 36 压到 18，当前 660×390 工作台可见六条记录。
- 状态灯与文字垂直居中，保留原来 12px 的文字大小。
- 长列表仍可通过滚轮和滚动条访问；更新了六行显示、滚动和命中区域测试。
- 此包不含实际运行截图或配额数据。

## 文件

- flat_workspace.py：完整工作台渲染与交互实现。
- test_flat_workspace.py：对应测试。
- six-row-workflow.patch：相对本机六行改动前备份的精简差异。

## 仓库背景和应用方式

目标仓库是 https://github.com/shuai9928/xiaoqiao-desktop-pet 。目前公开 main 不含 flat_workspace.py、test_flat_workspace.py 或这套半高工作台基线；本机 master 与公开 main 没有共同 Git 提交历史。本机差异统计约 175 个文件（约 25,976 行新增、3,724 行删除）。因此这个小补丁不能直接应用到公开 main，完整本机快照也不应与六行间距改动混在同一次上传。

若 Claude 云端使用的代码正好是本机六行改动前的基线，可运行 git apply --unidiff-zero six-row-workflow.patch，再运行 test_flat_workspace.py。公开 main 目前没有这些文件，不可直接应用。不要把这个补丁当成完整仓库，也不要用它覆盖 main。
