import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engineer import packets as P  # noqa: E402
from engineer.laps import CarLapRecorder, resample  # noqa: E402
from engineer.corners import detect_corners, compare_lap  # noqa: E402
from engineer.targets import Targets  # noqa: E402
from engineer.race import RaceTracker  # noqa: E402
from engineer.storage import Storage  # noqa: E402
from engineer.state import Engine  # noqa: E402
from engineer import llm  # noqa: E402
from tools import simulator as SIM  # noqa: E402


def trace_from_profile(errors=None, skill=0.93):
    prof, step = SIM.speed_profile(skill, errors)
    samples, t, d = [], 0.0, 0.0
    for i, v in enumerate(prof[:-1]):
        d = i * step
        samples.append((d, t * 1000, v, 1.0, 0.0, 0.0, 4, 0.0, 0.0))
        t += step / (v / 3.6)
    return resample(samples, SIM.TRACK_LEN, t * 1000)


def run_sim(mode='quali', laps=5, ai=95, seed=3, fmt=2025):
    eng = Engine(Storage(tempfile.mkdtemp()))
    eng.settings['lang'] = 'cs'
    for _, pkt in SIM.generate(mode, laps=laps, ai=ai, seed=seed, fmt=fmt):
        eng.handle(pkt)
    return eng


class PacketTests(unittest.TestCase):
    def test_simulator_packet_sizes_match_spec(self):
        seen = {}
        for _, pkt in SIM.generate('quali', laps=1, seed=1):
            pid = P.parse_header(pkt)['packet_id']
            seen[pid] = len(pkt)
            if len(seen) >= 7:
                break
        for pid, size in seen.items():
            self.assertEqual(size, P.PACKET_SIZES[pid], 'packet %d' % pid)

    def test_2026_packet_sizes_match_official_spec(self):
        # velikosti z "Data Output from F1 25: 2026 Season Pack" v1.2
        official = {0: 1325, 1: 926, 2: 1399, 4: 1470, 5: 1233, 6: 1448, 7: 1445, 10: 1133,
                    12: 231, 13: 273, 16: 269}
        seen = {}
        for _, pkt in SIM.generate('race', laps=1, seed=1, fmt=2026):
            seen[P.parse_header(pkt)['packet_id']] = len(pkt)
            if all(k in seen for k in official):
                break
        for pid, size in official.items():
            self.assertEqual(seen[pid], size, 'packet %d' % pid)
            self.assertEqual(P.LAYOUT_2026.sizes[pid], size)

    def test_2026_session_aero_zones(self):
        pk = SIM.Packer(2026, 7)
        _, _, s = P.parse_packet(pk.session(0.0, 0, 15, 10, 90))
        self.assertEqual(s['ai_difficulty'], 90)
        self.assertEqual(len(s['aero_zones_full']), len(SIM.AERO_ZONES))
        self.assertTrue(0 <= s['aero_zones_full'][0][0] < 1)

    def test_unknown_format_rejected(self):
        pkt = bytearray(SIM.pack_session(42, 1.0, 1, 7, 12, 93))
        pkt[0:2] = (2024).to_bytes(2, 'little')
        self.assertIsNone(P.parse_packet(bytes(pkt))[2])

    def test_session_fields(self):
        pkt = SIM.pack_session(42, 1.0, 1, 7, 12, 93)
        hdr, pid, s = P.parse_packet(pkt)
        self.assertEqual(pid, P.SESSION)
        self.assertEqual(hdr['format'], 2025)
        self.assertEqual(s['ai_difficulty'], 93)
        self.assertEqual(s['track_id'], 17)
        self.assertEqual(s['total_laps'], 12)
        self.assertAlmostEqual(s['sector2_start'], SIM.TRACK_LEN / 3, places=1)

    def test_short_packet_is_ignored(self):
        pkt = SIM.pack_session(42, 1.0, 1, 7, 12, 93)[:200]
        self.assertIsNone(P.parse_packet(pkt)[2])


class CornerTests(unittest.TestCase):
    def test_detects_all_corners_near_apex(self):
        tr = trace_from_profile()
        corners = detect_corners(tr)
        self.assertEqual(len(corners), len(SIM.CORNERS))
        for c, (apex, _) in zip(corners, SIM.CORNERS):
            self.assertLess(abs(c['apex'] - apex), 30)
        # segmenty pokrývají celé kolo
        self.assertEqual(corners[0]['start'], 0)
        self.assertAlmostEqual(corners[-1]['end'], SIM.TRACK_LEN, delta=1)

    def test_loss_located_in_right_corner_with_tip(self):
        ref = trace_from_profile()
        lap = trace_from_profile({3: ('slow', 0.12)})
        corners = detect_corners(ref)
        res = compare_lap(lap, ref, corners)
        worst = max(res, key=lambda c: c['loss'])
        self.assertEqual(worst['id'], 4)
        self.assertGreater(worst['loss'], 50)
        self.assertIn(worst['tips'][0][0], ('min_speed', 'overdrive'))
        total = sum(c['loss'] for c in res)
        self.assertAlmostEqual(total, lap.lap_time - ref.lap_time, delta=len(res) + 1)

    def test_early_braking_tip(self):
        ref = trace_from_profile()
        lap = trace_from_profile({0: ('early', 0.3)})
        res = compare_lap(lap, ref, detect_corners(ref))
        self.assertEqual(max(res, key=lambda c: c['loss'])['id'], 1)


class RecorderTests(unittest.TestCase):
    def lap(self, num, d, t, last=0, invalid=0):
        return {'lap_num': num, 'lap_distance': d, 'current_lap_ms': t, 'last_lap_ms': last,
                'invalid': invalid, 'pit_status': 0, 's1_ms': 0, 's2_ms': 0}

    def test_flashback_truncates_and_lap_completes(self):
        r = CarLapRecorder(0)
        tel = {'speed': 200, 'throttle': 1, 'brake': 0, 'steer': 0, 'gear': 6}
        for i in range(0, 600):
            r.update(self.lap(1, i * 5.0, i * 90), tel, None, 3000)
        # flashback zpět na 1000 m
        r.update(self.lap(1, 1000.0, 18000), tel, None, 3000)
        self.assertLessEqual(r.samples[-1][0], 1000.0)
        for i in range(201, 600):
            r.update(self.lap(1, i * 5.0, i * 90), tel, None, 3000)
        done = r.update(self.lap(2, 2.0, 30, last=54000), tel, None, 3000)
        self.assertIsNotNone(done)
        self.assertTrue(done.clean)
        self.assertEqual(done.trace.lap_time, 54000)

    def test_out_lap_not_clean(self):
        r = CarLapRecorder(0)
        for i in range(300, 600):
            r.update(self.lap(1, i * 5.0, i * 90), None, None, 3000)
        done = r.update(self.lap(2, 2.0, 30, last=54000), None, None, 3000)
        self.assertFalse(done.clean)


class TargetTests(unittest.TestCase):
    def test_target_and_matching(self):
        t = Targets({})
        lap95, src = t.target_lap(17, 95)
        lap100, _ = t.target_lap(17, 100)
        self.assertGreater(lap95, lap100)
        self.assertEqual(src, 'estimate')
        self.assertEqual(t.matching_difficulty(17, lap95), 95)

    def test_calibration(self):
        t = Targets({})
        t.calibrate(17, 90, 66000)
        lap90, src = t.target_lap(17, 90)
        self.assertAlmostEqual(lap90, 66000, delta=1)
        self.assertTrue(src.startswith('calibrated'))


class RaceTests(unittest.TestCase):
    def test_gap_trend(self):
        r = RaceTracker()
        for i, g in enumerate([3000, 2700, 2400, 2100]):
            r.on_new_lap(i + 2, None, None, g, 1500 - i * 200, 70000)
        gaps = r.gaps(2100, 900)
        self.assertEqual(gaps['ahead_trend'], -300)
        self.assertEqual(gaps['behind_trend'], -200)
        self.assertAlmostEqual(gaps['catch_in_laps'], 7.0)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = run_sim('quali', laps=5)
        cls.r = run_sim('race', laps=6, ai=85)

    def test_quali_session(self):
        s = self.q.snapshot()
        json.dumps(s)
        self.assertEqual(len(s['laps']), 5)
        self.assertEqual(len(s['corners']), len(SIM.CORNERS))
        self.assertIsNotNone(s['reference']['kind'])
        self.assertIsNotNone(s['target'])
        self.assertIsNotNone(s['theoretical_best'])
        self.assertLessEqual(s['theoretical_best'], s['best']['time'])
        self.assertTrue(any(c['last'] for c in s['corners']))
        self.assertTrue(self.q.ai_best is not None)
        self.assertGreater(len(s['messages']), 3)

    def test_compare_traces(self):
        c = self.q.compare_traces()
        self.assertEqual(len(c['dist']), len(c['delta']))

    def test_pb_persisted(self):
        data = self.q.storage.load_track(17)
        self.assertIn('pb', data)
        self.assertIn('corners', data)
        self.assertNotIn('trace_obj', data['pb'])

    def test_race_snapshot(self):
        s = self.r.snapshot()
        race = s['race']
        self.assertIsNotNone(race['fuel'])
        self.assertIn('burn_per_lap', race['fuel'])
        self.assertIn('wear', race['tyres'])
        self.assertIn('ahead_trend', race['gaps'])

    def test_offline_answers(self):
        for q in ['gumy?', 'palivo', 'mezera', 'kde ztrácím', 'obtížnost', 'tempo']:
            text, src = llm.answer(self.r, q)
            self.assertEqual(src, 'offline')
            self.assertTrue(text and isinstance(text, str))

    def test_english(self):
        self.r.settings['lang'] = 'en'
        try:
            text, _ = llm.answer(self.r, 'tyres')
            self.assertIn('Tyre wear', text)
        finally:
            self.r.settings['lang'] = 'cs'

    def test_session_change_resets(self):
        eng = run_sim('quali', laps=2, seed=5)
        first = eng.session_uid
        for _, pkt in SIM.generate('quali', laps=1, seed=6):
            eng.handle(pkt)
        self.assertNotEqual(eng.session_uid, first)
        self.assertEqual(len(eng.player_laps), 1)
        # PB z předchozí session zůstává
        self.assertIsNotNone(eng._stored_pb())


class Regs2026Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = run_sim('race', laps=8, ai=90, seed=11, fmt=2026)

    def test_regs_snapshot(self):
        s = self.e.snapshot()
        json.dumps(s)
        r = s['regs']
        self.assertTrue(r['active'])
        self.assertEqual(s['format'], 2026)
        self.assertIn('pct', r['ers'])
        self.assertIn('harvest_limit_mj', r['ers'])
        self.assertIn(r['aero']['mode'], ('Straight', 'Corner'))
        self.assertEqual(r['aero_status'], 'Full')
        self.assertEqual(len(r['aero_zones']), len(SIM.AERO_ZONES))

    def test_straight_mode_usage_per_lap(self):
        pcts = [l.meta.get('straight_pct') for l in self.e.player_laps[1:]]
        self.assertTrue(all(p is not None for p in pcts))
        self.assertTrue(all(0 <= p <= 100 for p in pcts))
        self.assertTrue(any(p >= 95 for p in pcts))

    def test_race_control_and_lap_analysis_still_work(self):
        texts = ' '.join(m['text'] for m in self.e.messages)
        self.assertEqual(len(self.e.corners), len(SIM.CORNERS))
        self.assertGreater(len(self.e.player_laps), 5)
        self.assertIn('Lap', texts)

    def test_ers_answer(self):
        text, src = llm.answer(self.e, 'Bono, how is the battery?')
        self.assertEqual(src, 'offline')
        self.assertIn('Battery', text)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.e = run_sim('race', laps=3, seed=4, fmt=2026)
        self.e.settings['lang'] = 'en'

    def test_wake_word_stripping(self):
        self.assertEqual(llm.strip_wake_word('Bono, how are my tyres?', 'bono'),
                         'how are my tyres')
        self.assertEqual(llm.strip_wake_word('hey bono gap ahead', 'bono'), 'gap ahead')

    def test_mute_unmute_repeat(self):
        text, src = llm.answer(self.e, 'Bono, be quiet')
        self.assertEqual(src, 'command')
        self.assertFalse(self.e.settings['voice'])
        llm.answer(self.e, 'bono talk to me')
        self.assertTrue(self.e.settings['voice'])
        self.e.say('Box this lap.')
        text, _ = llm.answer(self.e, 'Bono say again')
        self.assertEqual(text, 'Box this lap.')

    def test_only_wake_word_is_radio_check(self):
        text, src = llm.answer(self.e, 'Bono')
        self.assertEqual(text, 'Loud and clear.')

    def test_status_report(self):
        text, _ = llm.answer(self.e, 'Bono, status report')
        self.assertIn('P', text)
        self.assertIn('Battery', text)

    def test_controller_buttons(self):
        pk = SIM.Packer(2026, self.e.session_uid)
        n = len(self.e.messages)
        seq = self.e.listen_seq
        self.e.handle(pk.buttons(P.UDP_ACTION_BITS[2], 1.0, 1))   # status
        self.e.handle(pk.buttons(0, 1.0, 2))
        self.e.handle(pk.buttons(P.UDP_ACTION_BITS[1], 1.0, 3))   # listen
        self.e.handle(pk.buttons(P.UDP_ACTION_BITS[1], 1.0, 4))   # podržení = bez nové akce
        self.assertEqual(len(self.e.messages), n + 1)
        self.assertEqual(self.e.listen_seq, seq + 1)

    def test_foreign_session_packets_do_not_reset(self):
        uid = self.e.session_uid
        laps = len(self.e.player_laps)
        other = SIM.Packer(2026, 12345)
        self.e.handle(other.buttons(P.UDP_ACTION_BITS[3], 1.0, 1))
        self.e.handle(other.telemetry2({}, 1.0, 2))
        self.assertEqual(self.e.session_uid, uid)
        self.assertEqual(len(self.e.player_laps), laps)


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.orig = llm._post

    def tearDown(self):
        llm._post = self.orig

    def test_fallback_to_next_model_and_trim(self):
        calls = []

        def fake(url, body, key, timeout):
            calls.append(url.split('/models/')[1].split(':')[0])
            if len(calls) == 1:
                raise llm.GeminiError('503: high demand')
            return {'candidates': [{'finishReason': 'MAX_TOKENS', 'content': {'parts': [
                {'text': 'Gap ahead 0.8. You are closing. Harvest'}]}}]}
        llm._post = fake
        text, model = llm.ask_with_fallback('k', 'gemini-flash-lite-latest', 'en', 'gap?', {})
        self.assertEqual(calls[:2], ['gemini-flash-lite-latest', 'gemini-3.5-flash'])
        self.assertEqual(text, 'Gap ahead 0.8. You are closing.')

    def test_offline_when_gemini_down(self):
        def fake(url, body, key, timeout):
            raise llm.GeminiError('503: high demand')
        llm._post = fake
        e = run_sim('quali', laps=2, seed=8)
        e.settings['gemini_key'] = 'k'
        text, src = llm.answer(e, 'Bono, pace?')
        self.assertEqual(src, 'offline')
        self.assertTrue(text)
        self.assertIn('503', e.last_llm_error)


if __name__ == '__main__':
    unittest.main()
