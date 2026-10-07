"""Seated actions on the swing (I-40): short timelines that the swing art can actually show.

At real desktop size only a few channels read on the seated artwork: the swing itself (front/back),
gaze (the face moves rigidly, the hat brim more), the hat-tip rotation (about 5 px at most at 150 %),
breath, and the eyelid / emotion-mouth overlays. Hands, knees, legs and the cushion are pinned by
SceneArt.contact_gate, so nothing here waves, kicks or stretches. hat_dx and hair impulses stay below
one screen pixel after _art_pose's dead zones, so the timelines do not use them.

Pure logic: no Tk, no PIL and no clock of its own. pet.py passes `now`, blends gaze()/breath() into
_art_pose, applies due() impulses to its own springs and pendulum, and damps the swing while holding().
"""

HOLD_DAMPING = 2.2        # pendulum damping while she holds still (normal swinging uses 0.30)
PUSH_IMPULSE = 0.75       # B3: a push on the seat (rad/s); the pendulum soft-limits at SWING_MAX_AMP
LONG_PRESS_MS = 900       # B4: press without moving this long
SEAT_ZONE_Y = 880         # B3: clicks at or below this art-pixel row (cushion, knees, legs, shoes) push the swing;
                          #     her hand resting on the lap and the skirt above it stay a head pat
FADE_IN, FADE_OUT = 0.2, 0.45

# Gaze keys are absolute targets in -1..1 (+lx = towards screen right, where the workspace panel is;
# +ly = down). `side` mirrors lx and the hat impulses. hits: (seconds, 'hat' | 'swing', impulse).
# hold: (t0, t1) the swing is damped to a stop. lid: (eyelid 0..1, emotion mode, seconds) via Pet._offer_lid.
ACTIONS = {
    # 套一 · 陪你干活 (agent_companion maps reaction kinds onto these)
    'glance': dict(prio=0, dur=2.0,
                   lx=((0, 0), (.25, .875), (1.3, .875), (1.8, 0)),
                   ly=((0, 0), (.25, .25), (1.3, .25), (1.8, 0)),
                   hits=((.2, 'hat', .3),), lid=(.16, 'curious', 2.0)),
    'nudge': dict(prio=1, dur=3.2,
                  lx=((0, 0), (.35, 1.0), (2.6, 1.0), (3.1, 0)),
                  ly=((0, 0), (.35, .375), (2.6, .375), (3.1, 0)),
                  hits=((.7, 'hat', .45), (1.5, 'hat', .45)), hold=(0, 2.8), lid=(.16, 'curious', 3.0)),
    'startle': dict(prio=1, dur=1.8,
                    lx=((0, 0), (.1, .75), (1.3, .75), (1.7, 0)),
                    ly=((0, 0), (.1, -.25), (1.3, -.125), (1.7, 0)),
                    hits=((0, 'swing', -.22), (0, 'hat', -.6)), lid=(.02, 'surprised', 1.6)),
    'relief': dict(prio=0, dur=2.8, lx=None,
                   ly=((0, 0), (.9, -.375), (1.3, -.375), (2.0, .25), (2.7, 0)),
                   breath=((0, 0), (.9, 1.4), (1.2, 1.4), (2.2, -1.0), (2.8, 0)),
                   hits=((1.25, 'swing', .09), (1.3, 'hat', -.3)), lid=(.22, 'happy', 2.6)),
    # 套二 · 摸摸她 (direct input on the swing; always outranks the agent reactions)
    'pat': dict(prio=2, dur=2.6,
                lx=((0, 0), (.6, -.25), (1.0, .25), (1.4, -.25), (1.8, .25), (2.4, 0)),
                ly=((0, 0), (.3, .5), (2.1, .5), (2.5, 0)),
                breath=((0, 0), (.4, .5), (2.2, .5), (2.6, 0)),
                hits=((.5, 'hat', -.3), (.9, 'hat', .3), (1.3, 'hat', -.3), (1.7, 'hat', .3)),
                hold=(0, 2.2), lid=(.3, 'shy', 2.4)),
    'flick': dict(prio=2, dur=1.9,
                  lx=((0, 0), (.25, -.25), (1.2, -.25), (1.7, 0)),
                  ly=((0, 0), (.25, -.75), (1.2, -.75), (1.7, 0)),
                  hits=((0, 'hat', .6),), lid=(.05, 'amazed', 1.4)),
    'push': dict(prio=2, dur=4.0, lx=None,
                 ly=((0, 0), (.4, -.25), (3.4, -.25), (4.0, 0)),
                 lid=(.22, 'happy', 3.0), mouth=('laugh', 1.0)),
    'shy': dict(prio=2, dur=2.6,
                lx=((0, 0), (.3, -.875), (1.5, -.875), (1.8, -.25), (2.1, -.25), (2.5, 0)),
                ly=((0, 0), (.3, .375), (1.5, .375), (2.5, 0)),
                hits=((.2, 'hat', -.45),), hold=(0, 2.0), lid=(.3, 'shy', 2.6)),
}


def _ease(a, b, t0, t1, t):
    if t <= t0:
        return a
    if t >= t1:
        return b
    x = (t - t0) / (t1 - t0)
    return a + (b - a) * x * x * (3 - 2 * x)


def track(keys, t):
    """Smoothstep between neighbouring (time, value) keys; held flat outside them."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, a), (t1, b) in zip(keys, keys[1:]):
        if t <= t1:
            return _ease(a, b, t0, t1, t)
    return keys[-1][1]


class SeatMotion:
    """One seated action at a time. A new one replaces the current one unless the current one ranks higher."""

    def __init__(self):
        self.name, self.born, self.side, self.fired = None, 0.0, 1, set()

    def active(self, now):
        if self.name and 0.0 <= now - self.born < ACTIONS[self.name]['dur']:
            return self.name
        self.name = None
        return None

    def start(self, name, now, side=1):
        spec = ACTIONS[name]
        current = self.active(now)
        if current and ACTIONS[current]['prio'] > spec['prio']:
            return False
        self.name, self.born, self.side, self.fired = name, now, (1 if side >= 0 else -1), set()
        return True

    def stop(self):
        self.name = None

    def _weight(self, spec, age):
        """Blend weight against the pet's own gaze: eases in and back out, so the head never jumps."""
        return min(_ease(0.0, 1.0, 0.0, FADE_IN, age),
                   _ease(1.0, 0.0, spec['dur'] - FADE_OUT, spec['dur'], age))

    def gaze(self, now, base):
        name = self.active(now)
        if name is None:
            return base
        spec, age = ACTIONS[name], now - self.born
        w = self._weight(spec, age)
        lx, ly = base
        if spec.get('lx') is not None:
            lx = lx * (1 - w) + track(spec['lx'], age) * self.side * w
        if spec.get('ly') is not None:
            ly = ly * (1 - w) + track(spec['ly'], age) * w
        return lx, ly

    def breath(self, now, base):
        name = self.active(now)
        if name is None or ACTIONS[name].get('breath') is None:
            return base
        spec, age = ACTIONS[name], now - self.born
        w = self._weight(spec, age)
        return base * (1 - 0.6 * w) + track(spec['breath'], age)

    def holding(self, now):
        name = self.active(now)
        hold = ACTIONS[name].get('hold') if name else None
        return bool(hold and hold[0] <= now - self.born <= hold[1])

    def due(self, now):
        """Impulses whose time has come, each exactly once: [(channel, value)]. Hat impulses follow `side`."""
        name = self.active(now)
        if name is None:
            return []
        age, out = now - self.born, []
        for i, (t, channel, dv) in enumerate(ACTIONS[name].get('hits', ())):
            if i not in self.fired and age >= t:
                self.fired.add(i)
                out.append((channel, dv * self.side if channel == 'hat' else dv))
        return out
