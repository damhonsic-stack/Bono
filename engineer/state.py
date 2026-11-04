"""Mozek inženýra: zpracuje pakety, udržuje stav session a generuje hlášení."""
import threading
import time

from . import packets as P
from .constants import (TRACKS, SESSION_TYPES, PRACTICE, QUALI, RACE, TIME_TRIAL,
                        WEATHER)
from .laps import CarLapRecorder, LapTrace
from .corners import detect_corners, compare_lap, theoretical_best
from .targets import Targets, split_sectors
from .race import RaceTracker
from . import radio as R
from .regs import Regs26
from .incidents import Incidents
from .opponents import Opponents
from .strategy import Strategy, tyre_name
from .quali import Quali, track_gaps
from .setup import SetupAnalyzer
from .tts import GeminiTTS
from .constants import VISUAL_COMPOUND
from .speech import to_speech

REF_NAMES = {
    'cs': {'session_best': 'Session best', 'pb': 'Personal best',
           'ai_best': 'Fastest AI', 'tt_rival': 'Time Trial rival', 'tt_pb': 'Time Trial ghost (PB)',
           None: 'žádná'},
    'en': {'session_best': 'Session best', 'pb': 'Personal best',
           'ai_best': 'Fastest AI', 'tt_rival': 'Time Trial rival', 'tt_pb': 'Time Trial ghost (PB)',
           None: 'none'},
}


# Tiché rádio (výchozí): jen to, co by řekl skutečný inženýr v závodě. Na zbytek se zeptáš.
RADIO_QUIET = {
    'pb', 'provisional', 'box_this_lap', 'box_next_lap', 'sc_box', 'vsc_box', 'pit_window',
    'opp_pitted_ahead', 'opp_pitted_behind', 'opp_behind_fresh', 'undercut_on',
    'rain_coming', 'rain_now_slicks', 'drying', 'track_limits_many', 'penalty_time', 'penalty_dt',
    'penalty_sg', 'penalty_other', 'blue_flag', 'yellow_ahead', 'sc_deployed', 'vsc_deployed',
    'sc_in', 'green', 'red_flag', 'contact', 'damage', 'damage_box_wing', 'puncture', 'fault',
    'push_now', 'traffic_close', 'car_behind_push', 'time_left', 'regs_ot_behind',
    'regs_ot_enabled', 'regs_ot_disabled', 'regs_partial_on', 'regs_partial_off',
    'regs_battery_low', 'fuel_low', 'tyre_wear_high', 'gap_closing_close', 'gap_behind_close',
}
RADIO_NORMAL = {
    'lap', 'invalid', 'corner', 'gap_closing', 'gap_losing', 'gap_behind_closing', 'gap_behind_dropping',
    'track_limits', 'warning', 'plan', 'regs_ot_available', 'regs_straight_low', 'out_lap',
    'tyre_temps', 'clear_air', 'tyre_wear', 'target',
}


class RefLap:
    def __init__(self, kind, lap_ms, sectors, trace, label=''):
        self.kind = kind
        self.lap_ms = lap_ms
        self.sectors = sectors
        self.trace = trace
        self.label = label


class Engine:
    def __init__(self, storage):
        self.storage = storage
        self.settings = storage.load_settings()
        self.targets = Targets(storage.load_calibration())
        self.lock = threading.RLock()
        self.messages = []
        self.msg_id = 0
        self.packet_count = 0
        self.packet_rate = 0.0
        self._rate_t = time.time()
        self._rate_n = 0
        self.last_packet_at = 0
        self.format_warning = None
        self.track_version = 0
        self.listen_seq = 0          # požadavek na poslech (tlačítko na ovladači)
        self.last_llm_model = None
        self.last_llm_error = None
        self.prev_buttons = 0
        self.tts = GeminiTTS()
        self.presence = {}           # id zařízení -> (čas, má mikrofon) – kde běží „Start Bono“
        self.heard = None            # poslední přepis z mikrofonu Macu
        self.voice_status = None
        self.chat_history = []       # [(otázka, odpověď)] – paměť konverzace pro Gemini
        self.session_time = 0.0
        self._new_session(None)

    # ------------------------------------------------------------------ session
    def _new_session(self, uid):
        self.session_uid = uid
        self.session = {}
        self.player = 0
        self.lap = [None] * P.NUM_CARS
        self.tel = [None] * P.NUM_CARS
        self.status = [None] * P.NUM_CARS
        self.damage = [None] * P.NUM_CARS
        self.motion = [None] * P.NUM_CARS
        self.participants = None
        self.recorders = [CarLapRecorder(i) for i in range(P.NUM_CARS)]
        self.tt_rival_idx = 255
        self.tt_pb_idx = 255
        self.tt_info = None
        self.player_laps = []        # CompletedLap
        self.session_best = None     # CompletedLap s trace
        self.ai_best = None          # CompletedLap s trace
        self.ai_best_any_ms = None   # nejlepší čas AI (i bez trace)
        self.tt_rival = None
        self.tt_pb = None
        self.track_id = None
        self.track_data = {}
        self.corners = []
        self.last_compare = None
        self.last_compare_lap = None
        self.corner_hist = {}        # corner id -> list of losses
        self.race = RaceTracker()
        self.prev_sector = None
        self.announced_session = False
        self.calibrated = False
        self.regs = Regs26()
        self.packet_format = None
        self.incidents = Incidents()
        self.opponents = Opponents()
        self.strategy = Strategy()
        self.quali = Quali()
        self.setup = SetupAnalyzer()
        self.tyre_sets = None
        self.strategy_plan = None
        self.neutralized = False      # SC/VSC během aktuálního lapu
        self.session_started = time.time()
        self.debrief_done = False
        self.lap_driver_status = {}   # lap_num -> driver status během lapu (out/in/flying)

    def _load_track(self, track_id):
        self.track_id = track_id
        self.track_data = self.storage.load_track(track_id) or {}
        self.corners = self.track_data.get('corners', [])
        for c in self.corners:
            c['name'] = 'T%d' % c['id']
        self.track_version += 1

    def _pb_key(self):
        return 'pb_tt' if self.session.get('session_type') == TIME_TRIAL else 'pb'

    def _stored_pb(self):
        pb = self.track_data.get(self._pb_key())
        if pb and pb.get('trace'):
            if 'trace_obj' not in pb:
                pb['trace_obj'] = LapTrace.from_dict(pb['trace'])
            return pb
        return None

    # ------------------------------------------------------------------ helpers
    @property
    def lang(self):
        return self.settings.get('lang', 'en')

    @property
    def level(self):
        return int(self.settings.get('level', 2))

    def difficulty(self):
        o = self.settings.get('difficulty_override')
        if o not in (None, ''):
            return int(o)
        return self.session.get('ai_difficulty')

    def say(self, text, prio=1, urgent=False):
        self.msg_id += 1
        speech = to_speech(text, self.lang)
        self.messages.append({'id': self.msg_id, 'text': text, 'speech': speech, 'prio': prio,
                              'urgent': bool(urgent), 'ts': time.time()})
        self.messages = self.messages[-40:]
        eng = self.settings.get('voice_engine', 'mixed')
        key = self.settings.get('gemini_key')
        # mixed: realistický hlas jen pro odpovědi na otázky (prio >= 2); gemini: vše neurgentní
        if key and not urgent and (eng == 'gemini' or (eng == 'mixed' and prio >= 2)):
            self.tts.prefetch(key, speech, self.settings.get('tts_voice', 'Charon'), self.lang)

    def names(self):
        out = {}
        if self.participants:
            for i, p in enumerate(self.participants):
                out[i] = p['name'] or 'Car %d' % (i + 1)
        out[self.player] = 'You'
        return out

    def reference(self):
        """Vybere referenční kolo podle nastavení."""
        pref = self.settings.get('reference', 'auto')
        pb = self._stored_pb()
        options = {}
        if self.session_best:
            options['session_best'] = RefLap('session_best', self.session_best.lap_ms,
                                             self.session_best.sectors, self.session_best.trace)
        if pb:
            options['pb'] = RefLap('pb', pb['lap_ms'], pb.get('sectors'), pb['trace_obj'])
        if self.ai_best:
            options['ai_best'] = RefLap('ai_best', self.ai_best.lap_ms, self.ai_best.sectors,
                                        self.ai_best.trace, self.ai_best.meta.get('name', ''))
        if self.tt_rival:
            options['tt_rival'] = RefLap('tt_rival', self.tt_rival.lap_ms,
                                         self.tt_rival.sectors, self.tt_rival.trace)
        if self.tt_pb:
            options['tt_pb'] = RefLap('tt_pb', self.tt_pb.lap_ms, self.tt_pb.sectors,
                                      self.tt_pb.trace)
        if pref in options:
            return options[pref], options
        order = ['pb', 'session_best', 'tt_rival', 'tt_pb', 'ai_best']
        if self.session.get('session_type') == TIME_TRIAL:
            order = ['tt_rival', 'pb', 'tt_pb', 'session_best']
        for k in order:
            if k in options:
                return options[k], options
        return None, options

    # ------------------------------------------------------------------ packets
    def handle(self, data):
        parsed = P.parse_packet(data)
        if not parsed:
            return
        hdr, pid, payload = parsed
        with self.lock:
            self.packet_count += 1
            self._rate_n += 1
            now = time.time()
            self.last_packet_at = now
            if now - self._rate_t >= 1.0:
                self.packet_rate = self._rate_n / (now - self._rate_t)
                self._rate_t, self._rate_n = now, 0
            if hdr['format'] not in P.LAYOUTS:
                self.format_warning = (
                    'Hra posílá UDP formát %d. Nastav ve hře UDP Format = 2026 '
                    '(se Season Passem) nebo 2025.' % hdr['format'])
                return
            self.format_warning = None
            self.packet_format = hdr['format']
            if payload is None:
                return
            uid = hdr['session_uid']
            if uid != self.session_uid and uid != 0:
                if pid in (P.SESSION, P.LAP_DATA):
                    self._end_session()
                    self._new_session(uid)
                elif pid == P.EVENT and payload.get('code') == 'BUTN':
                    self._on_buttons(payload['buttons'])
                    return
                else:
                    return  # paket z jiné session (např. zpoždění) – ignoruj
            self.player = hdr['player'] if hdr['player'] < P.NUM_CARS else 0
            self.session_time = hdr['session_time']
            if pid == P.LAP_DATA:
                self._on_lap_data(payload)
                self._after_lap_data()
            elif pid == P.CAR_TELEMETRY:
                self.tel = payload['cars']
            elif pid == P.CAR_TELEMETRY_2:
                self._on_telemetry2(payload['cars'])
            elif pid == P.MOTION:
                self.motion = payload['cars']
            elif pid == P.CAR_STATUS:
                self.status = payload['cars']
                if self.player < len(self.status):
                    self.incidents.on_status(self.status[self.player], self.session_time)
                    self._flush_module(self.incidents)
            elif pid == P.CAR_DAMAGE:
                self.damage = payload['cars']
                if self.player < len(self.damage):
                    self.incidents.on_damage(self.damage[self.player], self._is_race(),
                                             self._laps_left())
                    self._flush_module(self.incidents)
            elif pid == P.CAR_SETUPS:
                if self.player < len(payload['cars']):
                    self.setup.on_setup(payload['cars'][self.player])
            elif pid == P.TYRE_SETS:
                if payload['car'] == self.player:
                    self.tyre_sets = payload
            elif pid == P.MOTION_EX:
                me = self.lap[self.player] if self.player < len(self.lap) else None
                self.setup.on_sample(payload, self.tel[self.player], me)
            elif pid == P.SESSION:
                self._on_session(payload)
                self._after_session()
            elif pid == P.PARTICIPANTS:
                self.participants = payload['cars']
            elif pid == P.TIME_TRIAL:
                self.tt_info = payload
            elif pid == P.EVENT:
                self._on_event(payload)
            elif pid == P.SESSION_HISTORY:
                self._on_history(payload)

    def _on_session(self, s):
        first = not self.session
        self.session = s
        if s['track_id'] != self.track_id and s['track_id'] >= 0:
            self._load_track(s['track_id'])
        if first and not self.announced_session:
            self.announced_session = True
            self.say(R.say(self.lang, 'session_start', name=self.settings.get('engineer_name', 'Bono'),
                           track=TRACKS.get(s['track_id'], 'Track %d' % s['track_id']),
                           session=SESSION_TYPES.get(s['session_type'], '?'),
                           ai=self.difficulty()), prio=0)

    def _on_event(self, ev):
        code = ev['code']
        if code == 'SEND':
            self._end_session()
        elif code == 'BUTN':
            self._on_buttons(ev['buttons'])
        else:
            self.regs.on_event(code)
            self._flush_regs_events()
            self.incidents.on_event(ev, self.player)
            self._flush_module(self.incidents)

    def _on_buttons(self, status):
        pressed = status & ~self.prev_buttons
        self.prev_buttons = status
        mapping = self.settings.get('buttons') or {}
        for n, bit in P.UDP_ACTION_BITS.items():
            if pressed & bit:
                action = mapping.get(str(n))
                if action:
                    self.button_action(action)

    def button_action(self, action):
        """Akce z tlačítka na ovladači (UDP Action) nebo hlasového příkazu."""
        from . import llm
        if action == 'listen':
            self.listen_seq += 1
            return
        text = llm.run_command(self, action)
        if text:
            cmd = action in ('mute', 'unmute', 'radio_check', 'repeat')
            self.say(text, prio=3 if cmd else 2)

    def _on_telemetry2(self, cars):
        me = self.lap[self.player] if self.player < len(self.lap) else None
        self.regs.on_telemetry2(cars, self.player, me)
        idx, gap = self._car_behind()
        self.regs.check_car_behind(idx, gap)
        self._flush_regs_events()

    def _flush_regs_events(self):
        st = self.session.get('session_type')
        for key, data in self.regs.pop_events():
            if key in ('ot_available', 'ot_missed', 'ot_behind') and st not in RACE:
                continue
            if key == 'ot_missed' and self.level < 2:
                continue
            kw = {}
            if key == 'ot_behind':
                kw['g'] = R.fmt_delta(data['gap'], self.lang)
            if key == 'ot_available':
                me = self.lap[self.player]
                kw['g'] = R.fmt_delta(me['delta_front_ms'], self.lang) if me else '?'
            if self.radio_ok('regs_' + key):
                self.say(R.say(self.lang, 'regs_' + key, **kw), prio=1)

    def _on_history(self, h):
        car = h['car']
        if car == self.player or not self.participants or car >= len(self.participants):
            return
        if not self.participants[car]['ai']:
            return
        if h['best_lap'] and h['best_lap'] <= len(h['laps']):
            lap = h['laps'][h['best_lap'] - 1]
            if lap['lap_ms'] and lap['valid_flags'] & 1:
                if self.ai_best_any_ms is None or lap['lap_ms'] < self.ai_best_any_ms:
                    self.ai_best_any_ms = lap['lap_ms']

    def _end_session(self):
        """Konec session: debrief (na pozadí), uložení pit loss, kalibrace cílů podle AI."""
        if not self.debrief_done and len(self.player_laps) >= 3:
            self.debrief_done = True
            self.start_debrief(announce=True)
        if self.opponents.pit_losses and self.track_id is not None:
            self.track_data['pit_loss_ms'] = round(self.opponents.pit_loss())
            self._save_track()
        s = self.session
        if self.calibrated or not s or self.ai_best_any_ms is None:
            return
        st = s.get('session_type')
        if (st in PRACTICE or st in QUALI) and s.get('weather', 0) < 3 and \
                s.get('ai_difficulty') is not None:
            if self.targets.calibrate(s['track_id'], s['ai_difficulty'], self.ai_best_any_ms):
                self.storage.save_calibration(self.targets.cal)
                self.calibrated = True

    def _on_lap_data(self, payload):
        cars = payload['cars']
        self.tt_pb_idx = payload['tt_pb_idx']
        self.tt_rival_idx = payload['tt_rival_idx']
        tl = self.session.get('track_length', 0)
        prev_player = self.lap[self.player]
        self.lap = cars
        if self.player < len(cars) and cars[self.player]:
            mp = cars[self.player]
            if mp['driver_status'] in (1, 2, 3):
                self.lap_driver_status.setdefault(mp['lap_num'], mp['driver_status'])
                if mp['driver_status'] == 1:
                    self.lap_driver_status[mp['lap_num']] = 1
        for i, lap in enumerate(cars):
            if lap['result_status'] < 2 and i != self.player and \
                    i not in (self.tt_pb_idx, self.tt_rival_idx):
                continue
            done = self.recorders[i].update(lap, self.tel[i], self.motion[i], tl)
            if done:
                self._on_lap_complete(i, done)
        me = cars[self.player]
        if prev_player and self.level >= 3:
            self._sector_message(prev_player, me)

    def _sector_message(self, prev, cur):
        if cur['sector'] == prev['sector'] or cur['lap_num'] != prev['lap_num']:
            return
        ref, _ = self.reference()
        if not ref or not ref.sectors or not all(ref.sectors):
            return
        if cur['sector'] == 1 and cur['s1_ms']:
            d = cur['s1_ms'] - ref.sectors[0]
            self.say(R.say(self.lang, 'sector', n=1, d=R.fmt_delta(d, self.lang, True)), 0)
        elif cur['sector'] == 2 and cur['s2_ms']:
            d = cur['s2_ms'] - ref.sectors[1]
            self.say(R.say(self.lang, 'sector', n=2, d=R.fmt_delta(d, self.lang, True)), 0)

    # ------------------------------------------------------------------ laps
    def _on_lap_complete(self, car, lap):
        if car == self.player:
            self._on_player_lap(lap)
            return
        if car == self.tt_rival_idx and lap.trace:
            if not self.tt_rival or lap.lap_ms < self.tt_rival.lap_ms:
                self.tt_rival = lap
                self._ensure_corners(lap.trace)
            return
        if car == self.tt_pb_idx and lap.trace:
            if not self.tt_pb or lap.lap_ms < self.tt_pb.lap_ms:
                self.tt_pb = lap
            return
        is_ai = self.participants and car < len(self.participants) and \
            self.participants[car]['ai']
        if is_ai and lap.valid and lap.clean:
            if self.ai_best_any_ms is None or lap.lap_ms < self.ai_best_any_ms:
                self.ai_best_any_ms = lap.lap_ms
            if not self.ai_best or lap.lap_ms < self.ai_best.lap_ms:
                lap.meta['name'] = self.participants[car]['name']
                self.ai_best = lap

    def _ensure_corners(self, trace):
        if self.corners or not trace:
            return
        corners = detect_corners(trace)
        if corners:
            self.corners = corners
            self.track_data['corners'] = corners
            # obrys trati pro mapu
            step = 4
            self.track_data['outline'] = {
                'x': [round(v, 1) for v in trace.cols['x'][::step]],
                'z': [round(v, 1) for v in trace.cols['z'][::step]],
                'dist': trace.dist[::step],
            }
            self._save_track()
            self.track_version += 1

    def _save_track(self):
        if self.track_id is None:
            return
        data = {}
        for k, v in self.track_data.items():
            if isinstance(v, dict) and 'trace_obj' in v:
                v = {kk: vv for kk, vv in v.items() if kk != 'trace_obj'}
            data[k] = v
        self.storage.save_track(self.track_id, data)

    def _on_player_lap(self, lap):
        lang, level = self.lang, self.level
        cfg = R.LEVELS[level]
        st = self.session.get('session_type')
        status = self.status[self.player]
        dmg = self.damage[self.player]
        if status:
            lap.meta['compound'] = status['visual_compound']
            lap.meta['tyre_age'] = status['tyre_age']
        lap_kind = self.lap_driver_status.get(lap.lap_num)
        prep_lap = st not in RACE and lap_kind in (2, 3)   # out lap / in lap
        lap.meta['kind'] = {1: 'flying', 2: 'in', 3: 'out'}.get(lap_kind)
        regs_stats = self.regs.on_lap_complete(lap.lap_num, status)
        lap.meta.update(regs_stats)
        ref_before, _ = self.reference()
        msgs = []
        pb = self._stored_pb()
        is_pb = False
        if lap.valid and lap.clean and not prep_lap:
            self._ensure_corners(lap.trace)
            if not self.session_best or lap.lap_ms < self.session_best.lap_ms:
                self.session_best = lap
            if not pb or lap.lap_ms < pb['lap_ms']:
                is_pb = bool(pb)
                self.track_data[self._pb_key()] = {
                    'lap_ms': lap.lap_ms, 'sectors': lap.sectors,
                    'trace': lap.trace.to_dict(), 'trace_obj': lap.trace,
                    'date': time.strftime('%Y-%m-%d'), 'session_type': st,
                    'difficulty': self.difficulty(),
                }
                self._save_track()
        # srovnání po zatáčkách
        compare = None
        if lap.trace and ref_before and ref_before.trace and self.corners:
            compare = compare_lap(lap.trace, ref_before.trace, self.corners)
            lap.meta['delta'] = lap.lap_ms - ref_before.lap_ms
            lap.meta['ref'] = ref_before.kind
            if lap.valid and not prep_lap:
                for c in compare:
                    self.corner_hist.setdefault(c['id'], []).append(c['loss'])
            if not prep_lap:
                self.last_compare = compare
                self.last_compare_lap = lap
        self.player_laps.append(lap)
        # race tracker
        me = self.lap[self.player]
        gap_behind = self._gap_behind()
        self.race.on_new_lap(lap.lap_num + 1, status, dmg,
                             me['delta_front_ms'] if me and me['position'] > 1 else None,
                             gap_behind, lap.lap_ms)
        # historie
        self.storage.append_history({
            'ts': int(time.time()), 'track': self.track_id, 'session': st,
            'lap_ms': lap.lap_ms, 'sectors': lap.sectors, 'valid': lap.valid,
            'compound': lap.meta.get('compound'), 'ai': self.difficulty(),
        })
        # ---- hlášení
        race_lap1 = st in RACE and lap.lap_num <= 1   # stojící start – analýza nedává smysl
        if prep_lap:
            # out lap / in lap v kvalifikaci a tréninku: čas ani zatáčky nehlásíme
            return
        if not lap.valid:
            msgs.append(('invalid', R.say(lang, 'invalid')))
        if is_pb:
            msgs.append(('pb', R.say(lang, 'pb', time=R.fmt_lap(lap.lap_ms))))
        else:
            m = R.say(lang, 'lap', time=R.fmt_lap(lap.lap_ms))
            if ref_before and lap.valid and 'delta' in lap.meta and not race_lap1:
                d = lap.meta['delta']
                if abs(d) >= 5:
                    m += ' ' + R.say(lang, 'lap_delta_slow' if d > 0 else 'lap_delta_fast',
                                     d=R.fmt_delta(d, lang))
            msgs.append(('lap', m))
        if compare and lap.valid and not race_lap1:
            worst = sorted(compare, key=lambda c: -c['loss'])
            n = 0
            max_c = cfg['corners'] if self.radio_mode() == 'full' else 1
            for c in worst:
                if c['loss'] < cfg['corner_min_loss'] or n >= max_c:
                    break
                msgs.append(('corner', R.corner_message(lang, c, level)))
                n += 1
        if lap.valid and (st in QUALI) and lap_kind == 1:
            me_now = self.lap[self.player]
            if me_now and me_now['position']:
                msgs.append(('provisional', R.say(lang, 'provisional', pos=me_now['position'])))
        if lap.valid and st not in RACE:
            tgt = self.target()
            if tgt and tgt.get('lap_ms') and (is_pb or len(self.player_laps) % 3 == 1):
                d = lap.lap_ms - tgt['lap_ms']
                key = 'target_gap_slow' if d > 0 else 'target_gap_fast'
                msgs.append(('target', R.say(lang, key, ai=tgt['ai'], d=R.fmt_delta(d, lang))))
        if st in RACE:
            fuel_start = self.race.fuel_at_lap_start.get(lap.lap_num)
            self.strategy.on_player_lap(lap.lap_num, lap.lap_ms, lap.valid,
                                        lap.meta.get('pitted', False), fuel_start,
                                        status['visual_compound'] if status else None,
                                        status['tyre_age'] if status else None, self.neutralized)
            self.neutralized = False
            self._update_plan()
            me_now = self.lap[self.player]
            in_pits = lap.meta.get('pitted') or (me_now and me_now['pit_status'])
            if not in_pits:
                self._emit_all(self.strategy.lap_calls(lap.lap_num + 1, self.strategy_plan,
                                                       self.session), source='strategy')
            self.opponents.alerts(self.lap, self.player, self.names(), lap.lap_num)
            self._undercut_check(lap.lap_num + 1)
        sp = regs_stats.get('straight_pct')
        if sp is not None and sp < 90 and regs_stats.get('aero_avail_m', 0) > 300:
            msgs.append(('regs_straight_low', R.say(lang, 'regs_straight_low', p=sp)))
        if st in RACE:
            msgs.extend(self._race_messages(lap.lap_num))
        for key, m in msgs:
            if self.radio_ok(key):
                self.say(m)

    # ------------------------------------------------------------------ rádio: co se říká nahlas
    def radio_mode(self):
        return self.settings.get('radio_mode', 'quiet')

    def radio_ok(self, key):
        mode = self.radio_mode()
        if mode == 'full':
            return True
        if key in RADIO_QUIET:
            return True
        return mode == 'normal' and key in RADIO_NORMAL

    # ------------------------------------------------------------------ nové moduly
    def _is_race(self):
        return self.session.get('session_type') in RACE

    def _laps_left(self):
        me = self.lap[self.player] if self.player < len(self.lap) else None
        tl = self.session.get('total_laps')
        if not me or not tl:
            return None
        return tl - me['lap_num'] + 1

    def _current_tyres(self):
        st = self.status[self.player] if self.player < len(self.status) else None
        if not st:
            return None
        life = None
        if self.tyre_sets:
            fi = self.tyre_sets['fitted_idx']
            if 0 <= fi < len(self.tyre_sets['sets']):
                life = self.tyre_sets['sets'][fi]['life_left']
        if life is None:
            t = self._tyres() or {}
            life = t.get('laps_to_70')
        return {'compound': st['visual_compound'], 'age': st['tyre_age'],
                'life_left': int(life) if life is not None else None}

    def _pit_loss(self):
        return self.opponents.pit_loss(self.track_data.get('pit_loss_ms', 22000))

    def _update_plan(self):
        if not self._is_race():
            self.strategy_plan = None
            return None
        me = self.lap[self.player] if self.player < len(self.lap) else None
        cur = self._current_tyres()
        if not me or not cur:
            return None
        wet = self.session.get('weather', 0) >= 3 or cur['compound'] in (7, 8)
        tl = self.session.get('total_laps', 0)
        self.strategy_plan = self.strategy.plan(
            me['lap_num'], tl, cur, self.tyre_sets['sets'] if self.tyre_sets else None,
            self._pit_loss(), wet, must_two=tl >= 10)
        return self.strategy_plan

    def _undercut_check(self, current_lap):
        me = self.lap[self.player]
        if not me or me['position'] <= 1 or not self.strategy_plan:
            return
        for i, l in enumerate(self.lap):
            if l and l['position'] == me['position'] - 1 and l['result_status'] == 2:
                c = self.opponents.cars.get(i)
                mine = self._current_tyres()
                opts = self.strategy.options(self.tyre_sets['sets'] if self.tyre_sets else None,
                                             mine, False)
                ev = self.strategy.undercut_call(self.strategy_plan, me['delta_front_ms'], i,
                                                 c.age if c else None, mine['age'] if mine else None,
                                                 current_lap, opts)
                if ev:
                    self._emit_all([ev], source='strategy')

    def _after_session(self):
        s = self.session
        sc = self.incidents.on_safety_car(s.get('safety_car', 0))
        if s.get('safety_car') in (1, 2):
            self.neutralized = True
        if sc and self._is_race():
            plan = self._update_plan()
            t = self._tyres() or {}
            me = self.lap[self.player] if self.player < len(self.lap) else None
            ev = self.strategy.safety_car_call(sc, plan, me['lap_num'] if me else 0,
                                               t.get('max_wear'))
            self._flush_module(self.incidents)
            if ev:
                self._emit_all([ev], source='strategy')
        st = self.status[self.player] if self.player < len(self.status) else None
        if st:
            self._emit_all(self.strategy.weather_calls(s, st['visual_compound']), source='weather')
        self._flush_module(self.incidents)

    def _after_lap_data(self):
        me = self.lap[self.player] if self.player < len(self.lap) else None
        if not me:
            return
        self.opponents.update(self.lap, self.status, self.player)
        self.incidents.on_lap(me)
        self.incidents.on_position(me['lap_distance'], self.session)
        self._flush_module(self.incidents)
        for key, data in self.opponents.pop_events():
            self._opponent_event(key, data)
        st = self.session.get('session_type')
        if st in PRACTICE or st in QUALI or st == TIME_TRIAL:
            tel = self.tel[self.player]
            ers = self.status[self.player]
            ers_pct = round(100 * ers['ers_store'] / 4.0e6) if ers else None
            self.quali.update(me, self.lap, self.player, tel, self.regs.active, ers_pct,
                              self.session, tel['speed'] if tel else 0)
            self._emit_all(self.quali.pop_events(), source='quali')

    def _opponent_event(self, key, data):
        if not self._is_race():
            return
        me = self.lap[self.player]
        names = self.names()
        i = data['car']
        l = self.lap[i] if i < len(self.lap) else None
        if not me or not l:
            return
        name = names.get(i, '?')
        if key == 'pitted':
            gap = l['delta_leader_ms'] - me['delta_leader_ms']
            tyre = tyre_name(data['compound'])
            if l['position'] < me['position'] and -gap < self._pit_loss() + 3000:
                self._emit_all([('opp_pitted_ahead', {'name': name, 'tyre': tyre}, False)])
            elif l['position'] == me['position'] + 1 and gap < 4000:
                self._emit_all([('opp_pitted_behind', {'name': name, 'tyre': tyre}, False)])
        elif key == 'behind_fresh':
            self._emit_all([('opp_behind_fresh', {'name': name, 'tyre': tyre_name(data['compound']),
                                                  'x': data['x'], 'n': data['n']}, False)])
        elif key == 'ahead_old':
            self._emit_all([('opp_ahead_old', {'name': name, 'tyre': tyre_name(data['compound']),
                                               'x': data['x'], 'age': data['age']}, False)])

    def _flush_module(self, mod):
        self._emit_all(mod.pop_events(), source='incidents')

    def _fmt_s(self, secs):
        txt = '%.1f s' % secs if self.lang == 'cs' else '%.1f seconds' % secs
        return txt.replace('.', ',') if self.lang == 'cs' else txt

    def _emit_all(self, events, source=''):
        """Převede události modulů (key, kwargs, urgent) na hlášení rádia."""
        lang = self.lang
        rookie = self.level <= 1
        for key, kw, urgent in events:
            if rookie and key in ('plan', 'box_next_lap', 'opp_ahead_old', 'tyre_temps', 'deg'):
                continue
            rkey = key
            if key == 'damage' and kw.get('p', 0) < 25:
                rkey = 'damage_minor'
            if not self.radio_ok(rkey):
                continue
            kw = dict(kw)
            if key == 'plan':
                text = self._plan_text()
                if text:
                    self.say(text, prio=1)
                continue
            for k in ('x', 'g'):
                if k in kw and isinstance(kw[k], (int, float)):
                    kw[k] = R.fmt_delta(kw[k], lang)
            if 'car' in kw and 'name' not in kw:
                kw['name'] = self.names().get(kw['car'], '?')
            if key == 'puncture':
                kw['wheel'] = R.WHEEL_NAMES[lang][['RL', 'RR', 'FL', 'FR'][kw.pop('wheel_idx')]]
            if key == 'out_lap':
                kw['battery'] = R.say(lang, 'out_lap_battery') if kw.get('battery') else ''
            if key == 'tyre_temps':
                kw['hint'] = R.say(lang, kw['hint'])
                ers = kw.pop('ers', None)
                text = R.say(lang, key, **kw)
                if ers is not None:
                    text += ' ' + R.say(lang, 'battery_quali', p=ers)
                self.say(text, urgent=urgent)
                continue
            if key in ('traffic_close', 'clear_air', 'car_behind_push'):
                kw['g'] = self._fmt_s(kw.pop('s'))
            if key == 'push_now':
                s = kw.pop('ahead_s', None)
                text = R.say(lang, key)
                if s is not None and s < 3:
                    text += ' ' + R.say(lang, 'traffic_push', g=self._fmt_s(s))
                self.say(text, urgent=True)
                continue
            try:
                text = R.say(lang, key, **kw)
            except (KeyError, IndexError):
                continue
            if key == 'box_this_lap':
                text += ' ' + self._rejoin_text()
            self.say(text, prio=1, urgent=urgent)

    def _rejoin_text(self):
        rj = self.strategy.rejoin(self.lap, self.player, self._pit_loss(), self.names())
        if not rj:
            return ''
        lang = self.lang
        who = ''
        if rj.get('ahead') and rj['ahead']['gap'] < 3000:
            who = R.say(lang, 'rejoin_behind', g=R.fmt_delta(rj['ahead']['gap'], lang),
                        name=rj['ahead']['name'])
        elif rj.get('behind') and rj['behind']['gap'] < 3000:
            who = R.say(lang, 'rejoin_ahead', g=R.fmt_delta(rj['behind']['gap'], lang),
                        name=rj['behind']['name'])
        return R.say(lang, 'rejoin', pos=rj['pos'], who=who)

    def _plan_text(self):
        p = self.strategy_plan
        if not p:
            return None
        lang = self.lang
        if not p['stops']:
            return R.say(lang, 'plan_none')
        parts = [R.say(lang, 'plan_stop', lap=k, tyre=t) for k, t in zip(p['laps'], p['tyres'])]
        return R.say(lang, 'plan', stops=p['stops'], plan=', '.join(parts))

    def start_debrief(self, announce=True):
        """Souhrn se postaví hned (pod zámkem), Gemini text na pozadí."""
        from . import debrief as D
        try:
            with self.lock:
                summary = D.build_summary(self)
        except Exception as e:  # noqa: BLE001
            self.last_llm_error = 'debrief: %s' % e
            return False
        args = (summary, self.lang, self.settings.get('gemini_key'),
                self.settings.get('gemini_model'), self.settings.get('engineer_name', 'Bono'))

        def work():
            D.make_debrief(self, *args)
            if announce:
                with self.lock:
                    self.say(R.say(self.lang, 'debrief_ready'), prio=2)
        threading.Thread(target=work, daemon=True).start()
        return True

    def can_talk(self):
        """Je teď vhodná chvíle mluvit? (rovinka, ne brzdění / zatáčka) – jako skutečný inženýr."""
        with self.lock:
            me = self.lap[self.player] if self.player < len(self.lap) else None
            tel = self.tel[self.player] if self.player < len(self.tel) else None
            if not me or not tel or me['pit_status'] or me['driver_status'] == 0:
                return True
            if tel['brake'] > 0.05 or abs(tel['steer']) > 0.15:
                return False
            d = me['lap_distance']
            for c in self.corners:
                if c['apex'] - 220 <= d <= c['apex'] + 60:
                    return False
            return True

    def heartbeat(self, dev_id, mic, name=''):
        self.presence[str(dev_id)[:40]] = (time.time(), bool(mic), str(name)[:40])

    def voice_devices(self):
        now = time.time()
        live = [(k, v) for k, v in self.presence.items() if now - v[0] < 12]
        return {'count': len(live), 'mic': sum(1 for _, v in live if v[1]),
                'names': [v[2] for _, v in live]}

    def snapshot_theoretical(self):
        traces = [l.trace for l in self.player_laps if l.valid and l.clean]
        return theoretical_best(traces, self.corners)

    def strategy_snapshot(self):
        me = self.lap[self.player] if self.player < len(self.lap) else None
        names = self.names()
        out = {'plan': self.strategy_plan, 'pit_loss_ms': round(self._pit_loss()),
               'pit_loss_measured': len(self.opponents.pit_losses),
               'game_window': [self.session.get('pit_ideal_lap'), self.session.get('pit_latest_lap')],
               'stints': [{'tyre': tyre_name(st['compound']), 'start_lap': st['start_lap'],
                           'deg_ms': round(self.strategy.deg(st['compound'])[0]),
                           'deg_src': self.strategy.deg(st['compound'])[1],
                           'points': len(st['points'])} for st in self.strategy.stints]}
        if me and self._is_race():
            out['rejoin'] = self.strategy.rejoin(self.lap, self.player, self._pit_loss(), names)
        if self.tyre_sets:
            out['sets'] = [{'tyre': tyre_name(t['visual']), 'actual': t['actual'], 'wear': t['wear'],
                            'life_left': t['life_left'], 'delta': t['lap_delta'], 'fitted': bool(t['fitted'])}
                           for t in self.tyre_sets['sets'] if t['available'] or t['fitted']]
        return out

    def weather_snapshot(self):
        s = self.session
        return {'now': WEATHER.get(s.get('weather')), 'track_temp': s.get('track_temp'),
                'forecast': [{'min': f['offset_min'], 'weather': WEATHER.get(f['weather']),
                              'rain': f['rain_pct']} for f in (s.get('forecast') or [])[:8]]}

    def quali_snapshot(self):
        me = self.lap[self.player] if self.player < len(self.lap) else None
        if not me:
            return None
        L = self.session.get('track_length') or 0
        ahead, behind = track_gaps(self.lap, self.player, L)
        tel = self.tel[self.player]
        v = max(30.0, tel['speed'] if tel else 0) / 3.6
        status_names = {0: 'Garage', 1: 'Flying lap', 2: 'In lap', 3: 'Out lap', 4: 'On track'}
        return {'status': status_names.get(me['driver_status']),
                'ahead_s': round(ahead[1] / v, 1) if ahead else None,
                'behind_s': round(behind[1] / v, 1) if behind else None,
                'time_left': self.session.get('time_left')}

    def _car_behind(self):
        me = self.lap[self.player] if self.player < len(self.lap) else None
        if not me:
            return None, None
        for i, l in enumerate(self.lap):
            if l and l['position'] == me['position'] + 1 and l['result_status'] == 2:
                return i, l['delta_front_ms']
        return None, None

    def _gap_behind(self):
        return self._car_behind()[1]

    def _race_messages(self, lap_num):
        lang = self.lang
        out = []
        g = self.race.gaps(None, None)
        if lap_num % 2 == 0:
            ga = self.race.gap_ahead[-1] if self.race.gap_ahead else None
            ta = g.get('ahead_trend')
            if ta is not None and ga is not None and abs(ta) >= 100 and ga < 6000:
                key = 'gap_closing' if ta < 0 else 'gap_losing'
                m = R.say(lang, key, r=R.fmt_delta(ta, lang), g=R.fmt_delta(ga, lang))
                if ta < 0 and ga / -ta < 15:
                    m += ' ' + R.say(lang, 'catch_in', n=max(1, round(ga / -ta)))
                close = ta < 0 and ga / -ta <= 3
                out.append(('gap_closing_close' if close else key, m))
            gb = self.race.gap_behind[-1] if self.race.gap_behind else None
            tb = g.get('behind_trend')
            if tb is not None and gb is not None and abs(tb) >= 100 and gb < 6000:
                key = 'gap_behind_closing' if tb < 0 else 'gap_behind_dropping'
                out.append(('gap_behind_close' if tb < 0 and gb < 1500 else key,
                            R.say(lang, key, r=R.fmt_delta(tb, lang), g=R.fmt_delta(gb, lang))))
        fuel = self._fuel()
        if fuel and lap_num % 3 == 0:
            fd = fuel['game_delta_laps']
            if fd < 0:
                out.append(('fuel_low', R.say(lang, 'fuel_low', d=('%.1f' % fd).replace('.', ',')
                                              if lang == 'cs' else '%.1f' % fd)))
        status = self.status[self.player]
        if self.regs.active and status and lap_num % 4 == 0 and \
                status['ers_store'] < 0.15 * 4.0e6:
            out.append(('regs_battery_low', R.say(lang, 'regs_battery_low',
                                                  p=round(100 * status['ers_store'] / 4.0e6))))
        tyres = self._tyres()
        if tyres and tyres.get('max_wear', 0) >= 50 and lap_num % 3 == 0:
            w = tyres['wear']
            wheel = max(w, key=w.get)
            out.append(('tyre_wear_high' if tyres['max_wear'] >= 60 else 'tyre_wear',
                        R.say(lang, 'tyre_wear', w=round(tyres['max_wear']),
                              wheel=R.WHEEL_NAMES[lang][wheel])))
        return out

    def _fuel(self):
        me = self.lap[self.player]
        if not me:
            return None
        return self.race.fuel(self.status[self.player], me['lap_num'],
                              self.session.get('total_laps', 0), me['lap_distance'],
                              self.session.get('track_length', 0))

    def _tyres(self):
        return self.race.tyres(self.status[self.player], self.damage[self.player],
                               self.tel[self.player])

    # ------------------------------------------------------------------ outputs
    def target(self):
        if self.track_id is None:
            return None
        ai = self.difficulty()
        if ai is None:
            return None
        lap_ms, src = self.targets.target_lap(self.track_id, ai)
        if not lap_ms:
            return None
        ref, _ = self.reference()
        best = self.session_best.lap_ms if self.session_best else None
        pb = self._stored_pb()
        out = {'ai': ai, 'lap_ms': round(lap_ms), 'src': src,
               'sectors': split_sectors(lap_ms, ref.sectors if ref else None)}
        if best:
            out['gap_best'] = best - round(lap_ms)
        ref_time = best or (pb['lap_ms'] if pb else None)
        if ref_time:
            out['match_ai'] = self.targets.matching_difficulty(self.track_id, ref_time)
        if self.ai_best_any_ms:
            out['ai_session_best'] = self.ai_best_any_ms
        return out

    def corner_summary(self):
        out = []
        for c in self.corners:
            h = self.corner_hist.get(c['id'], [])[-5:]
            last = None
            if self.last_compare:
                for x in self.last_compare:
                    if x['id'] == c['id']:
                        last = x
            if last is not None:
                last = dict(last, tips_text=[R.tip_text(self.lang, t) for t in last['tips']])
            out.append({**c, 'avg_loss': round(sum(h) / len(h)) if h else None,
                        'best_loss': min(h) if h else None, 'last': last})
        return out

    def snapshot(self):
        with self.lock:
            lang = self.lang
            s = self.session
            me = self.lap[self.player] if self.lap[self.player] else None
            tel = self.tel[self.player]
            ref, options = self.reference()
            live = None
            if me:
                live = {
                    'lap': me['lap_num'], 'lap_ms': me['current_lap_ms'],
                    'dist': round(me['lap_distance']), 'sector': me['sector'] + 1,
                    'position': me['position'], 'invalid': bool(me['invalid']),
                    's1': me['s1_ms'], 's2': me['s2_ms'], 'last_lap': me['last_lap_ms'],
                    'pit': me['pit_status'],
                }
                if tel:
                    live.update(speed=tel['speed'], gear=tel['gear'],
                                throttle=round(tel['throttle'], 2),
                                brake=round(tel['brake'], 2))
                if ref and ref.trace and me['lap_distance'] > 0:
                    rt = ref.trace.time_at(me['lap_distance'])
                    live['delta'] = round(me['current_lap_ms'] - rt)
                    live['predicted'] = round(ref.lap_ms + live['delta'])
            laps = []
            for l in self.player_laps[-30:]:
                laps.append(l.summary())
            lap_traces = [l.trace for l in self.player_laps if l.valid and l.clean]
            race = None
            if me:
                race = {
                    'fuel': self._fuel(), 'tyres': self._tyres(),
                    'gaps': self.race.gaps(me['delta_front_ms'] if me['position'] > 1 else None,
                                           self._gap_behind()),
                    'pace': self.race.pace(), 'position': me['position'],
                    'pit_stops': me['num_pit_stops'],
                }
            pb = self._stored_pb()
            return {
                'connected': time.time() - self.last_packet_at < 3,
                'rate': round(self.packet_rate),
                'warning': self.format_warning,
                'settings': {k: v for k, v in self.settings.items()
                             if k not in ('gemini_key', 'groq_key')},
                'has_gemini': bool(self.settings.get('gemini_key')),
                'has_groq': bool(self.settings.get('groq_key')),
                'llm': {'model': self.last_llm_model, 'error': self.last_llm_error},
                'session': {
                    'track_id': self.track_id,
                    'track': TRACKS.get(self.track_id, 'Track %s' % self.track_id)
                    if self.track_id is not None else None,
                    'type': SESSION_TYPES.get(s.get('session_type'), None),
                    'type_id': s.get('session_type'),
                    'weather': WEATHER.get(s.get('weather')),
                    'track_temp': s.get('track_temp'), 'air_temp': s.get('air_temp'),
                    'ai': self.difficulty(), 'ai_game': s.get('ai_difficulty'),
                    'total_laps': s.get('total_laps'), 'length': s.get('track_length'),
                    'sector_starts': [0, s.get('sector2_start'), s.get('sector3_start')],
                    'time_left': s.get('time_left'),
                },
                'live': live,
                'reference': {'kind': ref.kind if ref else None,
                              'name': REF_NAMES[lang].get(ref.kind if ref else None),
                              'lap_ms': ref.lap_ms if ref else None,
                              'sectors': ref.sectors if ref else None,
                              'options': sorted(options.keys())},
                'target': self.target(),
                'best': self.session_best.summary() if self.session_best else None,
                'pb': {'lap_ms': pb['lap_ms'], 'sectors': pb.get('sectors'),
                       'date': pb.get('date')} if pb else None,
                'theoretical_best': theoretical_best(lap_traces, self.corners),
                'laps': laps,
                'corners': self.corner_summary(),
                'compare_lap': self.last_compare_lap.lap_num if self.last_compare_lap else None,
                'race': race,
                'messages': self.messages[-20:],
                'track_version': self.track_version,
                'regs': self.regs.snapshot(self.status[self.player] if self.player <
                                           len(self.status) else None, s),
                'format': self.packet_format,
                'listen_seq': self.listen_seq,
                'voice_devices': self.voice_devices(),
                'heard': self.heard, 'voice_status': self.voice_status,
                'strategy': self.strategy_snapshot(),
                'around': self.opponents.around(self.lap, self.player, self.names()),
                'incidents': self.incidents.summary(me, self.damage[self.player]
                                                    if self.player < len(self.damage) else None),
                'weather': self.weather_snapshot(),
                'quali': self.quali_snapshot(),
                'setup': self.setup.summary(),
                'tts': {'available': self.tts.available(), 'error': self.tts.last_error,
                        'latency': self.tts.last_latency},
            }

    def track_info(self):
        with self.lock:
            return {'track_id': self.track_id,
                    'outline': self.track_data.get('outline'),
                    'corners': self.corners,
                    'version': self.track_version}

    def compare_traces(self):
        """Data pro graf: poslední kolo vs reference + průběžná delta."""
        with self.lock:
            lap = self.last_compare_lap
            ref, _ = self.reference()
            if not lap or not lap.trace or not ref or not ref.trace:
                return None
            step = 3
            lt, rt = lap.trace, ref.trace
            dist = lt.dist[::step]
            delta = [round(lt.time_at(d) - rt.time_at(d)) for d in dist]
            return {
                'lap': lap.lap_num, 'ref': ref.kind,
                'dist': dist,
                'speed': [round(rt.value_at('speed', d)) for d in dist],
                'lap_speed': [round(v) for v in lt.cols['speed'][::step]],
                'throttle': [round(v, 2) for v in lt.cols['throttle'][::step]],
                'ref_throttle': [round(rt.value_at('throttle', d), 2) for d in dist],
                'brake': [round(v, 2) for v in lt.cols['brake'][::step]],
                'ref_brake': [round(rt.value_at('brake', d), 2) for d in dist],
                'delta': delta,
                'corners': self.corners,
            }

    # ------------------------------------------------------------------ settings
    def update_settings(self, new):
        with self.lock:
            allowed = {'lang', 'level', 'reference', 'difficulty_override', 'voice',
                       'gemini_key', 'gemini_model', 'engineer_name', 'wake_word', 'buttons',
                       'voice_engine', 'tts_voice', 'groq_key', 'groq_model', 'chat_model',
                       'radio_mode'}
            for k, v in new.items():
                if k in allowed:
                    if k in ('gemini_key', 'groq_key') and v == '***':
                        continue
                    self.settings[k] = v
            self.storage.save_settings(self.settings)

    def reset_corners(self):
        with self.lock:
            self.corners = []
            self.track_data.pop('corners', None)
            self.track_data.pop('outline', None)
            self.corner_hist = {}
            ref, _ = self.reference()
            if ref and ref.trace:
                self._ensure_corners(ref.trace)
            else:
                self._save_track()
            self.track_version += 1

    def context_for_llm(self):
        """Kompaktní fakta pro jazykový model."""
        snap = self.snapshot()
        def lapfmt(ms):
            return R.fmt_lap(ms) if ms else None
        corners = [
            {'corner': c['name'], 'avg_loss_ms': c['avg_loss'],
             'last': {k: c['last'][k] for k in ('loss', 'min_speed', 'ref_min_speed',
                                                'brake_diff_m', 'throttle_diff_m',
                                                'exit_speed', 'ref_exit_speed')}
             if c.get('last') else None}
            for c in snap['corners']
        ]
        corners = [c for c in corners if c['avg_loss_ms'] is not None or c['last']]
        corners.sort(key=lambda c: -(c['avg_loss_ms'] or 0))
        return {
            'session': snap['session'],
            'live': snap['live'],
            'reference': {'type': snap['reference']['name'],
                          'lap': lapfmt(snap['reference']['lap_ms'])},
            'target': snap['target'],
            'session_best': lapfmt(snap['best']['time']) if snap['best'] else None,
            'personal_best': lapfmt(snap['pb']['lap_ms']) if snap['pb'] else None,
            'theoretical_best': lapfmt(snap['theoretical_best']),
            'last_laps': [{'lap': l['lap'], 'time': lapfmt(l['time']), 'valid': l['valid'],
                           'delta_ms': l.get('delta')} for l in snap['laps'][-6:]],
            'corners_worst_first': corners[:8],
            'race': snap['race'],
            'regs_2026': snap['regs'],
            'strategy': snap['strategy'],
            'cars_around': snap['around'],
            'incidents': snap['incidents'],
            'weather': snap['weather'],
            'quali': snap['quali'],
            'setup_advice': snap['setup']['advice'][:4],
            'car_balance': snap['setup']['balance'],
            'recent_radio': [m['text'] for m in snap['messages'][-5:]],
        }
