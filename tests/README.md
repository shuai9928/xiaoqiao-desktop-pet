# 测试入口

从仓库根目录运行 `python tools/run_checks.py`。运行器复制源码、测试、工具与素材到临时目录，生成空的账户目录、合成存档与禁用的 AI 配置；检查期间禁止网络，不读取桌宠真实聊天或原生账户日志。

- 默认：当前桌宠单元集，以及项目要求的 `test_pet.py` 冒烟检查。后者保留退休引擎的显式兼容 fixture，不能代替 `test_core_profile.py` 与 `test_core_runtime.py` 的现行核心档检查。
- `--unit-only`：同一当前单元集，省略会短暂创建测试窗口的 `test_pet.py` 脚本；CI 使用这个选项。
- `--legacy`：追加旧全功能行为、旧工作室与 `test_agent.py` 兼容检查。已有失败会保持红灯，不能当作现行核心功能失败，也不会为全绿改断言。

所有 `test_*.py` 均集中在本目录。单元测试仍可从根目录用 `python -m unittest discover -s tests -p test_workflow_stages.py -v` 定向发现；裸测试之间的 import 保持兼容。完整 discover 会包含旧兼容套件，而且不会执行 `test_pet.py`/`test_agent.py` 的脚本断言，因此推荐统一运行器。

运行器打印实际测试数量和每条 skip 原因。若素材没有旧 standing rig，两个旧 rig 几何测试允许明确 skip；若没有旧腿层素材，其测试在 `--legacy` 下同样明确列出。任何其他 skip（例如移动后找不到场景素材）使入口返回失败。

已知旧兼容差异：`test_recovery.DeferredFxTests.test_defer_builds_later_and_draws_nothing_until_then` 仍断言两种命中配色共20张预烘焙贴图；现有B5加入mint配色后实际为30张。该旧断言保持不变，因此 `--legacy` 会报告失败，默认当前检查不包含这一退役模块。
