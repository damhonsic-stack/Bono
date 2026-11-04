"""Synchronizace s Bono Cloud (Netlify Functions + Blobs).

Mac (Bono server) nahrává: debriefy s recapem a mapou, časy kol, rekordy tratí, kalibraci,
Bonovu paměť a sdílené nastavení. Stahuje: paměť a nastavení změněné na webu, rekordy tratí,
které lokálně chybí (třeba na jiném počítači).

Tajné věci (API klíče, sync kód) se do cloudu NIKDY neposílají.
"""
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .constants import TRACKS

SHARED_SETTINGS = ('lang', 'radio_mode', 'level', 'reference', 'engineer_name', 'wake_word',
                   'voice_engine', 'tts_voice', 'difficulty_override', 'voice')
PUSH_EVERY = 10
PULL_EVERY = 90


class CloudError(Exception):
    pass


class CloudClient:
    def __init__(self, url, code, timeout=15):
        self.url = url.rstrip('/')
        self.code = code
        self.timeout = timeout

    def _req(self, method, path, body=None, auth=True):
        data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
        headers = {'Content-Type': 'application/json', 'User-Agent': 'bono-f1-engineer'}
        if auth:
            headers['X-Bono-Code'] = self.code
        req = urllib.request.Request(self.url + '/api/' + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=ssl.create_default_context()) as r:
                raw = r.read().decode('utf-8')
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 404 and path.startswith('kv'):
                return None
            try:
                msg = json.loads(e.read().decode('utf-8')).get('error', '')
            except (ValueError, OSError):
                msg = ''
            raise CloudError('%d %s' % (e.code, msg))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise CloudError(str(e))

    def auth(self):
        return self._req('POST', 'auth', {'code': self.code}, auth=False)

    def get(self, key):
        return self._req('GET', 'kv?key=' + urllib.parse.quote(key, safe='/'))

    def put(self, key, value):
        return self._req('PUT', 'kv?key=' + urllib.parse.quote(key, safe='/'), value)

    def list(self, prefix=''):
        return (self._req('GET', 'list?prefix=' + urllib.parse.quote(prefix, safe='/')) or {}).get('keys', [])


class CloudSync:
    def __init__(self, engine, client_factory=CloudClient):
        self.engine = engine
        self.storage = engine.storage
        self.client_factory = client_factory
        self.dirty = set()
        self.lock = threading.Lock()
        self.status = 'off'
        self.last_error = None
        self.last_push = None
        self.last_pull = None
        self.shared_updated = 0
        self._stop = threading.Event()
        self.storage.listeners.append(self._on_change)

    # ------------------------------------------------------------ konfigurace
    def client(self):
        s = self.engine.settings
        url, code = (s.get('cloud_url') or '').strip(), (s.get('cloud_code') or '').strip()
        if not url or len(code) < 8:
            return None
        if not url.startswith('http'):
            url = 'https://' + url
        return self.client_factory(url, code)

    def snapshot(self):
        return {'enabled': bool(self.client()), 'status': self.status, 'error': self.last_error,
                'last_push': self.last_push, 'last_pull': self.last_pull, 'pending': len(self.dirty),
                'url': self.engine.settings.get('cloud_url') or ''}

    # ------------------------------------------------------------ změny lokálně → fronta
    def _on_change(self, kind, ident, obj):
        with self.lock:
            if kind == 'track':
                self.dirty.add(('track', ident))
                self.dirty.add(('tracks_index', None))
            elif kind == 'history':
                if ident is not None:
                    self.dirty.add(('history', ident))
            elif kind == 'debrief':
                self.dirty.add(('debrief', ident))
                self.dirty.add(('tracks_index', None))
            elif kind in ('calibration', 'memory', 'settings'):
                self.dirty.add((kind, None))

    def mark_all(self):
        with self.lock:
            for tid in self.storage.track_ids():
                self.dirty.add(('track', tid))
                self.dirty.add(('history', tid))
            for d in self.storage.load_debriefs(limit=200):
                self.dirty.add(('debrief', d.get('ts')))
            self.dirty.update({('calibration', None), ('memory', None), ('settings', None),
                               ('tracks_index', None)})

    # ------------------------------------------------------------ push
    def _debrief_key(self, d):
        return 'debriefs/%s' % d.get('ts')

    def push_one(self, c, kind, ident):
        st = self.storage
        if kind == 'track':
            data = st.load_track(ident)
            if data:
                data = {k: v for k, v in data.items() if k != 'trace_obj'}
                for pbk in ('pb', 'pb_tt'):
                    if isinstance(data.get(pbk), dict):
                        data[pbk] = {k: v for k, v in data[pbk].items() if k != 'trace_obj'}
                data['track_id'] = ident
                data['name'] = TRACKS.get(ident, str(ident))
                c.put('tracks/%s' % ident, data)
        elif kind == 'history':
            c.put('history/%s' % ident, {'track_id': ident, 'laps': st.load_history(ident, limit=5000)})
        elif kind == 'debrief':
            for d in st.load_debriefs(limit=500):
                if d.get('ts') == ident:
                    c.put(self._debrief_key(d), d)
                    break
        elif kind == 'calibration':
            c.put('calibration', {'updated': int(time.time() * 1000), 'data': st.load_calibration()})
        elif kind == 'memory':
            c.put('memory', self.engine.memory.data)
        elif kind == 'settings':
            vals = {k: self.engine.settings.get(k) for k in SHARED_SETTINGS}
            self.shared_updated = int(time.time() * 1000)
            c.put('settings/shared', {'updated': self.shared_updated, 'values': vals})
        elif kind == 'tracks_index':
            c.put('tracks_index', self.tracks_index())

    def tracks_index(self):
        st = self.storage
        debriefs = st.load_debriefs(limit=1000)
        out = []
        for tid in st.track_ids():
            data = st.load_track(tid) or {}
            name = TRACKS.get(tid, str(tid))
            mine = [d for d in debriefs if d.get('track') == name]
            pb = data.get('pb') or {}
            pbtt = data.get('pb_tt') or {}
            out.append({'track_id': tid, 'name': name, 'pb_ms': pb.get('lap_ms'), 'pb_date': pb.get('date'),
                        'tt_pb_ms': pbtt.get('lap_ms'), 'sessions': len(mine),
                        'last': max((d.get('ts', 0) for d in mine), default=None)})
        index = [{'key': self._debrief_key(d), 'ts': d.get('ts'), 'track': d.get('track'),
                  'session': d.get('session'), 'best': (d.get('summary') or {}).get('best_lap'),
                  'source': d.get('source')} for d in debriefs]
        return {'updated': int(time.time() * 1000), 'tracks': out, 'debriefs': index}

    def push(self):
        c = self.client()
        if not c:
            self.status = 'off'
            return 0
        with self.lock:
            todo = sorted(self.dirty, key=lambda x: (x[0] == 'tracks_index', str(x)))
            self.dirty.clear()
        n = 0
        try:
            for kind, ident in todo:
                self.push_one(c, kind, ident)
                n += 1
            self.status, self.last_error = 'ok', None
            if n:
                self.last_push = int(time.time())
        except CloudError as e:
            with self.lock:
                self.dirty.update(todo[n:])
            self.status, self.last_error = 'error', str(e)
        return n

    # ------------------------------------------------------------ pull
    def pull(self):
        c = self.client()
        if not c:
            return False
        eng = self.engine
        try:
            shared = c.get('settings/shared')
            if shared and shared.get('updated', 0) > self.shared_updated:
                with eng.lock:
                    for k, v in (shared.get('values') or {}).items():
                        if k in SHARED_SETTINGS and v is not None:
                            eng.settings[k] = v
                    self.storage.save_settings(eng.settings, notify=False)
                self.shared_updated = shared['updated']
            mem = c.get('memory')
            if mem and mem.get('updated', 0) > eng.memory.data.get('updated', 0):
                with eng.lock:
                    eng.memory.replace(mem)
            cal = c.get('calibration')
            if cal and cal.get('data'):
                local = self.storage.load_calibration()
                changed = False
                for k, v in cal['data'].items():
                    if v.get('samples', 0) > (local.get(k) or {}).get('samples', 0):
                        local[k] = v
                        changed = True
                if changed:
                    with eng.lock:
                        eng.targets.cal.update(local)
                        self.storage.save_calibration(local, notify=False)
            have = set(self.storage.track_ids())
            for key in c.list('tracks/'):
                tid = key.split('/', 1)[1]
                if tid.lstrip('-').isdigit() and int(tid) not in have:
                    data = c.get(key)
                    if data:
                        data.pop('track_id', None)
                        data.pop('name', None)
                        self.storage.save_track(int(tid), data, notify=False)
            self.status, self.last_error = 'ok', None
            self.last_pull = int(time.time())
            return True
        except CloudError as e:
            self.status, self.last_error = 'error', str(e)
            return False

    def connect(self):
        """Ověří sync kód (první zařízení ho nastaví) a nahraje všechno."""
        c = self.client()
        if not c:
            self.status = 'off'
            return False
        try:
            c.auth()
        except CloudError as e:
            self.status, self.last_error = 'error', str(e)
            return False
        self.pull()
        self.mark_all()
        self.push()
        return self.status == 'ok'

    # ------------------------------------------------------------ smyčka
    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        connected = False
        last_pull = 0
        while not self._stop.is_set():
            if self.client():
                if not connected:
                    connected = self.connect()
                    last_pull = time.time()
                else:
                    self.push()
                    if time.time() - last_pull > PULL_EVERY:
                        self.pull()
                        last_pull = time.time()
            else:
                connected = False
                self.status = 'off'
            self._stop.wait(PUSH_EVERY)
