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


def run_sim(mode='quali', laps=5, ai=95, seed=3):
    eng = Engine(Storage(tempfile.mkdtemp()))
    for _, pkt in SIM.generate(mode, laps=laps, ai=ai, seed=seed):
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
        self.assertEqual(src, 'odhad')
        self.assertEqual(t.matching_difficulty(17, lap95), 95)

    def test_calibration(self):
        t = Targets({})
        t.calibrate(17, 90, 66000)
        lap90, src = t.target_lap(17, 90)
        self.assertAlmostEqual(lap90, 66000, delta=1)
        self.assertTrue(src.startswith('kalibrováno'))


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


if __name__ == '__main__':
    unittest.main()
