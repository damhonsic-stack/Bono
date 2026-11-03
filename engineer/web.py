"""HTTP server (stdlib): statické soubory, Server-Sent Events a JSON API."""
import json
import os
import urllib.parse
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import llm

MIME = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8', '.json': 'application/json',
        '.png': 'image/png', '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json'}


def make_handler(engine, web_root):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get('Content-Length') or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode('utf-8'))
            except ValueError:
                return {}

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/events':
                return self._sse()
            if path == '/api/state':
                return self._json(engine.snapshot())
            if path == '/api/track':
                return self._json(engine.track_info())
            if path == '/api/compare':
                return self._json(engine.compare_traces() or {})
            if path == '/api/history':
                return self._json(engine.storage.load_history(engine.track_id))
            if path == '/api/debriefs':
                return self._json(engine.storage.load_debriefs())
            if path == '/api/tts':
                return self._tts()
            if path == '/':
                path = '/index.html'
            full = os.path.normpath(os.path.join(web_root, path.lstrip('/')))
            if not full.startswith(os.path.abspath(web_root)) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', MIME.get(os.path.splitext(full)[1],
                                                      'application/octet-stream'))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = self.path.split('?', 1)[0]
            data = self._body()
            if path == '/api/settings':
                engine.update_settings(data)
                return self._json({'ok': True})
            if path == '/api/ask':
                q = (data.get('q') or '').strip()
                if not q:
                    return self._json({'error': 'empty'}, 400)
                text, src = llm.answer(engine, q)
                with engine.lock:
                    engine.say(text, prio=3 if src == 'command' else 2)
                return self._json({'text': text, 'source': src})
            if path == '/api/reset_corners':
                engine.reset_corners()
                return self._json({'ok': True})
            if path == '/api/debrief':
                with engine.lock:
                    ok = engine.start_debrief(announce=True)
                return self._json({'ok': ok})
            self.send_error(404)

        def _tts(self):
            """Gemini hlas pro hlášení ?id=N. 204 = použij hlas iOS."""
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                mid = int(qs.get('id', ['0'])[0])
            except ValueError:
                mid = 0
            with engine.lock:
                msg = next((m for m in engine.messages if m['id'] == mid), None)
                key = engine.settings.get('gemini_key')
                voice = engine.settings.get('tts_voice', 'Charon')
                lang = engine.lang
            wav = engine.tts.get(key, msg['text'], voice, lang) if (msg and key) else None
            if not wav:
                self.send_response(204)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(wav)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(wav)

        def _sse(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            self.close_connection = True
            try:
                while True:
                    snap = engine.snapshot()
                    payload = json.dumps(snap, ensure_ascii=False)
                    self.wfile.write(('data: ' + payload + '\n\n').encode('utf-8'))
                    self.wfile.flush()
                    time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    return Handler


def udp_loop(engine, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass
    sock.bind(('0.0.0.0', port))
    while True:
        data, _ = sock.recvfrom(4096)
        try:
            engine.handle(data)
        except Exception as e:  # noqa: BLE001 - server nesmí spadnout kvůli jednomu paketu
            print('Chyba paketu:', repr(e))


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def run(engine, web_root, http_port, udp_port):
    t = threading.Thread(target=udp_loop, args=(engine, udp_port), daemon=True)
    t.start()
    server = ThreadingHTTPServer(('0.0.0.0', http_port), make_handler(engine, web_root))
    server.daemon_threads = True
    ip = local_ip()
    print('=' * 56)
    print(' F1 25 AI inženýr běží')
    print(' Ve hře nastav: UDP IP Address = %s, UDP Port = %d' % (ip, udp_port))
    print('               UDP Format = 2025, UDP Send Rate = 20 Hz')
    print(' Na iPadu/iPhonu otevři v Safari:  http://%s:%d' % (ip, http_port))
    print(' (na stejném iPadu stačí http://localhost:%d)' % http_port)
    print('=' * 56)
    server.serve_forever()
