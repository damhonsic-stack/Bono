"""Bono hlas na Macu: mikrofon → Whisper (lokálně) → Bono → český neural hlas.

Mikrofon poslouchá pořád, ale reaguje JEN po slově „Bono“ (wake word):
  - „Bono, jak jsou na tom gumy?“  → rovnou odpoví
  - „Bono.“  → pípne a 8 s čeká na otázku
Ostatní řeč se přepíše lokálně a zahodí (nikam se neposílá).

Proaktivní hlášení (lap time, gapy, box…) Bono říká sám, neurgentní počká na rovinku.

Závislosti (jen pro tento modul, instaluje setup_mac.sh):
    mlx-whisper (Apple Silicon), sounddevice, numpy, edge-tts
Bez nich zbytek Bona funguje dál (hlas v prohlížeči).
"""
import asyncio
import os
import platform
import queue
import random
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unicodedata
import wave

SAMPLE_RATE = 16000
FRAME = 480                      # 30 ms
WHISPER_MODEL = 'mlx-community/whisper-large-v3-turbo'
VOICES = {'cs': 'cs-CZ-AntoninNeural', 'en': 'en-GB-RyanNeural'}
FALLBACK_SAY = {'cs': 'Zuzana', 'en': 'Daniel'}
PROMPTS = {
    'cs': ('Bono, box, boxuju, gap, undercut, overcut, pneumatiky, gumy, soft, medium, hard, '
           'intermediate, palivo, baterie, overtake, DRS, safety car, strategie, zastávka, lap, '
           'sektor, zatáčka, Norris, Verstappen, Leclerc, Hamilton, Piastri, Russell.'),
    'en': ('Bono, box, gap, undercut, overcut, tyres, soft, medium, hard, inters, fuel, battery, '
           'overtake, DRS, safety car, strategy, pit stop, lap, sector, turn, Norris, Verstappen.'),
}
ARM_SECONDS = 8.0


# ---------------------------------------------------------------- čistá logika (testovatelná)
def normalize(text):
    t = unicodedata.normalize('NFKD', text.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', t).strip()


def wake_regex(wake='bono'):
    w = normalize(wake)
    if w == 'bono':
        variants = r'b[ou]+n+[oaeiuy]{1,2}[a-z]{0,2}|buono|bueno|bone ?oh?|bo no|vono'
    else:
        variants = re.escape(w)
    return re.compile(r'\b(?:hej |hey |ok |hele )?(?:%s)\b[\s,.!?:-]*' % variants)


class WakeLogic:
    """Rozhodne, co s přepsanou větou: ignorovat / čekat na otázku / odpovědět."""
    FILLER = {'', 'ok', 'okay', 'jo', 'jasne', 'diky', 'dik', 'ne', 'ano', 'yeah', 'thanks', 'hm',
              'hmm', 'aha', 'copy'}

    def __init__(self, wake='bono', clock=time.time):
        self.re = wake_regex(wake)
        self.armed_until = 0.0
        self.clock = clock

    def handle(self, text):
        """Vrátí ('ignore'|'arm'|'ask', otázka)."""
        n = normalize(text)
        now = self.clock()
        m = self.re.search(n)
        if m:
            rest = n[m.end():].strip(' .,!?')
            if len(rest) < 3 or rest in self.FILLER:
                self.armed_until = now + ARM_SECONDS
                return 'arm', ''
            self.armed_until = 0.0
            # otázka v původním znění (s diakritikou) za wake wordem
            words = text.split()
            skip = len(n[:m.end()].split())
            return 'ask', ' '.join(words[skip:]).strip(' ,.!?:-') or rest
        if now < self.armed_until:
            q = text.strip(' ,.!?')
            if normalize(q) in self.FILLER:
                return 'ignore', ''
            self.armed_until = 0.0
            return 'ask', q
        return 'ignore', ''


class Segmenter:
    """Jednoduchá detekce řeči podle energie s adaptivní hladinou šumu."""

    def __init__(self, start_frames=3, end_frames=25, preroll=10, min_len=0.35, max_len=15.0):
        self.floor = 0.003
        self.start_frames, self.end_frames, self.preroll = start_frames, end_frames, preroll
        self.min_len, self.max_len = min_len, max_len
        self.buf = []
        self.pre = []
        self.loud = 0
        self.quiet = 0
        self.active = False

    def feed(self, frame):
        """frame: numpy float32 [-1, 1]. Vrátí hotový segment (numpy) nebo None."""
        import numpy as np
        rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
        thr = max(self.floor * 3.0, 0.006)
        if not self.active:
            self.pre.append(frame)
            self.pre = self.pre[-self.preroll:]
            if rms > thr:
                self.loud += 1
                if self.loud >= self.start_frames:
                    self.active = True
                    self.buf = list(self.pre)
                    self.quiet = 0
            else:
                self.loud = 0
                self.floor = 0.95 * self.floor + 0.05 * rms
            return None
        self.buf.append(frame)
        self.quiet = self.quiet + 1 if rms < thr else 0
        dur = len(self.buf) * len(frame) / SAMPLE_RATE
        if self.quiet >= self.end_frames or dur >= self.max_len:
            seg = np.concatenate(self.buf)
            self.active = False
            self.buf, self.pre, self.loud = [], [], 0
            speech = dur - self.quiet * len(frame) / SAMPLE_RATE
            return seg if speech >= self.min_len else None
        return None


def make_click(path, ms=70):
    """Krátký šum týmového rádia (squelch)."""
    n = int(22050 * ms / 1000)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        frames = b''.join(struct.pack('<h', int(random.uniform(-1, 1) * 2500 * (1 - i / n)))
                          for i in range(n))
        w.writeframes(frames)


# ---------------------------------------------------------------- Mac runtime
class MacVoice:
    def __init__(self, engine, mic=None, model=WHISPER_MODEL, log=print):
        self.engine = engine
        self.mic = mic
        self.model = model
        self.log = log
        self.playing = False
        self.play_end = 0.0
        self.tmp = tempfile.mkdtemp(prefix='bono_voice_')
        self.click = os.path.join(self.tmp, 'click.wav')
        make_click(self.click)
        self.audio_q = queue.Queue()
        self.text_q = queue.Queue()
        self.loop = asyncio.new_event_loop()
        self.last_msg_id = None
        self.wake = WakeLogic(engine.settings.get('wake_word', 'bono'))
        self.status = 'starting'

    # ------------------------------------------------------------ start
    @staticmethod
    def check():
        """Vrátí seznam chybějících věcí (prázdný = vše OK)."""
        missing = []
        for mod in ('numpy', 'sounddevice', 'edge_tts', 'mlx_whisper'):
            try:
                __import__(mod)
            except Exception:  # noqa: BLE001
                missing.append(mod)
        if platform.system() != 'Darwin':
            missing.append('macOS')
        return missing

    def start(self):
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        threading.Thread(target=self._speaker, daemon=True).start()
        threading.Thread(target=self._transcriber, daemon=True).start()
        threading.Thread(target=self._listener, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _heartbeat(self):
        while True:
            with self.engine.lock:
                self.engine.heartbeat('mac-voice', self.status == 'listening', 'Mac')
                self.engine.voice_status = self.status
            time.sleep(4)

    # ------------------------------------------------------------ poslech
    def _listener(self):
        import numpy as np
        import sounddevice as sd
        seg = Segmenter()

        def cb(indata, frames, t, status):
            self.audio_q.put(indata[:, 0].copy())
        while True:
            try:
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32',
                                    blocksize=FRAME, device=self.mic, callback=cb):
                    self.status = 'listening'
                    self.log('🎙️  Bono poslouchá (mikrofon: %s). Řekni „Bono, …“' %
                             (self.mic or sd.query_devices(kind='input')['name']))
                    while True:
                        frame = self.audio_q.get()
                        # během mluvení Bona a chvíli po něm neposlouchej (ozvěna z reproduktoru)
                        if self.playing or time.time() - self.play_end < 0.4:
                            seg = Segmenter()
                            continue
                        out = seg.feed(frame.astype(np.float32))
                        if out is not None:
                            self.text_q.put(out)
            except Exception as e:  # noqa: BLE001 – mikrofon odpojen (AirPods) → zkus znovu
                self.status = 'mic error'
                self.log('Mikrofon nedostupný (%s), zkouším znovu za 3 s…' % e)
                time.sleep(3)

    def _transcriber(self):
        import numpy as np
        import mlx_whisper
        self.log('⏳ Načítám Whisper (%s), poprvé se stahuje ~1,6 GB…' % self.model)
        mlx_whisper.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), path_or_hf_repo=self.model)
        self.log('✅ Whisper připraven.')
        while True:
            audio = self.text_q.get()
            lang = self.engine.lang
            try:
                t0 = time.time()
                r = mlx_whisper.transcribe(
                    audio, path_or_hf_repo=self.model, language=lang,
                    initial_prompt=PROMPTS.get(lang, PROMPTS['en']), temperature=0.0,
                    condition_on_previous_text=False)
                text = (r.get('text') or '').strip()
            except Exception as e:  # noqa: BLE001
                self.log('Whisper chyba: %s' % e)
                continue
            if not text:
                continue
            action, q = self.wake.handle(text)
            with self.engine.lock:
                self.engine.heard = {'text': text, 'action': action, 'ts': time.time(),
                                     'ms': round((time.time() - t0) * 1000)}
            if action == 'arm':
                self._beep()
            elif action == 'ask':
                threading.Thread(target=self._answer, args=(q,), daemon=True).start()

    def _answer(self, q):
        from . import llm
        text, src = llm.answer(self.engine, q)
        with self.engine.lock:
            self.engine.say(text, prio=3 if src == 'command' else 2)

    # ------------------------------------------------------------ mluvení
    def _beep(self):
        subprocess.Popen(['afplay', '-v', '0.6', '/System/Library/Sounds/Tink.aiff'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def _edge(self, text, voice, path):
        import edge_tts
        await edge_tts.Communicate(text, voice, rate='+8%').save(path)

    def _synth(self, text, lang):
        voice = self.engine.settings.get('mac_voice_%s' % lang) or VOICES.get(lang, VOICES['en'])
        path = os.path.join(self.tmp, 'm%d.mp3' % random.randint(0, 1 << 30))
        fut = asyncio.run_coroutine_threadsafe(self._edge(text, voice, path), self.loop)
        return fut, path

    def _play(self, path=None, text=None, lang='cs'):
        self.playing = True
        try:
            subprocess.run(['afplay', '-v', '0.5', self.click], check=False)
            if path:
                subprocess.run(['afplay', path], check=False)
            elif text:   # záloha: offline hlas macOS
                subprocess.run(['say', '-v', FALLBACK_SAY.get(lang, 'Daniel'), text], check=False)
            subprocess.run(['afplay', '-v', '0.4', self.click], check=False)
        finally:
            self.playing = False
            self.play_end = time.time()

    def _speaker(self):
        pending = []     # [(msg, future, path)]
        while True:
            with self.engine.lock:
                msgs = list(self.engine.messages)
                voice_on = self.engine.settings.get('voice', True)
                lang = self.engine.lang
            if self.last_msg_id is None:
                self.last_msg_id = msgs[-1]['id'] if msgs else 0
            for m in msgs:
                if m['id'] > self.last_msg_id:
                    self.last_msg_id = m['id']
                    if voice_on or m.get('prio') == 3:
                        fut, path = self._synth(m['text'], lang)
                        item = (m, fut, path)
                        if m.get('urgent'):
                            pending.insert(0, item)
                        else:
                            pending.append(item)
            if not pending:
                time.sleep(0.12)
                continue
            m, fut, path = pending[0]
            urgent = m.get('urgent') or m.get('prio', 1) >= 2
            age = time.time() - m['ts']
            if not urgent and age > 30:
                pending.pop(0)
                continue
            # neurgentní hlášení počká na rovinku (max 8 s), odpovědi a urgentní věci hned
            if not urgent and age < 8 and not self.engine.can_talk():
                time.sleep(0.1)
                continue
            pending.pop(0)
            try:
                fut.result(timeout=6)
                ok = os.path.exists(path) and os.path.getsize(path) > 0
            except Exception:  # noqa: BLE001 – bez internetu / Edge nedostupné
                ok = False
            self._play(path if ok else None, None if ok else m['text'], lang)
            try:
                os.remove(path)
            except OSError:
                pass


def list_mics():
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] > 0:
            print('%2d  %s' % (i, d['name']))


def have_afplay():
    return shutil.which('afplay') is not None
