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
            if path == '/api/recap':
                from .recap import build_recap
                with engine.lock:
                    return self._json(build_recap(engine))
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
            if path == '/api/presence':
                with engine.lock:
                    engine.heartbeat(data.get('id', '?'), data.get('mic'), data.get('name', ''))
                return self._json({'ok': True})
            if path == '/api/action':
                action = data.get('action', '')
                if action not in ('status', 'strategy', 'gaps', 'gap', 'tyres', 'fuel', 'damage',
                                  'repeat', 'mute', 'unmute', 'corners', 'ers', 'weather', 'setup',
                                  'debrief', 'listen'):
                    return self._json({'error': 'unknown action'}, 400)
                with engine.lock:
                    engine.button_action('gap' if action == 'gaps' else action)
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
            wav = engine.tts.get(key, msg.get('speech') or msg['text'], voice, lang) \
                if (msg and key) else None
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


def _udp_socket(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass
    sock.bind(('0.0.0.0', port))
    sock.settimeout(5.0)
    return sock


def udp_loop(engine, port, make_socket=_udp_socket, stop=None):
    """Příjem telemetrie. Když iOS socket zavře (aplikace na chvíli v pozadí),
    vytvoří se nový a příjem pokračuje."""
    sock = None
    warned = False
    while not (stop and stop.is_set()):
        try:
            if sock is None:
                sock = make_socket(port)
                if warned:
                    print('UDP příjem obnoven.')
                    warned = False
            data, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError as e:
            if not warned:
                print('UDP příjem přerušen (%s), obnovuji…' % e)
                warned = True
            try:
                sock and sock.close()
            except OSError:
                pass
            sock = None
            time.sleep(1.0)
            continue
        try:
            engine.handle(data)
        except Exception as e:  # noqa: BLE001 - server nesmí spadnout kvůli jednomu paketu
            print('Chyba paketu:', repr(e))


def _is_lan(ip):
    a = [int(x) for x in ip.split('.')]
    return a[0] == 10 or (a[0] == 172 and 16 <= a[1] <= 31) or (a[0] == 192 and a[1] == 168)


def _is_cgnat(ip):
    a = [int(x) for x in ip.split('.')]
    return a[0] == 100 and 64 <= a[1] <= 127      # mobilní data / VPN (např. Tailscale)


def candidate_ips():
    """Všechny IPv4 adresy zařízení, které se dají zjistit bez dalších knihoven."""
    ips = []
    probes = ['192.168.0.1', '192.168.1.1', '192.168.100.1', '10.0.0.1', '10.0.0.138',
              '172.16.0.1', '10.255.255.255', '8.8.8.8']
    for target in probes:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            ip = s.getsockname()[0]
            if ip not in ips and not ip.startswith('127.') and ip != '0.0.0.0':
                ips.append(ip)
        except OSError:
            pass
        finally:
            s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith('127.'):
                ips.append(ip)
    except OSError:
        pass
    return ips


def local_ip():
    """Adresa pro Xbox: přednostně domácí Wi‑Fi (192.168.x.x, 10.x, 172.16–31.x)."""
    ips = candidate_ips()
    lan = [ip for ip in ips if _is_lan(ip)]
    if lan:
        return lan[0]
    other = [ip for ip in ips if not _is_cgnat(ip)]
    return (other or ips or ['127.0.0.1'])[0]


def run(engine, web_root, http_port, udp_port):
    t = threading.Thread(target=udp_loop, args=(engine, udp_port), daemon=True)
    t.start()
    ips = candidate_ips()
    ip = local_ip()
    print('=' * 60)
    print(' Bono – F1 25 AI race engineer běží')
    if _is_lan(ip):
        print(' Ve hře nastav: UDP IP Address = %s, UDP Port = %d' % (ip, udp_port))
    else:
        print(' !! Nenašel jsem adresu domácí Wi‑Fi (192.168.x.x / 10.x.x.x).')
        print(' !! Zjisti ji: Nastavení → Wi‑Fi → (i) u tvé sítě → IP adresa.')
        print(' !! Vypni VPN a zkontroluj, že je iPad na stejné Wi‑Fi jako Xbox.')
    if len(ips) > 1:
        notes = []
        for x in ips:
            tag = 'Wi‑Fi' if _is_lan(x) else ('mobilní data / VPN – NEpoužívat' if _is_cgnat(x) else '?')
            notes.append('%s (%s)' % (x, tag))
        print(' Nalezené adresy: ' + ', '.join(notes))
    print('                UDP Format = 2026 (se Season Passem, jinak 2025), Send Rate = 20 Hz')
    if _is_lan(ip):
        print(' Na iPadu / iPhonu / jiném zařízení otevři v Safari:  http://%s:%d' % (ip, http_port))
    print(' Na zařízení, kde běží server (např. iPad s a-Shell):  http://localhost:%d' % http_port)
    print(' Server zastavíš: Ctrl+C (nebo zavři a-Shell)')
    print('=' * 60)
    while True:
        server = None
        try:
            server = ThreadingHTTPServer(('0.0.0.0', http_port), make_handler(engine, web_root))
            server.daemon_threads = True
            server.serve_forever()
        except KeyboardInterrupt:
            raise
        except OSError as e:
            print('HTTP server přerušen (%s), obnovuji…' % e)
            time.sleep(1.0)
        finally:
            if server:
                try:
                    server.server_close()
                except OSError:
                    pass
