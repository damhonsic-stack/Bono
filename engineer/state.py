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

REF_NAMES = {
    'cs': {'session_best': 'Session best', 'pb': 'Personal best',
           'ai_best': 'Fastest AI', 'tt_rival': 'Time Trial rival', 'tt_pb': 'Time Trial ghost (PB)',
           None: 'žádná'},
    'en': {'session_best': 'Session best', 'pb': 'Personal best',
           'ai_best': 'Fastest AI', 'tt_rival': 'Time Trial rival', 'tt_pb': 'Time Trial ghost (PB)',
           None: 'none'},
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
        return self.settings.get('lang', 'cs')

    @property
    def level(self):
        return int(self.settings.get('level', 2))

    def difficulty(self):
        o = self.settings.get('difficulty_override')
        if o not in (None, ''):
            return int(o)
        return self.session.get('ai_difficulty')

    def say(self, text, prio=1):
        self.msg_id += 1
        self.messages.append({'id': self.msg_id, 'text': text, 'prio': prio,
                              'ts': time.time()})
        self.messages = self.messages[-40:]

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
            if hdr['format'] != 2025:
                self.format_warning = (
                    'Hra posílá formát %d. Nastav ve hře UDP Format = 2025.' % hdr['format'])
                if hdr['format'] < 2025:
                    return
            if payload is None:
                return
            if hdr['session_uid'] != self.session_uid and hdr['session_uid'] != 0:
                self._end_session()
                self._new_session(hdr['session_uid'])
            self.player = hdr['player'] if hdr['player'] < P.NUM_CARS else 0
            if pid == P.LAP_DATA:
                self._on_lap_data(payload)
            elif pid == P.CAR_TELEMETRY:
                self.tel = payload['cars']
            elif pid == P.MOTION:
                self.motion = payload['cars']
            elif pid == P.CAR_STATUS:
                self.status = payload['cars']
            elif pid == P.CAR_DAMAGE:
                self.damage = payload['cars']
            elif pid == P.SESSION:
                self._on_session(payload)
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
            self.say(R.say(self.lang, 'session_start',
                           track=TRACKS.get(s['track_id'], 'Track %d' % s['track_id']),
                           session=SESSION_TYPES.get(s['session_type'], '?'),
                           ai=self.difficulty()), prio=0)

    def _on_event(self, ev):
        if ev['code'] == 'SEND':
            self._end_session()

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
        """Kalibrace cílů podle AI na konci kvalifikace/tréninku."""
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
        ref_before, _ = self.reference()
        msgs = []
        pb = self._stored_pb()
        is_pb = False
        if lap.valid and lap.clean:
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
            if lap.valid:
                for c in compare:
                    self.corner_hist.setdefault(c['id'], []).append(c['loss'])
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
        if not lap.valid:
            msgs.append(R.say(lang, 'invalid'))
        if is_pb:
            msgs.append(R.say(lang, 'pb', time=R.fmt_lap(lap.lap_ms)))
        else:
            m = R.say(lang, 'lap', time=R.fmt_lap(lap.lap_ms))
            if ref_before and lap.valid and 'delta' in lap.meta:
                d = lap.meta['delta']
                if abs(d) >= 5:
                    m += ' ' + R.say(lang, 'lap_delta_slow' if d > 0 else 'lap_delta_fast',
                                     d=R.fmt_delta(d, lang))
            msgs.append(m)
        if compare and lap.valid:
            worst = sorted(compare, key=lambda c: -c['loss'])
            n = 0
            for c in worst:
                if c['loss'] < cfg['corner_min_loss'] or n >= cfg['corners']:
                    break
                msgs.append(R.corner_message(lang, c, level))
                n += 1
        if lap.valid and st not in RACE:
            tgt = self.target()
            if tgt and tgt.get('lap_ms') and (is_pb or len(self.player_laps) % 3 == 1):
                d = lap.lap_ms - tgt['lap_ms']
                key = 'target_gap_slow' if d > 0 else 'target_gap_fast'
                msgs.append(R.say(lang, key, ai=tgt['ai'], d=R.fmt_delta(d, lang)))
        if st in RACE:
            msgs.extend(self._race_messages(lap.lap_num))
        for m in msgs:
            self.say(m)

    def _gap_behind(self):
        me = self.lap[self.player]
        if not me:
            return None
        for i, l in enumerate(self.lap):
            if l and l['position'] == me['position'] + 1 and l['result_status'] == 2:
                return l['delta_front_ms']
        return None

    def _race_messages(self, lap_num):
        lang = self.lang
        out = []
        g = self.race.gaps(None, None)
        if lap_num % 2 == 0:
            ga = self.race.gap_ahead[-1] if self.race.gap_ahead else None
            ta = g.get('ahead_trend')
            if ta is not None and ga is not None and abs(ta) >= 100:
                key = 'gap_closing' if ta < 0 else 'gap_losing'
                m = R.say(lang, key, r=R.fmt_delta(ta, lang), g=R.fmt_delta(ga, lang))
                if ta < 0 and ga / -ta < 15:
                    m += ' ' + R.say(lang, 'catch_in', n=max(1, round(ga / -ta)))
                out.append(m)
            gb = self.race.gap_behind[-1] if self.race.gap_behind else None
            tb = g.get('behind_trend')
            if tb is not None and gb is not None and abs(tb) >= 100:
                key = 'gap_behind_closing' if tb < 0 else 'gap_behind_dropping'
                out.append(R.say(lang, key, r=R.fmt_delta(tb, lang), g=R.fmt_delta(gb, lang)))
        fuel = self._fuel()
        if fuel and lap_num % 3 == 0:
            fd = fuel['game_delta_laps']
            if fd < 0:
                out.append(R.say(lang, 'fuel_low', d=('%.1f' % fd).replace('.', ',')
                                 if lang == 'cs' else '%.1f' % fd))
        tyres = self._tyres()
        if tyres and tyres.get('max_wear', 0) >= 50 and lap_num % 3 == 0:
            w = tyres['wear']
            wheel = max(w, key=w.get)
            out.append(R.say(lang, 'tyre_wear', w=round(tyres['max_wear']),
                             wheel=R.WHEEL_NAMES[lang][wheel]))
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
                'settings': {k: v for k, v in self.settings.items() if k != 'gemini_key'},
                'has_gemini': bool(self.settings.get('gemini_key')),
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
                       'gemini_key', 'gemini_model'}
            for k, v in new.items():
                if k in allowed:
                    if k == 'gemini_key' and v == '***':
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
            'recent_radio': [m['text'] for m in snap['messages'][-5:]],
        }
