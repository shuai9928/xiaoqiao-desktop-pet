"""Wire Claude's pure reaction rules to the real Windows pet.

Session state, local quota snapshots and existing animation primitives only;
this module makes no model calls and does not read task text or chat history.
"""
import time
from agent_reactions import Reactor
from flat_workspace import agent_name, live_ui, quota_rows


def _engine(owner):
    engine = getattr(owner, '_agent_companion', None)
    if engine is None:
        settings = getattr(owner, 'settings', {}) or {}
        engine = owner._agent_companion = Reactor(settings.get('agent_companion', 'few'))
    return engine


def snapshot(owner, now, sessions=None):
    from pet import ai_session_stale
    muted_sources = getattr(owner, 'ai_mute_sources', set()) or set()
    muted_sessions = getattr(owner, 'ai_mute_sess', set()) or set()
    rows = []
    for s in sessions if sessions is not None else getattr(owner, '_ai_work_sessions', []):
        if not isinstance(s, dict) or s.get('id') is None:
            continue
        if s.get('agent') in muted_sources or s['id'] in muted_sessions:
            continue
        state = 'idle' if ai_session_stale(s, now) else s.get('state', 'idle')
        rows.append(dict(id=str(s['id']), agent=agent_name(s.get('agent')), state=state))
    return rows


def context(owner, *, now=None):
    now = time.time() if now is None else now
    sleeping = getattr(owner, 'state', '') in ('sleep', 'yawn') or getattr(owner, '_nap_on_swing', False)
    root = getattr(owner, 'root', None)
    if root is not None:
        sleeping = sleeping or root.state() == 'withdrawn'
    focus = getattr(owner, 'focus_mode', lambda: False)()
    # Foreground observation stays on the host. Only its boolean is passed to the rules.
    title = getattr(owner, '_fg_title', lambda: '')().lower()
    watching = any(name in title for name in ('codex', 'claude', 'zcode', 'powershell', 'terminal'))
    sw = getattr(owner, '_swing', None) or {}
    near = False
    if sw.get('geo', {}).get('flat'):
        from pet import cursor_pos
        from flat_workspace import PET_CX, PET_TOP, PET_BOX
        cx, cy = cursor_pos()
        u = sw['geo']['u']
        x, y = (cx-sw.get('scene_l', 0))/u, (cy-sw.get('scene_t', 0)-sw['geo'].get('hat_fx_pad',0))/u
        near = abs(x-PET_CX) < PET_BOX[0]*.6 and PET_TOP-12 <= y <= PET_TOP+PET_BOX[1]+12
    return dict(sleeping=sleeping, focus=focus,
                dragging=bool(getattr(owner, 'drag', None) or getattr(owner, '_scene_drag', None)),
                singing=getattr(owner, 'state', '') == 'sing',
                bubble_busy=bool(getattr(owner, 'bubble', None)),
                watching_agent=watching, cursor_near=near)


# On the swing the standing micro-motions never run (they need state idle/sticker), so these reaction
# kinds become seated actions instead (seat_motion, I-40). Off the swing the old primitives stay.
SEAT_ACTIONS = {'started': 'glance', 'waiting_notice': 'nudge', 'waiting': 'nudge',
                'waiting_again': 'nudge', 'error_seen': 'startle', 'done': 'relief'}


def execute(owner, reaction, now):
    if reaction is None:
        return False
    seated = SEAT_ACTIONS.get(reaction.kind)
    seated = bool(seated) and bool(getattr(owner, '_seat_allowed', lambda: False)())
    if seated:
        # A higher-priority action already playing (her own pat/push) simply keeps going.
        owner.start_seat_action(SEAT_ACTIONS[reaction.kind])
    if reaction.say:
        owner.say(reaction.say)
    if reaction.emotion:
        # The old sticker pack has no dedicated care category; comfort is the
        # single matching image, while the care eyelids work even with stickers off.
        shown = owner.play_emotion(reaction.emotion)
        if not shown and reaction.emotion == 'care' and getattr(owner, 'stickers_enabled', False):
            owner.play_emotion('comfort')
        elif not shown and reaction.fallback and reaction.emotion != 'care':
            owner.play_emotion(reaction.fallback)
    if reaction.motion and not seated:
        owner._start_micro_motion(reaction.motion)
        owner._moon_look_until = now + 2.0
    if 'hop' in reaction.effects and not seated:
        if getattr(owner, '_swing', None):
            owner._swing_impulse(.04)
        else:
            owner.hop(.4)
    if reaction.effects:
        # Small effects are painted on the actual scene canvas, not the retired
        # standalone sprite canvas (which flat_workspace.push intentionally omits).
        owner._companion_effect = (now, reaction.effects)
    if 'stretch' in reaction.effects:
        if owner.start_stretch() is False:
            owner._start_micro_motion('notice')
    if reaction.sfx:
        owner.sfx.play(reaction.sfx)
    owner._last_companion_reaction = dict(kind=reaction.kind, agent=reaction.agent, at=now)
    return True


def tick(owner, now, sessions):
    engine = _engine(owner)
    rows = snapshot(owner, now, sessions)
    ctx = context(owner, now=now)
    if not getattr(owner, 'ai_lights', True) or not getattr(owner, 'ai_announce', True):
        ctx['focus'] = True
    # Existing permission hooks must stay immediate; skip the new reminder for
    # the same waiting episode whether the scan or hook arrived first.
    hook = getattr(owner, '_companion_permission_hook', 0)
    for row in rows:
        rec = engine.sess.get(row['id'])
        if row['agent'] == 'ZCode' and row['state'] == 'waiting' and rec and rec.since <= hook:
            rec.marks.setdefault('w1', hook)
            rec.marks.setdefault('w2', hook)
    sw = getattr(owner, '_swing', None) or {}
    ui = live_ui(owner, sw.get('ui') or {})
    for reaction in engine.update(now, rows, quota_rows(ui), ctx):
        execute(owner, reaction, now)
    if hook:
        for rec in engine.sess.values():
            if rec.agent == 'ZCode' and rec.state == 'waiting' and rec.since <= hook+5:
                rec.marks.setdefault('w1', hook)
                rec.marks.setdefault('w2', hook)


def acknowledge_hook(owner, now):
    """The hook is already responsible for delivering the permission request."""
    owner._companion_permission_hook = now
    engine = _engine(owner)
    for rec in engine.sess.values():
        if rec.agent == 'ZCode' and rec.state == 'waiting':
            rec.marks.update(w1=now, w2=now)
            engine.notes.pop(('waiting', 'ZCode'), None)


def pull(owner, now, why):
    if not getattr(owner, 'ai_announce', True):
        return False
    return execute(owner, _engine(owner).pull(now, why, ctx=context(owner, now=now)), now)


def report(owner, now):
    return execute(owner, _engine(owner).report(snapshot(owner, now), context(owner, now=now)), now)


def paint_effect(owner, canvas, u, now):
    """Quiet, short marks beside her head; all coordinates follow the new geometry."""
    import math
    from PIL import ImageDraw
    from flat_workspace import PET_CX, PET_TOP
    born, effects = getattr(owner, '_companion_effect', (0, ()))
    age = now-born
    if not 0 <= age <= 1.4:
        return
    d = ImageDraw.Draw(canvas)
    pad=(getattr(owner,'_swing',None) or {}).get('geo',{}).get('hat_fx_pad',0)
    if 'sweat' in effects:
        x, y = (PET_CX+30)*u, (PET_TOP+44+age*5)*u+pad
        d.polygon([(x,y-4*u),(x-3*u,y+2*u),(x+3*u,y+2*u)], fill='#9ac9e6')
        d.ellipse((x-3*u,y,x+3*u,y+5*u), fill='#9ac9e6')
    if 'star_burst' in effects:
        for angle in (.3, 1.4, 2.5, 3.6, 4.7):
            radius = (22+age*13)*u
            x = PET_CX*u+math.cos(angle)*radius
            y = (PET_TOP+40)*u+math.sin(angle)*radius+pad
            d.line((x-2*u,y,x+2*u,y), fill='#d6c3ec', width=max(1, round(u)))
            d.line((x,y-2*u,x,y+2*u), fill='#d6c3ec', width=max(1, round(u)))
