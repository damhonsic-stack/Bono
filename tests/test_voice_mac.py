import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engineer import voice_mac as V, llm  # noqa: E402
from engineer.storage import Storage  # noqa: E402
from engineer.state import Engine  # noqa: E402
from tools import simulator as SIM  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.w = V.WakeLogic('bono', clock=lambda: self.t[0])

    def test_ignores_speech_without_wake_word(self):
        self.assertEqual(self.w.handle('Jak jsou na tom gumy?'), ('ignore', ''))
        self.assertEqual(self.w.handle('ten Norris je rychlej'), ('ignore', ''))

    def test_wake_word_with_question(self):
        self.assertEqual(self.w.handle('Bono, jak jsou na tom gumy?'), ('ask', 'jak jsou na tom gumy'))
        self.assertEqual(self.w.handle('Hej Bóno kdy boxuju'), ('ask', 'kdy boxuju'))
        self.assertEqual(self.w.handle('Bonno, gap ahead?')[0], 'ask')

    def test_bare_wake_word_arms_then_question(self):
        self.assertEqual(self.w.handle('Bono.'), ('arm', ''))
        self.t[0] += 3
        self.assertEqual(self.w.handle('Jaký je gap za mnou?'), ('ask', 'Jaký je gap za mnou'))
        self.assertEqual(self.w.handle('A co palivo?'), ('ignore', ''))   # už neposlouchá

    def test_armed_window_expires(self):
        self.w.handle('Bono')
        self.t[0] += 9
        self.assertEqual(self.w.handle('jak jsou gumy'), ('ignore', ''))


@unittest.skipIf(np is None, 'numpy není k dispozici')
class SegmenterTests(unittest.TestCase):
    def test_detects_speech_segment(self):
        seg = V.Segmenter()
        rng = np.random.default_rng(1)
        out = []
        frames = [rng.normal(0, 0.001, V.FRAME) for _ in range(40)]            # ticho
        t = np.arange(V.FRAME) / V.SAMPLE_RATE
        frames += [0.2 * np.sin(2 * np.pi * 220 * t) for _ in range(40)]       # ~1,2 s řeči
        frames += [rng.normal(0, 0.001, V.FRAME) for _ in range(40)]           # ticho
        for f in frames:
            r = seg.feed(f.astype(np.float32))
            if r is not None:
                out.append(r)
        self.assertEqual(len(out), 1)
        self.assertGreater(len(out[0]) / V.SAMPLE_RATE, 1.0)

    def test_ignores_click(self):
        seg = V.Segmenter()
        t = np.arange(V.FRAME) / V.SAMPLE_RATE
        frames = [np.zeros(V.FRAME)] * 10 + [0.3 * np.sin(2 * np.pi * 300 * t)] * 4 + [np.zeros(V.FRAME)] * 40
        self.assertTrue(all(seg.feed(f.astype(np.float32)) is None for f in frames))


class EngineVoiceTests(unittest.TestCase):
    def test_can_talk_only_on_straights(self):
        e = Engine(Storage(tempfile.mkdtemp()))
        for _, p in SIM.generate('quali', laps=2, seed=2):
            e.handle(p)
        me, tel = e.lap[e.player], e.tel[e.player]
        apex = e.corners[2]['apex']
        me['lap_distance'], me['pit_status'], me['driver_status'] = apex - 100, 0, 1
        tel['brake'], tel['steer'] = 0.0, 0.0
        self.assertFalse(e.can_talk())          # brzdná zóna před zatáčkou
        me['lap_distance'] = apex + 200
        self.assertTrue(e.can_talk())
        tel['brake'] = 0.8
        self.assertFalse(e.can_talk())

    def test_chat_history_sent_to_gemini(self):
        e = Engine(Storage(tempfile.mkdtemp()))
        e.settings['gemini_key'] = 'k'
        bodies = []
        orig = llm._post

        def fake(url, body, key, timeout):
            bodies.append((url, body))
            return {'candidates': [{'content': {'parts': [{'text': 'Odpověď %d.' % len(bodies)}]}}]}
        llm._post = fake
        try:
            llm.answer(e, 'Bono, jak je na tom Norris?')
            llm.answer(e, 'A kdy boxoval?')
        finally:
            llm._post = orig
        url, body = bodies[-1]
        self.assertIn('gemini-3.5-flash', url)
        texts = [c['parts'][0]['text'] for c in body['contents']]
        self.assertEqual(texts[0], 'DRIVER: jak je na tom Norris')
        self.assertEqual(texts[1], 'Odpověď 1.')
        self.assertTrue(texts[-1].endswith('DRIVER: A kdy boxoval'))
        self.assertEqual(len(e.chat_history), 2)

    def test_default_language_is_czech(self):
        e = Engine(Storage(tempfile.mkdtemp()))
        self.assertEqual(e.lang, 'cs')

    def test_check_reports_missing_on_linux(self):
        self.assertIn('macOS', V.MacVoice.check()) if sys.platform != 'darwin' else None


if __name__ == '__main__':
    unittest.main()
