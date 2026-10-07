# 小乔桌宠 · 开发约定

当前生产程序是根目录 `pet.py` 及同目录模块，Windows / Tk / Pillow。先读[项目说明](README.md)和[开发指南](docs/DEVELOPMENT.md)，不要在历史交接副本继续开发。

## 动手前必读

四文件体系保持有效，每轮先读前三份：

1. [设计宪法](docs/design/DESIGN_CONSTITUTION.md)：最新用户修订优先，视觉中心是小乔，脸保持刚性，接触稳定，真实桌面尺寸优先。
2. [问题池](docs/design/DESIGN_ISSUES.md)：新问题先入池，再排期。
3. [经验](docs/design/DESIGN_MEMORY.md)：已验证事实与待验证假设分开；M1–M11是已验证的坑与边界。
4. [迭代记录](docs/design/DESIGN_ITERATIONS.md)：八步流程；结论只有 ACCEPT / REJECT / INCONCLUSIVE。

再查[实验记录](docs/design/EXPERIMENTS.md)，不重复引入已回滚设计（如自动切层E40）；[内容与边界](docs/design/CONTENTS.md)记录当前功能、状态和指令约束。

## 工程边界

- 改 `pet.py` 前核对mtime，确认无并行会话写同一文件；原子保存。
- 保持运行模块、素材、存档与IPC位置，兼容 `py pet.py`、自启动、外部hook及打包。
- 统一测试入口 `py tools/run_checks.py` 在临时副本运行。五套强制回归：test_pet / test_life / test_swing / test_session_lights / test_ai_lights_data。test_pet是旧引擎兼容fixture，现行核心档须另测。
- 测试与预览用合成数据，不消耗真实模型额度，不读写个人配置、会话、记忆或额度样本。
- 工作流只归纳已观察阶段、方向和子智能体职责；不列文件/命令琐事，不造下一步、完成百分比或并行数。
- 写 `pet_cmd.json` 驱动，`--debug-state` 时读 `pet_state.json`。模拟用demo且标「模拟」，不污染真实数据。
- 加星光走 `gain_star()`；位置用像素。不以拉伸、模糊或发光掩盖缺料、连接和结构问题。
- 发布前运行 `tools/check_docs.py`、`tools/check_public_files.py`，不提交运行数据、密钥或真实账户样本。

`docs/archive/`、`tools/legacy/` 是历史参考，不是当前规格或默认测试。`house3d/` 保留可选实验。
