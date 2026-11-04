"""Kvalifikační režim: out lap (gumy, baterie), provoz na trati, push call, zbývající čas.

Používá m_driverStatus z Lap Data: 0 garage, 1 flying lap, 2 in lap, 3 out lap, 4 on track.
"""
SURFACE_WINDOW = (80, 105)   # přibližné okno povrchové teploty slicků (°C)
FLYING, IN_LAP, OUT_LAP = 1, 2, 3


def track_gaps(laps, player, track_len):
    """Najde nejbližší auto před a za hráčem NA TRATI (ne podle pozice). Vrací
    ((idx, metres), (idx, metres)) nebo None."""
    me = laps[player] if player < len(laps) else None
    if not me or not track_len:
        return None, None
    my_d = me['lap_distance'] % track_len
    ahead = behind = None
    for i, l in enumerate(laps):
        if not l or i == player or l['result_status'] != 2 or l['pit_status'] or \
                l['driver_status'] == 0:
            continue
        d = (l['lap_distance'] % track_len - my_d) % track_len
        if ahead is None or d < ahead[1]:
            ahead = (i, d)
        back = track_len - d
        if behind is None or back < behind[1]:
            behind = (i, back)
    return ahead, behind


class Quali:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prev_status = None
        self.prev_lap = None
        self.lap_key = None
        self.temps_called = False
        self.traffic_called = False
        self.behind_called = set()
        self.time_called = set()
        self.events = []

    def pop_events(self):
        ev, self.events = self.events, []
        return ev

    def update(self, me, laps, player, tel, regs_active, ers_pct, session, speed_kmh):
        if not me:
            return
        L = session.get('track_length') or 0
        status = me['driver_status']
        prev = self.prev_status
        self.prev_status = status
        prev_lap, self.prev_lap = self.prev_lap, me['lap_num']
        if prev == FLYING and status == FLYING and prev_lap is not None and me['lap_num'] == prev_lap + 1 \
                and session.get('session_type') != 18:
            self.events.append(('push_again', {}, True))      # další rychlé kolo hned po předchozím
        key = (me['lap_num'], status)
        if key != self.lap_key:
            self.lap_key = key
            self.temps_called = self.traffic_called = False
            self.behind_called = set()
        if prev is not None and status != prev:
            if status == OUT_LAP:
                self.events.append(('out_lap', {'battery': bool(regs_active)}, False))
            elif status == FLYING and prev == OUT_LAP:
                ahead, _ = track_gaps(laps, player, L)
                kw = {}
                if ahead and speed_kmh > 50:
                    kw['ahead_s'] = ahead[1] / (speed_kmh / 3.6)
                self.events.append(('push_now', kw, True))
        d = me['lap_distance']
        if status == OUT_LAP and L:
            if not self.temps_called and d > L * 0.5 and tel:
                self.temps_called = True
                s = tel['tyre_surface']
                f, r = round((s[2] + s[3]) / 2), round((s[0] + s[1]) / 2)
                lo, hi = SURFACE_WINDOW
                hint = 'temps_ok'
                if min(f, r) < lo:
                    hint = 'temps_cold'
                elif max(f, r) > hi:
                    hint = 'temps_hot'
                self.events.append(('tyre_temps', {'f': f, 'r': r, 'hint': hint,
                                                   'ers': ers_pct if regs_active else None}, False))
            if not self.traffic_called and d > L - 700:
                self.traffic_called = True
                ahead, _ = track_gaps(laps, player, L)
                if ahead and speed_kmh > 50:
                    secs = ahead[1] / (speed_kmh / 3.6)
                    key2 = 'traffic_close' if secs < 3.0 else 'clear_air'
                    self.events.append((key2, {'s': secs}, key2 == 'traffic_close'))
        if status in (OUT_LAP, IN_LAP) and L:
            _, behind = track_gaps(laps, player, L)
            if behind and behind[0] not in self.behind_called:
                lb = laps[behind[0]]
                if lb['driver_status'] == FLYING and speed_kmh > 30:
                    secs = behind[1] / max(30.0, speed_kmh) * 3.6
                    if secs < 2.5:
                        self.behind_called.add(behind[0])
                        self.events.append(('car_behind_push', {'s': secs}, True))
        left = session.get('time_left')
        if left:
            for m in (5, 2):
                if left <= m * 60 and left > m * 60 - 30 and m not in self.time_called:
                    self.time_called.add(m)
                    self.events.append(('time_left', {'m': m}, False))
