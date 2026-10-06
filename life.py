# -*- coding: utf-8 -*-
"""角色"生命感"次级物理 —— 帽尖/发梢/裙摆的延迟摆动与惯性。

思路与 depth_model 的部位网格互补:网格管"看向哪 / 倾斜 / 压扁"这类主动
变形;这里管"身体动了之后,身上松垮的部分要晚一点才跟上来"的被动变形
—— Live2D 术语里的 Secondary Animation。

全部是纯数学弹簧与有机漂移,不依赖 Tk/PIL,可独立单测。

激励源(pet.py 渲染处采集):
- 呼吸浮动的速度:身体上抬时,帽尖/裙摆向下拖一下再弹回
- 水平速度与加速度(走路、被拖拽、抛掷):加速时帽子后仰、发梢反甩
- 落地冲击:fy 速度骤停 → 帽子前倾、发梢上扬、裙摆下压(自动检测,
  不需要在每个落地调用点埋钩子)
- 走路落脚上升沿:帽尖点一下、裙摆荡一下
- 有机漂移:多个不可通约频率正弦叠加的"微风"——永不精确循环,
  静止时也有极轻微的不规则起伏,这是"不像循环 GIF"的关键。

输出四通道 sway (hat_rot, hat_dx, hair_dx, hem_dx),由
depth_model.DepthWarp.displacement 的 hat/hair/skirt 权重消费。
所有通道:限幅、blocked 状态衰减、恢复 0.3s 缓入,绝不和主动作打架。
"""
import math


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class Spring:
    """欠阻尼标量弹簧。半隐式欧拉积分,dt 抖动稳定;impulse 打击速度。"""

    def __init__(self, freq=2.4, zeta=0.34, limit=1.0):
        self.omega = max(0.4, freq) * 2 * math.pi
        self.zeta = zeta
        self.limit = limit
        self.x = 0.0
        self.v = 0.0

    def step(self, dt, target=0.0, force=0.0):
        """推进一步。target 是静止点,force 是持续外力(加速度)。"""
        if dt <= 0:
            return self.x
        dt = min(dt, 0.05)
        self.v += (-self.omega * self.omega * (self.x - target)
                   - 2 * self.zeta * self.omega * self.v + force) * dt
        self.x += self.v * dt
        if self.limit is not None and abs(self.x) > self.limit:
            self.x = clamp(self.x, -self.limit, self.limit)
            self.v *= -0.35           # 触限不是撞墙:留一点软反弹
        return self.x

    def impulse(self, dv):
        self.v += dv


class Wander:
    """有机漂移:三个不可通约频率的正弦叠加,输出约 -1..1。

    频率之间无公倍数,永不精确循环;不同 seed 给不同角色/通道。"""

    def __init__(self, seed=0.0):
        s = math.sin(seed * 12.9898) * 43758.5453
        base = s - math.floor(s)
        self.freqs = (0.11 + 0.05 * base, 0.043 + 0.031 * base,
                      0.017 + 0.023 * (1.0 - base))
        self.phases = (base * 6.283, base * 3.1, base * 9.7)

    def sample(self, t):
        (a, b, c), (p0, p1, p2) = self.freqs, self.phases
        return (0.55 * math.sin(t * a * 6.283 + p0)
                + 0.30 * math.sin(t * b * 6.283 + p1)
                + 0.15 * math.sin(t * c * 6.283 + p2))


class Pendulum:
    """可积钟摆(秋千的心脏):θ'' = -k·sinθ - c·θ'。

    不是固定正弦:被拉到一边松手、被点击推一下,都会真实地进入摆动,
    再由阻尼慢慢衰减回微摆。amp < idle_amp 时沿速度方向"泵"能量
    (像人荡秋千),让她静止时也有 ±4° 左右的活气;
    amp > max_amp 时软限幅,拉爆也不会翻圈。"""

    def __init__(self, period=3.4, damping=0.30, idle_amp=0.075, max_amp=0.80):
        self.w0 = 2 * math.pi / max(0.5, period)
        self.k = self.w0 * self.w0
        self.damping = damping
        self.idle_amp = idle_amp
        self.max_amp = max_amp
        self.theta = 0.0
        self.omega = 0.0

    def step(self, dt, pump=True):
        dt = min(max(dt, 0.0), 0.05)
        self.omega += (-self.k * math.sin(self.theta)
                       - self.damping * self.omega) * dt
        self.theta += self.omega * dt
        amp = self.amplitude
        if pump and amp < self.idle_amp:
            if abs(self.omega) <= 1e-4:
                # 绝对静止的对称点没有任何力,永远启动不了 —— 主动荡第一圈
                self.omega = 0.06 * self.w0
            else:
                # 沿当前速度方向补能量:补的是角速度,不瞬跳
                add = min(self.idle_amp - amp, 0.02) * self.w0 * dt * 8.0
                self.omega += math.copysign(add, self.omega)
        if amp > self.max_amp:
            scale = self.max_amp / amp
            self.theta *= scale
            self.omega *= scale
        return self.theta, self.omega

    def impulse(self, dv):
        self.omega += dv

    @property
    def amplitude(self):
        return math.hypot(self.theta, self.omega / self.w0)


class LifeMotion:
    """汇总激励源 → 四通道 sway。数字单位是原画像素域(730x750)。

    hat_rot:帽尖微旋转(rad 级)。depth 端乘 (帽基y - y),越高处位移越大,
             呈现"帽尖拖在后面"的延迟感;
    hat_dx: 帽子整体水平微移;
    hair_dx / hem_dx:发梢/裙摆下缘的水平拖尾,深度端按高度加权,
             越靠下摆动越大。"""

    BLOCKED = frozenset(("flip", "roll", "twirl", "rewind", "fly", "transform"))
    LAND_VY = 260.0        # 判定"落地"的下落速度阈值(逻辑 px/s)
    LAND_JERK = 420.0      # 速度骤变量阈值

    def __init__(self):
        self.hat_rot = Spring(freq=1.7, zeta=0.30, limit=0.055)
        self.hat_dx = Spring(freq=2.2, zeta=0.36, limit=6.0)
        self.hair = Spring(freq=2.6, zeta=0.42, limit=6.0)
        # 发层分缕:三缕频率略差,配合不同微风相位 → 波浪般的独立起伏
        self.hair_strands = (Spring(freq=2.20, zeta=0.36, limit=7.0),
                             Spring(freq=2.42, zeta=0.37, limit=7.0),
                             Spring(freq=2.64, zeta=0.38, limit=7.0),
                             Spring(freq=2.86, zeta=0.39, limit=7.0),
                             Spring(freq=3.08, zeta=0.40, limit=7.0),
                             Spring(freq=3.30, zeta=0.42, limit=7.0))
        self.hair_gust = (Wander(21.3), Wander(33.7), Wander(48.1),
                          Wander(13.9), Wander(27.6), Wander(55.2))
        self.hem = Spring(freq=1.6, zeta=0.44, limit=5.0)
        self.leg_l = Spring(freq=2.7, zeta=0.32, limit=0.10)  # 左腿悬垂角
        self.leg_r = Spring(freq=2.9, zeta=0.32, limit=0.10)  # 右腿悬垂角(频率略差→自然剪刀)
        self.knee_l = Spring(freq=2.1, zeta=0.30, limit=7.0)  # 膝弯剪切(px)
        self.knee_r = Spring(freq=2.3, zeta=0.30, limit=7.0)
        self.gust = (Wander(1.7), Wander(4.2), Wander(9.1), Wander(6.3))  # 幅度在 update 里取
        self.last = None
        self.prev_x = None
        self.prev_fy = None
        self.prev_vy = 0.0
        self.step_armed = True
        self.blocked = False
        self.recovered = None

    def update(self, now, state, dragging, x, fy, bob_vel=0.0,
               walking=False, t=0.0):
        """每帧调用。返回 (hat_rot, hat_dx, hair_dx, hem_dx)。

        x/fy 用逻辑像素即可,内部只看差分;bob_vel 是呼吸浮动的瞬时速度
        (向上为负),walking 表示正在走路(用它抓落脚上升沿)。"""
        dt = max(0.0, min(now - self.last, 0.05)) if self.last is not None else 0.016
        self.last = now
        vx = 0.0
        if self.prev_x is not None and dt > 0:
            vx = (x - self.prev_x) / dt
        self.prev_x = x

        # 落地自动检测:fy 向下为正 —— 上一帧还在明显下坠(vy 大正数)、
        # 这一帧速度骤停 → 冲击
        land = 0.0
        if self.prev_fy is not None and dt > 0:
            vy = (fy - self.prev_fy) / dt
            if (self.prev_vy > self.LAND_VY
                    and self.prev_vy - vy > self.LAND_JERK
                    and not dragging):
                land = clamp(self.prev_vy, 0.0, 1600.0)
            self.prev_vy = vy
        self.prev_fy = fy

        # 走路落脚的上升沿(每步只触发一次)
        step = False
        if walking:
            if self.step_armed:
                step = True
                self.step_armed = False
        else:
            self.step_armed = True

        # blocked 衰减与恢复缓入(和 DepthMotion 相同的手法)
        blocked = state in self.BLOCKED
        if self.blocked and not blocked:
            self.recovered = now
        self.blocked = blocked
        gain = 1.0
        if blocked:
            gain = 0.0
        elif self.recovered is not None:
            ph = clamp((now - self.recovered) / 0.3, 0.0, 1.0)
            gain *= ph * ph * (3 - 2 * ph)

        # --- 连续力 ---
        # 呼吸反相:身体上抬(bob_vel<0)时帽尖向下拖(负向旋转)、
        # 裙摆向上飘;幅度极小,只是"松垮部分跟不上身体"的那一点意思
        f = gain * 46.0
        self.hat_rot.step(dt, force=bob_vel * f * 0.0035)
        self.hem.step(dt, force=bob_vel * f * 0.010)
        # 微风:静止时的有机漂移,幅度极小(这就是"不是循环 GIF"的那口气)
        g2 = self.gust[2].sample(t) * 2.2 * gain
        self.leg_l.step(dt, force=g2 * 1.0)
        self.leg_r.step(dt, force=g2 * -0.8)   # 微风里两腿反相,像真的悬垂
        self.knee_l.step(dt, target=self.gust[3].sample(t) * 1.2 * gain)
        self.knee_r.step(dt, target=self.gust[3].sample(t + 9.0) * 1.2 * gain)
        self.hat_rot.step(dt, target=self.gust[0].sample(t) * 0.010 * gain)
        self.hat_dx.step(dt, target=self.gust[1].sample(t) * 0.5 * gain)
        self.hair.step(dt, target=self.gust[2].sample(t) * 0.7 * gain)
        breath_f = (0.006, 0.0055, 0.005, 0.0045, 0.004, 0.0035)
        for idx, sp in enumerate(self.hair_strands):
            gt = self.hair_gust[idx].sample(t) * 0.85 * gain
            fv = bob_vel * f * breath_f[idx] * gain
            sp.step(dt, target=gt, force=fv)
        self.hem.step(dt, target=self.gust[3].sample(t) * 0.6 * gain)

        # --- 冲击 ---
        if dragging:
            # 被拎着甩:水平加速度让帽子后仰、发梢反甩、裙摆拖沓(温和)
            ax = clamp((vx - getattr(self, "_pvx", 0.0)) / max(dt, 1e-4),
                       -4000.0, 4000.0) if dt > 0 else 0.0
            self.hat_rot.impulse(clamp(-ax * 1.6e-5, -0.045, 0.045) * gain)
            self.hair.impulse(clamp(-ax * 2.2e-4, -0.55, 0.55) * gain)
            self.hem.impulse(clamp(ax * 1.6e-4, -0.45, 0.45) * gain)
        if land > 0.0:
            k = gain * clamp(land / 700.0, 0.25, 1.6)
            self.hat_rot.impulse(-0.075 * k)      # 帽子往前扣一下
            self.impulse_hair(3.4 * k)            # 发梢上扬(含分缕)
            self.hem.impulse(-2.6 * k)            # 裙摆下压
            self.leg_l.impulse(-0.05 * k)         # 落地屈膝:两腿前收
            self.leg_r.impulse(-0.045 * k)
            self.knee_l.impulse(-2.6 * k)         # 膝弯:落地时小腿后甩
            self.knee_r.impulse(-2.4 * k)
        if step:
            self.hat_rot.impulse(0.028 * gain)    # 落脚:帽尖点一下
            self.hem.impulse(1.8 * gain)          # 裙摆荡一下
        if vx and not dragging:
            # 匀速走路的持续拖尾(幅度小,方向反速度)
            self.hair.step(dt, target=clamp(-vx * 0.045, -3.0, 3.0) * gain)
            self.hem.step(dt, target=clamp(vx * 0.030, -2.2, 2.2) * gain)
        self._pvx = vx
        return (self.hat_rot.x, self.hat_dx.x, self.hair.x, self.hem.x)

    def impulse_hair(self, dv):
        """发层统一冲量入口:主弹簧 + 三缕按 1.0/0.82/0.66 递减滞后。"""
        self.hair.impulse(dv)
        fac = (1.0, 0.92, 0.83, 0.74, 0.65, 0.55)
        for idx, sp in enumerate(self.hair_strands):
            sp.impulse(dv * fac[idx])

    def values(self):
        return (self.hat_rot.x, self.hat_dx.x, self.hair.x, self.hem.x)
