"""Ukládání nastavení, kalibrace a osobních rekordů do JSON souborů."""
import json
import os
import threading

DEFAULT_SETTINGS = {
    'lang': 'en',            # 'en' | 'cs'
    'engineer_name': 'Bono',
    'wake_word': 'bono',
    # UDP Action tlačítka (ve hře je namapuj na ovladač) -> akce
    'buttons': {'1': 'listen', '2': 'status', '3': 'corners', '4': 'tyres',
                '5': 'gaps', '6': 'fuel', '7': 'repeat', '8': 'mute',
                '9': 'strategy', '10': 'damage', '11': 'setup', '12': 'debrief'},
    'level': 2,              # 1 nováček, 2 pokročilý, 3 pro
    'reference': 'auto',     # auto | session_best | pb | ai_best | tt_rival
    'difficulty_override': None,  # None = vezmi obtížnost ze hry
    'voice': True,
    'gemini_key': '',
    'gemini_model': 'gemini-flash-lite-latest',
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
        os.makedirs(os.path.join(root, 'tracks'), exist_ok=True)

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

    def save_settings(self, s):
        self._save(self._path('settings.json'), s)

    def load_calibration(self):
        return self._load(self._path('calibration.json'), {})

    def save_calibration(self, c):
        self._save(self._path('calibration.json'), c)

    def load_track(self, track_id):
        return self._load(self._path('tracks', '%s.json' % track_id), {})

    def save_track(self, track_id, data):
        self._save(self._path('tracks', '%s.json' % track_id), data)

    def append_history(self, entry):
        path = self._path('history.jsonl')
        with self.lock:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def append_debrief(self, entry):
        path = self._path('debriefs.jsonl')
        with self.lock:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

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
