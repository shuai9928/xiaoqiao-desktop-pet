# 帽上特效第二批（B 系列）设计规格 — outputs/fx2

2026-10-04 起草（设计稿，未动任何代码）。定位：**介于现版（I-29 A1+A2）和王者荣耀皮肤特效之间的中间态**——明显更浓、更活，但不破设计宪法。

对上一批用户反馈"太单调"的回应分四路：**浓度**（点阵→光带、烟柱有核有晕）、**色彩**（灰紫单色→金/紫双色渐变）、**常驻生命**（idle 也有微氛围）、**时刻感**（思考起/止、AI 完成的短促爆发）。所有数值从代码与本机实测读出，出处随文标注。

验收基准档（下文所有"2x 帧 px"指 SS=2 超采样坐标，同 fx.py 约定）：本机当前设置 pet scale 0.8 + 秋千 scene_scale 1.0 → 人物可见高 ≈280 逻辑 px（1x）≈ **560 px（2x）**，人物包围盒（girl_bbox 906×1187 原画 px × k）≈ **428×560 ≈ 240K px²（2x）**；I-29 的对照档 scene_scale 0.76 → 人物高 ≈426 px（2x）。百分比指标一律按当帧实测包围盒算，不写死。

---

## A. 现状诊断（量化）

数据来源：hat_fx.py（槽位/采样/alpha 公式）、fx.py（烘焙与精灵）、assets/hat_fx_v1/*.png 实测像素统计、outputs/hat-fx-a1-a2/帧耗时采样.json（真机 A/B）、I-29 记录（DESIGN_ITERATIONS.md）。

| 维度 | A1 星轨拖尾 | A2 思考星烟 |
|---|---|---|
| 固定槽位 | 3 天体 × 10 历史槽 = 30 | 12 槽 |
| 实际存活/帧 | fast 全 30；reduced keep=6 → 18 | fast ≈8（发射 1/6s × 寿命 1.25s）；慢 ≈3–4 |
| 采样间隔 | 75ms（fast）/ 125ms（reduced） | 同左（发射率 6.7/s / 3/s） |
| 生命周期 | 0.82s | 1.25s |
| 烘焙精灵尺寸 | extent 12 × pixel_scale 1.6 → 长边 ≤19 px（2x）≈9.6 逻辑 px | extent 36 → 52×58 px（2x）≈26×29 逻辑 px |
| 不透明核心（α≥96） | ≈5–6 px（2x）≈**3 逻辑 px** | 柱芯 ≈16 px（2x） |
| alpha 公式峰值 | (1−age/.82)×(.45+.18·depth) → 量化后 **≤0.48**，多数时间 0.12–0.34 | 峰 0.75 → 量化 **≤0.62**，多数 0.22–0.48 |
| alpha 档表 | ALPHAS = (0, .12, .22, .34, .48, .62, .78, .95)，8 档 | 同左 |
| 运动 | 纯轨道采样点列，离轨偏移为常量 12×scale，无漂移 | 上升 8×1.6=12.8 px/s（2x）→ 全程仅 ~16 px（2x）=8 逻辑 px；横摆 ±1.8 px（2x）→ **近乎静止** |
| 主导饱和色（实测 HSV 统计） | 灰紫 (168,144,192) H270 **S0.25**；"金尘"的金只在芯部 | 灰紫 (192,168,240) H260 S0.30；蓝烟 H240 S0.30 |

常驻帧粒子数：实测峰值 **37**（真机采样），固定存储 **45/48** 上限。帧成本：A/B 实测（含 UpdateLayeredWindow 口径）+1.376/+1.536 ms（中位，1.0/0.76 两档），均值 +1.163/+0.932 ms。全屏"效果像素"（α≥0.1 口径）估算 ≈7.6K px²（2x）≈ 人物包围盒 **3.2%**。

**"单调"的四个根因**：
1. **浓度**：核心只有 3 逻辑 px、alpha 封顶 0.48/0.62，且相邻采样点之间无连接 → 读作稀疏点阵，不成光带。
2. **色彩**：三色素材的主导饱和色全是 S≤0.4 的灰紫系，金色只存在于名字里；无沿程/结构渐变。
3. **运动**：烟柱 1.25 秒只挪 8 逻辑 px，等于贴着帽尖的一小团静止雾；拖尾无能量响应。
4. **时刻感**：思考只有"渐亮渐灭"，开始/完成没有一拍重音；idle（轨道静止时拖尾为零，test_stationary_orbit_does_not_emit 锁定）完全无生命。

---

## B. 效果规格表（5 个）

统一约定：所有新效果继续走 `gain_star(..., hat_fx=True)` 零奖励像素通道（CONTENTS 红线）；坐标一律 2x 超采样像素；运行时零 filter/resize/bake（既有测试锁定）；不新增音效、额度请求、数据写入。

能量参数 E（运动质感挂现有量）：`E = clamp(max(|_orbit_speed|/2.4, |dθ_swing/dt|/2.2), 0, 1)`，render 侧每帧已有这两个量，经 gain_star 关键字传一个标量进层，层内不建新状态机。拖尾长度/亮度随 E 变化即"拖尾长度随秋千速度变化"。

### B1 沿程渐变星轨光带（升级替代 A1）

| 项 | 规格 |
|---|---|
| 触发状态 | 常驻；轨道运动（\|_orbit_speed\|>0.025）时发射；密度/长度/亮度挂 E |
| 粒子数 | 3 天体 × **12 采样槽** = 36；存活 keep = 8 + round(4·E) → 24~36；采样间隔 45ms（fast）/75ms（reduced） |
| 精灵尺寸 | 复用 dust-gold / dust-mote / dust-lilac 三张现有 PNG 重烘焙，extent 12→**15**（长边 ≈24 px 2x，核心 6–8 px 2x） |
| 颜色 RGB 表（沿程渐变） | 头 30%：dust-gold（暖金芯≈(253,244,224)+淡紫晕）；中 40%：dust-mote（暖白 (255,246,230)）；尾 30%：dust-lilac（薰衣草紫 (186,160,240)）→ 金→暖白→紫的沿程双色渐变 |
| 连接 | 相邻槽间 1 段 2 层描边矢量线（GOLD_L(255,233,160) α90 / MAGIC_B(199,155,255) α60，宽 ≈1.1px）→ 点阵连成光带 |
| 运动曲线 | 轨道采样 + 呼吸式外漂：offset = 12×(1+0.35·sin(2πt/1.7+体相位))×scale，方向永远向轨道外侧（不朝脸） |
| alpha 范围 | 头 3 槽 0.78~0.95，中段 0.48~0.62，尾段 0.22~0.34；全体 ×(0.8+0.2E) |
| 生命周期 | 0.82 → **1.15s** |
| 帧成本估算 | ≈30 贴 × 576 px² ≈ 0.57ms + 连接线 ≈0.08ms → **≈0.65ms** |

### B2 核晕双层思考星烟（升级替代 A2）

| 项 | 规格 |
|---|---|
| 触发状态 | 仅真实 ai_thinking（或 DEBUG_STATE 显式标注 demo），沿袭 A2 门禁 |
| 粒子数 | **14 槽**；发射 7/s（fast）/4/s（慢）；存活 ≈9/5 |
| 精灵尺寸 | extent 36 不变（52×58 px 2x）；bake 时程序化合成**双层**：底部 1/3 暖白亮核 + 上 2/3 紫晕 + 顶 1 颗金星点；另备 4 档"成长"（核先亮→晕展开） |
| 颜色 RGB 表 | 核 (255,246,214) 暖白；晕 (199,155,255) 紫，顶部渐淡至 (168,216,255)；星点 (242,193,78) 金 → 金核紫晕 |
| 运动曲线 | 上升 8→**22 px/s×scale**（2x 35 px/s，全程 ≈45 px 2x = 23 逻辑 px）；横摆 amp 1.1→**3.0**×scale、频率 1.6Hz；螺旋相位 = 槽序号 ×0.55 rad（烟柱呈微螺旋而非直线） |
| alpha 范围 | 核峰 0.78 / 晕峰 0.48；末 1/3 寿命线性淡出 |
| 生命周期 | 1.25 → **1.3s** |
| 帧成本估算 | ≈9 贴 × 3.0K px² ≈ **0.9ms** |

### B3 常驻微氛围（新增：萤火 + 帽檐符文微光）

| 项 | 规格 |
|---|---|
| 触发状态 | 常驻（含 idle——这是"她 idle 也有生命感"的唯一来源，拖尾静止时仍活） |
| 粒子数 | **3 颗萤火**（固定 3 槽，无发射/回收）+ **6 个帽檐符文微光刻度**（静态几何+慢转，非粒子场） |
| 精灵尺寸 | 萤火：dust-mote 重烘焙 extent 9→11（长边 ≈18 px 2x）；微光：复用 fx._sigil_sprite（≈9 px 2x） |
| 颜色 RGB 表 | 萤火 2 紫（dust-lilac）+ 1 金（dust-gold）；微光 MAGIC_B(199,155,255) 单色 |
| 运动曲线 | 萤火：绕肩线椭圆（2x：rx≈265=0.62×人物包围盒宽，落在身体两侧留白区，ry=0.5rx，倾角 27° 同帽檐），周期 14/19/26s 错相，亮度呼吸 2.8s；微光：沿 HAT_ORBIT 椭圆 6 个固定刻度，0.05 rad/s 慢转（与星轨反向），6s 呼吸 |
| alpha 范围 | 萤火 0.22~**0.45**；微光 0.14~**0.20**（极淡，可被"装饰否决权"检验：两者合计不透明像素 <0.6K px² ≈ 包围盒 0.25%） |
| 生命周期 | 永驻（仅亮度呼吸）；ui_reduced_anim / 缺素材时随整层关闭 |
| 帧成本估算 | 3×196 px² + 6×~80 px² ≈ **0.03ms** |
| 位置红线 | 萤火画在人物剪影后层（被身体自然遮挡，不可能压脸）；微光只画轨道远侧上半圈（sin(ang)<0），与近脸侧永久隔离 |

### B4 帽尖星爆（新增：思考开始 / 完成重音）

| 项 | 规格 |
|---|---|
| 触发状态 | 层内检测 set_thinking 边沿：False→True 起爆（金紫）；True→False 且本轮 ≥2s 完成爆（暖白金）。仍经 gain_star(hat_fx=True) 通道传 event，不碰 _apply_ai 以外的状态 |
| 粒子数 | **0 槽**——整段爆预渲染为 1 张复合贴图 ×10 档（fx.py 的 burst/hit 同语言），每帧只 1 贴；同时最多 1 个爆 |
| 精灵尺寸 | 复合贴图 ≈**64×64 px 2x**：白金芯（(255,250,240)，r≈9px）+ 8 向金刺（GOLD_L，长 ≈20px）+ 6 颗紫星尘（MAGIC_B，环带 r≈26px） |
| 运动曲线 | ease-out 扩散（同 _hit_sprite 节奏：先冲后化）；完成爆叠加 B5 错峰 |
| alpha 范围 | 峰 **0.90**，0.75s 内 (1−u)^0.75 衰减 |
| 生命周期 | **0.75s**（<1s 红线） |
| 帧成本估算 | 4.1K px² ≈ **0.14ms**（瞬时） |

### B5 完成环爆（新增：AI 完成的绿色环爆）

| 项 | 规格 |
|---|---|
| 触发状态 | 与 B4 完成爆同沿触发，错峰 +0.15s；爆心 = 帽尖 |
| 粒子数 | 0 槽——复用 fx.hit_ring()：hit 表新增 **"mint"** 档（_hit_sprite 换色即可，一行级改动） |
| 精灵尺寸 | 终半径 ≈34 px（2x），与现有 gold/pink 命中环同量级；色 (150,238,206)（与既有星晶精灵同色系，对应 CONTENTS"绿=完成"）+ 暖白芯 (255,250,240) |
| 运动曲线 | 环 ease-out 扩散 + 前 40% 亮芯星芒（_hit_sprite 既有语言） |
| alpha 范围 | 峰 0.85 |
| 生命周期 | **0.55s** |
| 帧成本估算 | ≈6.7K px² ≈ **0.22ms**（瞬时） |

### 汇总：峰值粒子账本与成本

| 层 | 槽/贴数（峰值） |
|---|---|
| B1 拖尾 | 36 |
| B2 星烟 | 14 |
| B3 萤火 | 3 |
| 轨道天体（既有 3 颗，不动） | 3 |
| B3 符文微光（复合贴） | 6 |
| B4+B5 爆（复合贴，瞬时 ≤0.9s） | 2 |
| **合计** | **64 峰值（常态 ≤59）≤ 64 上限** |

帧成本（0.033ms/Kpx² 经验系数，由 I-29 实测 35K px² ↔ 1.0–1.3ms 标定）：稳态（思考中无爆）≈ 0.68+0.89+0.03 ≈ **1.6ms**；全开峰值（满能量拖尾 36 槽 + 双爆同帧）≈ **2.0ms**，贴着预算上限——若实测超限，第一杠杆是 B1 keep 档 −2（成本 −0.06ms/槽），不动浓度结构。B 系列替换 A1/A2（今 1.0–1.3ms），对现状净增 ≈+0.3~0.7ms 稳态。

---

## C. 全局硬阈值

1. **特效像素覆盖**（α≥0.1 口径，占当帧人物包围盒）：常驻 ≤**10%**，爆发期间瞬时（<0.9s）≤**13%**。
   依据：现状 3.2%；B 系列设计值 ≈9.3%（详见 E 表），恰为"浓度 ×3"的像素体现，其余 1~2 倍观感浓度来自亮芯 alpha、双色渐变与连续光带，不再堆像素。王者荣耀级常驻覆盖 20%+，中间态取其半——超过 10%/13% 就进入"光盖人"区间，违反宪法第 2 条（装饰否决权）与 M42（不做常亮大光效）。
2. **脸/帽尖/身体主轮廓覆盖 = 0**：B 系全部绘制在人物剪影**后层**（hat.draw 既有挂点，I-29 已验证"人物不透明像素最大变化=0"的测法沿用）；B2 烟整体起于 tip 上方（既有测试锁定）；B4/B5 爆心 y ≤ tip_y − 6 px（2x）；B3 微光只出现在帽檐远侧上半圈。每帧人物不透明像素前后差必须 = 0。
3. **粒子总数上限 ≤64**：固定槽 56（36 拖尾+14 烟+3 萤火+3 天体）+ 微光 6 + 爆 2 = 64 封顶；`stats().total` 扩展上报，超限先降 B1 keep 数。
4. **帧成本增量 ≤2ms**：沿用 I-29 的 A/B 同帧口径（含 UpdateLayeredWindow），0.76/1.00 双档中位 ≤+2.0ms、p95 ≤+3.0ms；每帧 paste 总面积 ≤60K px²（2x）；单精灵长边 ≤64 px（2x，防大光斑）。
5. **降级链**：_fast_ok=False → 发射率减半、keep=8；ui_reduced_anim 或素材缺失 → 整体退回现 A1/A2 行为或全关（B1/B2 复用现有 6 张 PNG，B3 复用 dust-mote 与 sigil 程序化，B4/B5 纯程序化——缺图退路天然存在）。
6. **入口纪律**：新触发一律经 gain_star(hat_fx=True) 零奖励分支，位置参数用像素不用比例；不加音效、不加额度请求、不写任何存档。

---

## D. 实现路径

### 主路径：程序化 PIL（延续 fx.py 全预渲染风格，零新外部素材）

| 效果 | 生成参数（全部 bake/预渲染期完成） |
|---|---|
| B1 | 零新图：3 张现有 dust PNG 重烘焙 extent 15；连接线为帧内矢量 ImageDraw.line 两层（宽 1.1 主线 + 宽 2.6 低α垫层），与 ground_circle 五芒星同语言、近零成本 |
| B2 | bake 时合成：核 = 椭圆 (0.22w×0.18h) fill (255,246,214,230)，_soft 模糊 0.06h；晕 = 现有 smoke PNG（α×0.85）叠其上；顶星 = 4 芒星（_flash_sprite 语言，r=0.12h，(242,193,78)）；成长 4 档 = 核 α 与晕半径的预渲染档位；模糊一律 _soft_half（半分辨率，省 3/4） |
| B3 | 萤火 = dust-mote 重烘焙 extent 11，_alpha_scaled 备 4 档；微光 = _sigil_sprite(9, seed=1700+i) 经 _alpha_scaled(0.2) 预合成 6 张，运行时按角度挑档 |
| B4 | _burst_sprite(r≈20×k, GOLD_L, 250)（8 刺+实芯）与 6 颗紫星尘（MAGIC_B，环绕 r≈26px）预合成为 10 档 sheet（复用 _merge_mask_layers 思路），尺寸 ≤64px |
| B5 | _hit_sprite(i/9, scale·ss, (150,238,206)) 直接生成 hit["mint"] 10 档，挂进现有 hit 表 |
| 通用 | 不引入 numpy（M41）；运行时零 filter/resize/bake（test_hat_fx 既有守卫延续）；槽位就地更新数字字段、不新建对象（I-29 既有模式） |

### 备用路径：imagegen 提示词（每效果 1 条，给用户侧 imagegen 重新出素材用；产出仍走 bake() 的裁切/预乘/8 档 alpha 流水线）

- **B1 拖尾**：`A single horizontal trail ribbon of tiny glowing four-point star-dust specks, warm gold at the leading head fading through ivory into soft lavender violet at the tail, hand-painted anime mobile-game cosmetic VFX, restrained baked halo, one isolated sprite, actual transparent background, no text.`
- **B2 星烟**：`A small vertical plume of airy star-smoke rising from a bright warm ivory pearl core, translucent lavender-violet vapor tapering into a gentle spiral curl, one tiny warm gold four-point star near the tip, hand-painted anime cosmetic VFX, isolated sprite, actual transparent background.`
- **B3 萤火**：`A single tiny round firefly mote of warm champagne light with a soft lavender halo and one faint four-point glint, hand-painted anime cosmetic VFX sprite, isolated, actual transparent background.`
- **B3 符文微光**：`One faint minimal arcane runic glyph fragment glowing soft violet, thin luminous stroke, extremely subtle, hand-painted anime VFX sprite, isolated, actual transparent background.`
- **B4 星爆**：`A compact radial starburst: bright white-gold core, eight short warm gold rays, six small lavender star sparks arranged in a loose ring, hand-painted anime mobile-game cosmetic VFX, one isolated sprite, no long beams, actual transparent background.`
- **B5 环爆**：`A thin elegant mint-green glowing ring expanding with a warm white inner core flash and subtle spark glints, hand-painted anime cosmetic VFX, one isolated sprite, actual transparent background.`

---

## E. 验收阈值表（供比例检查 agent 与颜色对比度 agent 程序化测量）

| # | 指标 | 阈值 | 程序化测法 |
|---|---|---|---|
| 1 | 拖尾精灵尺寸 | 长边 20~28 px（2x）、核心 5~8 px；单粒 ≤5% 人物高（人物高 560 px 2x @ pet0.8/scene1.0；426 px @ scene0.76） | 读 bake 输出 sprite.size；人物高 = 帧内 girl 不透明 bbox 高 |
| 2 | 拖尾连续性（光带不断点） | 沿轨道弧采样 alpha 剖面，α<0.1 的空隙 ≤8 px（2x） | 用当帧轨道参数沿弧线取帧像素 |
| 3 | 主色相（双色渐变） | 金 H 40~55° 且 S≥0.45；紫 H 255~275° 且 S 0.25~0.60；白芯 V≥0.95；金系像素占比 35~55%（余为紫系/白芯） | 效果区域像素 HSV 直方图（效果区域 = 前后帧差分 ∪ alpha>0 蒙版） |
| 4 | 亮度对比 | 效果像素平均加权亮度 − 同帧本地背景均值 ≥ **35**（0–255）；爆发芯峰值 ≥200 | 前后帧差分定位效果像素，背景取差分区域外扩 12px 环带 |
| 5 | alpha 档上限 | 拖尾头槽 ≤0.95、尾槽 ≤0.34；烟核 ≤0.78、烟晕 ≤0.48；萤火 ≤0.45；符文微光 ≤0.20 | ALPHAS 表 + level 公式单测（公式入 spec 附录，直测档位数组） |
| 6 | 覆盖率 | 常驻 ≤10% 人物包围盒、爆发瞬时 ≤13%；人物不透明像素前后差 = **0** | 差分像素计数 ÷ 当帧 girl bbox 面积；I-29 同法 |
| 7 | 粒子计数 | stats().total ≤64（常态 ≤59）；静止（orbit_speed<0.025）trail=0；非思考 smoke=0 且无爆；reduced 档 B1/B2 发射减半 | 扩展 stats()；复用既有单测模式 |
| 8 | 帧成本 | A/B 中位 ≤+2.0ms、p95 ≤+3.0ms（0.76/1.00 双档）；每帧 paste 面积 ≤60K px²（2x） | outputs/hat-fx-a1-a2/帧耗时采样.json 同法重跑 |
| 9 | 爆发时序 | 起/完成爆 ≤0.75s、环爆 ≤0.55s、错峰 0.15s；仅 ai_thinking 边沿触发（失败路径 _bg_failed 同沿触发为已知边界，记录不阻断） | 层单测注入时间序列断言档位窗口 |
| 10 | 布局与降级 | hat_fx_pad 留边不改变面板六行密度/字号/滚动（既有测试）；ui_reduced_anim、缺素材、_fast_ok=False 三条降级路径各自可渲染且不抛错 | 既有 flat_workspace/hat_fx 测试扩展 |

## 红线对照（设计自检）

- 宪法 1/2（视觉中心、装饰否决权）：B 系全部后层绘制、覆盖硬顶 10%/13%、微氛围合计 0.25% 且极淡——先量占比再谈效果。
- 宪法 3 / M42（发光不掩盖结构、不做常亮大光效）：无任何新增常亮大光斑；微光是"生命感"最小单位（0.03ms、α≤0.2/0.45），判定标准"去掉它会不会更好"在 idle 场景才成立。
- 宪法 6（脸部红线）：无网格变形参与，纯贴图层。
- CONTENTS：gain_star 零奖励通道、像素坐标、无音效/额度/数据写入、_fast_ok 降档、ui_reduced_anim 停用、缺素材退回旧星轨——全部沿用 I-29 已验收的门禁，不新增第二入口。
