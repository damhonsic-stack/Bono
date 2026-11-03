"""Regulace 2026: active aero (Straight/Corner mode), Overtake mode a ERS.

Data jsou jen ve formátu UDP 2026 (paket Car Telemetry 2 + rozšířený Car Status
a Session). Ve formátu 2025 modul nic nehlásí.
"""

ERS_CAPACITY_J = 4.0e6  # kapacita baterie v F1 hrách (4 MJ)
ERS_MODES = {0: 'None', 1: 'Medium', 2: 'Hotlap', 3: 'Overtake'}


class Regs26:
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False          # přišel aspoň jeden paket Car Telemetry 2
        self.player = None           # poslední CarTelemetry2Data hráče
        self.cars = []
        self.prev = {}               # předchozí stav pro detekci změn (per car)
        self.events = []             # (key, data) k vyhlášení rádiem
        self._last_dist = None
        self._lap = None
        self.avail_m = 0.0
        self.used_m = 0.0
        self.ot_uses = 0
        self.ot_windows = 0
        self.ot_window_used = False
        self.ot_window_m = 0.0       # jak dlouho (m) je aktuální okno dostupné
        self.ot_announced_lap = None
        self.ot_missed_lap = None
        self.lap_stats = {}          # lap_num -> dict

    # ------------------------------------------------------------ vstupy
    def on_telemetry2(self, cars, player, lap):
        """cars: list CarTelemetry2Data, lap: LapData hráče (nebo None)."""
        self.active = True
        self.cars = cars
        me = cars[player] if player < len(cars) else None
        if not me:
            return
        prev = self.prev.get(player)
        self.player = me
        # využití straight mode po vzdálenosti
        step = 0.0
        if lap:
            d, n = lap['lap_distance'], lap['lap_num']
            if self._lap == n and self._last_dist is not None:
                step = d - self._last_dist
                if not 0 < step < 200:
                    step = 0.0
                if me['aero_available']:
                    self.avail_m += step
                    if me['aero_mode'] == 1:
                        self.used_m += step
            self._lap, self._last_dist = n, d
        # overtake mode: okna dostupnosti a aktivace (s debounce – max 1 hlášení za lap)
        if me['overtake_available']:
            self.ot_window_m += step
        if prev:
            if me['overtake_available'] and not prev['overtake_available']:
                self.ot_windows += 1
                self.ot_window_used = False
                self.ot_window_m = 0.0
                if not me['overtake_active'] and self.ot_announced_lap != self._lap:
                    self.ot_announced_lap = self._lap
                    self.events.append(('ot_available', {}))
            if me['overtake_active'] and not prev['overtake_active']:
                self.ot_uses += 1
                self.ot_window_used = True
            if prev['overtake_available'] and not me['overtake_available'] and \
                    not self.ot_window_used and not me['overtake_active'] and \
                    self.ot_window_m >= 150 and self.ot_missed_lap != self._lap:
                self.ot_missed_lap = self._lap
                self.events.append(('ot_missed', {}))
        self.prev[player] = dict(me)

    def check_car_behind(self, behind_idx, gap_behind_ms):
        """Auto za mnou získalo overtake mode → varování (jednou za okno)."""
        if behind_idx is None or behind_idx >= len(self.cars):
            return
        c = self.cars[behind_idx]
        key = ('behind', behind_idx)
        was = self.prev.get(key, 0)
        now = c['overtake_available'] or c['overtake_active']
        if now and not was and gap_behind_ms is not None and gap_behind_ms < 1500 and \
                self.prev.get('behind_lap') != self._lap:
            self.prev['behind_lap'] = self._lap
            self.events.append(('ot_behind', {'gap': gap_behind_ms}))
        self.prev[key] = now

    def on_event(self, code):
        mapping = {'OVEN': 'ot_enabled', 'OVDI': 'ot_disabled',
                   'PMEN': 'partial_on', 'PMDI': 'partial_off'}
        if code in mapping:
            self.events.append((mapping[code], {}))

    def on_lap_complete(self, lap_num, status):
        """Uzavře statistiky dokončeného kola."""
        st = {}
        if self.avail_m > 50:
            st['straight_pct'] = round(100.0 * self.used_m / self.avail_m)
            st['aero_avail_m'] = round(self.avail_m)
        if self.active:
            st['ot_uses'] = self.ot_uses
        if status:
            st['ers_deployed_mj'] = round(status['ers_deployed_lap'] / 1e6, 2)
            st['ers_harvested_mj'] = round((status['ers_harvested_k'] +
                                            status['ers_harvested_h']) / 1e6, 2)
            if status.get('ers_harvest_limit'):
                st['ers_harvest_limit_mj'] = round(status['ers_harvest_limit'] / 1e6, 2)
            st['ers_end_pct'] = round(100.0 * status['ers_store'] / ERS_CAPACITY_J)
        self.lap_stats[lap_num] = st
        self.avail_m = self.used_m = 0.0
        self.ot_uses = 0
        self._last_dist = None
        return st

    def pop_events(self):
        ev, self.events = self.events, []
        return ev

    # ------------------------------------------------------------ výstup
    def snapshot(self, status, session):
        out = {'active': self.active}
        if status:
            store = status['ers_store']
            harvested = status['ers_harvested_k'] + status['ers_harvested_h']
            out['ers'] = {
                'store_mj': round(store / 1e6, 2),
                'pct': round(100.0 * store / ERS_CAPACITY_J),
                'mode': ERS_MODES.get(status['ers_mode'], str(status['ers_mode'])),
                'deployed_lap_mj': round(status['ers_deployed_lap'] / 1e6, 2),
                'harvested_lap_mj': round(harvested / 1e6, 2),
            }
            lim = status.get('ers_harvest_limit')
            if lim:
                out['ers']['harvest_limit_mj'] = round(lim / 1e6, 2)
                out['ers']['harvest_left_mj'] = round(max(0.0, lim - harvested) / 1e6, 2)
        me = self.player
        if me:
            out['aero'] = {'mode': 'Straight' if me['aero_mode'] == 1 else 'Corner',
                           'available': bool(me['aero_available']),
                           'distance': me['aero_distance']}
            out['overtake'] = {'available': bool(me['overtake_available']),
                               'active': bool(me['overtake_active']),
                               'distance': me['overtake_distance']}
            out['regs_2026'] = bool(me['regs_2026'])
            if self.avail_m > 50:
                out['straight_pct_live'] = round(100.0 * self.used_m / self.avail_m)
        if session and 'aero_status' in session:
            out['aero_status'] = 'Partial' if session['aero_status'] == 1 else 'Full'
            out['aero_zones'] = session['aero_zones_partial'] if session['aero_status'] == 1 \
                else session['aero_zones_full']
            out['drs_zones'] = session.get('drs_zones', [])
        last = max(self.lap_stats) if self.lap_stats else None
        if last is not None:
            out['last_lap'] = dict(self.lap_stats[last], lap=last)
        return out
