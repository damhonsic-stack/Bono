import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engineer.storage import Storage  # noqa: E402
from engineer.state import Engine  # noqa: E402
from engineer import web  # noqa: E402
from tools import simulator as SIM  # noqa: E402
import update  # noqa: E402


class ActionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = Engine(Storage(tempfile.mkdtemp()))
        for _, p in SIM.generate('race', laps=4, seed=3, fmt=2026):
            cls.e.handle(p)
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), web.make_handler(cls.e, os.path.join(ROOT, 'web')))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:%d' % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_actions_speak(self):
        n = len(self.e.messages)
        self.assertEqual(self.post('/api/action', {'action': 'status'})[0], 200)
        self.assertEqual(self.post('/api/action', {'action': 'gaps'})[0], 200)
        self.assertEqual(len(self.e.messages), n + 2)
        self.assertTrue(self.e.messages[-2]['text'].startswith('P'))

    def test_mute_and_listen(self):
        seq = self.e.listen_seq
        self.post('/api/action', {'action': 'mute'})
        self.assertFalse(self.e.settings['voice'])
        self.post('/api/action', {'action': 'unmute'})
        self.assertTrue(self.e.settings['voice'])
        self.post('/api/action', {'action': 'listen'})
        self.assertEqual(self.e.listen_seq, seq + 1)

    def test_unknown_action_rejected(self):
        self.assertEqual(self.post('/api/action', {'action': 'rm -rf'})[0], 400)

    def test_tts_without_key_is_204(self):
        with urllib.request.urlopen(self.base + '/api/tts?id=1', timeout=5) as r:
            self.assertEqual(r.status, 204)

    def test_index_has_pad(self):
        with urllib.request.urlopen(self.base + '/', timeout=5) as r:
            html = r.read().decode()
        self.assertIn('id="pad"', html)


class UpdateTests(unittest.TestCase):
    def test_update_overwrites_code_but_keeps_data(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, 'data'))
            with open(os.path.join(tmp, 'data', 'settings.json'), 'w') as f:
                f.write('{"gemini_key": "secret"}')
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                z.writestr('Bono-f1-ai-engineer/', '')
                z.writestr('Bono-f1-ai-engineer/server.py', 'NEW')
                z.writestr('Bono-f1-ai-engineer/web/app.js', 'JS')
                z.writestr('Bono-f1-ai-engineer/data/settings.json', '{}')
            payload = buf.getvalue()

            class Resp(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            orig_open, orig_here = update.urllib.request.urlopen, update.HERE
            update.urllib.request.urlopen = lambda url, timeout=0: Resp(payload)
            update.HERE = tmp
            try:
                update.main()
            finally:
                update.urllib.request.urlopen, update.HERE = orig_open, orig_here
            self.assertEqual(open(os.path.join(tmp, 'server.py')).read(), 'NEW')
            self.assertEqual(open(os.path.join(tmp, 'web', 'app.js')).read(), 'JS')
            self.assertIn('secret', open(os.path.join(tmp, 'data', 'settings.json')).read())
        finally:
            shutil.rmtree(tmp)


if __name__ == '__main__':
    unittest.main()
