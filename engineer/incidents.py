"""Incidenty: track limits, penalizace, vlajky, safety car, kontakt a poškození.

Modul jen vytváří události (key, kwargs, urgent); texty a jazyk řeší state/radio.
"""
from . import radio as R

DAMAGE_KEYS = ['fl_wing', 'fr_wing', 'rear_wing', 'floor', 'diffuser', 'sidepod', 'gearbox', 'engine']
WHEELS = ['RL', 'RR', 'FL', 'FR']


class Incidents:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prev_lap = None
        self.prev_damage = None
        self.prev_sc = None
        self.blue_until = -1.0
        self.yellow_zone = None
        self.events = []
        self.log = []          # historie pro UI / debrief
        self.wing_box_called = False
        self.punctures = set()
        self.faults = set()
        self.pena_dt = 0       # DT/SG už ohlášené přes PENA event (aby se nehlásily dvakrát)
        self.pena_sg = 0

    def _emit(self, key, urgent=False, **kw):
        self.events.append((key, kw, urgent))
        self.log.append({'key': key, **{k: v for k, v in kw.items() if isinstance(v, (int, str))}})
        self.log = self.log[-50:]

    def pop_events(self):
        ev, self.events = self.events, []
        return ev

    # ------------------------------------------------------------ vstupy
    def on_lap(self, me):
        p = self.prev_lap
        self.prev_lap = dict(me)
        if not p:
            return
        if me['cc_warnings'] > p['cc_warnings']:
            n = me['cc_warnings']
            self._emit('track_limits_many' if n >= 3 else 'track_limits', n=n)
        elif me['warnings'] > p['warnings']:
            self._emit('warning', n=me['warnings'])
        if me['unserved_dt'] > p['unserved_dt']:
            if self.pena_dt:
                self.pena_dt -= 1
            else:
                self._emit('penalty_dt', urgent=True, why='')
        if me['unserved_sg'] > p['unserved_sg']:
            if self.pena_sg:
                self.pena_sg -= 1
            else:
                self._emit('penalty_sg', urgent=True, why='')

    def on_penalty_event(self, ev, player):
        if ev['car'] != player:
            return
        why = R.INFRINGEMENTS.get(ev['infringement'], '')
        t = ev['penalty_type']
        if t == 4:
            self._emit('penalty_time', urgent=True, s=ev['time'], why=why)
        elif t == 0:
            self.pena_dt += 1
            self._emit('penalty_dt', urgent=True, why=why)
        elif t == 1:
            self.pena_sg += 1
            self._emit('penalty_sg', urgent=True, why=why)
        elif t in (2, 6, 9, 17):
            self._emit('penalty_other', urgent=True, what=R.PENALTY_TYPES[t], why=why)

    def on_status(self, status, session_time):
        flag = status.get('fia_flag')
        if flag == 2 and session_time > self.blue_until:
            self.blue_until = session_time + 20
            self._emit('blue_flag', urgent=True)

    def on_position(self, lap_distance, session):
        """Žlutá vlajka v příští marshal zóně před jezdcem."""
        zones = session.get('marshal_zones') or []
        L = session.get('track_length') or 0
        if not zones or not L or lap_distance < 0:
            return
        f = (lap_distance % L) / L
        cur = 0
        for i, (start, _flag) in enumerate(zones):
            if start <= f:
                cur = i
        nxt = (cur + 1) % len(zones)
        yellow = None
        for idx in (cur, nxt):
            if zones[idx][1] == 3:
                yellow = idx
        if yellow is not None and yellow != self.yellow_zone:
            self._emit('yellow_ahead', urgent=True)
        self.yellow_zone = yellow

    def on_safety_car(self, sc_status):
        """sc_status ze session: 0 none, 1 full, 2 virtual, 3 formation."""
        prev = self.prev_sc
        self.prev_sc = sc_status
        if prev is None or prev == sc_status:
            return None
        if sc_status == 1:
            self._emit('sc_deployed', urgent=True)
            return 'sc'
        if sc_status == 2:
            self._emit('vsc_deployed', urgent=True)
            return 'vsc'
        if sc_status == 0 and prev in (1, 2):
            self._emit('green', urgent=True)
        return None

    def on_event(self, ev, player):
        code = ev['code']
        if code == 'SCAR' and ev.get('sc_event') == 1 and ev.get('sc_type') == 1:
            self._emit('sc_in', urgent=True)
        elif code == 'RDFL':
            self._emit('red_flag', urgent=True)
        elif code == 'COLL' and player in (ev.get('car1'), ev.get('car2')):
            self._emit('contact')
        elif code == 'PENA':
            self.on_penalty_event(ev, player)

    def on_damage(self, dmg, is_race, laps_left):
        p = self.prev_damage
        self.prev_damage = dict(dmg)
        if not p:
            return
        for k in DAMAGE_KEYS:
            if dmg[k] >= p[k] + 5 and dmg[k] >= 10:
                self._emit('damage', part=R.DAMAGE_PARTS[k], p=dmg[k])
        front = max(dmg['fl_wing'], dmg['fr_wing'])
        if is_race and front >= 40 and not self.wing_box_called and (laps_left or 99) > 3:
            self.wing_box_called = True
            self._emit('damage_box_wing', urgent=True)
        for i, d in enumerate(dmg['tyre_damage']):
            if d >= 50 and p['tyre_damage'][i] < 50 and i not in self.punctures:
                self.punctures.add(i)
                self._emit('puncture', urgent=True, wheel_idx=i)
        for k, name in (('drs_fault', 'DRS'), ('ers_fault', 'ERS')):
            if dmg[k] and not p[k] and k not in self.faults:
                self.faults.add(k)
                self._emit('fault', part=name)

    def summary(self, me, dmg):
        out = {}
        if me:
            out.update(warnings=me['warnings'], track_limits=me['cc_warnings'],
                       penalty_s=me['penalties'], unserved_dt=me['unserved_dt'],
                       unserved_sg=me['unserved_sg'])
        if dmg:
            out['damage'] = {k: dmg[k] for k in DAMAGE_KEYS if dmg[k]}
        out['sc'] = {0: None, 1: 'SC', 2: 'VSC', 3: 'Formation'}.get(self.prev_sc)
        out['log'] = self.log[-10:]
        return out
