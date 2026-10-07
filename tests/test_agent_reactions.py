import json, random, unittest
import agent_reactions as ar


def S(id, state, agent='Claude', **extra):
    return dict(id=id, agent=agent, state=state, **extra)


class Rig:
    """Drives a Reactor on a fake clock; the day changes every 86400 s."""
    def __init__(self, level='few', rng=None):
        self.r = ar.Reactor(level, rng or random.Random(1), day_of=lambda t: int(t // 86400))
        self.t = 1000.0

    def up(self, *sessions, t=None, quota=(), **ctx):
        if t is not None:
            self.t = t
        return self.r.update(self.t, list(sessions), quota, ctx)

    def pull(self, why, *sessions, t=None, **ctx):
        if t is not None:
            self.t = t
        return self.r.pull(self.t, why, list(sessions), ctx)

    def wait_until_spoken(self, t0, agent='Claude', sid='a', **ctx):
        """running at t0, waiting at t0+1, then the dwell elapses: returns what the dwell tick produced."""
        self.up(S(sid, 'running', agent), t=t0, **ctx)
        self.up(S(sid, 'waiting', agent), t=t0 + 1, **ctx)
        return self.up(S(sid, 'waiting', agent), t=t0 + 1 + ar.WAIT_DWELL, **ctx)


class FakeRng(random.Random):
    """random() follows a script; getrandbits() stays real so choice() does not eat the script."""
    def __init__(self, rolls):
        super().__init__(0)
        self.rolls, self._real = list(rolls), random.Random(0)

    def random(self):
        return self.rolls.pop(0) if self.rolls else 0.99

    def getrandbits(self, k):
        return self._real.getrandbits(k)


class BaselineTests(unittest.TestCase):
    def test_first_sample_is_only_a_baseline(self):
        g = Rig('normal')
        self.assertEqual(g.up(S('a', 'running'), S('b', 'done'), S('c', 'idle')), [])
        self.assertEqual(g.up(S('a', 'running'), S('b', 'done'), S('c', 'idle'), t=1002), [])

    def test_turning_it_off_and_on_starts_a_fresh_baseline(self):
        g = Rig('normal')
        g.up(S('a', 'idle'))
        g.r.level = 'off';self.assertEqual(g.up(S('a', 'running'), t=1100), [])
        g.r.level = 'normal';self.assertEqual(g.up(S('a', 'running'), t=1200), [])

    def test_garbage_input_is_ignored(self):
        g = Rig('normal')
        for junk in (None, 5, {}, {'id': None}, {'id': 'x', 'state': 'bogus'}, 'text'):
            g.up(junk, S('ok', 'running'))
        self.assertEqual(g.pull('ask', None).kind, 'report')      # nothing usable in the snapshot: still a polite answer
        g.r.update(1.0, None, None, None)


class WaitingTests(unittest.TestCase):
    def test_speaks_once_after_the_dwell_not_before(self):
        g = Rig('few')
        g.up(S('a', 'running'), t=1000)
        self.assertEqual(g.up(S('a', 'waiting'), t=1001), [])
        self.assertEqual(g.up(S('a', 'waiting'), t=1001 + ar.WAIT_DWELL - 1), [])
        out = g.up(S('a', 'waiting'), t=1001 + ar.WAIT_DWELL)
        self.assertEqual([r.kind for r in out], ['waiting'])
        self.assertIn('Claude', out[0].say);self.assertEqual(out[0].emotion, 'curious');self.assertIn('hop', out[0].effects)
        self.assertEqual(g.up(S('a', 'waiting'), t=1001 + ar.WAIT_DWELL + 30), [])

    def test_one_gentle_nudge_after_ten_minutes_then_never(self):
        g = Rig('few');t1 = 1001 + ar.WAIT_DWELL
        self.assertEqual(len(g.wait_until_spoken(1000)), 1)
        self.assertEqual(g.up(S('a', 'waiting'), t=t1 + ar.REMIND_WAIT - 1), [])
        again = g.up(S('a', 'waiting'), t=t1 + ar.REMIND_WAIT)
        self.assertEqual([r.kind for r in again], ['waiting_again'])
        self.assertEqual(g.up(S('a', 'waiting'), t=t1 + 3 * ar.REMIND_WAIT), [])

    def test_answered_before_the_dwell_never_speaks(self):
        g = Rig('few')
        g.up(S('a', 'running'), t=1000);g.up(S('a', 'waiting'), t=1001)
        self.assertEqual(g.up(S('a', 'running'), t=1001 + ar.WAIT_DWELL - 2), [])
        self.assertEqual(g.up(S('a', 'running'), t=1001 + 3 * ar.WAIT_DWELL), [])

    def test_the_silent_notice_only_exists_at_level_normal(self):
        for level, expect in (('few', []), ('normal', ['waiting_notice'])):
            g = Rig(level);g.up(S('a', 'running'), t=1000)
            self.assertEqual([r.kind for r in g.up(S('a', 'waiting'), t=1001)], expect, level)

    def test_a_held_note_is_cancelled_when_the_session_moves_on(self):
        g = Rig('few');g.wait_until_spoken(1000, sid='a')                  # speaks, which starts the global gap
        g.up(S('a', 'waiting'), S('b', 'running', 'ZCode'), t=1030)
        g.up(S('a', 'waiting'), S('b', 'waiting', 'ZCode'), t=1031)
        self.assertEqual(g.up(S('a', 'waiting'), S('b', 'waiting', 'ZCode'), t=1031 + ar.WAIT_DWELL), [])   # held: too soon
        g.up(S('a', 'waiting'), S('b', 'running', 'ZCode'), t=1060)         # b resolved
        self.assertIsNone(g.pull('approach', t=1000 + ar.GLOBAL_GAP + 60))

    def test_a_held_note_is_delivered_on_approach(self):
        g = Rig('few');g.wait_until_spoken(1000, sid='a')
        g.up(S('a', 'waiting'), S('b', 'running', 'ZCode'), t=1030);g.up(S('a', 'waiting'), S('b', 'waiting', 'ZCode'), t=1031)
        g.up(S('a', 'waiting'), S('b', 'waiting', 'ZCode'), t=1031 + ar.WAIT_DWELL)
        r = g.pull('approach', S('a', 'waiting'), S('b', 'waiting', 'ZCode'), t=1000 + ar.GLOBAL_GAP + 60)
        self.assertEqual((r.kind, r.agent), ('waiting', 'ZCode'))


class ErrorAndDoneTests(unittest.TestCase):
    def test_error_waits_for_a_touch_and_comforts(self):
        g = Rig('few');g.up(S('a', 'running'), t=1000);g.up(S('a', 'error'), t=1001)
        self.assertEqual(g.up(S('a', 'error'), t=1001 + ar.ERROR_DWELL + 1), [])      # never interrupts
        r = g.pull('approach', S('a', 'error'), t=1100)
        self.assertEqual((r.kind, r.emotion, r.fallback, r.effects), ('error', 'care', 'mild', ('sweat',)))
        self.assertIn('Claude', r.say)
        self.assertIsNone(g.pull('approach', S('a', 'error'), t=1100 + ar.APPROACH_GAP + 1))   # consumed

    def test_error_that_clears_is_not_mentioned(self):
        g = Rig('few');g.up(S('a', 'running'), t=1000);g.up(S('a', 'error'), t=1001);g.up(S('a', 'error'), t=1030)
        g.up(S('a', 'running'), t=1040)
        self.assertIsNone(g.pull('approach', S('a', 'running'), t=1100))

    def test_a_long_run_finishes_with_a_silent_sparkle_and_a_line_on_touch(self):
        g = Rig('normal');g.up(S('a', 'running'), t=1000)
        out = g.up(S('a', 'done'), t=1000 + ar.DONE_MIN_RUN + 10)
        self.assertEqual([(r.kind, r.say, r.effects) for r in out], [('done', '', ('star_burst',))])
        r = g.pull('approach', t=1300)
        self.assertEqual((r.kind, r.emotion), ('done', 'proud'));self.assertIn('Claude', r.say)

    def test_a_short_run_finishes_unremarked(self):
        g = Rig('normal');g.up(S('a', 'running'), t=1000)
        self.assertEqual(g.up(S('a', 'done'), t=1000 + ar.DONE_MIN_RUN - 5), [])
        self.assertIsNone(g.pull('approach', t=1300))

    def test_stale_idle_is_never_a_finish(self):
        g = Rig('normal');g.up(S('a', 'running'), t=1000)
        self.assertEqual(g.up(S('a', 'idle'), t=1000 + 3 * ar.DONE_MIN_RUN), [])
        self.assertIsNone(g.pull('approach', t=1400))

    def test_finishes_close_together_merge_into_one_line(self):
        g = Rig('normal');g.up(S('a', 'running'), S('b', 'running', 'ZCode'), t=1000)
        first = g.up(S('a', 'done'), S('b', 'running', 'ZCode'), t=1100)
        second = g.up(S('a', 'done'), S('b', 'done', 'ZCode'), t=1100 + ar.COALESCE - 5)
        self.assertEqual(len(first), 1);self.assertEqual(second, [])                       # one sparkle, not two
        r = g.pull('approach', t=1300)
        self.assertEqual(r.n, 2);self.assertIn('2', r.say);self.assertNotIn('Claude', r.say)

    def test_approving_a_prompt_does_not_restart_the_run(self):
        g = Rig('normal');g.up(S('a', 'running'), t=1000);g.up(S('a', 'waiting'), t=1050);g.up(S('a', 'running'), t=1070)
        self.assertEqual([r.kind for r in g.up(S('a', 'done'), t=1105)], ['done'])         # 105 s since the original start


class ErrorSeenTests(unittest.TestCase):
    """I-40: entering error gives one wordless 'error_seen' (a startle on the swing); the spoken line still waits."""
    def test_silent_once_per_episode_and_rate_limited(self):
        g = Rig('few');g.up(S('a', 'running'), S('b', 'running'), t=1000)
        self.assertEqual([r.kind for r in g.up(S('a', 'error'), S('b', 'running'), t=1001)], ['error_seen'])
        self.assertEqual(g.up(S('a', 'error'), S('b', 'running'), t=1005), [])              # same episode: nothing more
        self.assertEqual(g.up(S('a', 'error'), S('b', 'error'), t=1010), [])                # another error inside the gap
        g.up(S('a', 'running'), S('b', 'running'), t=1020)
        out = g.up(S('a', 'error'), S('b', 'running'), t=1001 + ar.ERROR_SEEN_GAP + 1)
        self.assertEqual([r.kind for r in out], ['error_seen'])

    def test_quiet_states_off_level_and_baseline_stay_still(self):
        for ctx in ({'focus': True}, {'sleeping': True}, {'dragging': True}, {'singing': True}, {'watching_agent': True}):
            with self.subTest(ctx=ctx):
                g = Rig('few');g.up(S('a', 'running'), t=1000)
                self.assertEqual(g.up(S('a', 'error'), t=1001, **ctx), [])
        g = Rig('off');g.up(S('a', 'running'), t=1000)
        self.assertEqual(g.up(S('a', 'error'), t=1001), [])
        g = Rig('few')
        self.assertEqual(g.up(S('a', 'error'), t=1000), [])                                  # first sample = baseline, no storm

    def test_the_spoken_error_line_still_waits_for_a_touch(self):
        g = Rig('few');g.up(S('a', 'running'), t=1000);g.up(S('a', 'error'), t=1001)
        self.assertEqual(g.up(S('a', 'error'), t=1001 + ar.ERROR_DWELL + 1), [])
        self.assertEqual(g.pull('approach', S('a', 'error'), t=1100).kind, 'error')


class LevelTests(unittest.TestCase):
    def test_few_only_covers_waiting_and_error(self):
        g = Rig('few');g.up(S('a', 'running'), S('e', 'running', 'Codex'), t=1000)
        out = g.up(S('a', 'done'), S('e', 'error', 'Codex'), t=1100)                       # no 'done' at few; the error
        self.assertEqual([(r.kind, r.agent, r.say, r.emotion, r.effects, r.sfx) for r in out],  # only gets the wordless startle
                         [('error_seen', 'Codex', '', '', (), '')])
        g.up(S('a', 'done'), S('e', 'error', 'Codex'), t=1115)
        self.assertEqual(g.pull('approach', t=1200).kind, 'error')
        self.assertIsNone(g.pull('approach', t=1400))                                      # no 'done' note was ever kept

    def test_normal_adds_started_and_quota_and_stretch(self):
        g = Rig('normal');g.up(S('a', 'idle'), t=1000)
        out = g.up(S('a', 'running'), t=1001)
        self.assertEqual([(r.kind, r.motion, r.say) for r in out], [('started', 'notice', '')])
        self.assertEqual(g.up(S('a', 'idle'), t=1100), [])
        self.assertEqual(g.up(S('a', 'running'), t=1200), [])                                # rate-limited glance

    def test_off_is_silent_but_a_direct_question_is_still_answered(self):
        g = Rig('off')
        self.assertEqual(g.up(S('a', 'waiting'), t=1000), [])
        self.assertIsNone(g.pull('head', S('a', 'waiting')));self.assertIsNone(g.pull('approach', S('a', 'waiting'), t=1200))
        self.assertIn('在等你确认', g.pull('ask', S('a', 'waiting')).say)


class QuietAndRateTests(unittest.TestCase):
    def test_quiet_states_drop_the_reaction_for_good(self):
        for key in ('focus', 'sleeping', 'dragging', 'singing'):
            g = Rig('few');t1 = 1001 + ar.WAIT_DWELL
            self.assertEqual(g.wait_until_spoken(1000, **{key: True}), [], key)
            self.assertEqual(g.up(S('a', 'waiting'), t=t1 + 30), [], key)                  # not made up for afterwards
            self.assertIsNone(g.pull('approach', S('a', 'waiting'), t=t1 + 200), key)       # and not kept as a note
            self.assertEqual([r.kind for r in g.up(S('a', 'waiting'), t=t1 + ar.REMIND_WAIT)], ['waiting_again'], key)

    def test_looking_at_the_agent_already_means_no_reminder(self):
        g = Rig('few')
        self.assertEqual(g.wait_until_spoken(1000, watching_agent=True), [])
        self.assertIsNone(g.pull('approach', S('a', 'waiting'), t=1200))

    def test_a_busy_bubble_holds_the_line_as_a_note(self):
        g = Rig('few')
        self.assertEqual(g.wait_until_spoken(1000, bubble_busy=True), [])
        self.assertEqual(g.pull('approach', S('a', 'waiting'), t=1100).kind, 'waiting')

    def test_two_reactions_closer_than_the_global_gap_become_one_line_and_one_note(self):
        g = Rig('few');first = g.wait_until_spoken(1000, sid='a')
        g.up(S('a', 'waiting'), S('b', 'running', 'ZCode'), t=1030);g.up(S('a', 'waiting'), S('b', 'waiting', 'ZCode'), t=1031)
        second = g.up(S('a', 'waiting'), S('b', 'waiting', 'ZCode'), t=1031 + ar.WAIT_DWELL)
        self.assertEqual((len(first), second), (1, []))

    def test_daily_cap_then_a_new_day(self):
        g = Rig('few');spoken = []
        for i in range(ar.DAILY_CAP + 1):
            t = 1000 + i * 200
            g.up(S('a', 'running'), t=t);g.up(S('a', 'waiting'), t=t + 1)
            spoken.append(len(g.up(S('a', 'waiting'), t=t + 1 + ar.WAIT_DWELL)))
        self.assertEqual(spoken, [1] * ar.DAILY_CAP + [0])
        self.assertEqual(len(g.wait_until_spoken(1000 + 86400)), 1)                        # the counter resets with the day

    def test_head_pat_is_chancy_rate_limited_and_works_during_focus(self):
        g = Rig('few', FakeRng([0.9, 0.1, 0.1, 0.1]));g.up(S('a', 'running'), t=1000);g.up(S('a', 'error'), t=1001);g.up(S('a', 'error'), t=1020)
        self.assertIsNone(g.pull('head', S('a', 'error'), t=1100, focus=True))             # unlucky roll keeps the note
        self.assertEqual(g.pull('head', S('a', 'error'), t=1101, focus=True).kind, 'error')  # lucky roll; focus does not block a pat
        self.assertIsNone(g.pull('head', S('a', 'error'), t=1102))                          # head cooldown

    def test_approach_is_ignored_in_focus_and_while_asleep(self):
        g = Rig('few');g.up(S('a', 'running'), t=1000);g.up(S('a', 'error'), t=1001);g.up(S('a', 'error'), t=1020)
        self.assertIsNone(g.pull('approach', t=1100, focus=True));self.assertIsNone(g.pull('approach', t=1100, sleeping=True))
        self.assertEqual(g.pull('approach', t=1100).kind, 'error')

    def test_cursor_near_delivers_a_held_note_straight_away(self):
        g = Rig('few');g.up(S('a', 'running'), t=1000);g.up(S('a', 'error'), t=1001)
        out = g.up(S('a', 'error'), t=1001 + ar.ERROR_DWELL, cursor_near=True)
        self.assertEqual([r.kind for r in out], ['error'])

    def test_notes_expire(self):
        g = Rig('few');g.up(S('a', 'running'), t=1000);g.up(S('a', 'error'), t=1001);g.up(S('a', 'error'), t=1020)
        self.assertIsNone(g.pull('approach', S('a', 'error'), t=1020 + ar.NOTE_TTL + 1))


class QuotaAndLongRunTests(unittest.TestCase):
    def q(self, used, stale=False, name='Claude', label='5h'):
        return [dict(name=name, cycles=[dict(label=label, used=used, stale=stale)])]

    def test_warns_once_per_crossing_and_rearms_below_the_floor(self):
        g = Rig('normal');kinds = []
        for t, used, stale in ((1000, 85, False), (1200, 91, False), (1400, 95, False), (1600, 99, True), (1800, 60, False), (2000, 92, False)):
            kinds.append([r.kind for r in g.up(t=t, quota=self.q(used, stale))])
        self.assertEqual(kinds, [[], ['quota'], [], [], [], ['quota']])

    def test_a_stale_reading_never_warns_even_when_it_is_the_first_one(self):
        g = Rig('normal')
        self.assertEqual(g.up(t=1000, quota=self.q(99, stale=True)), [])
        self.assertEqual([r.kind for r in g.up(t=1200, quota=self.q(95))], ['quota'])    # the first fresh reading still warns

    def test_never_mid_run_and_never_below_normal(self):
        g = Rig('normal');g.up(S('a', 'running'), t=1000)
        self.assertEqual(g.up(S('a', 'running'), t=1100, quota=self.q(95)), [])           # held, not spoken
        self.assertEqual(g.pull('approach', t=1300).kind, 'quota')
        f = Rig('few');self.assertEqual(f.up(t=1000, quota=self.q(95)), [])
        self.assertIsNone(f.pull('approach', t=1300))

    def test_stretch_after_a_long_run_once_and_only_at_normal(self):
        g = Rig('normal');g.up(S('a', 'running'), t=1000)
        self.assertEqual([r.kind for r in g.up(S('a', 'running'), t=1000 + ar.LONG_RUN)], ['long_run'])
        self.assertEqual(g.up(S('a', 'running'), t=1000 + 2 * ar.LONG_RUN), [])
        f = Rig('few');f.up(S('a', 'running'), t=1000)
        self.assertEqual(f.up(S('a', 'running'), t=1000 + ar.LONG_RUN), [])


class ReportTests(unittest.TestCase):
    def test_names_the_agents_and_counts_but_never_titles_or_errors(self):
        secret = '/home/me/private/plan.md'
        ss = [S('a', 'waiting', 'ZCode', title=secret, error='KeyError: token'), S('b', 'running', 'Claude', title=secret),
              S('c', 'running', 'Claude'), S('d', 'done', 'Codex')]
        r = Rig('few').pull('ask', *ss)
        self.assertEqual((r.kind, r.emotion), ('report', 'curious'))
        self.assertIn('ZCode 在等你确认', r.say);self.assertIn('Claude 2 个 在跑', r.say.replace('Claude 2 个在跑', 'Claude 2 个 在跑'))
        self.assertNotIn(secret, r.say);self.assertNotIn('KeyError', r.say);self.assertNotIn('Codex', r.say)

    def test_nothing_running_and_asleep(self):
        g = Rig('few')
        self.assertIn('没有在跑', g.pull('ask', S('d', 'done')).say)
        self.assertIsNone(g.pull('ask', S('a', 'running'), sleeping=True))
        self.assertEqual(g.pull('ask', S('a', 'error')).emotion, 'care')


class ShapeTests(unittest.TestCase):
    def test_every_spec_and_line_is_usable_by_the_host(self):
        for kind, spec in ar.SPEC.items():
            self.assertTrue(set(spec) <= {'emotion', 'fallback', 'motion', 'effects', 'sfx'}, kind)
        for kind, pool in ar.LINES.items():
            for line in pool:
                self.assertNotIn('{', line.format(a='X', n=2));self.assertLess(len(line), 30, line)
        for r in (ar.Reaction('done', 'X', effects=('star_burst',)), ar.Reactor('normal').report([S('a', 'running')])):
            self.assertEqual(json.loads(json.dumps(r.to_dict()))['kind'], r.kind)

    def test_sfx_only_survives_at_level_normal(self):
        for level, sfx in (('few', ''), ('normal', 'notify')):
            g = Rig(level);self.assertEqual(g.wait_until_spoken(1000)[0].sfx, sfx, level)

    def test_the_global_gap_is_what_stops_chatter(self):
        self.assertGreaterEqual(ar.GLOBAL_GAP, 60);self.assertLessEqual(ar.DAILY_CAP, 12)


if __name__ == '__main__':
    unittest.main()
