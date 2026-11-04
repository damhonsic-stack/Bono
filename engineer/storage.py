"""Ukládání nastavení, kalibrace a osobních rekordů do JSON souborů."""
import json
import os
import threading

DEFAULT_SETTINGS = {
    'lang': 'cs',            # 'cs' | 'en'
    'engineer_name': 'Bono',
    'wake_word': 'bono',
    'wake_radio': True,      # reaguj i na „Rádio, …“ (jako skutečné týmové rádio)
    'persona': 'bono',       # bono = klidný, vlasta = energická, kouc = přísný kouč
    # UDP Action tlačítka (ve hře je namapuj na ovladač) -> akce
    'buttons': {'1': 'listen', '2': 'status', '3': 'corners', '4': 'tyres',
                '5': 'gaps', '6': 'fuel', '7': 'repeat', '8': 'mute',
                '9': 'strategy', '10': 'damage', '11': 'setup', '12': 'debrief'},
    'radio_mode': 'quiet',   # quiet = jen důležité, normal = + lap times a gapy, full = vše
    'cloud_url': '',         # Bono Cloud (Netlify), např. https://moje-bono.netlify.app
    'cloud_code': '',        # osobní sync kód (min. 8 znaků), stejný na všech zařízeních
    'level': 2,              # 1 nováček, 2 pokročilý, 3 pro
    'reference': 'auto',     # auto | session_best | pb | ai_best | tt_rival
    'difficulty_override': None,  # None = vezmi obtížnost ze hry
    'voice': True,
    'gemini_key': '',
    'gemini_model': 'gemini-flash-lite-latest',
    'chat_model': 'gemini-flash-lite-latest',   # Gemini model pro konverzaci
    'groq_key': '',                       # volitelné: zdarma na console.groq.com (rychlejší mozek)
    'groq_model': 'llama-3.3-70b-versatile',
    # hlas: 'mixed' = urgentní hlášení hlasem iOS (okamžitě), ostatní Gemini hlasem s rádiovým
    # filtrem; 'gemini' = vše Gemini (záloha iOS); 'ios' = jen hlas iOS
    'voice_engine': 'mixed',
    'tts_voice': 'Charon',
    'udp_port': 20777,
    'http_port': 8080,
}


class Storage:
    def __init__(self, root):
        self.root = root
        self.lock = threading.Lock()
        self.listeners = []      # fn(kind, ident, obj) – např. synchronizace do Bono Cloud
        os.makedirs(os.path.join(root, 'tracks'), exist_ok=True)

    def _notify(self, kind, ident=None, obj=None):
        for fn in list(self.listeners):
            try:
                fn(kind, ident, obj)
            except Exception:  # noqa: BLE001 – sync nesmí rozbít ukládání
                pass

    def _path(self, *parts):
        return os.path.join(self.root, *parts)

    def _load(self, path, default):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def _save(self, path, obj):
        with self.lock:
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
            os.replace(tmp, path)

    def load_settings(self):
        s = dict(DEFAULT_SETTINGS)
        s.update(self._load(self._path('settings.json'), {}))
        return s

    def save_settings(self, s, notify=True):
        self._save(self._path('settings.json'), s)
        if notify:
            self._notify('settings', None, s)

    def load_calibration(self):
        return self._load(self._path('calibration.json'), {})

    def save_calibration(self, c, notify=True):
        self._save(self._path('calibration.json'), c)
        if notify:
            self._notify('calibration', None, c)

    def load_track(self, track_id):
        return self._load(self._path('tracks', '%s.json' % track_id), {})

    def save_track(self, track_id, data, notify=True):
        self._save(self._path('tracks', '%s.json' % track_id), data)
        if notify:
            self._notify('track', track_id, data)

    def track_ids(self):
        try:
            return sorted(int(f[:-5]) for f in os.listdir(self._path('tracks'))
                          if f.endswith('.json') and f[:-5].lstrip('-').isdigit())
        except OSError:
            return []

    def load_memory(self):
        return self._load(self._path('memory.json'), {})

    def save_memory(self, m, notify=True):
        self._save(self._path('memory.json'), m)
        if notify:
            self._notify('memory', None, m)

    def append_history(self, entry):
        path = self._path('history.jsonl')
        with self.lock:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self._notify('history', entry.get('track'), entry)

    def append_debrief(self, entry):
        path = self._path('debriefs.jsonl')
        with self.lock:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self._notify('debrief', entry.get('ts'), entry)

    def load_debriefs(self, limit=20):
        out = []
        try:
            with open(self._path('debriefs.jsonl'), 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            pass
        return out[-limit:][::-1]

    def load_history(self, track_id=None, limit=500):
        out = []
        try:
            with open(self._path('history.jsonl'), 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if track_id is None or e.get('track') == track_id:
                        out.append(e)
        except OSError:
            pass
        return out[-limit:]
