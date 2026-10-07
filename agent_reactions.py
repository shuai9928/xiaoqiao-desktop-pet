"""AI-companion reaction rules for the desktop pet. Pure logic: no Tk, no PIL, no clock of its own.

Shaped like the battery code in pet.py (_battery_event / _battery_tick / _battery_react): the host calls update()
every second or two with a snapshot of the agent sessions, executes the Reactions it returns with its own
primitives (say, play_emotion, _start_micro_motion, hop, star_burst, add_part("sweat"), start_stretch), and calls
pull() when the user touches her or moves the cursor near. Nothing here reads task titles, paths or error text:
she only ever names the agent. All numbers are first guesses; tune them on the real machine.

Session dicts: {"id", "agent", "state"} with state in running / waiting / error / done / idle. Pass the state that
flat_workspace.rows_for() reports, so a stale session already arrives as "idle" and never counts as "done".
"""
import random, time
from dataclasses import asdict, dataclass, field

LEVELS = ('off', 'few', 'normal')
DEFAULT_LEVEL = 'few'            # few = only "waiting for you" and "error"; normal adds started / done / quota / long run
WAIT_DWELL, ERROR_DWELL = 20.0, 10.0        # seconds a state must hold before she reacts (debounce)
DONE_MIN_RUN, LONG_RUN = 90.0, 1200.0       # shorter runs finish unremarked; one stretch per session after 20 min
REMIND_WAIT = 600.0                         # one more nudge this long after the first, then never again
STARTED_GAP, GLOBAL_GAP, DAILY_CAP = 600.0, 120.0, 10   # between "started" glances / between spoken lines / spoken lines per day
ERROR_SEEN_GAP = 120.0                      # between silent "error_seen" startles (the spoken line still waits for a touch)
NOTE_TTL, COALESCE = 1800.0, 20.0           # a held note expires; finishes closer than this merge into one line
HEAD_CHANCE, HEAD_GAP, APPROACH_GAP = 0.25, 120.0, 60.0
QUOTA_HI, QUOTA_REARM = 90.0, 70.0          # warn once when crossing 90 %, re-arm after it falls below 70 %
FEW = frozenset(('waiting', 'waiting_again', 'error'))
LIVE = ('running', 'waiting', 'error')
PRIORITY = {'error': 0, 'waiting': 1, 'done': 2, 'quota': 3}

# How each reaction maps onto pet.py primitives. emotion is a key of assets/emotions.json; "care" does NOT exist yet
# (add {"care": ["comfort"]}; the "tired"/"lazy" categories also draw the goodnight / slacking stickers) and
# falls back to `fallback`. sfx is an assets/audio prefix and is only kept at level "normal".
SPEC = {
    'started': dict(motion='notice'),
    'waiting_notice': dict(motion='notice'),
    'waiting': dict(emotion='curious', effects=('hop',), sfx='notify'),
    'waiting_again': dict(emotion='curious'),
    'error': dict(emotion='care', fallback='mild', effects=('sweat',)),
    'done': dict(emotion='proud', effects=('star_burst',)),
    'quota': dict(emotion='mild'),
    'long_run': dict(effects=('stretch',)),
    'report': dict(emotion='mild'),
}
LINES = {
    'waiting': ['{a} 那边在等你点头~', '{a} 有个确认在等你哦', '{a} 停下来等你啦~'],
    'waiting_again': ['{a} 还在等你呢…不急的~'],
    'error': ['{a} 好像卡住了…要我陪你看看吗?', '{a} 那边出了点状况,别急~'],
    'done': ['{a} 跑完啦~歇口气吧', '{a} 搞定啦!', '{a} 干完一段了,辛苦啦~'],
    'done_many': ['跑完 {n} 个啦~歇会儿吧'],
    'quota': ['{a} 的额度快用完了…省着点哦', '{a} 额度吃紧啦,我帮你记着~'],
}


@dataclass(frozen=True)
class Reaction:
    kind: str
    agent: str = ''
    say: str = ''            # empty = silent (motion / effects only)
    emotion: str = ''
    fallback: str = ''
    motion: str = ''
    effects: tuple = ()
    sfx: str = ''
    n: int = 1

    def to_dict(self):
        return {**asdict(self), 'effects': list(self.effects)}


@dataclass
class _Sess:
    agent: str
    state: str
    since: float
    run_since: float | None = None
    marks: dict = field(default_factory=dict)    # per state episode: when a reaction already fired
    once: set = field(default_factory=set)       # per session: fired once for good


class Reactor:
    def __init__(self, level=DEFAULT_LEVEL, rng=None, day_of=None):
        self.level = level if level in LEVELS else DEFAULT_LEVEL
        self.rng = rng or random.Random()
        self.day_of = day_of or (lambda t: time.strftime('%Y-%m-%d', time.localtime(t)))
        self.sess, self.notes, self.armed = {}, {}, {}
        self.ready = False
        self.last_say = self.last_started = self.last_error_seen = -1e9
        self.last_pull = {'head': -1e9, 'approach': -1e9}
        self.day, self.spoken = None, 0

    # ---- gates -------------------------------------------------------------------------------------------------
    def _allowed(self, kind):
        return self.level == 'normal' or (self.level == 'few' and kind in FEW)

    @staticmethod
    def _quiet(ctx):
        """Focus, sleep, dragging and singing drop the reaction outright: she never makes up for it later."""
        return any(ctx.get(k) for k in ('focus', 'sleeping', 'dragging', 'singing'))

    def _muted(self, kind, ctx):
        return not self._allowed(kind) or self._quiet(ctx) or bool(ctx.get('watching_agent'))

    def _can_speak(self, now):
        d = self.day_of(now)
        if d != self.day:
            self.day, self.spoken = d, 0
        return now - self.last_say >= GLOBAL_GAP and self.spoken < DAILY_CAP

    def _spoke(self, now):
        self.last_say, self.spoken = now, self.spoken + 1

    def _spoken(self, kind, agent, n=1):
        spec = dict(SPEC[kind])
        if self.level != 'normal':
            spec.pop('sfx', None)
        line = self.rng.choice(LINES['done_many' if kind == 'done' and n > 1 else kind]).format(a=agent or 'AI', n=n)
        return Reaction(kind, agent, line, n=n, **spec)

    # ---- push path: called every second or two ----------------------------------------------------------------
    def update(self, now, sessions, quota=(), ctx=None):
        ctx, out = ctx or {}, []
        if self.level == 'off':
            self.sess.clear()
            self.notes.clear()
            self.armed.clear()
            self.ready = False                       # turning it back on starts from a fresh baseline
            return out
        baseline, self.ready, seen = not self.ready, True, set()
        for s in sessions or ():
            if not isinstance(s, dict) or s.get('id') is None:
                continue
            sid, agent = str(s['id']), str(s.get('agent') or 'AI')
            st = s.get('state') if s.get('state') in ('running', 'waiting', 'error', 'done', 'idle') else 'idle'
            seen.add(sid)
            rec = self.sess.get(sid)
            if rec is None:                          # first sample only records a baseline: no start-up storm
                rec = self.sess[sid] = _Sess(agent, st if baseline else 'idle', now, now if baseline and st == 'running' else None)
            rec.agent = agent
            if rec.state != st:
                self._transition(now, ctx, rec, st, out)
            self._dwell(now, ctx, rec, out)
        for sid in [k for k in self.sess if k not in seen]:
            del self.sess[sid]
        self._quota(now, ctx, quota, out)
        self._purge(now)
        if ctx.get('cursor_near'):
            r = self.pull(now, 'approach', ctx=ctx)
            if r:
                out.append(r)
        return out

    def _transition(self, now, ctx, rec, st, out):
        prev, rec.state, rec.since, rec.marks = rec.state, st, now, {}
        if st == 'running':
            if prev not in ('waiting', 'error'):
                rec.run_since = now                  # approving a prompt does not restart the run
            if prev in ('idle', 'done') and now - self.last_started >= STARTED_GAP and not self._muted('started', ctx):
                self.last_started = now
                out.append(Reaction('started', rec.agent, motion='notice'))
        elif st == 'waiting':
            if not self._muted('waiting_notice', ctx):
                out.append(Reaction('waiting_notice', rec.agent, motion='notice'))
        elif st == 'error':
            # Silent and wordless: on the swing the host plays a short startle. The spoken line keeps
            # waiting for a touch (see _dwell), so an error still never interrupts with a bubble or sound.
            if now - self.last_error_seen >= ERROR_SEEN_GAP and not self._muted('error', ctx):
                self.last_error_seen = now
                out.append(Reaction('error_seen', rec.agent))
        elif st == 'done':
            if prev in LIVE and rec.run_since is not None and now - rec.run_since >= DONE_MIN_RUN \
                    and not self._muted('done', ctx):
                self._note_done(now, rec, out)
            rec.run_since = None
        elif st == 'idle':
            rec.run_since = None                     # idle (including stale) is never a finish

    def _note_done(self, now, rec, out):
        old = self.notes.get(('done', '*'))
        n = (old[1].n if old else 0) + 1
        agent = rec.agent if not old or old[1].agent == rec.agent else ''
        self.notes[('done', '*')] = (now, self._spoken('done', agent, n))
        if not old:                                  # the first finish gets a silent sparkle; the line waits for a touch
            out.append(Reaction('done', agent, effects=SPEC['done']['effects']))

    def _dwell(self, now, ctx, rec, out):
        dt = now - rec.since
        if rec.state == 'waiting':
            if 'w1' not in rec.marks and dt >= WAIT_DWELL:
                rec.marks['w1'] = now
                self._speak_now(now, ctx, 'waiting', rec, out, keep=True)
            elif 'w1' in rec.marks and 'w2' not in rec.marks and now - rec.marks['w1'] >= REMIND_WAIT:
                rec.marks['w2'] = now
                self._speak_now(now, ctx, 'waiting_again', rec, out, keep=False)
        elif rec.state == 'error':
            if 'e1' not in rec.marks and dt >= ERROR_DWELL:
                rec.marks['e1'] = now                # error waits for a touch instead of interrupting
                if not self._muted('error', ctx):
                    self.notes[('error', rec.agent)] = (now, self._spoken('error', rec.agent))
        elif rec.state == 'running' and rec.run_since is not None and 'long' not in rec.once \
                and now - rec.run_since >= LONG_RUN:
            rec.once.add('long')
            if not self._muted('long_run', ctx):
                out.append(Reaction('long_run', rec.agent, effects=SPEC['long_run']['effects']))

    def _speak_now(self, now, ctx, kind, rec, out, keep):
        if self._muted(kind, ctx):
            return
        r = self._spoken(kind, rec.agent)
        if self._can_speak(now) and not ctx.get('bubble_busy'):
            self._spoke(now)
            out.append(r)
        elif keep:                                   # too soon / bubble busy: hold it as a note instead of dropping
            self.notes[(kind, rec.agent)] = (now, r)

    def _quota(self, now, ctx, quota, out):
        fresh = {}
        for row in quota or ():
            if not isinstance(row, dict):
                continue
            for c in row.get('cycles') or ():
                if not isinstance(c, dict):
                    continue
                key, v = (row.get('name'), c.get('label')), c.get('used')
                if c.get('stale') or isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue                         # unknown or stale usage neither warns nor re-arms
                fresh.setdefault(str(row.get('name') or 'AI'), []).append(v)
                if v >= QUOTA_HI and not self.armed.get(key):
                    self.armed[key] = True
                    if self._muted('quota', ctx):
                        continue
                    r = self._spoken('quota', str(row.get('name') or 'AI'))
                    busy = any(x.state == 'running' for x in self.sess.values())
                    if not busy and self._can_speak(now) and not ctx.get('bubble_busy'):
                        self._spoke(now)
                        out.append(r)
                    else:                            # never mid-run: it rides along with the next finish or touch
                        self.notes[('quota', r.agent)] = (now, r)
                elif v < QUOTA_REARM:
                    self.armed[key] = False
        # A reset cancels the held warning only when every fresh cycle
        # is safely below the re-arm threshold (another cycle may be high).
        for agent, values in fresh.items():
            if values and max(values) < QUOTA_REARM:
                self.notes.pop(("quota", agent), None)

    def _purge(self, now):
        for k, (t, _) in list(self.notes.items()):
            gone = k[0] in ('waiting', 'error') and not any(x.state == k[0] and x.agent == k[1] for x in self.sess.values())
            if gone or now - t > NOTE_TTL:           # resolved, or too old to still be news
                del self.notes[k]

    # ---- pull path: the user touched her / came near / asked --------------------------------------------------
    def pull(self, now, why, sessions=(), ctx=None):
        """why: "head" (pat), "approach" (cursor came near) or "ask" ("进度" / "在忙吗"). Returns a Reaction or None."""
        ctx = ctx or {}
        if why == 'ask':
            return self.report(sessions, ctx)
        if why not in self.last_pull or self.level == 'off' or any(ctx.get(k) for k in ('sleeping', 'dragging', 'singing')):
            return None
        if why == 'approach' and ctx.get('focus'):
            return None                              # a head pat during focus still works: that was the user's choice
        if now - self.last_pull[why] < (HEAD_GAP if why == 'head' else APPROACH_GAP):
            return None
        if why == 'head' and self.rng.random() >= HEAD_CHANCE:
            return None
        self._purge(now)
        if not self.notes or not self._can_speak(now) or ctx.get('bubble_busy'):
            return None
        key = min(self.notes, key=lambda k: (PRIORITY.get(k[0], 9), self.notes[k][0]))
        r = self.notes.pop(key)[1]
        self.last_pull[why] = now
        self._spoke(now)
        return r

    def report(self, sessions, ctx=None):
        """A direct question always gets an answer (even at level "off"), except while asleep or being dragged."""
        ctx = ctx or {}
        if ctx.get('sleeping') or ctx.get('dragging'):
            return None
        groups = {k: [] for k in LIVE}
        for s in sessions or ():
            if isinstance(s, dict) and s.get('state') in groups:
                groups[s['state']].append(str(s.get('agent') or 'AI'))

        def names(xs):
            order = list(dict.fromkeys(xs))
            return '、'.join(f'{x} {xs.count(x)} 个' if xs.count(x) > 1 else x for x in order)
        parts = [f"{names(groups[k])} {t}" for k, t in (('waiting', '在等你确认'), ('error', '出了点状况'), ('running', '在跑')) if groups[k]]
        if not parts:
            return Reaction('report', say='现在没有在跑的任务,歇会儿吧~', emotion='mild')
        emotion, fallback = ('curious', '') if groups['waiting'] else ('care', 'mild') if groups['error'] else ('mild', '')
        return Reaction('report', say='，'.join(parts) + '~', emotion=emotion, fallback=fallback, n=sum(map(len, groups.values())))
