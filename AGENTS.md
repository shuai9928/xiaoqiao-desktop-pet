# AGENTS.md — 小乔桌宠项目须知

本目录是「小乔·时之魔女」2.5D 桌宠(Python/Tk/PIL,主文件 pet.py)。

## 必读(动手前)

0. **四文件体系(2026-10-03 起生效,缺一不可)**:
   [DESIGN_CONSTITUTION.md](DESIGN_CONSTITUTION.md)(宪法,否决权)、
   [DESIGN_ISSUES.md](DESIGN_ISSUES.md)(问题池:出问题先入池再排期)、
   [DESIGN_MEMORY.md](DESIGN_MEMORY.md)(经验:已验证事实+待验证假设)、
   [DESIGN_ITERATIONS.md](DESIGN_ITERATIONS.md)(迭代记录:每轮八步,
   结论只有 ACCEPT/REJECT/INCONCLUSIVE)。每轮先读前三者;经验条目
   M1~M11 是已验证的坑与边界。
1. **[DESIGN_CONSTITUTION.md](DESIGN_CONSTITUTION.md) — 设计宪法,拥有否决权**。
   视觉中心永远是小乔;装饰降低识别度就删;不用发光掩盖结构问题;
   角色必须有重量;脸部禁止橡皮变形;AI UI 要世界化;真实桌面尺寸优先。
2. `EXPERIMENTS.md` — 实验决策记录。**回滚过的设计不要重复引入**
   (如自动切层 E40);改前查,改后记。
3. `CONTENTS.md` — 功能/彩蛋清单与状态机速查(新增状态、粒子、音效
   的红线都在里面,如:加星光走 gain_star()、位置参数用像素不用比例)。

## 工程红线

- 改 pet.py 前:确认没有并行会话在写同一文件(比对 mtime),改动要原子。
- 测试:test_pet / test_life / test_swing / test_session_lights /
  test_ai_lights_data 全绿才算过;测试隔离用户数据,不跑消耗真实
  AI 额度的质量测试。
- 自动化口:写 pet_cmd.json 驱动,读 pet_state.json(--debug-state 启动)
  观测;演示/模拟数据用 {"op":"demo",...},页脚会标注「模拟」。
- 素材:不要用拉伸、模糊、发光掩盖结构或素材缺失;缺被遮挡区域就补
  素材或调分层。
