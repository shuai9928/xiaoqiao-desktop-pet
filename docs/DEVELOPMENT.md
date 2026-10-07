# 开发与维护

[文档导航](README.md) · [贡献约定](../CONTRIBUTING.md) · [工具说明](../tools/README.md)

## 当前入口与目录

`pet.py` 是唯一日常启动入口，生产 Python 模块保持在根目录。这样保留现有素材路径、打包导入、ZCode／WSL hook 和外部指令兼容性。本轮整理移动测试、工具和文档，不借目录迁移改写角色引擎。

```text
根目录 *.py            生产模块和外部接入入口
assets/                 角色、分层场景、特效与声音
tests/                  当前测试及旧兼容测试
tools/
  run_checks.py         隔离测试入口
  check_docs.py         本地文档链接检查
  check_public_files.py 发布内容检查
  preview_workspace.py  当前生产工作台的模拟数据预览
  assets/               素材制作与分层工具
  diagnostics/          特效、性能及其他诊断探针
  release/              Windows 打包工具
  legacy/               旧版制作／展示工具
docs/
  design/               六份设计与实验记录
  archive/              旧手册、交接与历史展示
  media/                当前文档图片
house3d/                保留原位的 Godot 实验
```

根目录入口源码代表当前行为。历史交接里的复制源码与旧预览只用于追溯，不是另外一套可继续修改的生产代码。

## 按职责找模块

| 修改方向 | 主要入口 |
| --- | --- |
| 角色状态、交互、菜单、聊天窗、Windows 窗口 | `pet.py`：`Pet`、`InteractionCard`、`ChatBox` |
| 实时／展开工作台、状态图形与额度布局 | `flat_workspace.py` |
| 活动合并成阶段、委派记录展开 | `workflow_stages.py` |
| 有限任务方向与子代理职责标签 | `task_directions.py` |
| Windows 原生 Codex／Claude 事件采集 | `native_session_sync.py` |
| 会话标签清洗与 hook 公共数据层 | `ai_lights_core.py`、`xiaoqiao-lights-hook.py`、`wsl_lights_hook.py`、`zcode_notify.py` |
| 跨机来源快照 | `mac_session_sync.py` |
| 额度快照的单位、缺失和过期语义 | `ai_quota.py` |
| 状态触发的陪伴规则与接线 | `agent_reactions.py`、`agent_companion.py` |
| 帽上特效与预烘焙缓存 | `hat_fx.py`、`fx.py` |
| 2.5D 网格、惯性和接触稳定 | `depth_model.py`、`life.py`、场景模块 |
| 聊天／卡片／原生菜单透明度 | `popup_material.py` |
| 可选角色模型聊天与记忆 | `ai_chat.py` |

桌宠不会因工作流显示而自动执行代理任务或批准操作。会话采集、额度读取和角色模型聊天保持独立，新增来源也应遵守这一边界。

## 开发环境与检查

按[安装指南](GUIDE.md)建立虚拟环境，之后从仓库根目录运行：

```powershell
py tools/run_checks.py
py tools/run_checks.py --unit-only
py tools/check_docs.py
py tools/check_public_files.py
```

使用虚拟环境时，将 `py` 换成 `.\.venv\Scripts\python.exe`。运行器把源码、测试和允许的素材复制到临时目录，禁用真实模型，提供测试配置，隔离聊天、记忆、会话与额度来源。不要直接在日常运行目录执行会建立 `Pet` 的集成脚本。

| 模式 | 检查范围 |
| --- | --- |
| 默认 | 规定的角色、生命、秋千、会话灯、数据层检查，加当前工作台／方向／原生采集／闭眼／弹层／特效等定向检查，并运行脚本式 `test_pet` |
| `--unit-only` | 用于 Windows CI 的当前单元与定向检查，省略脚本式 `test_pet` |
| `--legacy` | 另外运行旧引擎兼容检查；退役功能的断言可能失败，输出必须如实记录 |

`test_pet` 包含旧引擎兼容 fixture，不能替代默认核心模式的证明；`test_core_profile`、`test_core_runtime` 和当前 UI 测试负责约束日常行为。不要把 unittest 的发现数量当成 `test_pet` 的脚本断言数。检查数量以本轮实际输出为准，不保留旧总数充当当前成绩。

关键定向测试集中在 `tests/test_flat_workspace.py`、`test_workflow_stages.py`、`test_task_directions.py`、`test_native_session_sync.py`、`test_rest_eyes.py`、`test_popup_material.py` 和 `test_hat_fx.py`。缺失来源、过期记录、委派成功但代理未完成等情况必须按数据边界验证。

## 当前界面预览

```powershell
py tools/preview_workspace.py
py tools/preview_workspace.py --mode tasks
py tools/preview_workspace.py --mode steps
```

默认输出到 `outputs/current-workspace.png`。工具调用当前生产合成器，使用固定模拟活动，额度保持未知，不调用 AI，也不读取个人会话或真实用量。图片内保留“模拟”，文档图复制到 `docs/media/current-workspace.png`。`--mode` 可切换实时、任务或阶段视图；预览不运行思考过程或动态特效。

静态预览用于看布局、颜色和文字，不能替代实际桌面尺寸、动态效果或窗口操作验收。聊天和原生菜单还需检查输入、复制、焦点、键盘与透明度；半透明不是实时背景模糊。

## 修改时的约束

先读 [AGENTS.md](../AGENTS.md) 和 [设计宪法](design/DESIGN_CONSTITUTION.md)、[问题池](design/DESIGN_ISSUES.md)、[设计记忆](design/DESIGN_MEMORY.md)。视觉／行为问题先登记再实现，记录对应的验证与结论；累积结果放在[迭代记录](design/DESIGN_ITERATIONS.md)。

- 修改 `pet.py` 前检查并行写入和 mtime，使用原子写入；保持日常实例、个人存档和设置可恢复。
- 脸部不做明显橡皮变形，握绳、坐垫和身体接触保持稳定；真实桌面尺寸先于放大图。
- 动作按经过时间计算，一次性反馈去重；粒子和缓存有上限，运行时不加入重模糊来掩盖结构问题。
- 互动奖励走 `gain_star()`；不通过新视觉反馈增加模型调用或改写真实额度。
- 工作流只能归纳已观察的公开活动，不输出文件／命令流水账，不虚构计划、并行数、子代理完成或百分比。
- 额度缺失／过期与会话结束／等待分开处理；不要用测试数据替代真实接入。
- 辅助窗口透明度接口不能用于主人物的 `UpdateLayeredWindow` 绘图窗口。

## 发布

审阅改动、运行隔离检查、复核对应界面，再运行 `git diff --check`、文档和公开文件检查。发布检查只检查跟踪／暂存内容，是额外守卫，不能代替对新增文件和演示图的人工审阅。

Windows 打包入口是 `py tools/release/build_release.py`，需安装 `requirements-build.txt`。目录整理不等于可执行发布包已经验收；包内素材、运行入口、外部 hook 依赖和敏感文件排除需另行验证。

历史说明集中在 [docs/archive](archive/README.md)。不要把归档中的旧菜单、源代码副本、性能数字或图稿写进当前能力清单。新增依赖和素材来源应同步更新许可说明。
