"""Realistický hlas Bona přes Gemini TTS (volitelné).

Hlášení se generují na pozadí hned, jak vzniknou, takže když si je aplikace vyžádá,
často už jsou hotová. Výsledek je WAV (24 kHz mono); rádiový filtr se přidává v aplikaci.
Při chybě / přetížení / vyčerpání kvóty se vrátí None a aplikace použije hlas iOS.
"""
import base64
import io
import json
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor

TTS_MODELS = ['gemini-3.8-flash-tts', 'gemini-2.5-flash-preview-tts']
VOICES = ['Charon', 'Fenrir', 'Orus', 'Puck', 'Kore', 'Aoede']
STYLE = {'en': '[calm, quick, focused F1 race engineer on team radio]',
         'cs': '[klidný, rychlý, soustředěný F1 závodní inženýr v týmovém rádiu]'}


def pcm_to_wav(pcm, rate=24000, channels=1, width=2):
    buf = io.BytesIO()
    buf.write(b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVE')
    buf.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, rate, rate * channels * width,
                                    channels * width, width * 8))
    buf.write(b'data' + struct.pack('<I', len(pcm)) + pcm)
    return buf.getvalue()


class GeminiTTS:
    def __init__(self):
        self.cache = OrderedDict()      # (text, voice) -> wav bytes
        self.pending = {}               # key -> threading.Event
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()
        self.cooldown_until = 0.0
        self.last_error = None
        self.last_latency = None
        self.max_per_min = 2            # free tier TTS: Google pustí jen ~2 požadavky za minutu
        self.recent = deque()           # časy posledních požadavků
        self.last_429 = 0.0

    def _allow(self):
        now = time.time()
        while self.recent and now - self.recent[0] > 60:
            self.recent.popleft()
        if len(self.recent) >= self.max_per_min:
            return False
        self.recent.append(now)
        return True

    def available(self):
        return time.time() >= self.cooldown_until

    def _key(self, text, voice):
        return (text, voice)

    def _start(self, api_key, text, voice, lang):
        """Zajistí běžící generování; vrátí (wav | None, event | None). Volat pod zámkem."""
        k = self._key(text, voice)
        if k in self.cache:
            self.cache.move_to_end(k)
            return self.cache[k], None
        ev = self.pending.get(k)
        if ev is None and api_key and self.available() and self._allow():
            ev = self.pending[k] = threading.Event()
            self.pool.submit(self._work, api_key, text, voice, lang, k)
        return None, ev

    def prefetch(self, api_key, text, voice='Charon', lang='en'):
        """Spustí generování na pozadí (bez čekání)."""
        with self.lock:
            self._start(api_key, text, voice, lang)

    def get(self, api_key, text, voice='Charon', lang='en', timeout=7.0):
        """Vrátí WAV nebo None (do timeout sekund)."""
        with self.lock:
            wav, ev = self._start(api_key, text, voice, lang)
        if wav or ev is None:
            return wav
        ev.wait(timeout)
        with self.lock:
            return self.cache.get(self._key(text, voice))

    def _work(self, api_key, text, voice, lang, k):
        try:
            t0 = time.time()
            wav = self.synthesize(api_key, text, voice, lang)
            self.last_latency = round(time.time() - t0, 2)
            if wav:
                with self.lock:
                    self.cache[k] = wav
                    while len(self.cache) > 120:
                        self.cache.popitem(last=False)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)[:160]
        finally:
            with self.lock:
                ev = self.pending.pop(k, None)
            if ev:
                ev.set()

    def synthesize(self, api_key, text, voice='Charon', lang='en'):
        body = {
            'contents': [{'parts': [{'text': '%s %s' % (STYLE.get(lang, STYLE['en']), text)}]}],
            'generationConfig': {
                'responseModalities': ['AUDIO'],
                'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}},
            },
        }
        last = None
        for model in TTS_MODELS:
            url = 'https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model
            req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                         headers={'Content-Type': 'application/json',
                                                  'x-goog-api-key': api_key})
            try:
                with urllib.request.urlopen(req, timeout=15,
                                            context=ssl.create_default_context()) as r:
                    data = json.loads(r.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                last = 'HTTP %d' % e.code
                if e.code == 429:
                    # limit za minutu → 1 min pauza; opakovaně → nejspíš denní limit → 30 min
                    now = time.time()
                    pause = 1800 if now - self.last_429 < 300 else 60
                    self.last_429 = now
                    self.cooldown_until = now + pause
                    raise RuntimeError('TTS rate limit, iOS voice for %d min' % (pause // 60))
                if e.code in (401, 403):
                    raise RuntimeError('TTS key rejected (%d)' % e.code)
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = str(e)
                continue
            try:
                part = data['candidates'][0]['content']['parts'][0]['inlineData']
            except (KeyError, IndexError):
                last = 'no audio'
                continue
            raw = base64.b64decode(part['data'])
            if raw[:4] == b'RIFF':
                return raw
            rate = 24000
            for kv in part.get('mimeType', '').split(';'):
                if kv.strip().startswith('rate='):
                    rate = int(kv.strip()[5:])
            return pcm_to_wav(raw, rate)
        raise RuntimeError(last or 'TTS failed')
