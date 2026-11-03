import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engineer.strategy import Strategy  # noqa: E402
from engineer.incidents import Incidents  # noqa: E402
from engineer.opponents import Opponents  # noqa: E402
from engineer.quali import Quali, track_gaps  # noqa: E402
from engineer.setup import SetupAnalyzer  # noqa: E402
from engineer.storage import Storage  # noqa: E402
from engineer.state import Engine  # noqa: E402
from engineer import debrief as D, llm, tts as TTS  # noqa: E402
from tools import simulator as SIM  # noqa: E402


def lapd(**kw):
    base = {'last_lap_ms': 0, 'current_lap_ms': 0, 's1_ms': 0, 's2_ms': 0, 'delta_front_ms': 0,
            'delta_leader_ms': 0, 'lap_distance': 100.0, 'total_distance': 100.0, 'position': 1,
            'lap_num': 1, 'pit_status': 0, 'num_pit_stops': 0, 'sector': 0, 'invalid': 0,
            'penalties': 0, 'warnings': 0, 'cc_warnings': 0, 'unserved_dt': 0, 'unserved_sg': 0,
            'grid': 1, 'driver_status': 4, 'result_status': 2, 'pit_lane_active': 0,
            'pit_lane_ms': 0, 'pit_stop_ms': 0, 'sc_delta': 0.0}
    base.update(kw)
    return base


def race_log(**kw):
    e = Engine(Storage(tempfile.mkdtemp()))
    e.settings['lang'] = 'en'
    log = []
    orig = e.say

    def say(text, prio=1, urgent=False):
        me = e.lap[e.player]
        log.append((me['lap_num'] if me else 0, urgent, text))
        orig(text, prio, urgent)
    e.say = say
    for _, p in SIM.generate('race', laps=kw.pop('laps', 20), ai=90, seed=21, fmt=2026, **kw):
        e.handle(p)
    return e, log


class StrategyTests(unittest.TestCase):
    def make(self, deg=80):
        st = Strategy()
        for lap in range(1, 6):
            st.on_player_lap(lap, 90000 + deg * lap + 30 * (40 - 1.6 * lap), True, False,
                             40 - 1.6 * lap, 17, lap, False)
        return st

    def test_deg_measured_with_fuel_correction(self):
        st = self.make(80)
        d, src = st.deg(17)
        self.assertEqual(src, 'measured')
        self.assertAlmostEqual(d, 80, delta=1)

    def test_one_stop_vs_two_stop(self):
        st = self.make(80)
        cur = {'compound': 17, 'age': 5, 'life_left': 21}
        short = st.plan(6, 30, cur, None, 22000, False, True)
        self.assertEqual(short['stops'], 1)
        self.assertTrue(6 <= short['laps'][0] < 30)
        self.assertIn('alt', short)
        st2 = self.make(80)
        long = st2.plan(6, 70, cur, None, 22000, False, True)
        self.assertEqual(long['stops'], 2)

    def test_mandatory_two_compounds(self):
        st = self.make(10)   # skoro žádná degradace → bez pravidla by vyšlo 0 zastávek
        cur = {'compound': 17, 'age': 5, 'life_left': 40}
        self.assertEqual(st.plan(6, 25, cur, None, 22000, False, False)['stops'], 0)
        p = st.plan(6, 25, cur, None, 22000, False, True)
        self.assertEqual(p['stops'], 1)
        self.assertNotEqual(p['compounds'][0], 17)

    def test_box_call_not_repeated_every_lap(self):
        st = self.make()
        plan = {'stops': 1, 'laps': [8], 'tyres': ['Hard'], 'compounds': [18], 'remaining': 20}
        calls = []
        for lap in range(6, 13):
            calls += [c[0] for c in st.lap_calls(lap, plan, {})]
        self.assertEqual(calls.count('box_next_lap'), 1)
        self.assertEqual(calls.count('box_this_lap'), 2)   # lap 8 + připomínka lap 11

    def test_safety_car_call_once(self):
        st = Strategy()
        plan = {'stops': 1, 'laps': [12], 'tyres': ['Hard'], 'compounds': [18], 'remaining': 15}
        self.assertEqual(st.safety_car_call('sc', plan, 5, 20)[0], 'sc_box')
        self.assertIsNone(st.safety_car_call('sc', plan, 6, 20))

    def test_rejoin(self):
        laps = [lapd(delta_leader_ms=10000, position=3), lapd(delta_leader_ms=0, position=1),
                lapd(delta_leader_ms=5000, position=2), lapd(delta_leader_ms=30000, position=4),
                lapd(delta_leader_ms=34000, position=5)]
        r = Strategy.rejoin(laps, 0, 22000, {3: 'Norris', 4: 'Leclerc'})
        self.assertEqual(r['pos'], 4)
        self.assertEqual(r['ahead']['name'], 'Norris')
        self.assertEqual(r['ahead']['gap'], 2000)
        self.assertEqual(r['behind']['gap'], 2000)

    def test_weather_calls(self):
        st = Strategy()
        s = {'weather': 0, 'time_left': 0,
             'forecast': [{'offset_min': 10, 'weather': 3, 'rain_pct': 70}]}
        self.assertEqual(st.weather_calls(s, 17)[0][0], 'rain_coming')
        self.assertEqual(st.weather_calls(s, 17), [])
        wet = {'weather': 4, 'forecast': []}
        ev = st.weather_calls(wet, 17)
        self.assertEqual(ev[0][0], 'rain_now_slicks')
        self.assertEqual(ev[0][1]['tyre'], 'Wet')


class IncidentTests(unittest.TestCase):
    def test_track_limits_penalties_flags(self):
        inc = Incidents()
        inc.on_lap(lapd())
        inc.on_lap(lapd(cc_warnings=1, warnings=1))
        inc.on_lap(lapd(cc_warnings=3, warnings=3))
        keys = [e[0] for e in inc.pop_events()]
        self.assertEqual(keys, ['track_limits', 'track_limits_many'])
        inc.on_event({'code': 'PENA', 'penalty_type': 0, 'infringement': 17, 'car': 0, 'other': 255,
                      'time': 0, 'lap': 3, 'places': 0}, 0)
        inc.on_lap(lapd(cc_warnings=3, warnings=3, unserved_dt=1))
        ev = inc.pop_events()
        self.assertEqual([e[0] for e in ev], ['penalty_dt'])     # neohlášeno dvakrát
        self.assertEqual(ev[0][1]['why'], 'Pit lane speeding')
        self.assertIsNone(inc.on_safety_car(0))
        self.assertEqual(inc.on_safety_car(2), 'vsc')
        inc.on_safety_car(0)
        self.assertEqual([e[0] for e in inc.pop_events()], ['vsc_deployed', 'green'])

    def test_damage_and_puncture(self):
        inc = Incidents()
        base = {k: 0 for k in ['fl_wing', 'fr_wing', 'rear_wing', 'floor', 'diffuser', 'sidepod',
                               'gearbox', 'engine', 'drs_fault', 'ers_fault']}
        base['tyre_damage'] = [0, 0, 0, 0]
        inc.on_damage(dict(base), True, 20)
        hit = dict(base, fl_wing=45, tyre_damage=[0, 0, 60, 0])
        inc.on_damage(hit, True, 20)
        keys = [e[0] for e in inc.pop_events()]
        self.assertIn('damage', keys)
        self.assertIn('damage_box_wing', keys)
        self.assertIn('puncture', keys)

    def test_yellow_flag_ahead(self):
        inc = Incidents()
        session = {'track_length': 3000, 'marshal_zones': [(0.0, 0), (0.33, 3), (0.66, 0)]}
        inc.on_position(500, session)
        inc.on_position(600, session)
        self.assertEqual([e[0] for e in inc.pop_events()], ['yellow_ahead'])


class OpponentTests(unittest.TestCase):
    def test_pit_detection_and_pit_loss(self):
        opp = Opponents()
        st = [{'visual_compound': 17, 'tyre_age': 5}, {'visual_compound': 17, 'tyre_age': 5}]
        laps_ms = [60000, 60100, 60050, 60000]
        for n, ms in enumerate(laps_ms, start=2):
            opp.update([lapd(), lapd(lap_num=n, last_lap_ms=ms)], st, 0)
        # in lap (pit lane na konci), out lap (pit lane na začátku)
        opp.update([lapd(), lapd(lap_num=5, pit_status=1, num_pit_stops=0)], st, 0)
        opp.update([lapd(), lapd(lap_num=6, last_lap_ms=71000, pit_status=1, num_pit_stops=1)], st, 0)
        st2 = [st[0], {'visual_compound': 18, 'tyre_age': 0}]
        opp.update([lapd(), lapd(lap_num=6, num_pit_stops=1)], st2, 0)
        opp.update([lapd(), lapd(lap_num=7, last_lap_ms=72000, num_pit_stops=1)], st2, 0)
        ev = opp.pop_events()
        self.assertEqual(ev[0], ('pitted', {'car': 1, 'compound': 18}))
        self.assertAlmostEqual(opp.pit_loss(), 71000 + 72000 - 2 * 60025, delta=100)


class QualiTests(unittest.TestCase):
    def test_out_lap_flow(self):
        q = Quali()
        session = {'track_length': 4000, 'time_left': 900}
        tel = {'tyre_surface': [90, 90, 70, 70], 'speed': 200}
        laps = [lapd(driver_status=4, lap_distance=100), lapd(lap_distance=400, driver_status=4)]
        q.update(laps[0], laps, 0, tel, True, 60, session, 200)
        laps[0] = lapd(driver_status=3, lap_distance=200)
        q.update(laps[0], laps, 0, tel, True, 60, session, 200)
        laps[0] = lapd(driver_status=3, lap_distance=2500)
        q.update(laps[0], laps, 0, tel, True, 60, session, 200)
        laps[0] = lapd(driver_status=3, lap_distance=3500)
        laps[1] = lapd(lap_distance=3600, driver_status=4)
        q.update(laps[0], laps, 0, tel, True, 60, session, 200)
        laps[0] = lapd(driver_status=1, lap_distance=5, lap_num=2)
        q.update(laps[0], laps, 0, tel, True, 60, session, 200)
        ev = q.pop_events()
        keys = [e[0] for e in ev]
        self.assertEqual(keys, ['out_lap', 'tyre_temps', 'traffic_close', 'push_now'])
        self.assertEqual(ev[1][1]['hint'], 'temps_cold')

    def test_track_gaps_wrap(self):
        laps = [lapd(lap_distance=3900), lapd(lap_distance=50)]
        ahead, behind = track_gaps(laps, 0, 4000)
        self.assertEqual(ahead, (1, 150))


class SetupTests(unittest.TestCase):
    def test_understeer_detection_and_advice(self):
        import math
        a = SetupAnalyzer()
        a.on_setup({'front_wing': 25, 'front_arb': 8, 'brake_bias': 57, 'on_throttle': 60,
                    'rear_wing': 22, 'rear_arb': 6})
        lap = lapd()
        for i in range(200):
            tel = {'speed': 110, 'brake': 0.0, 'throttle': 0.3, 'steer': 0.4,
                   'tyre_surface': [95, 95, 95, 95]}
            mex = {'slip_angle': [math.radians(2)] * 2 + [math.radians(3.5)] * 2,
                   'slip_ratio': [0, 0, 0, 0]}
            a.on_sample(mex, tel, lap)
        bal = a.balance()
        self.assertEqual(bal['mid_slow']['state'], 'under')
        adv = a.advice()
        self.assertEqual(adv[0]['issue'], 'Low/medium-speed understeer')
        self.assertEqual(adv[0]['current'], 'front arb 8 → 7')


class TTSTests(unittest.TestCase):
    def test_pcm_to_wav(self):
        wav = TTS.pcm_to_wav(b'\x00\x00' * 24000)
        self.assertEqual(wav[:4], b'RIFF')
        self.assertEqual(len(wav), 44 + 48000)

    def test_get_uses_cache_and_fallback(self):
        t = TTS.GeminiTTS()
        calls = []
        t.synthesize = lambda k, text, v, l: (calls.append(text), b'RIFFfake')[1]
        self.assertEqual(t.get('k', 'hello'), b'RIFFfake')
        self.assertEqual(t.get('k', 'hello'), b'RIFFfake')
        self.assertEqual(calls, ['hello'])

        def boom(*a):
            raise RuntimeError('quota')
        t.synthesize = boom
        self.assertIsNone(t.get('k', 'other', timeout=2))
        self.assertIn('quota', t.last_error)


class EngineIntegrationTests(unittest.TestCase):
    def test_race_strategy_and_incidents(self):
        e, log = race_log(pit_lap=12, sc_lap=6, damage_lap=4, penalty_lap=8)
        texts = [t for _, _, t in log]
        box = [(lap, t) for lap, u, t in log if t.startswith('Box this lap')]
        self.assertTrue(any('Safety car! Cheap stop' in t for t in texts))
        self.assertTrue(any(t.startswith('5 second penalty') for t in texts))
        self.assertTrue(any(t.startswith('Front left wing damage 45') for t in texts))
        self.assertTrue(any(t.startswith('Race control: overtake mode enabled') for t in texts))
        self.assertTrue(any(t.startswith('Rain expected') for t in texts) is False)
        self.assertLessEqual(len(box), 2)
        s = e.snapshot()
        self.assertGreater(s['strategy']['pit_loss_measured'], 0)
        self.assertTrue(s['around'])
        self.assertTrue(s['strategy']['sets'])

    def test_debrief_offline(self):
        e, _ = race_log(laps=6)
        e.settings['lang'] = 'en'
        with e.lock:
            summary = D.build_summary(e)
        entry = D.make_debrief(e, summary, 'en', key=None)
        self.assertIn('Top 3 focus points', entry['text'])
        self.assertEqual(e.storage.load_debriefs()[0]['text'], entry['text'])

    def test_start_debrief_background(self):
        e, _ = race_log(laps=4)
        n = len(e.messages)
        with e.lock:
            self.assertTrue(e.start_debrief(announce=True))
        for _ in range(50):
            if len(e.messages) > n:
                break
            time.sleep(0.05)
        self.assertEqual(e.messages[-1]['text'], 'Debrief is ready on the screen.')

    def test_new_intents_offline(self):
        e, _ = race_log(laps=8, pit_lap=None)
        for q, words in [('Bono, what is the strategy?', ('stop', 'tyre deg')),
                         ('any damage?', ('damage',)), ('weather?', ('currently',)),
                         ('setup advice', ('setup',))]:
            text, src = llm.answer(e, q)
            self.assertEqual(src, 'offline')
            self.assertTrue(any(w in text.lower() for w in words), (q, text))

    def test_say_prefetches_tts_only_for_non_urgent(self):
        e = Engine(Storage(tempfile.mkdtemp()))
        e.settings.update(gemini_key='k', voice_engine='mixed')
        got = []
        e.tts.prefetch = lambda key, text, voice, lang: got.append(text)
        e.say('lap report')
        e.say('answer to driver', prio=2)
        e.say('urgent!', prio=2, urgent=True)
        self.assertEqual(got, ['answer to driver'])
        e.settings['voice_engine'] = 'gemini'
        e.say('lap report 2')
        self.assertEqual(got[-1], 'lap report 2')

    def test_tts_rate_limit(self):
        t = TTS.GeminiTTS()
        t.synthesize = lambda *a: b'RIFF'
        results = [t.get('k', 'msg %d' % i, timeout=1) for i in range(6)]
        self.assertEqual(results.count(b'RIFF'), t.max_per_min)
        self.assertIsNone(results[-1])


if __name__ == '__main__':
    unittest.main()


class RecapTests(unittest.TestCase):
    def test_recap_turns_sectors_and_highlights(self):
        from engineer.recap import build_recap, for_llm
        e, _ = race_log(laps=10, pit_lap=None)
        e.settings['lang'] = 'cs'
        with e.lock:
            rc = build_recap(e)
        self.assertTrue(rc['ok'])
        self.assertEqual(len(rc['corners']), len(SIM.CORNERS))
        self.assertTrue(rc['outline']['x'])
        # úseky zatáček pokrývají kolo → součet průměrů ≈ průměrný čas kola
        self.assertGreater(rc['best_lap']['lap'], 1)              # 1. kolo závodu vynecháno
        self.assertEqual(rc['sectors']['best']['lap'], rc['best_lap']['lap'])
        self.assertLessEqual(rc['ideal_time'], rc['best_lap']['time'])
        h = rc['highlights']
        self.assertTrue(all(x['ms'] > 0 for x in h['most_loss']))
        self.assertTrue(all(x['ms'] < 0 for x in h['best_gains']))
        self.assertTrue(all(x['ms'] > 0 for x in h['worst_losses']))
        self.assertTrue(rc['text'][0].startswith('Nejvíc pravidelně ztrácíš'))
        self.assertNotIn('outline', for_llm(rc))

    def test_recap_saved_with_debrief(self):
        e, _ = race_log(laps=8)
        with e.lock:
            summary = D.build_summary(e)
        entry = D.make_debrief(e, summary, 'en', key=None)
        saved = e.storage.load_debriefs()[0]
        self.assertTrue(saved['summary']['recap']['ok'])
        self.assertIn('Losing most consistently', entry['text'])
