"""次级物理(life.py)回归:纯数学,无窗口。

钉住:弹簧收敛与限幅、永不 NaN、微风永不精确循环、落地冲击的
检测-触发-单次语义、blocked 状态衰减与恢复缓入。
"""
import math
import random
import unittest

from life import LifeMotion, Spring, Wander, clamp


class SpringTests(unittest.TestCase):
    def test_converges_to_target(self):
        s = Spring(freq=2.0, zeta=0.5, limit=None)
        for _ in range(4000):
            s.step(1 / 60.0, target=0.6)
        self.assertAlmostEqual(s.x, 0.6, delta=0.01)

    def test_impulse_decays(self):
        s = Spring(freq=2.4, zeta=0.34, limit=None)
        s.impulse(5.0)
        peak = max(abs(s.step(1 / 60.0)) for _ in range(600))
        self.assertLessEqual(abs(s.x), 0.01)       # 最终归零
        self.assertGreater(peak, 0.0)

    def test_limit_is_soft_wall(self):
        s = Spring(freq=2.0, zeta=0.1, limit=1.0)
        s.impulse(50.0)
        for _ in range(2000):
            s.step(1 / 60.0)
            self.assertLessEqual(abs(s.x), 1.0 + 1e-9)

    def test_no_nan_with_jittery_dt(self):
        s = Spring(freq=3.0, zeta=0.3, limit=2.0)
        rng = random.Random(7)
        for _ in range(10000):
            s.step(rng.uniform(0.0, 0.12), target=rng.uniform(-1, 1))
            self.assertFalse(math.isnan(s.x))
            self.assertFalse(math.isnan(s.v))


class WanderTests(unittest.TestCase):
    def test_bounded(self):
        w = Wander(3.3)
        for i in range(5000):
            v = w.sample(i * 0.016)
            self.assertGreaterEqual(v, -1.05)
            self.assertLessEqual(v, 1.05)

    def test_never_repeats(self):
        w = Wander(1.1)
        a = [round(w.sample(t), 6) for t in (100.0, 100.0 + 7 * 86400.0)]
        self.assertNotEqual(a[0], a[1])            # 一周后不循环


class LifeMotionTests(unittest.TestCase):
    def test_landing_impulse_fires_once(self):
        m = LifeMotion()
        t = 100.0
        # 模拟下坠:fy 每帧 +12,持续 30 帧
        fy = 1000.0
        for _ in range(30):
            t += 1 / 60.0
            fy += 12.0
            m.update(t, "fall", False, 1400.0, fy)
        before = m.hair.v
        # 着地:速度骤停
        t += 1 / 60.0
        m.update(t, "fall_stand", False, 1400.0, fy + 4.0)
        self.assertGreater(abs(m.hat_rot.v) + abs(m.hair.v) + abs(m.hem.v), 0.1)
        self.assertGreater(m.hair.v, before)
        # 站稳后继续相同 fy:不再触发新的落地冲击(帽子不再被再次前扣),
        # 弹簧只受阻尼和微风影响,自然衰减
        hat_v_after = m.hat_rot.v
        for _ in range(10):
            t += 1 / 60.0
            m.update(t, "idle", False, 1400.0, fy)
        self.assertLess(abs(m.hat_rot.v), abs(hat_v_after) + 0.005)

    def test_blocked_decays_and_recovers(self):
        m = LifeMotion()
        t = 100.0
        m.hair.impulse(4.0)
        for _ in range(60):
            t += 1 / 60.0
            m.update(t, "flip", False, 0.0, 800.0)
        self.assertLess(abs(m.hair.x), 0.05)       # blocked 全程衰减
        for _ in range(60):
            t += 1 / 60.0
            m.update(t, "idle", False, 0.0, 800.0)
        self.assertLessEqual(abs(m.hair.x), 6.0)   # 恢复后限幅之内

    def test_values_stay_bounded_in_chaos(self):
        m = LifeMotion()
        rng = random.Random(11)
        t, x, fy = 0.0, 1400.0, 1500.0
        for _ in range(12000):
            t += 1 / 30.0
            x += rng.uniform(-14, 14)
            fy += rng.uniform(-30, 30)
            st = rng.choice(("idle", "walk", "drag", "flip", "sleep", "dance"))
            drag = st == "drag"
            sway = m.update(t, st, drag, x, fy,
                            bob_vel=rng.uniform(-4, 4),
                            walking=st == "walk", t=t)
            for v in sway:
                self.assertFalse(math.isnan(v))
        limits = (0.075, 6.0, 6.0, 5.0)
        for v, lim in zip(sway, limits):
            self.assertLessEqual(abs(v), lim + 1e-9)

    def test_hair_strands_mirrored_and_bounded(self):
        m = LifeMotion()
        t = 0.0
        for _ in range(3000):
            t += 1 / 30.0
            m.impulse_hair(0.9)
            m.update(t, "idle", False, 0.0, 800.0, bob_vel=-3.0)
            for sp in m.hair_strands:
                self.assertFalse(math.isnan(sp.x))
                self.assertLessEqual(abs(sp.x), 7.0 + 1e-9)
        # 三缕相位/频率不同 → 稳态值必然互相有别(波浪感的数据面)
        vals = [sp.x for sp in m.hair_strands]
        self.assertTrue(len(set(round(v, 3) for v in vals)) >= 2)

    def test_knee_shear_bounded_and_landing_bend(self):
        m = LifeMotion()
        t, fy = 100.0, 1000.0
        for _ in range(30):                    # 下坠
            t += 1 / 60.0
            fy += 12.0
            m.update(t, "fall", False, 0.0, fy)
        m.update(t + 1 / 60.0, "fall_stand", False, 0.0, fy + 4.0)
        # 落地屈膝冲量直接体现在速度上(位置会被微风目标淹没)
        self.assertLess(m.knee_l.v, 0.0)
        self.assertLess(m.knee_r.v, 0.0)
        for _ in range(600):
            t += 1 / 60.0
            m.update(t, "idle", False, 0.0, fy)
        self.assertLessEqual(abs(m.knee_l.x), 7.0 + 1e-9)
        self.assertLessEqual(abs(m.knee_r.x), 7.0 + 1e-9)

    def test_breathing_drives_hat_against_body(self):
        # 同一条时间线跑两遍:恒定上抬 vs 恒定下压,帽尖响应方向必须相反
        # (对照式断言,不受微风相位影响)
        ends = []
        for bob_vel in (-3.0, 3.0):
            m = LifeMotion()
            t = 100.0
            for _ in range(240):
                t += 1 / 60.0
                m.update(t, "idle", False, 0.0, 800.0, bob_vel=bob_vel)
            ends.append(m.hat_rot.x)
        self.assertLess(ends[0], ends[1])


if __name__ == "__main__":
    unittest.main()
