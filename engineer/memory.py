"""Bonova dlouhodobá paměť o jezdci – sdílená mezi zařízeními přes Bono Cloud.

Obsahuje:
  - notes:  věci, které mu řekneš („Bono, zapamatuj si, že …“) nebo dopíšeš na webu
  - tracks: pro každou trať best lap, počet session a turny, kde opakovaně ztrácíš
Bono ji dostává do kontextu, takže může říct „minule jsi tady ztrácel v T8“.
"""
import re
import time

from .constants import TRACKS

REMEMBER_RE = re.compile(r'^\s*(?:zapamatuj si|pamatuj si|zapiš si|remember|note that|remember that)'
                         r'[\s,:]*(?:že|ze|that)?\s*(.+)$', re.I)
FORGET_RE = re.compile(r'^\s*(?:zapomeň|zapomen|forget)\b', re.I)


def empty():
    return {'updated': 0, 'notes': [], 'tracks': {}}


class Memory:
    def __init__(self, storage):
        self.storage = storage
        self.data = storage.load_memory() or empty()
        for k, v in empty().items():
            self.data.setdefault(k, v)

    def save(self):
        self.data['updated'] = int(time.time() * 1000)
        self.storage.save_memory(self.data)

    def replace(self, data):
        """Novější verze z cloudu (bez zpětného nahrání)."""
        if not data:
            return False
        d = dict(empty(), **data)
        self.data = d
        self.storage.save_memory(d, notify=False)
        return True

    # ------------------------------------------------------------ poznámky
    def add_note(self, text):
        text = text.strip().rstrip('.')
        if not text:
            return False
        self.data['notes'].append({'text': text, 'ts': int(time.time())})
        self.data['notes'] = self.data['notes'][-50:]
        self.save()
        return True

    def forget_last(self):
        if not self.data['notes']:
            return None
        n = self.data['notes'].pop()
        self.save()
        return n['text']

    # ------------------------------------------------------------ po session
    def update_from_session(self, track_id, summary):
        """summary = debrief summary (s recapem)."""
        if track_id is None:
            return
        key = str(track_id)
        t = self.data['tracks'].setdefault(key, {'name': TRACKS.get(track_id, str(track_id)),
                                                 'sessions': 0, 'weak_turns': {}})
        t['name'] = TRACKS.get(track_id, t.get('name'))
        t['sessions'] = t.get('sessions', 0) + 1
        best = (summary.get('recap') or {}).get('best_lap') or {}
        if best.get('time') and (not t.get('best_ms') or best['time'] < t['best_ms']):
            t['best_ms'] = best['time']
        weak = t.setdefault('weak_turns', {})
        for item in ((summary.get('recap') or {}).get('highlights') or {}).get('most_loss', []):
            w = weak.setdefault(item['turn'], {'count': 0, 'avg_loss_ms': 0})
            w['avg_loss_ms'] = round((w['avg_loss_ms'] * w['count'] + item['ms']) / (w['count'] + 1))
            w['count'] += 1
        t['last'] = {'date': time.strftime('%Y-%m-%d'), 'session': summary.get('session'),
                     'best': summary.get('best_lap'), 'finish': summary.get('finish_position')}
        self.save()

    # ------------------------------------------------------------ pro AI
    def context(self, track_id):
        t = self.data['tracks'].get(str(track_id)) if track_id is not None else None
        out = {'driver_notes': [n['text'] for n in self.data['notes'][-12:]]}
        if t:
            weak = sorted(t.get('weak_turns', {}).items(), key=lambda kv: (-kv[1]['count'],
                                                                           -kv[1]['avg_loss_ms']))
            out['this_track'] = {
                'name': t.get('name'), 'sessions_before': t.get('sessions', 0),
                'best_ever_ms': t.get('best_ms'),
                'recurring_weak_turns': [{'turn': k, 'sessions': v['count'], 'avg_loss_ms': v['avg_loss_ms']}
                                         for k, v in weak[:4]],
                'last_session': t.get('last'),
            }
        return out
