# 仓库工具

[← 开发指南](../docs/DEVELOPMENT.md)

所有命令从仓库根目录运行。使用 Windows、Python 和 `requirements.txt` 中的依赖；图文生成沿用 Pillow/Tkinter，不额外引入绘图库。

| 工具 | 命令 | 会做什么 |
| --- | --- | --- |
| 隔离完整回归 | `python tools/run_checks.py` | 临时复制代码和素材，关闭真实 AI，运行单元、助手及完整角色检查；短暂打开测试窗口 |
| CI 检查 | `python tools/run_checks.py --unit-only` | 单元、模拟 UI 和助手检查，不运行完整角色集成 |
| 公开文件检查 | `python tools/check_public_files.py` | 检查 Git 跟踪文件，拒绝运行数据、常见密钥与本机用户路径；输出位置而不输出密钥值 |
| 文档检查 | `python tools/check_docs.py` | 检查 Markdown 本地链接、HTML 图片引用、显式锚点和空媒体文件，不访问外网 |
| 全部角色演示 | `python tools/render_showcase.py` | 覆盖 `docs/media/` 中主视觉、六段 WebP 和六张 PNG；实际角色渲染、20 fps 离线输出 |
| 只更新新增演示 | `python tools/render_showcase.py --new-only` | 生成冥想、点击／喂糖反馈、模拟充电三组媒体 |
| 只更新主视觉 | `python tools/render_showcase.py --hero-only` | 更新 `hero.svg`，不生成所有动画 |
| 操作图解 | `python tools/render_guides.py` | 生成菜单、专注流程、助手范围三个可编辑 SVG |
| 实际卡片／聊天预览 | `python tools/preview_ui.py --view card` / `--view chat` | 使用虚构数据打开真实 Tk 控件；约三分钟后关闭；不自动保存截图 |

渲染脚本和 UI 预览使用临时目录，不读取个人 AI 配置和存档。充电演示调用模拟事件，不操作硬件。UI 预览为了方便截图保留 Windows 标题栏，并让卡片失焦后仍留在屏幕；这两个行为只在预览进程内覆盖，桌宠正式交互不改变。

`check_public_files.py` 只覆盖已跟踪／暂存路径，不能替代对新增文件的人工审阅。`check_docs.py` 不检查远程网站的可用性。GitHub 实际渲染、图片显示和下载入口仍需在发布后查看。
